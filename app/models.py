# app/models.py
from sqlalchemy import Column, Integer, String, Text, DateTime, func, UniqueConstraint
from .db import Base


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    category_uuid = Column(String(64), nullable=False, unique=True, index=True)
    category_name = Column(String(255), nullable=False)
    category_description = Column(Text, nullable=True)
    products_url = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)

    product_uuid = Column(String(64), nullable=False, index=True)
    product_code = Column(String(128), nullable=True)
    product_description = Column(Text, nullable=True)

    category_uuid = Column(String(64), nullable=True, index=True)

    raw_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("product_uuid", "category_uuid", name="uq_product_uuid_category"),
    )
