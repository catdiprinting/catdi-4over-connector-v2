# db.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Generator

from sqlalchemy import (
    create_engine,
    Column,
    DateTime,
    Integer,
    String,
    func,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.types import JSON

from config import DATABASE_URL

# Normalize postgres:// to postgresql:// for SQLAlchemy
db_url = DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

connect_args = {}
if db_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    db_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class BasepriceCache(Base):
    __tablename__ = "baseprice_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_uuid = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, nullable=True)  # MUST exist (this is what was failing)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema() -> None:
    """
    Idempotent schema setup + lightweight migration to add payload column if missing.
    This fixes: column "payload" of relation "baseprice_cache" does not exist
    """
    Base.metadata.create_all(bind=engine)

    insp = inspect(engine)
    if "baseprice_cache" not in insp.get_table_names():
        return

    cols = {c["name"] for c in insp.get_columns("baseprice_cache")}
    if "payload" not in cols:
        # Add payload column without dropping table (safe migration)
        with engine.begin() as conn:
            if db_url.startswith("postgresql://"):
                conn.execute(text("ALTER TABLE baseprice_cache ADD COLUMN payload JSONB NULL"))
            else:
                conn.execute(text("ALTER TABLE baseprice_cache ADD COLUMN payload JSON NULL"))


def insert_baseprice_cache(product_uuid: str, payload: dict[str, Any]) -> int:
    ensure_schema()
    db = SessionLocal()
    try:
        row = BasepriceCache(product_uuid=product_uuid, payload=payload)
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def list_baseprice_cache(limit: int = 25) -> list[dict[str, Any]]:
    ensure_schema()
    db = SessionLocal()
    try:
        rows = (
            db.query(BasepriceCache)
            .order_by(BasepriceCache.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "product_uuid": r.product_uuid,
                "payload": r.payload,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()


def latest_baseprice_cache(product_uuid: str) -> dict[str, Any] | None:
    ensure_schema()
    db = SessionLocal()
    try:
        r = (
            db.query(BasepriceCache)
            .filter(BasepriceCache.product_uuid == product_uuid)
            .order_by(BasepriceCache.id.desc())
            .first()
        )
        if not r:
            return None
        return {
            "id": r.id,
            "product_uuid": r.product_uuid,
            "payload": r.payload,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
    finally:
        db.close()
