# db.py
from __future__ import annotations

import os
import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway sometimes uses postgres:// which SQLAlchemy wants as postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


def _is_sqlite() -> bool:
    return DATABASE_URL.startswith("sqlite")


def ensure_schema() -> None:
    """
    Idempotent schema setup + schema healing.
    IMPORTANT: This function must never crash the app.
    """
    try:
        if _is_sqlite():
            _ensure_sqlite_schema()
        else:
            _ensure_postgres_schema()
    except Exception as e:
        # Don't hard-crash the service on schema check;
        # raise so /db/init shows the error clearly.
        raise RuntimeError(f"ensure_schema failed: {e}") from e


def _ensure_postgres_schema() -> None:
    with engine.begin() as conn:
        # 1) Create table if missing (new standard schema)
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id BIGSERIAL PRIMARY KEY,
                    product_uuid VARCHAR NOT NULL,
                    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb
                );
                """
            )
        )

        # 2) Add missing columns safely (older deployments)
        # NOTE: We purposely ignore errors if column already exists.
        _try(conn, "ALTER TABLE baseprice_cache ADD COLUMN fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW();")
        _try(conn, "ALTER TABLE baseprice_cache ADD COLUMN payload JSONB NOT NULL DEFAULT '{}'::jsonb;")

        # 3) Ensure unique constraint (for UPSERT by product_uuid)
        # If duplicates exist historically, this will fail — but we handle that by de-duping first.
        _dedupe_product_uuid(conn)
        _try(conn, "ALTER TABLE baseprice_cache ADD CONSTRAINT uq_baseprice_cache_product_uuid UNIQUE (product_uuid);")


def _dedupe_product_uuid(conn) -> None:
    """
    If previous code inserted duplicates, the UNIQUE constraint will fail.
    This keeps the most recent fetched_at row for each product_uuid and deletes the rest.
    Safe to run repeatedly.
    """
    try:
        conn.execute(
            text(
                """
                DELETE FROM baseprice_cache a
                USING baseprice_cache b
                WHERE a.product_uuid = b.product_uuid
                  AND a.id < b.id;
                """
            )
        )
    except Exception:
        # If table shape is weird or dialect doesn't support USING, ignore.
        pass


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


def _try(conn, sql: str) -> None:
    """
    Execute SQL and ignore 'already exists' / duplicate / undefined issues.
    Keeps schema healing from crashing the app.
    """
    try:
        conn.execute(text(sql))
    except Exception:
        # Intentionally swallow; we only want this to be best-effort.
        pass


def upsert_baseprice_cache(product_uuid: str, payload: dict) -> dict:
    if _is_sqlite():
        return _sqlite_upsert(product_uuid, payload)
    return _pg_upsert(product_uuid, payload)


def _pg_upsert(product_uuid: str, payload: dict) -> dict:
    """
    Use json.dumps(payload) then Postgres casts with ::jsonb in SQL (more reliable than CAST(:payload AS jsonb)).
    """
    payload_str = json.dumps(payload)

    with engine.begin() as conn:
        r = conn.execute(
            text(
                """
                INSERT INTO baseprice_cache (product_uuid, payload, fetched_at)
                VALUES (:product_uuid, (:payload)::jsonb, NOW())
                ON CONFLICT (product_uuid)
                DO UPDATE SET payload = EXCLUDED.payload, fetched_at = NOW()
                RETURNING id, product_uuid, fetched_at, payload;
                """
            ),
            {"product_uuid": product_uuid, "payload": payload_str},
        ).mappings().first()

        return {
            "id": r["id"],
            "product_uuid": r["product_uuid"],
            "fetched_at": r["fetched_at"].isoformat() if r["fetched_at"] else None,
            "payload": r["payload"],
        }


def _sqlite_upsert(product_uuid: str, payload: dict) -> dict:
    fetched_at = datetime.now(timezone.utc).isoformat()
    payload_str = json.dumps(payload)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO baseprice_cache (product_uuid, fetched_at, payload)
                VALUES (:product_uuid, :fetched_at, :payload);
                """
            ),
            {"product_uuid": product_uuid, "fetched_at": fetched_at, "payload": payload_str},
        )

        r = conn.execute(
            text(
                """
                SELECT id, product_uuid, fetched_at, payload
                FROM baseprice_cache
                WHERE product_uuid = :product_uuid
                LIMIT 1;
                """
            ),
            {"product_uuid": product_uuid},
        ).mappings().first()

        return {
            "id": r["id"],
            "product_uuid": r["product_uuid"],
            "fetched_at": r["fetched_at"],
            "payload": json.loads(r["payload"]),
        }


def latest_baseprice_cache(product_uuid: str) -> dict | None:
    ensure_schema()

    if _is_sqlite():
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

            return {
                "id": r["id"],
                "product_uuid": r["product_uuid"],
                "fetched_at": r["fetched_at"],
                "payload": json.loads(r["payload"]),
            }

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

        return {
            "id": r["id"],
            "product_uuid": r["product_uuid"],
            "fetched_at": r["fetched_at"].isoformat() if r["fetched_at"] else None,
            "payload": r["payload"],
        }


def list_baseprice_cache(limit: int = 25) -> list[dict]:
    ensure_schema()

    if _is_sqlite():
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
                    "fetched_at": r["fetched_at"],
                    "payload": json.loads(r["payload"]),
                }
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
