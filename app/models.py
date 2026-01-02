from sqlalchemy import Column, Integer, String, Text, DateTime, func, UniqueConstraint
from app.db import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    category_uuid = Column(String(64), unique=True, index=True, nullable=False)
    category_name = Column(String(255), nullable=False)
    category_description = Column(Text, nullable=True)
    products_url = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    product_uuid = Column(String(64), unique=True, index=True, nullable=False)
    product_code = Column(String(255), index=True, nullable=True)
    product_description = Column(Text, nullable=True)

    # primary category (optional) – for Door Hangers etc.
    category_uuid = Column(String(64), index=True, nullable=True)

    # urls (handy for debugging)
    full_product_path = Column(Text, nullable=True)
    option_groups_url = Column(Text, nullable=True)
    base_prices_url = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PriceBlob(Base):
    """
    Stores pricing responses / option pricing payloads as JSON text.
    This is the scalable approach: keep raw payloads first, normalize later.
    """
    __tablename__ = "price_blobs"
    __table_args__ = (
        UniqueConstraint("product_uuid", "blob_type", "fingerprint", name="uq_priceblob"),
    )

    id = Column(Integer, primary_key=True)
    product_uuid = Column(String(64), index=True, nullable=False)

    # e.g. "baseprices", "product_detail", "option_prices"
    blob_type = Column(String(64), index=True, nullable=False)

    # helps avoid duplicates; can be option_uuid or hash key
    fingerprint = Column(String(255), nullable=False)

    json_text = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
