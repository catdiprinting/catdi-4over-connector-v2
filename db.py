# db.py
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------
# SCHEMA / MIGRATIONS
# ---------------------------

def ensure_schema() -> None:
    """
    Idempotent schema creation + light migration.
    This prevents regressions when a table already exists but is missing columns.
    """
    with engine.begin() as conn:
        # Create table if it doesn't exist
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS baseprice_cache (
            id SERIAL PRIMARY KEY,
            product_uuid VARCHAR NOT NULL,
            payload JSON NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """))

        # If table already existed without payload, add it
        conn.execute(text("""
        ALTER TABLE baseprice_cache
        ADD COLUMN IF NOT EXISTS payload JSON NULL;
        """))

        # Ensure created_at exists
        conn.execute(text("""
        ALTER TABLE baseprice_cache
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        """))

        # Helpful index
        conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_baseprice_cache_product_uuid
        ON baseprice_cache (product_uuid);
        """))


# ---------------------------
# CACHE FUNCTIONS
# ---------------------------

def insert_baseprice_cache(product_uuid: str, payload: Dict[str, Any]) -> int:
    ensure_schema()
    with engine.begin() as conn:
        res = conn.execute(
            text("""
                INSERT INTO baseprice_cache (product_uuid, payload)
                VALUES (:product_uuid, :payload::json)
                RETURNING id;
            """),
            {"product_uuid": product_uuid, "payload": _json_dump(payload)},
        )
        return int(res.scalar_one())


def list_baseprice_cache(limit: int = 25) -> List[Dict[str, Any]]:
    ensure_schema()
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT id, product_uuid, payload, created_at
                FROM baseprice_cache
                ORDER BY id DESC
                LIMIT :limit;
            """),
            {"limit": limit},
        ).mappings().all()
        return [dict(r) for r in rows]


def latest_baseprice_cache(product_uuid: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT id, product_uuid, payload, created_at
                FROM baseprice_cache
                WHERE product_uuid = :product_uuid
                ORDER BY id DESC
                LIMIT 1;
            """),
            {"product_uuid": product_uuid},
        ).mappings().first()
        return dict(row) if row else None


def _json_dump(obj: Any) -> str:
    # Keep deps minimal: use stdlib json
    import json
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
