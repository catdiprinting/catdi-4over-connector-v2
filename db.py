# db.py
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db").strip()

# Railway often uses postgres:// but SQLAlchemy wants postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# NOTE: do NOT use connect_args unless sqlite
engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

def ensure_schema() -> Dict[str, Any]:
    """
    Idempotent schema create/migrate.
    Creates table baseprice_cache with:
      - one row per product_uuid (UPSERT)
      - fetched_at timestamp
      - payload_json JSON (jsonb for Postgres)
    """
    ddl = """
    CREATE TABLE IF NOT EXISTS baseprice_cache (
        id SERIAL PRIMARY KEY,
        product_uuid VARCHAR(64) NOT NULL UNIQUE,
        fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        payload_json JSONB NOT NULL
    );
    """
    # SQLite fallback (if someone runs locally)
    ddl_sqlite = """
    CREATE TABLE IF NOT EXISTS baseprice_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_uuid TEXT NOT NULL UNIQUE,
        fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
        payload_json TEXT NOT NULL
    );
    """

    with engine.begin() as conn:
        if DATABASE_URL.startswith("sqlite"):
            conn.execute(text(ddl_sqlite))
        else:
            conn.execute(text(ddl))

    return {"ok": True, "tables": ["baseprice_cache"]}

def insert_baseprice_cache(product_uuid: str, payload: Dict[str, Any]) -> int:
    """
    UPSERT: one row per product_uuid.
    Returns the row id (best effort).
    """
    if not product_uuid:
        raise ValueError("product_uuid is required")

    with engine.begin() as conn:
        if DATABASE_URL.startswith("sqlite"):
            # store JSON as string for sqlite
            import json
            payload_str = json.dumps(payload)

            conn.execute(
                text("""
                INSERT INTO baseprice_cache (product_uuid, fetched_at, payload_json)
                VALUES (:product_uuid, datetime('now'), :payload_json)
                ON CONFLICT(product_uuid) DO UPDATE SET
                  fetched_at = excluded.fetched_at,
                  payload_json = excluded.payload_json
                """),
                {"product_uuid": product_uuid, "payload_json": payload_str},
            )
            row = conn.execute(
                text("SELECT id FROM baseprice_cache WHERE product_uuid=:product_uuid"),
                {"product_uuid": product_uuid},
            ).fetchone()
            return int(row[0]) if row else 0

        # Postgres
        row = conn.execute(
            text("""
            INSERT INTO baseprice_cache (product_uuid, fetched_at, payload_json)
            VALUES (:product_uuid, NOW(), :payload_json::jsonb)
            ON CONFLICT (product_uuid) DO UPDATE SET
              fetched_at = EXCLUDED.fetched_at,
              payload_json = EXCLUDED.payload_json
            RETURNING id
            """),
            {"product_uuid": product_uuid, "payload_json": __import__("json").dumps(payload)},
        ).fetchone()

        return int(row[0]) if row else 0

def list_baseprice_cache(limit: int = 25) -> List[Dict[str, Any]]:
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
            SELECT id, product_uuid, fetched_at, payload_json
            FROM baseprice_cache
            ORDER BY fetched_at DESC
            LIMIT :limit
            """),
            {"limit": int(limit)},
        ).fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        payload = r[3]
        # sqlite payload_json is string
        if isinstance(payload, str):
            try:
                payload = __import__("json").loads(payload)
            except Exception:
                payload = {}
        out.append({"id": r[0], "product_uuid": r[1], "created_at": str(r[2]), "payload": payload})
    return out

def latest_baseprice_cache(product_uuid: str) -> Optional[Dict[str, Any]]:
    with engine.begin() as conn:
        row = conn.execute(
            text("""
            SELECT id, product_uuid, fetched_at, payload_json
            FROM baseprice_cache
            WHERE product_uuid = :product_uuid
            ORDER BY fetched_at DESC
            LIMIT 1
            """),
            {"product_uuid": product_uuid},
        ).fetchone()

    if not row:
        return None

    payload = row[3]
    if isinstance(payload, str):
        try:
            payload = __import__("json").loads(payload)
        except Exception:
            payload = {}
    return {"id": row[0], "product_uuid": row[1], "created_at": str(row[2]), "payload": payload}
