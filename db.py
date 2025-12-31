# db.py
import json
from sqlalchemy import create_engine, text
from config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


def ensure_schema():
    """
    Ensures baseprice_cache exists AND has payload column,
    and fixes old rows where payload accidentally became NULL.
    """
    dialect = engine.dialect.name

    with engine.begin() as conn:
        if dialect == "postgresql":
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

            # If table exists but payload column is missing, add it
            conn.execute(
                text(
                    """
                    ALTER TABLE baseprice_cache
                    ADD COLUMN IF NOT EXISTS payload JSONB;
                    """
                )
            )

            # If created_at missing, add it
            conn.execute(
                text(
                    """
                    ALTER TABLE baseprice_cache
                    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
                    """
                )
            )

            # Backfill any NULLs from earlier drift
            conn.execute(
                text(
                    """
                    UPDATE baseprice_cache
                    SET payload = '{}'::jsonb
                    WHERE payload IS NULL;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE baseprice_cache
                    SET created_at = NOW()
                    WHERE created_at IS NULL;
                    """
                )
            )

            # Enforce NOT NULL + default going forward
            conn.execute(
                text(
                    """
                    ALTER TABLE baseprice_cache
                    ALTER COLUMN payload SET DEFAULT '{}'::jsonb;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE baseprice_cache
                    ALTER COLUMN payload SET NOT NULL;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE baseprice_cache
                    ALTER COLUMN created_at SET DEFAULT NOW();
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE baseprice_cache
                    ALTER COLUMN created_at SET NOT NULL;
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

        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS baseprice_cache (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_uuid TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
            )


def insert_baseprice_cache(product_uuid: str, payload_obj: dict) -> int:
    payload_json = json.dumps(payload_obj)

    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            row = conn.execute(
                text(
                    """
                    INSERT INTO baseprice_cache (product_uuid, payload)
                    VALUES (:product_uuid, CAST(:payload AS jsonb))
                    RETURNING id;
                    """
                ),
                {"product_uuid": product_uuid, "payload": payload_json},
            ).first()
            return int(row[0])
        else:
            row = conn.execute(
                text(
                    """
                    INSERT INTO baseprice_cache (product_uuid, payload)
                    VALUES (:product_uuid, :payload);
                    """
                ),
                {"product_uuid": product_uuid, "payload": payload_json},
            )
            return int(row.lastrowid)


def list_baseprice_cache(limit: int = 25) -> list[dict]:
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
        ).fetchall()

    out = []
    for r in rows:
        payload = r.payload
        if payload is None:
            payload = {}
        elif isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {"raw": payload}

        out.append(
            {
                "id": r.id,
                "product_uuid": r.product_uuid,
                "payload": payload,
                "created_at": str(r.created_at),
            }
        )
    return out


def latest_baseprice_cache(product_uuid: str) -> dict | None:
    with engine.begin() as conn:
        r = conn.execute(
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
        ).first()

    if not r:
        return None

    payload = r.payload
    if payload is None:
        payload = {}
    elif isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {"raw": payload}

    return {
        "id": r.id,
        "product_uuid": r.product_uuid,
        "payload": payload,
        "created_at": str(r.created_at),
    }
