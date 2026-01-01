import os
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway sometimes provides postgres:// (SQLAlchemy expects postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


class BasePriceCache(Base):
    __tablename__ = "baseprice_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_uuid = Column(String(64), nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    payload_json = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("product_uuid", name="uq_baseprice_cache_product_uuid"),
    )


def ensure_schema():
    """
    Safe, idempotent schema creation + minimal migrations.
    Prevents your 'fetched_at does not exist' crash.
    """
    Base.metadata.create_all(bind=engine)

    # Minimal migration for older tables missing columns
    with engine.begin() as conn:
        # Check columns
        cols = set()
        if DATABASE_URL.startswith("sqlite"):
            rows = conn.execute(text("PRAGMA table_info(baseprice_cache)")).fetchall()
            cols = {r[1] for r in rows}
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='baseprice_cache'
                    """
                )
            ).fetchall()
            cols = {r[0] for r in rows}

        if "fetched_at" not in cols:
            conn.execute(text("ALTER TABLE baseprice_cache ADD COLUMN fetched_at TIMESTAMPTZ"))
            conn.execute(text("UPDATE baseprice_cache SET fetched_at = NOW() WHERE fetched_at IS NULL"))

        if "payload_json" not in cols:
            conn.execute(text("ALTER TABLE baseprice_cache ADD COLUMN payload_json TEXT"))
            conn.execute(text("UPDATE baseprice_cache SET payload_json = '{}' WHERE payload_json IS NULL"))


def upsert_baseprice_cache(product_uuid: str, payload_json: str) -> int:
    """
    One row per product_uuid. Replaces duplicates with updates.
    Works on Postgres + SQLite.
    Returns the row id.
    """
    ensure_schema()

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        existing = db.query(BasePriceCache).filter(BasePriceCache.product_uuid == product_uuid).first()
        if existing:
            existing.payload_json = payload_json
            existing.fetched_at = now
            db.commit()
            db.refresh(existing)
            return existing.id

        row = BasePriceCache(product_uuid=product_uuid, payload_json=payload_json, fetched_at=now)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def list_baseprice_cache(limit: int = 25):
    ensure_schema()
    db = SessionLocal()
    try:
        rows = (
            db.query(BasePriceCache)
            .order_by(BasePriceCache.fetched_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "product_uuid": r.product_uuid,
                "created_at": r.fetched_at.isoformat(),
            }
            for r in rows
        ]
    finally:
        db.close()


def latest_baseprice_cache(product_uuid: str):
    ensure_schema()
    db = SessionLocal()
    try:
        r = (
            db.query(BasePriceCache)
            .filter(BasePriceCache.product_uuid == product_uuid)
            .order_by(BasePriceCache.fetched_at.desc())
            .first()
        )
        if not r:
            return None
        return {
            "id": r.id,
            "product_uuid": r.product_uuid,
            "created_at": r.fetched_at.isoformat(),
            "payload_json": r.payload_json,
        }
    finally:
        db.close()
