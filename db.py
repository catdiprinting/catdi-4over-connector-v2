# db.py
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway Postgres URLs sometimes start with postgres:// which SQLAlchemy wants as postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_schema() -> List[str]:
    """
    Idempotent schema setup.
    Creates baseprice_cache if missing, and ensures product_uuid unique.
    Uses columns: id, product_uuid, payload (json/jsonb), created_at.
    """
    created = []
    with engine.begin() as conn:
        if DATABASE_URL.startswith("sqlite"):
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_uuid TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );
            """))
            created.append("baseprice_cache")
        else:
            # Postgres
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id BIGSERIAL PRIMARY KEY,
                    product_uuid VARCHAR NOT NULL UNIQUE,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """))
            # extra safety: ensure unique constraint exists
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND indexname = 'ix_baseprice_cache_product_uuid'
                    ) THEN
                        CREATE UNIQUE INDEX ix_baseprice_cache_product_uuid
                        ON baseprice_cache (product_uuid);
                    END IF;
                END$$;
            """))
            created.append("baseprice_cache")

    return created


def insert_baseprice_cache(product_uuid: str, payload: Dict[str, Any]) -> int:
    """
    Upsert cache row for product_uuid.
    Returns the row id.
    """
    if not product_uuid:
        raise ValueError("product_uuid is required")

    with engine.begin() as conn:
        if DATABASE_URL.startswith("sqlite"):
            # store JSON as string in sqlite
            import json
            payload_str = json.dumps(payload)

            conn.execute(text("""
                INSERT INTO baseprice_cache (product_uuid, payload)
                VALUES (:product_uuid, :payload)
                ON CONFLICT(product_uuid) DO UPDATE SET
                    payload=excluded.payload
            """), {"product_uuid": product_uuid, "payload": payload_str})

            row = conn.execute(
                text("SELECT id FROM baseprice_cache WHERE product_uuid = :product_uuid"),
                {"product_uuid": product_uuid},
            ).fetchone()
            return int(row[0])

        # Postgres JSONB
        row = conn.execute(text("""
            INSERT INTO baseprice_cache (product_uuid, payload)
            VALUES (:product_uuid, :payload::jsonb)
            ON CONFLICT (product_uuid) DO UPDATE SET
                payload = EXCLUDED.payload,
                created_at = NOW()
            RETURNING id;
        """), {"product_uuid": product_uuid, "payload": payload}).fetchone()

        return int(row[0])


def list_baseprice_cache(limit: int = 25) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 200))

    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, product_uuid, payload, created_at
            FROM baseprice_cache
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()

        # If sqlite payload stored as string, decode it
        out: List[Dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            if DATABASE_URL.startswith("sqlite"):
                import json
                item["payload"] = json.loads(item["payload"])
            out.append(item)
        return out


def latest_baseprice_cache(product_uuid: str) -> Optional[Dict[str, Any]]:
    if not product_uuid:
        return None

    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT id, product_uuid, payload, created_at
            FROM baseprice_cache
            WHERE product_uuid = :product_uuid
            ORDER BY created_at DESC
            LIMIT 1
        """), {"product_uuid": product_uuid}).mappings().fetchone()

        if not row:
            return None

        item = dict(row)
        if DATABASE_URL.startswith("sqlite"):
            import json
            item["payload"] = json.loads(item["payload"])
        return item
