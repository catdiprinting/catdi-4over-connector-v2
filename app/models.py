from sqlalchemy import Column, String, Text, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.db import Base


class Category(Base):
    __tablename__ = "categories"

    category_uuid = Column(String, primary_key=True)
    category_name = Column(String, nullable=False)
    category_description = Column(Text, nullable=True)

    products = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "products"

    product_uuid = Column(String, primary_key=True)
    product_code = Column(String, index=True, nullable=False)
    product_description = Column(Text, nullable=True)

    category_uuid = Column(String, ForeignKey("categories.category_uuid"), nullable=True)
    category = relationship("Category", back_populates="products")

    option_groups = relationship("OptionGroup", back_populates="product", cascade="all, delete-orphan")
    base_prices = relationship("BasePrice", back_populates="product", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_products_category_uuid", "category_uuid"),
    )


class OptionGroup(Base):
    __tablename__ = "option_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid"), nullable=False)

    group_uuid = Column(String, nullable=False)
    group_name = Column(String, nullable=True)
    minoccurs = Column(String, nullable=True)
    maxoccurs = Column(String, nullable=True)

    product = relationship("Product", back_populates="option_groups")
    options = relationship("Option", back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("product_uuid", "group_uuid", name="uq_option_groups_product_groupuuid"),
        Index("ix_option_groups_product_uuid", "product_uuid"),
    )


class Option(Base):
    __tablename__ = "options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("option_groups.id"), nullable=False)

    option_uuid = Column(String, nullable=False)
    option_name = Column(String, nullable=True)
    option_description = Column(Text, nullable=True)

    group = relationship("OptionGroup", back_populates="options")

    __table_args__ = (
        UniqueConstraint("group_id", "option_uuid", name="uq_options_group_optionuuid"),
        Index("ix_options_group_id", "group_id"),
    )


class BasePrice(Base):
    __tablename__ = "base_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid"), nullable=False)

    # store raw row as JSON string for now (scalable + safe)
    # later we can normalize into a true pricing matrix table
    raw_json = Column(Text, nullable=False)

    product = relationship("Product", back_populates="base_prices")

    __table_args__ = (Index("ix_base_prices_product_uuid", "product_uuid"),)
