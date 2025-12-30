# models_pricing.py
from sqlalchemy import Column, String, Integer, Numeric, Boolean
from db import Base


class PricingProduct(Base):
    __tablename__ = "pricing_products"

    product_uuid = Column(String, primary_key=True)
    product_code = Column(String)
    product_description = Column(String)


class PricingOptionGroup(Base):
    __tablename__ = "pricing_option_groups"

    product_option_group_uuid = Column(String, primary_key=True)
    product_uuid = Column(String, index=True)
    name = Column(String)
    minoccurs = Column(Integer)
    maxoccurs = Column(Integer)


class PricingOption(Base):
    __tablename__ = "pricing_options"

    option_uuid = Column(String, primary_key=True)
    group_uuid = Column(String, index=True)
    option_name = Column(String)
    option_description = Column(String)
    runsize_uuid = Column(String)
    runsize = Column(String)
    colorspec_uuid = Column(String)
    colorspec = Column(String)


class PricingBasePrice(Base):
    __tablename__ = "pricing_baseprices"

    base_price_uuid = Column(String, primary_key=True)
    product_uuid = Column(String, index=True)
    product_baseprice = Column(Numeric)
    runsize_uuid = Column(String)
    runsize = Column(String)
    colorspec_uuid = Column(String)
    colorspec = Column(String)
    can_group_ship = Column(Boolean, default=False)
