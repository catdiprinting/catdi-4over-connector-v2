# db.py
import os
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway sometimes uses postgres:// (SQLAlchemy wants postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if is_sqlite else {},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def ensure_schema() -> Dict[str, Any]:
    """
    Idempotent schema creation + lightweight migrations.
    Ensures baseprice_cache exists with:
      - id (pk)
      - product_uuid (unique)
      - fetched_at (timestamp)
      - payload_json (json/text)
    """
    with engine.begin() as conn:
        if is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_uuid TEXT NOT NULL UNIQUE,
                    fetched_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
            """))

            # SQLite "ALTER TABLE ADD COLUMN" is limited but works for adding columns
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(baseprice_cache)")).fetchall()}
            if "fetched_at" not in cols:
                conn.execute(text("ALTER TABLE baseprice_cache ADD COLUMN fetched_at TEXT"))
                conn.execute(text("UPDATE baseprice_cache SET fetched_at = COALESCE(fetched_at, '')"))
            if "payload_json" not in cols:
                conn.execute(text("ALTER TABLE baseprice_cache ADD COLUMN payload_json TEXT"))
                conn.execute(text("UPDATE baseprice_cache SET payload_json = COALESCE(payload_json, '{}')"))

        else:
            # Postgres
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id BIGSERIAL PRIMARY KEY,
                    product_uuid VARCHAR NOT NULL UNIQUE,
                    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    payload_json JSONB NOT NULL
                )
            """))

            # self-heal missing columns if you had an older table
            conn.execute(text("""
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
                        WHERE table_name='baseprice_cache' AND column_name='payload_json'
                    ) THEN
                        ALTER TABLE baseprice_cache ADD COLUMN payload_json JSONB NOT NULL DEFAULT '{}'::jsonb;
                    END IF;
                END$$;
            """))

    return {"ok": True, "tables": ["baseprice_cache"]}


def insert_baseprice_cache(product_uuid: str, payload: Dict[str, Any]) -> int:
    """
    Upsert: one row per product_uuid (prevents duplicates).
    Returns row id.
    """
    ensure_schema()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        if is_sqlite:
            payload_str = json.dumps(payload)
            # SQLite upsert
            conn.execute(
                text("""
                    INSERT INTO baseprice_cache (product_uuid, fetched_at, payload_json)
                    VALUES (:product_uuid, :fetched_at, :payload_json)
                    ON CONFLICT(product_uuid)
                    DO UPDATE SET fetched_at=excluded.fetched_at, payload_json=excluded.payload_json
                """),
                {"product_uuid": product_uuid, "fetched_at": now.isoformat(), "payload_json": payload_str},
            )
            row = conn.execute(
                text("SELECT id FROM baseprice_cache WHERE product_uuid = :product_uuid"),
                {"product_uuid": product_uuid},
            ).fetchone()
            return int(row[0])

        else:
            row = conn.execute(
                text("""
                    INSERT INTO baseprice_cache (product_uuid, fetched_at, payload_json)
                    VALUES (:product_uuid, :fetched_at, CAST(:payload_json AS jsonb))
                    ON CONFLICT (product_uuid)
                    DO UPDATE SET fetched_at = EXCLUDED.fetched_at, payload_json = EXCLUDED.payload_json
                    RETURNING id
                """),
                {"product_uuid": product_uuid, "fetched_at": now, "payload_json": json.dumps(payload)},
            ).fetchone()
            return int(row[0])


def list_baseprice_cache(limit: int = 25) -> List[Dict[str, Any]]:
    ensure_schema()
    with engine.begin() as conn:
        if is_sqlite:
            rows = conn.execute(
                text("""
                    SELECT id, product_uuid, fetched_at, payload_json
                    FROM baseprice_cache
                    ORDER BY id DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            ).fetchall()
            out = []
            for r in rows:
                out.append({
                    "id": int(r[0]),
                    "product_uuid": r[1],
                    "created_at": r[2],
                    "payload": json.loads(r[3]) if r[3] else {},
                })
            return out
        else:
            rows = conn.execute(
                text("""
                    SELECT id, product_uuid, fetched_at, payload_json
                    FROM baseprice_cache
                    ORDER BY fetched_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            ).fetchall()
            return [
                {"id": int(r[0]), "product_uuid": r[1], "created_at": r[2].isoformat(), "payload": r[3]}
                for r in rows
            ]


def latest_baseprice_cache(product_uuid: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with engine.begin() as conn:
        if is_sqlite:
            row = conn.execute(
                text("""
                    SELECT id, product_uuid, fetched_at, payload_json
                    FROM baseprice_cache
                    WHERE product_uuid = :product_uuid
                    ORDER BY id DESC
                    LIMIT 1
                """),
                {"product_uuid": product_uuid},
            ).fetchone()
            if not row:
                return None
            return {
                "id": int(row[0]),
                "product_uuid": row[1],
                "created_at": row[2],
                "payload": json.loads(row[3]) if row[3] else {},
            }

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

        return {
            "id": int(row[0]),
            "product_uuid": row[1],
            "created_at": row[2].isoformat(),
            "payload": row[3],
        }
