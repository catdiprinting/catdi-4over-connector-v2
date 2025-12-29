import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def _clean(s: str) -> str:
    return (s or "").strip().strip('"').strip("'")

DATABASE_URL = _clean(os.getenv("DATABASE_URL", "sqlite:///./local.db"))

# Fix common Railway / legacy prefix
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Ensure we use psycopg (NOT psycopg2)
if DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
