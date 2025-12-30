# models.py
from sqlalchemy import Column, String, Integer, Boolean, Numeric, ForeignKey, Text
from sqlalchemy.orm import relationship
from db import Base


class Product(Base):
    __tablename__ = "products"

    product_uuid = Column(String, primary_key=True, index=True)
    product_code = Column(String, index=True)
    product_description = Column(Text)

    option_groups = relationship("OptionGroup", back_populates="product", cascade="all, delete-orphan")
    baseprices = relationship("BasePrice", back_populates="product", cascade="all, delete-orphan")


class OptionGroup(Base):
    __tablename__ = "option_groups"

    product_option_group_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid"), index=True)

    name = Column(String)
    minoccurs = Column(Integer, nullable=True)
    maxoccurs = Column(Integer, nullable=True)

    product = relationship("Product", back_populates="option_groups")
    values = relationship("OptionValue", back_populates="group", cascade="all, delete-orphan")


class OptionValue(Base):
    __tablename__ = "option_values"

    product_option_value_uuid = Column(String, primary_key=True, index=True)
    group_uuid = Column(String, ForeignKey("option_groups.product_option_group_uuid"), index=True)

    name = Column(String)
    code = Column(String)
    sort = Column(Integer, nullable=True)

    # helpful denormalized fields for pricing lookups
    runsize_uuid = Column(String, nullable=True)
    runsize = Column(String, nullable=True)
    colorspec_uuid = Column(String, nullable=True)
    colorspec = Column(String, nullable=True)
    turnaroundtime_uuid = Column(String, nullable=True)
    turnaroundtime = Column(String, nullable=True)

    group = relationship("OptionGroup", back_populates="values")


class BasePrice(Base):
    __tablename__ = "baseprices"

    base_price_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid"), index=True)

    product_baseprice = Column(Numeric(18, 6))
    runsize_uuid = Column(String, index=True)
    runsize = Column(String)
    colorspec_uuid = Column(String, index=True)
    colorspec = Column(String)

    can_group_ship = Column(Boolean, default=False)

    product = relationship("Product", back_populates="baseprices")
