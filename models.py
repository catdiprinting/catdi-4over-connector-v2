# models.py (ROOT)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import Index
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class BasePriceCache(Base):
    __tablename__ = "baseprice_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_uuid: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # JSONB on Postgres; on non-Postgres SQLAlchemy will map JSON reasonably for dev
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)

    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_baseprice_cache_product_uuid", "product_uuid"),
        Index("ix_baseprice_cache_created_at", "created_at"),
    )
