import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def _clean_env(v: str | None) -> str | None:
    if v is None:
        return None
    # Strip whitespace + accidental newlines from Railway UI copy/paste
    return v.strip()

DATABASE_URL = _clean_env(os.getenv("DATABASE_URL")) or "sqlite:///./local.db"

# SQLAlchemy expects postgresql:// not postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
