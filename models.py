from sqlalchemy import Column, String, Integer, Text, Boolean, Numeric, ForeignKey, Index
from sqlalchemy.orm import relationship
from db import Base


class PricingProduct(Base):
    __tablename__ = "pricing_products"
    product_uuid = Column(String, primary_key=True, index=True)
    product_code = Column(String, nullable=True)
    product_description = Column(Text, nullable=True)

    option_groups = relationship("PricingOptionGroup", back_populates="product", cascade="all, delete-orphan")
    baseprices = relationship("PricingBasePrice", back_populates="product", cascade="all, delete-orphan")


class PricingOptionGroup(Base):
    __tablename__ = "pricing_option_groups"
    product_option_group_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("pricing_products.product_uuid", ondelete="CASCADE"), index=True)

    name = Column(String, nullable=False, default="")
    minoccurs = Column(Integer, nullable=True)
    maxoccurs = Column(Integer, nullable=True)

    product = relationship("PricingProduct", back_populates="option_groups")
    values = relationship("PricingOptionValue", back_populates="group", cascade="all, delete-orphan")


class PricingOptionValue(Base):
    __tablename__ = "pricing_option_values"
    product_option_value_uuid = Column(String, primary_key=True, index=True)
    group_uuid = Column(String, ForeignKey("pricing_option_groups.product_option_group_uuid", ondelete="CASCADE"), index=True)

    name = Column(String, nullable=False, default="")
    code = Column(String, nullable=True)
    sort = Column(Integer, nullable=True)

    group = relationship("PricingOptionGroup", back_populates="values")


class PricingBasePrice(Base):
    __tablename__ = "pricing_baseprices"
    base_price_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("pricing_products.product_uuid", ondelete="CASCADE"), index=True)

    product_baseprice = Column(Numeric(18, 6), nullable=False, default=0)

    runsize_uuid = Column(String, nullable=True, index=True)
    runsize = Column(String, nullable=True)

    colorspec_uuid = Column(String, nullable=True, index=True)
    colorspec = Column(String, nullable=True)

    can_group_ship = Column(Boolean, default=False)

    product = relationship("PricingProduct", back_populates="baseprices")


Index("ix_baseprices_product_runsize_colorspec", PricingBasePrice.product_uuid, PricingBasePrice.runsize_uuid, PricingBasePrice.colorspec_uuid)
