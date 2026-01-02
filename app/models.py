from sqlalchemy import Column, String, Integer, Boolean, Numeric, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.db import Base


class Category(Base):
    __tablename__ = "categories"
    category_uuid = Column(String, primary_key=True, index=True)
    category_name = Column(String, nullable=False)
    category_description = Column(Text, nullable=True)

    products = relationship("ProductCategory", back_populates="category", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"
    product_uuid = Column(String, primary_key=True, index=True)
    product_code = Column(String, nullable=True, index=True)
    product_description = Column(Text, nullable=True)

    details_json = relationship("ProductDetail", back_populates="product", uselist=False, cascade="all, delete-orphan")
    categories = relationship("ProductCategory", back_populates="product", cascade="all, delete-orphan")
    base_prices = relationship("BasePriceRow", back_populates="product", cascade="all, delete-orphan")


class ProductCategory(Base):
    __tablename__ = "product_categories"
    id = Column(Integer, primary_key=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid"), nullable=False)
    category_uuid = Column(String, ForeignKey("categories.category_uuid"), nullable=False)

    product = relationship("Product", back_populates="categories")
    category = relationship("Category", back_populates="products")

    __table_args__ = (
        UniqueConstraint("product_uuid", "category_uuid", name="uq_product_category"),
        Index("ix_product_categories_product_uuid", "product_uuid"),
        Index("ix_product_categories_category_uuid", "category_uuid"),
    )


class ProductDetail(Base):
    """
    Store the entire hydrated product detail payload (options, groups, etc)
    so we can evolve normalization later without losing anything.
    """
    __tablename__ = "product_details"
    product_uuid = Column(String, ForeignKey("products.product_uuid"), primary_key=True)
    raw_json = Column(Text, nullable=False)

    product = relationship("Product", back_populates="details_json")


class BasePriceRow(Base):
    """
    Mirrors 4over /baseprices rows (runsize/colorspec table).
    """
    __tablename__ = "base_price_rows"
    id = Column(Integer, primary_key=True)

    product_uuid = Column(String, ForeignKey("products.product_uuid"), nullable=False, index=True)
    base_price_uuid = Column(String, nullable=False, index=True)

    product_baseprice = Column(Numeric(12, 4), nullable=False)

    runsize_uuid = Column(String, nullable=False, index=True)
    runsize = Column(String, nullable=True, index=True)

    colorspec_uuid = Column(String, nullable=False, index=True)
    colorspec = Column(String, nullable=True, index=True)

    can_group_ship = Column(Boolean, nullable=True)

    raw_json = Column(Text, nullable=True)

    product = relationship("Product", back_populates="base_prices")

    __table_args__ = (
        UniqueConstraint("product_uuid", "base_price_uuid", name="uq_product_base_price_uuid"),
        Index("ix_base_prices_lookup", "product_uuid", "runsize_uuid", "colorspec_uuid"),
    )
