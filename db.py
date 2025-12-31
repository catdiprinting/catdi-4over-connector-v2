from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine

from config import DATABASE_URL

# Railway Postgres URLs sometimes start with postgres:// which SQLAlchemy wants as postgresql://
db_url = DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# IMPORTANT:
# - sqlite needs check_same_thread
# - postgres does NOT
connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}

engine: Engine = create_engine(db_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
