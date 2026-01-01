import os
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway sometimes gives postgres://; SQLAlchemy expects postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
)

# -------------------------
# Schema
# -------------------------
def ensure_schema() -> None:
    """
    Creates:
      baseprice_cache (1 row per product_uuid; payload_json for debug)
      baseprice_rows  (normalized rows for quoting)
    Safe to call repeatedly.
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
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_baseprice_cache_product_uuid
                ON baseprice_cache(product_uuid)
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS baseprice_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_uuid TEXT NOT NULL,
                    base_price_uuid TEXT NOT NULL,
                    runsize_uuid TEXT,
                    runsize TEXT,
                    colorspec_uuid TEXT,
                    colorspec TEXT,
                    product_baseprice TEXT NOT NULL,  -- keep as text for precision (Decimal-compatible)
                    can_group_ship INTEGER NOT NULL DEFAULT 0,
                    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """))
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_baseprice_rows_key
                ON baseprice_rows(product_uuid, runsize_uuid, colorspec_uuid)
            """))
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_baseprice_rows_base_price_uuid
                ON baseprice_rows(base_price_uuid)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_baseprice_rows_lookup_text
                ON baseprice_rows(product_uuid, runsize, colorspec)
            """))
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
        conn.execute(text("ALTER TABLE baseprice_cache ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()"))
        conn.execute(text("ALTER TABLE baseprice_cache ADD COLUMN IF NOT EXISTS payload_json JSONB NOT NULL DEFAULT '{}'::jsonb"))

        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_baseprice_cache_product_uuid'
                ) THEN
                    ALTER TABLE baseprice_cache
                    ADD CONSTRAINT uq_baseprice_cache_product_uuid UNIQUE (product_uuid);
                END IF;
            END $$;
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS baseprice_rows (
                id BIGSERIAL PRIMARY KEY,
                product_uuid VARCHAR NOT NULL,
                base_price_uuid VARCHAR NOT NULL,
                runsize_uuid VARCHAR,
                runsize VARCHAR,
                colorspec_uuid VARCHAR,
                colorspec VARCHAR,
                product_baseprice NUMERIC(18,6) NOT NULL,
                can_group_ship BOOLEAN NOT NULL DEFAULT false,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_baseprice_rows_key'
                ) THEN
                    ALTER TABLE baseprice_rows
                    ADD CONSTRAINT uq_baseprice_rows_key UNIQUE (product_uuid, runsize_uuid, colorspec_uuid);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_baseprice_rows_base_price_uuid'
                ) THEN
                    ALTER TABLE baseprice_rows
                    ADD CONSTRAINT uq_baseprice_rows_base_price_uuid UNIQUE (base_price_uuid);
                END IF;
            END $$;
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_baseprice_rows_lookup_text
            ON baseprice_rows(product_uuid, runsize, colorspec)
        """))


# -------------------------
# Cache (debug/raw)
# -------------------------
def upsert_baseprice_cache(product_uuid: str, payload: Dict[str, Any]) -> int:
    ensure_schema()

    if IS_SQLITE:
        payload_text = json.dumps(payload)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO baseprice_cache (product_uuid, fetched_at, payload_json)
                VALUES (:product_uuid, datetime('now'), :payload_json)
                ON CONFLICT(product_uuid) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    payload_json = excluded.payload_json
            """), {"product_uuid": product_uuid, "payload_json": payload_text})

            row = conn.execute(text("""
                SELECT id FROM baseprice_cache WHERE product_uuid = :product_uuid
            """), {"product_uuid": product_uuid}).fetchone()
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

        return [{
            "id": r["id"],
            "product_uuid": r["product_uuid"],
            "created_at": r["fetched_at"].isoformat(),
            "payload": r["payload_json"],
        } for r in rows]


# -------------------------
# Normalized rows (quote-ready)
# -------------------------
def replace_baseprice_rows(product_uuid: str, entities: List[Dict[str, Any]]) -> int:
    """
    Writes normalized rows for a product.
    Strategy:
      - delete existing rows for product_uuid
      - insert fresh rows
    This keeps it simple, correct, and avoids "stale rows".
    """
    ensure_schema()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM baseprice_rows WHERE product_uuid = :product_uuid"), {"product_uuid": product_uuid})

        inserted = 0
        for r in entities or []:
            base_price_uuid = r.get("base_price_uuid") or ""
            runsize_uuid = r.get("runsize_uuid")
            runsize = r.get("runsize")
            colorspec_uuid = r.get("colorspec_uuid")
            colorspec = r.get("colorspec")
            product_baseprice = r.get("product_baseprice")
            can_group_ship = bool(r.get("can_group_ship", False))

            if not base_price_uuid or product_baseprice is None:
                continue

            if IS_SQLITE:
                conn.execute(text("""
                    INSERT INTO baseprice_rows
                    (product_uuid, base_price_uuid, runsize_uuid, runsize, colorspec_uuid, colorspec, product_baseprice, can_group_ship, fetched_at)
                    VALUES
                    (:product_uuid, :base_price_uuid, :runsize_uuid, :runsize, :colorspec_uuid, :colorspec, :product_baseprice, :can_group_ship, datetime('now'))
                """), {
                    "product_uuid": product_uuid,
                    "base_price_uuid": base_price_uuid,
                    "runsize_uuid": runsize_uuid,
                    "runsize": runsize,
                    "colorspec_uuid": colorspec_uuid,
                    "colorspec": colorspec,
                    "product_baseprice": str(product_baseprice),
                    "can_group_ship": 1 if can_group_ship else 0,
                })
            else:
                conn.execute(text("""
                    INSERT INTO baseprice_rows
                    (product_uuid, base_price_uuid, runsize_uuid, runsize, colorspec_uuid, colorspec, product_baseprice, can_group_ship, fetched_at)
                    VALUES
                    (:product_uuid, :base_price_uuid, :runsize_uuid, :runsize, :colorspec_uuid, :colorspec, :product_baseprice::numeric, :can_group_ship, now())
                """), {
                    "product_uuid": product_uuid,
                    "base_price_uuid": base_price_uuid,
                    "runsize_uuid": runsize_uuid,
                    "runsize": runsize,
                    "colorspec_uuid": colorspec_uuid,
                    "colorspec": colorspec,
                    "product_baseprice": str(product_baseprice),
                    "can_group_ship": can_group_ship,
                })

            inserted += 1

        return inserted


def get_runsizes_and_colorspecs(product_uuid: str) -> Dict[str, Any]:
    ensure_schema()
    with engine.begin() as conn:
        if IS_SQLITE:
            runs = conn.execute(text("""
                SELECT DISTINCT runsize_uuid, runsize
                FROM baseprice_rows
                WHERE product_uuid = :product_uuid AND runsize IS NOT NULL
                ORDER BY CAST(runsize AS INTEGER)
            """), {"product_uuid": product_uuid}).fetchall()

            cols = conn.execute(text("""
                SELECT DISTINCT colorspec_uuid, colorspec
                FROM baseprice_rows
                WHERE product_uuid = :product_uuid AND colorspec IS NOT NULL
            """), {"product_uuid": product_uuid}).fetchall()

            return {
                "runsizes": [{"runsize_uuid": r[0], "runsize": r[1]} for r in runs],
                "colorspecs": [{"colorspec_uuid": c[0], "colorspec": c[1]} for c in cols],
            }

        runs = conn.execute(text("""
            SELECT DISTINCT runsize_uuid, runsize
            FROM baseprice_rows
            WHERE product_uuid = :product_uuid AND runsize IS NOT NULL
            ORDER BY (runsize::int)
        """), {"product_uuid": product_uuid}).mappings().all()

        cols = conn.execute(text("""
            SELECT DISTINCT colorspec_uuid, colorspec
            FROM baseprice_rows
            WHERE product_uuid = :product_uuid AND colorspec IS NOT NULL
        """), {"product_uuid": product_uuid}).mappings().all()

        return {
            "runsizes": [{"runsize_uuid": r["runsize_uuid"], "runsize": r["runsize"]} for r in runs],
            "colorspecs": [{"colorspec_uuid": c["colorspec_uuid"], "colorspec": c["colorspec"]} for c in cols],
        }


def find_baseprice_row(
    product_uuid: str,
    runsize: Optional[str] = None,
    colorspec: Optional[str] = None,
    runsize_uuid: Optional[str] = None,
    colorspec_uuid: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with engine.begin() as conn:
        if runsize_uuid and colorspec_uuid:
            q = """
                SELECT product_uuid, runsize_uuid, runsize, colorspec_uuid, colorspec, product_baseprice, can_group_ship, base_price_uuid
                FROM baseprice_rows
                WHERE product_uuid = :product_uuid
                  AND runsize_uuid = :runsize_uuid
                  AND colorspec_uuid = :colorspec_uuid
                LIMIT 1
            """
            params = {"product_uuid": product_uuid, "runsize_uuid": runsize_uuid, "colorspec_uuid": colorspec_uuid}
        else:
            q = """
                SELECT product_uuid, runsize_uuid, runsize, colorspec_uuid, colorspec, product_baseprice, can_group_ship, base_price_uuid
                FROM baseprice_rows
                WHERE product_uuid = :product_uuid
                  AND runsize = :runsize
                  AND colorspec = :colorspec
                LIMIT 1
            """
            params = {"product_uuid": product_uuid, "runsize": str(runsize), "colorspec": str(colorspec)}

        if IS_SQLITE:
            r = conn.execute(text(q), params).fetchone()
            if not r:
                return None
            return {
                "product_uuid": r[0],
                "runsize_uuid": r[1],
                "runsize": r[2],
                "colorspec_uuid": r[3],
                "colorspec": r[4],
                "product_baseprice": str(r[5]),
                "can_group_ship": bool(r[6]),
                "base_price_uuid": r[7],
            }

        r = conn.execute(text(q), params).mappings().first()
        if not r:
            return None
        return {
            "product_uuid": r["product_uuid"],
            "runsize_uuid": r["runsize_uuid"],
            "runsize": r["runsize"],
            "colorspec_uuid": r["colorspec_uuid"],
            "colorspec": r["colorspec"],
            "product_baseprice": str(r["product_baseprice"]),
            "can_group_ship": bool(r["can_group_ship"]),
            "base_price_uuid": r["base_price_uuid"],
        }
