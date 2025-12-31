from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy import JSON
from sqlalchemy.sql import func

Base = declarative_base()


class BasePriceCache(Base):
    __tablename__ = "baseprice_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_uuid = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
