from sqlalchemy import Column, String, Integer, Numeric, Boolean, ForeignKey, Index
from db import Base

class PricingProduct(Base):
    __tablename__ = "pricing_products"

    product_uuid = Column(String, primary_key=True)
    product_code = Column(String)
    product_description = Column(String)


class PricingOptionGroup(Base):
    __tablename__ = "pricing_option_groups"

    product_option_group_uuid = Column(String, primary_key=True)
    product_uuid = Column(String, ForeignKey("pricing_products.product_uuid"), index=True)
    name = Column(String)
    minoccurs = Column(Integer, nullable=True)
    maxoccurs = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_pricing_option_groups_product_uuid", "product_uuid"),
    )


class PricingOption(Base):
    __tablename__ = "pricing_options"

    option_uuid = Column(String, primary_key=True)
    group_uuid = Column(String, ForeignKey("pricing_option_groups.product_option_group_uuid"), index=True)

    option_name = Column(String)
    option_description = Column(String, nullable=True)

    capi_name = Column(String, nullable=True)
    capi_description = Column(String, nullable=True)

    runsize_uuid = Column(String, nullable=True, index=True)
    runsize = Column(String, nullable=True)

    colorspec_uuid = Column(String, nullable=True, index=True)
    colorspec = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_pricing_options_group_uuid", "group_uuid"),
    )


class PricingBasePrice(Base):
    __tablename__ = "pricing_base_prices"

    base_price_uuid = Column(String, primary_key=True)
    product_uuid = Column(String, ForeignKey("pricing_products.product_uuid"), index=True)

    product_baseprice = Column(Numeric(18, 6), nullable=False)

    runsize_uuid = Column(String, nullable=True, index=True)
    runsize = Column(String, nullable=True)

    colorspec_uuid = Column(String, nullable=True, index=True)
    colorspec = Column(String, nullable=True)

    can_group_ship = Column(Boolean, default=False)

    __table_args__ = (
        Index("ix_pricing_base_prices_product_uuid", "product_uuid"),
        Index("ix_pricing_base_prices_combo", "product_uuid", "runsize_uuid", "colorspec_uuid"),
    )
