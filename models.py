from sqlalchemy import Column, Integer, String, Text, DateTime, func, UniqueConstraint, Index
from db import Base

class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id = Column(Integer, primary_key=True, index=True)
    # 4over UUID id for the item
    item_id = Column(String(64), nullable=False, unique=True, index=True)

    # Optional metadata
    sku = Column(String(128), nullable=True, index=True)
    name = Column(String(255), nullable=True, index=True)
    category = Column(String(255), nullable=True, index=True)
    status = Column(String(64), nullable=True, index=True)

    # Raw JSON payload (string) so we can re-parse later without re-fetching
    raw_json = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("item_id", name="uq_catalog_items_item_id"),
        Index("ix_catalog_items_name", "name"),
        Index("ix_catalog_items_category", "category"),
    )
