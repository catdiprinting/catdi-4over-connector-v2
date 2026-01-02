from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .db import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    category_uuid = Column(String(64), unique=True, nullable=False, index=True)
    category_name = Column(String(255), nullable=False)
    category_description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    product_uuid = Column(String(64), unique=True, nullable=False, index=True)
    product_code = Column(String(128), nullable=True)
    product_description = Column(Text, nullable=True)
    category_uuid = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    option_groups = relationship("OptionGroup", back_populates="product", cascade="all, delete-orphan")


class OptionGroup(Base):
    __tablename__ = "option_groups"

    id = Column(Integer, primary_key=True)
    product_uuid = Column(String(64), ForeignKey("products.product_uuid"), nullable=False, index=True)

    product_option_group_uuid = Column(String(64), nullable=False)
    product_option_group_name = Column(String(255), nullable=True)
    minoccurs = Column(String(16), nullable=True)
    maxoccurs = Column(String(16), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="option_groups")
    options = relationship("Option", back_populates="option_group", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("product_uuid", "product_option_group_uuid", name="uq_product_group"),
    )


class Option(Base):
    __tablename__ = "options"

    id = Column(Integer, primary_key=True)
    option_group_id = Column(Integer, ForeignKey("option_groups.id"), nullable=False, index=True)

    option_uuid = Column(String(64), nullable=False)
    option_name = Column(String(255), nullable=True)
    option_description = Column(Text, nullable=True)
    capi_name = Column(String(255), nullable=True)
    capi_description = Column(Text, nullable=True)
    option_prices_url = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    option_group = relationship("OptionGroup", back_populates="options")

    __table_args__ = (
        UniqueConstraint("option_group_id", "option_uuid", name="uq_group_option"),
    )
