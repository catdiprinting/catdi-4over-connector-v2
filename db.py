# db.py
from __future__ import annotations

import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway sometimes uses postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


def ensure_schema() -> None:
    """
    Idempotent schema setup + schema healing for older deployments.
    Supports Postgres (Railway) and SQLite (local).
    """
    if DATABASE_URL.startswith("sqlite"):
        _ensure_sqlite_schema()
    else:
        _ensure_postgres_schema()


def _ensure_postgres_schema() -> None:
    with engine.begin() as conn:
        # Create table if missing
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id BIGSERIAL PRIMARY KEY,
                    product_uuid VARCHAR NOT NULL,
                    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    payload JSONB NOT NULL,
                    CONSTRAINT uq_baseprice_cache_product_uuid UNIQUE (product_uuid)
                );
                """
            )
        )

        # Schema healing: add columns if an older version exists
        # (If they already exist, Postgres will throw; we catch by using DO blocks)
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='baseprice_cache' AND column_name='fetched_at'
                    ) THEN
                        ALTER TABLE baseprice_cache ADD COLUMN fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='baseprice_cache' AND column_name='payload'
                    ) THEN
                        ALTER TABLE baseprice_cache ADD COLUMN payload JSONB NOT NULL DEFAULT '{}'::jsonb;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname='uq_baseprice_cache_product_uuid'
                    ) THEN
                        ALTER TABLE baseprice_cache
                        ADD CONSTRAINT uq_baseprice_cache_product_uuid UNIQUE (product_uuid);
                    END IF;
                END
                $$;
                """
            )
        )


def _ensure_sqlite_schema() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_uuid TEXT NOT NULL UNIQUE,
                    fetched_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )
        )


def upsert_baseprice_cache(product_uuid: str, payload: dict) -> dict:
    """
    Postgres: INSERT ... ON CONFLICT DO UPDATE
    SQLite: INSERT OR REPLACE
    Returns: {"id": ..., "product_uuid": ..., "payload": ..., "fetched_at": ...}
    """
    if DATABASE_URL.startswith("sqlite"):
        return _sqlite_upsert(product_uuid, payload)
    return _pg_upsert(product_uuid, payload)


def _pg_upsert(product_uuid: str, payload: dict) -> dict:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO baseprice_cache (product_uuid, payload, fetched_at)
                VALUES (:product_uuid, CAST(:payload AS jsonb), NOW())
                ON CONFLICT (product_uuid)
                DO UPDATE SET payload = EXCLUDED.payload, fetched_at = NOW()
                RETURNING id, product_uuid, fetched_at, payload;
                """
            ),
            {"product_uuid": product_uuid, "payload": __import__("json").dumps(payload)},
        )
        row = result.mappings().first()
        return {
            "id": row["id"],
            "product_uuid": row["product_uuid"],
            "fetched_at": row["fetched_at"].isoformat() if row["fetched_at"] else None,
            "payload": row["payload"],
        }


def _sqlite_upsert(product_uuid: str, payload: dict) -> dict:
    import json

    fetched_at = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO baseprice_cache (product_uuid, fetched_at, payload)
                VALUES (:product_uuid, :fetched_at, :payload);
                """
            ),
            {"product_uuid": product_uuid, "fetched_at": fetched_at, "payload": json.dumps(payload)},
        )
        r = conn.execute(
            text(
                "SELECT id, product_uuid, fetched_at, payload FROM baseprice_cache WHERE product_uuid = :product_uuid LIMIT 1"
            ),
            {"product_uuid": product_uuid},
        ).mappings().first()
        return {"id": r["id"], "product_uuid": r["product_uuid"], "fetched_at": r["fetched_at"], "payload": json.loads(r["payload"])}


def latest_baseprice_cache(product_uuid: str) -> dict | None:
    """
    Return latest cached row for product_uuid.
    """
    if DATABASE_URL.startswith("sqlite"):
        import json

        with engine.begin() as conn:
            r = conn.execute(
                text(
                    """
                    SELECT id, product_uuid, fetched_at, payload
                    FROM baseprice_cache
                    WHERE product_uuid = :product_uuid
                    ORDER BY fetched_at DESC
                    LIMIT 1;
                    """
                ),
                {"product_uuid": product_uuid},
            ).mappings().first()
            if not r:
                return None
            return {"id": r["id"], "product_uuid": r["product_uuid"], "fetched_at": r["fetched_at"], "payload": json.loads(r["payload"])}

    with engine.begin() as conn:
        r = conn.execute(
            text(
                """
                SELECT id, product_uuid, fetched_at, payload
                FROM baseprice_cache
                WHERE product_uuid = :product_uuid
                ORDER BY fetched_at DESC
                LIMIT 1;
                """
            ),
            {"product_uuid": product_uuid},
        ).mappings().first()
        if not r:
            return None
        return {"id": r["id"], "product_uuid": r["product_uuid"], "fetched_at": r["fetched_at"].isoformat() if r["fetched_at"] else None, "payload": r["payload"]}


def list_baseprice_cache(limit: int = 25) -> list[dict]:
    if DATABASE_URL.startswith("sqlite"):
        import json

        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, product_uuid, fetched_at, payload
                    FROM baseprice_cache
                    ORDER BY fetched_at DESC
                    LIMIT :limit;
                    """
                ),
                {"limit": limit},
            ).mappings().all()
            return [
                {"id": r["id"], "product_uuid": r["product_uuid"], "fetched_at": r["fetched_at"], "payload": json.loads(r["payload"])}
                for r in rows
            ]

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, product_uuid, fetched_at, payload
                FROM baseprice_cache
                ORDER BY fetched_at DESC
                LIMIT :limit;
                """
            ),
            {"limit": limit},
        ).mappings().all()

        return [
            {
                "id": r["id"],
                "product_uuid": r["product_uuid"],
                "fetched_at": r["fetched_at"].isoformat() if r["fetched_at"] else None,
                "payload": r["payload"],
            }
            for r in rows
        ]
