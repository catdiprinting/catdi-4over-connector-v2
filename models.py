from sqlalchemy import Column, Integer, String, DateTime, func, Text, Index, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class BasePriceCache(Base):
    __tablename__ = "baseprice_cache"

    id = Column(Integer, primary_key=True)
    product_uuid = Column(String(64), nullable=False)
    # store the full JSON payload as text (portable across sqlite/postgres)
    payload_json = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("product_uuid", name="uq_baseprice_cache_product_uuid"),
        Index("ix_baseprice_cache_product_uuid", "product_uuid"),
    )
