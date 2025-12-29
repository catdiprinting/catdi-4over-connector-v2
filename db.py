import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Default to your Railway Postgres (but strongly prefer setting DATABASE_URL in Railway Variables)
DEFAULT_DATABASE_URL = "postgresql://postgres:hEiDUmFjYAwMIxVEuQydPfEImKdKcIdA@ballast.proxy.rlwy.net:24014/railway"

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL).strip()

# Railway sometimes uses postgres:// which SQLAlchemy wants as postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
