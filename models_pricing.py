# models_pricing.py
from sqlalchemy import Column, String, Integer, Boolean, Numeric, ForeignKey, UniqueConstraint, Index, Text
from sqlalchemy.orm import relationship

from db import Base


class PricingProduct(Base):
    __tablename__ = "pricing_products"

    product_uuid = Column(String, primary_key=True)  # 4over product_uuid
    product_code = Column(String, index=True, nullable=True)
    product_description = Column(Text, nullable=True)

    option_groups = relationship("PricingOptionGroup", back_populates="product", cascade="all, delete-orphan")
    base_prices = relationship("PricingBasePrice", back_populates="product", cascade="all, delete-orphan")


class PricingOptionGroup(Base):
    __tablename__ = "pricing_option_groups"

    product_option_group_uuid = Column(String, primary_key=True)
    product_uuid = Column(String, ForeignKey("pricing_products.product_uuid"), nullable=False, index=True)

    name = Column(String, nullable=False)
    minoccurs = Column(Integer, nullable=True)
    maxoccurs = Column(Integer, nullable=True)

    product = relationship("PricingProduct", back_populates="option_groups")
    options = relationship("PricingOption", back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_pricing_option_groups_product_uuid_name", "product_uuid", "name"),
    )


class PricingOption(Base):
    __tablename__ = "pricing_options"

    option_uuid = Column(String, primary_key=True)
    group_uuid = Column(String, ForeignKey("pricing_option_groups.product_option_group_uuid"), nullable=False, index=True)

    option_name = Column(String, nullable=False)
    option_description = Column(Text, nullable=True)
    capi_name = Column(String, nullable=True)
    capi_description = Column(Text, nullable=True)

    # Some optiongroups (like Turnaround) attach these:
    runsize_uuid = Column(String, nullable=True, index=True)
    runsize = Column(String, nullable=True)
    colorspec_uuid = Column(String, nullable=True, index=True)
    colorspec = Column(String, nullable=True)

    group = relationship("PricingOptionGroup", back_populates="options")

    __table_args__ = (
        Index("ix_pricing_options_group_uuid_name", "group_uuid", "option_name"),
    )


class PricingBasePrice(Base):
    __tablename__ = "pricing_base_prices"

    base_price_uuid = Column(String, primary_key=True)
    product_uuid = Column(String, ForeignKey("pricing_products.product_uuid"), nullable=False, index=True)

    product_baseprice = Column(Numeric(18, 6), nullable=False)

    runsize_uuid = Column(String, nullable=False, index=True)
    runsize = Column(String, nullable=True)

    colorspec_uuid = Column(String, nullable=False, index=True)
    colorspec = Column(String, nullable=True)

    can_group_ship = Column(Boolean, default=False)

    product = relationship("PricingProduct", back_populates="base_prices")

    __table_args__ = (
        UniqueConstraint("product_uuid", "runsize_uuid", "colorspec_uuid", name="uq_price_matrix"),
        Index("ix_price_lookup", "product_uuid", "runsize_uuid", "colorspec_uuid"),
    )
