import os
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway sometimes provides postgres:// which SQLAlchemy wants as postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
)


def ensure_schema() -> None:
    """
    Idempotent schema setup. Works on Postgres; best-effort on SQLite for local dev.
    Creates:
      baseprice_cache(product_uuid UNIQUE, fetched_at, payload_json)
    """
    with engine.begin() as conn:
        if IS_SQLITE:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_uuid TEXT NOT NULL,
                    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
                    payload_json TEXT NOT NULL DEFAULT '{}'
                )
            """))
            # SQLite: enforce uniqueness via index
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_baseprice_cache_product_uuid ON baseprice_cache(product_uuid)"))
            return

        # Postgres
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS baseprice_cache (
                id BIGSERIAL PRIMARY KEY,
                product_uuid VARCHAR NOT NULL,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb
            )
        """))

        # Add missing columns if older table exists (schema drift protection)
        conn.execute(text("ALTER TABLE baseprice_cache ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()"))
        conn.execute(text("ALTER TABLE baseprice_cache ADD COLUMN IF NOT EXISTS payload_json JSONB NOT NULL DEFAULT '{}'::jsonb"))

        # Unique constraint (one row per product)
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_baseprice_cache_product_uuid'
                ) THEN
                    ALTER TABLE baseprice_cache
                    ADD CONSTRAINT uq_baseprice_cache_product_uuid UNIQUE (product_uuid);
                END IF;
            END $$;
        """))


def upsert_baseprice_cache(product_uuid: str, payload: Dict[str, Any]) -> int:
    """
    Writes exactly one row per product_uuid. Returns the row id.
    """
    ensure_schema()

    if IS_SQLITE:
        payload_text = json.dumps(payload)
        with engine.begin() as conn:
            # SQLite UPSERT
            conn.execute(text("""
                INSERT INTO baseprice_cache (product_uuid, fetched_at, payload_json)
                VALUES (:product_uuid, datetime('now'), :payload_json)
                ON CONFLICT(product_uuid) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    payload_json = excluded.payload_json
            """), {"product_uuid": product_uuid, "payload_json": payload_text})

            row = conn.execute(text("SELECT id FROM baseprice_cache WHERE product_uuid = :product_uuid"), {"product_uuid": product_uuid}).fetchone()
            return int(row[0])

    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO baseprice_cache (product_uuid, fetched_at, payload_json)
            VALUES (:product_uuid, now(), :payload_json::jsonb)
            ON CONFLICT (product_uuid) DO UPDATE SET
                fetched_at = EXCLUDED.fetched_at,
                payload_json = EXCLUDED.payload_json
            RETURNING id
        """), {"product_uuid": product_uuid, "payload_json": json.dumps(payload)}).fetchone()

        return int(row[0])


def list_baseprice_cache(limit: int = 25) -> List[Dict[str, Any]]:
    ensure_schema()
    with engine.begin() as conn:
        if IS_SQLITE:
            rows = conn.execute(text("""
                SELECT id, product_uuid, fetched_at, payload_json
                FROM baseprice_cache
                ORDER BY fetched_at DESC
                LIMIT :limit
            """), {"limit": limit}).fetchall()

            out = []
            for r in rows:
                out.append({
                    "id": r[0],
                    "product_uuid": r[1],
                    "created_at": r[2],
                    "payload": json.loads(r[3] or "{}"),
                })
            return out

        rows = conn.execute(text("""
            SELECT id, product_uuid, fetched_at, payload_json
            FROM baseprice_cache
            ORDER BY fetched_at DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()

        return [
            {
                "id": r["id"],
                "product_uuid": r["product_uuid"],
                "created_at": r["fetched_at"].isoformat(),
                "payload": r["payload_json"],
            }
            for r in rows
        ]


def latest_baseprice_cache(product_uuid: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with engine.begin() as conn:
        if IS_SQLITE:
            r = conn.execute(text("""
                SELECT id, product_uuid, fetched_at, payload_json
                FROM baseprice_cache
                WHERE product_uuid = :product_uuid
                LIMIT 1
            """), {"product_uuid": product_uuid}).fetchone()
            if not r:
                return None
            return {
                "id": r[0],
                "product_uuid": r[1],
                "created_at": r[2],
                "payload": json.loads(r[3] or "{}"),
            }

        r = conn.execute(text("""
            SELECT id, product_uuid, fetched_at, payload_json
            FROM baseprice_cache
            WHERE product_uuid = :product_uuid
            ORDER BY fetched_at DESC
            LIMIT 1
        """), {"product_uuid": product_uuid}).mappings().first()

        if not r:
            return None

        return {
            "id": r["id"],
            "product_uuid": r["product_uuid"],
            "created_at": r["fetched_at"].isoformat(),
            "payload": r["payload_json"],
        }
