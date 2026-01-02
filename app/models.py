from sqlalchemy import (
    Column, String, Text, ForeignKey, Numeric, Boolean, Index
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Category(Base):
    __tablename__ = "categories"

    category_uuid = Column(String, primary_key=True)
    category_name = Column(String, nullable=False, default="")
    category_description = Column(Text, nullable=True)


class Product(Base):
    __tablename__ = "products"

    product_uuid = Column(String, primary_key=True)
    product_code = Column(String, nullable=True)
    product_description = Column(Text, nullable=True)


class ProductCategory(Base):
    __tablename__ = "product_categories"

    product_uuid = Column(String, ForeignKey("products.product_uuid"), primary_key=True)
    category_uuid = Column(String, ForeignKey("categories.category_uuid"), primary_key=True)

    product = relationship("Product")
    category = relationship("Category")


class ProductDetail(Base):
    """
    Stores the full JSON response for /printproducts/products/{uuid}
    so we can build calculators without re-fetching constantly.
    """
    __tablename__ = "product_details"

    product_uuid = Column(String, ForeignKey("products.product_uuid"), primary_key=True)
    raw_json = Column(Text, nullable=False)

    product = relationship("Product")


class BasePriceRow(Base):
    """
    Stores each row from /printproducts/products/{uuid}/baseprices
    (the pricing matrix rows).
    """
    __tablename__ = "base_price_rows"

    id = Column(String, primary_key=True)  # we’ll set = base_price_uuid (unique)
    product_uuid = Column(String, ForeignKey("products.product_uuid"), index=True, nullable=False)

    base_price_uuid = Column(String, nullable=False)  # kept for clarity
    product_baseprice = Column(Numeric(12, 4), nullable=False, default=0)

    runsize_uuid = Column(String, nullable=True)
    runsize = Column(String, nullable=True)

    colorspec_uuid = Column(String, nullable=True)
    colorspec = Column(String, nullable=True)

    can_group_ship = Column(Boolean, nullable=True)

    raw_json = Column(Text, nullable=False)

    product = relationship("Product")


Index("ix_base_price_product_uuid", BasePriceRow.product_uuid)
