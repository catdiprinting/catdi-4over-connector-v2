# models.py
from sqlalchemy import Column, Integer, String, DateTime, func, Index
from sqlalchemy.types import JSON
from db import Base


class FourOverProductsFeed(Base):
    __tablename__ = "fourover_productsfeed"

    id = Column(Integer, primary_key=True, index=True)
    product_uuid = Column(String, nullable=False, unique=True, index=True)

    # store the entire item payload from the API
    payload = Column(JSON, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


Index("ix_fourover_productsfeed_product_uuid", FourOverProductsFeed.product_uuid)
