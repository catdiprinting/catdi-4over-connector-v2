# db.py
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL

# SQLAlchemy 2.0 engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _is_postgres() -> bool:
    return engine.dialect.name in ("postgresql", "postgres")


def _dt_to_iso(dt: Any) -> Any:
    if isinstance(dt, datetime):
        # ensure timezone awareness for consistent API output
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return dt


def ensure_schema() -> None:
    """
    Idempotent schema creation.
    Safe to call on every request.
    """
    with engine.begin() as conn:
        if _is_postgres():
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS baseprice_cache (
                        id BIGSERIAL PRIMARY KEY,
                        product_uuid VARCHAR NOT NULL,
                        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
            )

            # indexes (Postgres supports IF NOT EXISTS on CREATE INDEX)
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_baseprice_cache_product_uuid "
                    "ON baseprice_cache (product_uuid);"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_baseprice_cache_created_at "
                    "ON baseprice_cache (created_at DESC);"
                )
            )
        else:
            # SQLite fallback for local/dev
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS baseprice_cache (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_uuid TEXT NOT NULL,
                        payload TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_baseprice_cache_product_uuid "
                    "ON baseprice_cache (product_uuid);"
                )
            )


def insert_baseprice_cache(product_uuid: str, payload: Dict[str, Any]) -> int:
    """
    Insert a new cache row and return its id.
    """
    ensure_schema()

    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    with engine.begin() as conn:
        if _is_postgres():
            # IMPORTANT: use CAST(:payload AS JSONB) instead of :payload::jsonb
            result = conn.execute(
                text(
                    """
                    INSERT INTO baseprice_cache (product_uuid, payload)
                    VALUES (:product_uuid, CAST(:payload AS JSONB))
                    RETURNING id;
                    """
                ),
                {"product_uuid": product_uuid, "payload": payload_json},
            )
            new_id = result.scalar_one()
            return int(new_id)

        # SQLite: store JSON as TEXT
        result = conn.execute(
            text(
                """
                INSERT INTO baseprice_cache (product_uuid, payload)
                VALUES (:product_uuid, :payload);
                """
            ),
            {"product_uuid": product_uuid, "payload": payload_json},
        )
        return int(result.lastrowid)


def list_baseprice_cache(limit: int = 25) -> List[Dict[str, Any]]:
    ensure_schema()

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
            {"limit": int(limit)},
        ).mappings().all()

    entities: List[Dict[str, Any]] = []
    for r in rows:
        payload_val = r["payload"]
        if not _is_postgres():
            # sqlite text -> dict
            try:
                payload_val = json.loads(payload_val or "{}")
            except Exception:
                payload_val = {}

        entities.append(
            {
                "id": r["id"],
                "product_uuid": r["product_uuid"],
                "payload": payload_val if payload_val is not None else {},
                "created_at": _dt_to_iso(r["created_at"]),
            }
        )
    return entities


def latest_baseprice_cache(product_uuid: str) -> Optional[Dict[str, Any]]:
    ensure_schema()

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

    payload_val = row["payload"]
    if not _is_postgres():
        try:
            payload_val = json.loads(payload_val or "{}")
        except Exception:
            payload_val = {}

    return {
        "id": row["id"],
        "product_uuid": row["product_uuid"],
        "payload": payload_val if payload_val is not None else {},
        "created_at": _dt_to_iso(row["created_at"]),
    }


# Optional: FastAPI dependency (handy for pricing_tester/router files)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
