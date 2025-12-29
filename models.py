from sqlalchemy import Column, String, Integer, Text, DateTime
from sqlalchemy.sql import func
from db import Base

class ProductFeedItem(Base):
    __tablename__ = "product_feed_items"

    id = Column(Integer, primary_key=True, index=True)
    fourover_id = Column(String(64), unique=True, index=True, nullable=False)

    name = Column(String(255), nullable=True)
    raw_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
