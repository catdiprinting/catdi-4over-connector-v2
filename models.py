# models.py
from sqlalchemy import Column, Integer, String, Text, Index
from db import Base

class BasePriceCache(Base):
    __tablename__ = "baseprice_cache"

    id = Column(Integer, primary_key=True, index=True)
    product_uuid = Column(String(64), nullable=False, index=True)
    payload_json = Column(Text, nullable=False)  # store raw JSON

Index("ix_baseprice_cache_product_uuid", BasePriceCache.product_uuid)
