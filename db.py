import os
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_ENGINE: Optional[Engine] = None

def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    _ENGINE = create_engine(database_url, pool_pre_ping=True)
    return _ENGINE

def ping_db() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
