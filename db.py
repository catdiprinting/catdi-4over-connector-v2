# db.py
import json
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def db_session():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ensure_schema():
    """
    Ensures baseprice_cache exists AND has the 'payload' column.
    This prevents the regression you hit:
    'column "payload" of relation "baseprice_cache" does not exist'
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
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
            )
            # In case table already existed WITHOUT payload:
            conn.execute(
                text(
                    """
                    ALTER TABLE baseprice_cache
                    ADD COLUMN IF NOT EXISTS payload JSONB;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE baseprice_cache
                    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
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
            # SQLite / other: best-effort minimal schema
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
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                pass
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
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            pass

    return {
        "id": r.id,
        "product_uuid": r.product_uuid,
        "payload": payload,
        "created_at": str(r.created_at),
    }
