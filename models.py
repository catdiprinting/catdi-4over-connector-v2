from sqlalchemy import Column, String, Integer, Numeric, ForeignKey, Index
from sqlalchemy.orm import relationship
from db import Base


class Product(Base):
    __tablename__ = "products"

    product_uuid = Column(String, primary_key=True)
    product_code = Column(String, nullable=True, index=True)
    product_description = Column(String, nullable=True)

    categories_path = Column(String, nullable=True)
    optiongroups_path = Column(String, nullable=True)
    baseprices_path = Column(String, nullable=True)

    option_groups = relationship("ProductOptionGroup", back_populates="product", cascade="all, delete-orphan")
    baseprices = relationship("ProductBasePrice", back_populates="product", cascade="all, delete-orphan")


class ProductOptionGroup(Base):
    __tablename__ = "product_option_groups"

    product_option_group_uuid = Column(String, primary_key=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid", ondelete="CASCADE"), index=True, nullable=False)

    name = Column(String, nullable=True)
    minoccurs = Column(String, nullable=True)
    maxoccurs = Column(String, nullable=True)

    product = relationship("Product", back_populates="option_groups")
    values = relationship("ProductOptionValue", back_populates="group", cascade="all, delete-orphan")


class ProductOptionValue(Base):
    __tablename__ = "product_option_values"

    product_option_value_uuid = Column(String, primary_key=True)
    product_option_group_uuid = Column(
        String, ForeignKey("product_option_groups.product_option_group_uuid", ondelete="CASCADE"), index=True, nullable=False
    )

    name = Column(String, nullable=True)
    code = Column(String, nullable=True)
    sort = Column(Integer, nullable=True)

    group = relationship("ProductOptionGroup", back_populates="values")


class ProductBasePrice(Base):
    __tablename__ = "product_baseprices"

    product_baseprice_uuid = Column(String, primary_key=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid", ondelete="CASCADE"), index=True, nullable=False)

    quantity = Column(Integer, nullable=True)
    turnaround = Column(String, nullable=True)
    price = Column(Numeric(12, 4), nullable=True)

    product = relationship("Product", back_populates="baseprices")


Index("ix_pov_group_code", ProductOptionValue.product_option_group_uuid, ProductOptionValue.code)
Index("ix_pbp_product_qty", ProductBasePrice.product_uuid, ProductBasePrice.quantity)
