from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, Mapped, mapped_column

Base = declarative_base()


class BasePriceCache(Base):
    """
    ONE row per product_uuid.
    We UPSERT this row on each import so you never get duplicates.
    """
    __tablename__ = "baseprice_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_uuid: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class BasePriceRow(Base):
    """
    Normalized rows for fast quoting: one row per (product_uuid, runsize_uuid, colorspec_uuid).
    """
    __tablename__ = "baseprice_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    product_uuid: Mapped[str] = mapped_column(String, nullable=False, index=True)

    runsize_uuid: Mapped[str] = mapped_column(String, nullable=False)
    runsize: Mapped[str] = mapped_column(String, nullable=False)

    colorspec_uuid: Mapped[str] = mapped_column(String, nullable=False)
    colorspec: Mapped[str] = mapped_column(String, nullable=False)

    base_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    can_group_ship: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("product_uuid", "runsize_uuid", "colorspec_uuid", name="uq_price_combo"),
        Index("ix_price_lookup", "product_uuid", "runsize", "colorspec"),
    )
