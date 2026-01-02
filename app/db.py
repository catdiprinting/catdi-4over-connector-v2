from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .config import DATABASE_URL

_engine = None
SessionLocal = None

def _init_engine():
    global _engine, SessionLocal
    if _engine is not None:
        return

    if not DATABASE_URL:
        # No DB configured; don't crash app
        _engine = None
        SessionLocal = None
        return

    db_url = DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    _engine = create_engine(db_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=_engine)

def ping_db():
    _init_engine()
    if _engine is None:
        raise RuntimeError("DATABASE_URL is not set for this service.")
    with _engine.connect() as conn:
        conn.execute(text("SELECT 1"))
