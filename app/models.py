from sqlalchemy import Column, String, Integer, Text, DateTime, func, Index
from app.db import Base


class Category(Base):
    __tablename__ = "categories"

    category_uuid = Column(String, primary_key=True)
    category_name = Column(String, nullable=False)
    category_description = Column(String, nullable=True)
    products_url = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Product(Base):
    __tablename__ = "products"

    product_uuid = Column(String, primary_key=True)
    product_code = Column(String, nullable=True, index=True)
    product_description = Column(Text, nullable=True)

    # category (denormalized quick filter)
    category_uuid = Column(String, nullable=True, index=True)

    # store the full product JSON from /printproducts/products/{uuid}
    detail_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PriceBlob(Base):
    """
    Cache raw price JSON responses from 4over option price URLs.
    This avoids guessing the matrix schema too early.
    """
    __tablename__ = "price_blobs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    product_uuid = Column(String, nullable=False, index=True)
    option_prices_url = Column(Text, nullable=False)
    price_json = Column(Text, nullable=False)

    fetched_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_price_blobs_product_url", "product_uuid", "option_prices_url"),
    )
