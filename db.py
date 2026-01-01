import os
import json
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Text, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import text as sql_text
from sqlalchemy import inspect

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway postgres URLs sometimes start with postgres:// which SQLAlchemy wants as postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class BasepriceCache(Base):
    __tablename__ = "baseprice_cache"

    id = Column(Integer, primary_key=True, index=True)
    product_uuid = Column(String(64), nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, index=True)
    payload_json = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("product_uuid", name="uq_baseprice_cache_product_uuid"),
    )


def ensure_schema() -> dict:
    """
    Idempotent schema ensure + tiny migration for existing tables.
    """
    Base.metadata.create_all(bind=engine)

    # If table existed from older version without fetched_at/payload_json, add them.
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("baseprice_cache")} if insp.has_table("baseprice_cache") else set()

    with engine.begin() as conn:
        if "fetched_at" not in cols:
            conn.execute(sql_text("ALTER TABLE baseprice_cache ADD COLUMN fetched_at TIMESTAMPTZ"))
            conn.execute(sql_text("UPDATE baseprice_cache SET fetched_at = NOW() WHERE fetched_at IS NULL"))

        if "payload_json" not in cols:
            conn.execute(sql_text("ALTER TABLE baseprice_cache ADD COLUMN payload_json TEXT"))
            conn.execute(sql_text("UPDATE baseprice_cache SET payload_json = '{}' WHERE payload_json IS NULL"))

        # Ensure uniqueness (Postgres only; SQLite will ignore/raise)
        # If constraint already exists, this may fail; ignore safely.
        try:
            conn.execute(sql_text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_baseprice_cache_product_uuid_idx ON baseprice_cache(product_uuid)"
            ))
        except Exception:
            pass

    return {"ok": True, "tables": ["baseprice_cache"]}


def insert_baseprice_cache(product_uuid: str, payload: dict) -> int:
    """
    UPSERT: keep exactly 1 row per product_uuid.
    Returns row id.
    """
    now = datetime.now(timezone.utc)
    payload_str = json.dumps(payload)

    db = SessionLocal()
    try:
        row = db.query(BasepriceCache).filter(BasepriceCache.product_uuid == product_uuid).one_or_none()
        if row:
            row.fetched_at = now
            row.payload_json = payload_str
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id

        row = BasepriceCache(
            product_uuid=product_uuid,
            fetched_at=now,
            payload_json=payload_str,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def list_baseprice_cache(limit: int = 25) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (
            db.query(BasepriceCache)
            .order_by(BasepriceCache.fetched_at.desc())
            .limit(limit)
            .all()
        )
        out = []
        for r in rows:
            out.append({
                "id": r.id,
                "product_uuid": r.product_uuid,
                "created_at": r.fetched_at.isoformat() if r.fetched_at else None,
                "payload": json.loads(r.payload_json) if r.payload_json else {},
            })
        return out
    finally:
        db.close()


def latest_baseprice_cache(product_uuid: str) -> dict | None:
    db = SessionLocal()
    try:
        r = (
            db.query(BasepriceCache)
            .filter(BasepriceCache.product_uuid == product_uuid)
            .order_by(BasepriceCache.fetched_at.desc())
            .first()
        )
        if not r:
            return None
        return {
            "id": r.id,
            "product_uuid": r.product_uuid,
            "created_at": r.fetched_at.isoformat() if r.fetched_at else None,
            "payload": json.loads(r.payload_json) if r.payload_json else {},
        }
    finally:
        db.close()
