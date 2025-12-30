# models.py
from sqlalchemy import Column, String, Integer, Numeric, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship

from db import Base


class Product(Base):
    __tablename__ = "products"

    product_uuid = Column(String, primary_key=True, index=True)
    product_code = Column(String, nullable=True, index=True)
    product_description = Column(Text, nullable=True)

    # store raw API paths (handy for debugging)
    categories_path = Column(Text, nullable=True)
    optiongroups_path = Column(Text, nullable=True)
    baseprices_path = Column(Text, nullable=True)

    option_groups = relationship("ProductOptionGroup", back_populates="product", cascade="all, delete-orphan")
    base_prices = relationship("ProductBasePrice", back_populates="product", cascade="all, delete-orphan")


class ProductOptionGroup(Base):
    __tablename__ = "product_option_groups"

    product_option_group_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid", ondelete="CASCADE"), index=True)

    name = Column(String, nullable=True)
    minoccurs = Column(String, nullable=True)
    maxoccurs = Column(String, nullable=True)

    product = relationship("Product", back_populates="option_groups")
    values = relationship("ProductOptionValue", back_populates="group", cascade="all, delete-orphan")


class ProductOptionValue(Base):
    __tablename__ = "product_option_values"

    product_option_value_uuid = Column(String, primary_key=True, index=True)
    product_option_group_uuid = Column(
        String, ForeignKey("product_option_groups.product_option_group_uuid", ondelete="CASCADE"), index=True
    )

    name = Column(String, nullable=True)
    code = Column(String, nullable=True)
    sort = Column(Integer, nullable=True)

    # optional fields used for pricing matrix (when provided)
    runsize_uuid = Column(String, nullable=True, index=True)
    runsize = Column(String, nullable=True)
    colorspec_uuid = Column(String, nullable=True, index=True)
    colorspec = Column(String, nullable=True)
    turnaround_uuid = Column(String, nullable=True, index=True)
    turnaround = Column(String, nullable=True)

    group = relationship("ProductOptionGroup", back_populates="values")


class ProductBasePrice(Base):
    __tablename__ = "product_baseprices"

    # 4over uses base_price_uuid (you showed this in your curl output)
    base_price_uuid = Column(String, primary_key=True, index=True)

    product_uuid = Column(String, ForeignKey("products.product_uuid", ondelete="CASCADE"), index=True)

    # numeric string from API -> store precisely
    product_baseprice = Column(Numeric(18, 6), nullable=True)

    runsize_uuid = Column(String, nullable=True, index=True)
    runsize = Column(String, nullable=True)

    colorspec_uuid = Column(String, nullable=True, index=True)
    colorspec = Column(String, nullable=True)

    turnaround_uuid = Column(String, nullable=True, index=True)
    turnaround = Column(String, nullable=True)

    can_group_ship = Column(Boolean, nullable=True)

    product = relationship("Product", back_populates="base_prices")
