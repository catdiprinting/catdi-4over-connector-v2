# models.py
from sqlalchemy import Column, String, Integer, Boolean, Numeric, ForeignKey, Index
from sqlalchemy.orm import relationship
from db import Base

class PricingProduct(Base):
    __tablename__ = "pricing_products"
    product_uuid = Column(String, primary_key=True, index=True)
    product_code = Column(String, nullable=True)
    product_description = Column(String, nullable=True)

class PricingOptionGroup(Base):
    __tablename__ = "pricing_option_groups"
    product_option_group_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, index=True, nullable=False)
    name = Column(String, nullable=True)
    minoccurs = Column(Integer, nullable=True)
    maxoccurs = Column(Integer, nullable=True)

class PricingOption(Base):
    __tablename__ = "pricing_options"
    option_uuid = Column(String, primary_key=True, index=True)
    group_uuid = Column(String, ForeignKey("pricing_option_groups.product_option_group_uuid"), index=True)
    option_name = Column(String, nullable=True)
    option_description = Column(String, nullable=True)
    capi_name = Column(String, nullable=True)
    capi_description = Column(String, nullable=True)

    runsize_uuid = Column(String, nullable=True, index=True)
    runsize = Column(String, nullable=True)

    colorspec_uuid = Column(String, nullable=True, index=True)
    colorspec = Column(String, nullable=True)

class PricingBasePrice(Base):
    __tablename__ = "pricing_baseprices"
    base_price_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, index=True, nullable=False)

    product_baseprice = Column(Numeric(18, 6), nullable=False)

    runsize_uuid = Column(String, nullable=True, index=True)
    runsize = Column(String, nullable=True)

    colorspec_uuid = Column(String, nullable=True, index=True)
    colorspec = Column(String, nullable=True)

    can_group_ship = Column(Boolean, default=False)

Index("ix_bp_product_runsize_colorspec", PricingBasePrice.product_uuid, PricingBasePrice.runsize_uuid, PricingBasePrice.colorspec_uuid)
