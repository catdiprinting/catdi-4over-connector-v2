# models.py
from sqlalchemy import Column, Integer, String, Text
from db import Base

class BasePriceCache(Base):
    __tablename__ = "baseprice_cache"

    id = Column(Integer, primary_key=True, index=True)

    # IMPORTANT:
    # index=True creates ix_baseprice_cache_product_uuid automatically.
    # Do NOT also define Index(...) elsewhere for product_uuid.
    product_uuid = Column(String(64), unique=True, nullable=False, index=True)

    payload_json = Column(Text, nullable=False)
