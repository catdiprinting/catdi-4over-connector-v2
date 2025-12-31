# db.py (ROOT)
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

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
    Idempotent schema creation + tiny migrations.
    This MUST be called by /db/init.
    """
    dialect = engine.dialect.name

    with engine.begin() as conn:
        if dialect == "postgresql":
            # Create table if missing (correct final shape)
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id SERIAL PRIMARY KEY,
                    product_uuid VARCHAR NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """))

            # Add missing columns safely (works even if table exists already)
            conn.execute(text("""
                ALTER TABLE baseprice_cache
                ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;
            """))
            conn.execute(text("""
                ALTER TABLE baseprice_cache
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
            """))

            # Ensure indexes exist
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_baseprice_cache_product_uuid
                ON baseprice_cache (product_uuid);
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_baseprice_cache_created_at
                ON baseprice_cache (created_at DESC);
            """))

        else:
            # SQLite dev fallback
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_uuid TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_baseprice_cache_product_uuid ON baseprice_cache (product_uuid);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_baseprice_cache_created_at ON baseprice_cache (created_at);"))
