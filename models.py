# models.py
from sqlalchemy import Column, Integer, String, Text
from db import Base


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id = Column(Integer, primary_key=True, index=True)
    product_uuid = Column(String(64), unique=True, index=True, nullable=False)
    product_code = Column(String(128), nullable=True)
    description = Column(Text, nullable=True)
