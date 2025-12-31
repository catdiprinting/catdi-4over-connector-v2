# db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway sometimes provides postgres:// but SQLAlchemy wants postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}

# SQLite only
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# Postgres (psycopg) connect timeout so the app doesn't hang on boot
if DATABASE_URL.startswith("postgresql://"):
    connect_args = {"connect_timeout": 5}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
