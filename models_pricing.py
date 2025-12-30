from sqlalchemy import Column, String, Integer, Numeric, Boolean, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from db import Base

class PricingProduct(Base):
    __tablename__ = "pricing_products"

    product_uuid = Column(String, primary_key=True, index=True)
    product_code = Column(String, nullable=True, index=True)
    product_description = Column(Text, nullable=True)

    groups = relationship("PricingOptionGroup", back_populates="product", cascade="all, delete-orphan")
    prices = relationship("PricingBasePrice", back_populates="product", cascade="all, delete-orphan")


class PricingOptionGroup(Base):
    __tablename__ = "pricing_option_groups"

    product_option_group_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("pricing_products.product_uuid", ondelete="CASCADE"), index=True, nullable=False)

    name = Column(String, nullable=True)
    minoccurs = Column(Integer, nullable=True)
    maxoccurs = Column(Integer, nullable=True)

    product = relationship("PricingProduct", back_populates="groups")
    options = relationship("PricingOption", back_populates="group", cascade="all, delete-orphan")


class PricingOption(Base):
    __tablename__ = "pricing_options"

    option_uuid = Column(String, primary_key=True, index=True)
    group_uuid = Column(String, ForeignKey("pricing_option_groups.product_option_group_uuid", ondelete="CASCADE"), index=True, nullable=False)

    option_name = Column(String, nullable=True)
    option_description = Column(Text, nullable=True)

    capi_name = Column(String, nullable=True)
    capi_description = Column(Text, nullable=True)

    # Convenience fields (some 4over options carry these)
    runsize_uuid = Column(String, nullable=True, index=True)
    runsize = Column(String, nullable=True)
    colorspec_uuid = Column(String, nullable=True, index=True)
    colorspec = Column(String, nullable=True)

    group = relationship("PricingOptionGroup", back_populates="options")

Index("ix_pricing_options_group_uuid", PricingOption.group_uuid)


class PricingBasePrice(Base):
    __tablename__ = "pricing_base_prices"

    base_price_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("pricing_products.product_uuid", ondelete="CASCADE"), index=True, nullable=False)

    product_baseprice = Column(Numeric(18, 6), nullable=False)

    runsize_uuid = Column(String, nullable=True, index=True)
    runsize = Column(String, nullable=True)

    colorspec_uuid = Column(String, nullable=True, index=True)
    colorspec = Column(String, nullable=True)

    can_group_ship = Column(Boolean, default=False)

    product = relationship("PricingProduct", back_populates="prices")

Index("ix_pricing_base_prices_lookup", PricingBasePrice.product_uuid, PricingBasePrice.runsize_uuid, PricingBasePrice.colorspec_uuid)
