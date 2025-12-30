from sqlalchemy import Column, String, Text, Numeric, Boolean, Index, ForeignKey
from sqlalchemy.orm import relationship
from db import Base


class Product(Base):
    __tablename__ = "products"

    product_uuid = Column(String, primary_key=True, index=True)
    product_code = Column(String, index=True, nullable=True)
    product_description = Column(Text, nullable=True)

    full_product_path = Column(Text, nullable=True)
    categories_path = Column(Text, nullable=True)
    optiongroups_path = Column(Text, nullable=True)
    baseprices_path = Column(Text, nullable=True)

    option_groups = relationship("ProductOptionGroup", cascade="all, delete-orphan", back_populates="product")
    option_values = relationship("ProductOptionValue", cascade="all, delete-orphan", back_populates="product")
    baseprices = relationship("ProductBasePrice", cascade="all, delete-orphan", back_populates="product")


class ProductOptionGroup(Base):
    __tablename__ = "product_option_groups"

    product_option_group_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid", ondelete="CASCADE"), index=True, nullable=False)

    name = Column(String, nullable=True)
    minoccurs = Column(String, nullable=True)
    maxoccurs = Column(String, nullable=True)

    product = relationship("Product", back_populates="option_groups")

Index("ix_pog_product_uuid", ProductOptionGroup.product_uuid)


class ProductOptionValue(Base):
    __tablename__ = "product_option_values"

    option_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid", ondelete="CASCADE"), index=True, nullable=False)
    product_option_group_uuid = Column(String, index=True, nullable=True)

    option_name = Column(String, nullable=True)
    option_description = Column(Text, nullable=True)
    option_prices = Column(Text, nullable=True)

    # helpful for turnaround-time rows
    runsize_uuid = Column(String, nullable=True)
    runsize = Column(String, nullable=True)
    colorspec_uuid = Column(String, nullable=True)
    colorspec = Column(String, nullable=True)

    product = relationship("Product", back_populates="option_values")

Index("ix_pov_product_uuid", ProductOptionValue.product_uuid)
Index("ix_pov_group_uuid", ProductOptionValue.product_option_group_uuid)


class ProductBasePrice(Base):
    __tablename__ = "product_baseprices"

    base_price_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid", ondelete="CASCADE"), index=True, nullable=False)

    product_baseprice = Column(Numeric(18, 6), nullable=True)

    runsize_uuid = Column(String, nullable=True)
    runsize = Column(String, nullable=True)
    colorspec_uuid = Column(String, nullable=True)
    colorspec = Column(String, nullable=True)

    can_group_ship = Column(Boolean, nullable=True)

    product = relationship("Product", back_populates="baseprices")

Index("ix_pbp_product_uuid", ProductBasePrice.product_uuid)
