# db.py
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    create_engine,
    text,
)
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db").strip()

# Normalize Railway/Heroku style
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_schema() -> None:
    """
    Idempotent schema creation.
    Uses raw SQL with IF NOT EXISTS so it won't spam errors like
    "relation already exists" when called multiple times.
    """
    with engine.begin() as conn:
        # Only Postgres needs JSONB; SQLite fallback uses TEXT
        is_postgres = conn.dialect.name == "postgresql"

        if is_postgres:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto;"))
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS baseprice_cache (
                        id BIGSERIAL PRIMARY KEY,
                        product_uuid VARCHAR NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_baseprice_cache_product_uuid
                    ON baseprice_cache (product_uuid);
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_baseprice_cache_created_at
                    ON baseprice_cache (created_at);
                    """
                )
            )
        else:
            # SQLite dev-mode fallback
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS baseprice_cache (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_uuid TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
            )


def insert_baseprice_cache(product_uuid: str, payload: Dict[str, Any]) -> int:
    """
    Inserts a new cache row. We keep history (multiple rows per product_uuid),
    and "latest" is max(id).
    """
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            result = conn.execute(
                text(
                    """
                    INSERT INTO baseprice_cache (product_uuid, payload)
                    VALUES (:product_uuid, :payload::jsonb)
                    RETURNING id;
                    """
                ),
                {"product_uuid": product_uuid, "payload": payload},
            )
            return int(result.scalar_one())
        else:
            # SQLite: store JSON as string
            import json

            now = datetime.utcnow().isoformat()
            result = conn.execute(
                text(
                    """
                    INSERT INTO baseprice_cache (product_uuid, payload, created_at)
                    VALUES (:product_uuid, :payload, :created_at);
                    """
                ),
                {"product_uuid": product_uuid, "payload": json.dumps(payload), "created_at": now},
            )
            return int(result.lastrowid)


def list_baseprice_cache(limit: int = 25) -> List[Dict[str, Any]]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, product_uuid, payload, created_at
                FROM baseprice_cache
                ORDER BY id DESC
                LIMIT :limit;
                """
            ),
            {"limit": limit},
        ).mappings().all()

        out: List[Dict[str, Any]] = []
        if conn.dialect.name == "postgresql":
            for r in rows:
                out.append(
                    {
                        "id": int(r["id"]),
                        "product_uuid": r["product_uuid"],
                        "payload": r["payload"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                )
        else:
            import json

            for r in rows:
                out.append(
                    {
                        "id": int(r["id"]),
                        "product_uuid": r["product_uuid"],
                        "payload": json.loads(r["payload"]) if r["payload"] else {},
                        "created_at": r["created_at"],
                    }
                )
        return out


def latest_baseprice_cache(product_uuid: str) -> Optional[Dict[str, Any]]:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, product_uuid, payload, created_at
                FROM baseprice_cache
                WHERE product_uuid = :product_uuid
                ORDER BY id DESC
                LIMIT 1;
                """
            ),
            {"product_uuid": product_uuid},
        ).mappings().first()

        if not row:
            return None

        if conn.dialect.name == "postgresql":
            return {
                "id": int(row["id"]),
                "product_uuid": row["product_uuid"],
                "payload": row["payload"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
        else:
            import json

            return {
                "id": int(row["id"]),
                "product_uuid": row["product_uuid"],
                "payload": json.loads(row["payload"]) if row["payload"] else {},
                "created_at": row["created_at"],
            }
