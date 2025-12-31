# db.py (ROOT)
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway Postgres URLs sometimes start with postgres:// which SQLAlchemy wants as postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def ensure_schema() -> None:
    """
    Creates the baseprice_cache table if missing AND adds missing columns/indexes if the table already exists.
    This prevents schema drift issues (like 'payload column does not exist').
    """
    dialect = engine.dialect.name

    with engine.begin() as conn:
        if dialect == "postgresql":
            # 1) Ensure table exists
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS baseprice_cache (
                        id SERIAL PRIMARY KEY,
                        product_uuid VARCHAR NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );
                    """
                )
            )

            # 2) Add missing columns (safe migrations)
            # payload
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name='baseprice_cache' AND column_name='payload'
                        ) THEN
                            ALTER TABLE baseprice_cache ADD COLUMN payload JSONB;
                            UPDATE baseprice_cache SET payload = '{}'::jsonb WHERE payload IS NULL;
                            ALTER TABLE baseprice_cache ALTER COLUMN payload SET NOT NULL;
                        END IF;
                    END$$;
                    """
                )
            )
            # created_at
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name='baseprice_cache' AND column_name='created_at'
                        ) THEN
                            ALTER TABLE baseprice_cache ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();
                        END IF;
                    END$$;
                    """
                )
            )

            # 3) Ensure indexes exist
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
                    ON baseprice_cache (created_at DESC);
                    """
                )
            )

        else:
            # SQLite / fallback (dev only)
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
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_baseprice_cache_product_uuid ON baseprice_cache (product_uuid);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_baseprice_cache_created_at ON baseprice_cache (created_at);"))
