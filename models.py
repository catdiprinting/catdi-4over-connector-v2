from sqlalchemy import Column, DateTime, Integer, String, Text, func, Index
from db import Base


class ProductFeedItem(Base):
    __tablename__ = "product_feed_items"

    id = Column(Integer, primary_key=True, index=True)
    product_uuid = Column(String(64), unique=True, nullable=False, index=True)
    raw_json = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_product_feed_items_product_uuid", "product_uuid"),
    )
