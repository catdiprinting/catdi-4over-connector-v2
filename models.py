# models.py
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Numeric,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from db import Base


class Product(Base):
    __tablename__ = "products"

    product_uuid = Column(String, primary_key=True, index=True)
    product_code = Column(String, index=True)
    product_description = Column(Text)

    full_product_path = Column(Text)
    categories_path = Column(Text)
    optiongroups_path = Column(Text)
    baseprices_path = Column(Text)

    option_groups = relationship("OptionGroup", back_populates="product", cascade="all, delete-orphan")
    base_prices = relationship("BasePrice", back_populates="product", cascade="all, delete-orphan")


class OptionGroup(Base):
    __tablename__ = "option_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid", ondelete="CASCADE"), index=True)

    group_uuid = Column(String, index=True)
    group_name = Column(String, index=True)
    minoccurs = Column(String, nullable=True)
    maxoccurs = Column(String, nullable=True)

    product = relationship("Product", back_populates="option_groups")
    options = relationship("Option", back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("product_uuid", "group_uuid", name="uq_product_group"),
    )


class Option(Base):
    __tablename__ = "options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    option_group_id = Column(Integer, ForeignKey("option_groups.id", ondelete="CASCADE"), index=True)

    option_uuid = Column(String, index=True)
    option_name = Column(String)
    option_description = Column(Text, nullable=True)
    capi_name = Column(String, nullable=True)
    capi_description = Column(Text, nullable=True)

    # Some groups (like Turn Around Time) include these:
    runsize_uuid = Column(String, nullable=True)
    runsize = Column(String, nullable=True)
    colorspec_uuid = Column(String, nullable=True)
    colorspec = Column(String, nullable=True)

    option_prices_path = Column(Text, nullable=True)

    group = relationship("OptionGroup", back_populates="options")

    __table_args__ = (
        UniqueConstraint("option_group_id", "option_uuid", name="uq_group_option"),
    )


class BasePrice(Base):
    __tablename__ = "base_prices"

    base_price_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid", ondelete="CASCADE"), index=True)

    product_baseprice = Column(Numeric(18, 6))  # keep precision
    can_group_ship = Column(Boolean, default=False)

    runsize_uuid = Column(String, index=True)
    runsize = Column(String, index=True)

    colorspec_uuid = Column(String, index=True)
    colorspec = Column(String, index=True)

    product = relationship("Product", back_populates="base_prices")


Index("idx_baseprice_lookup", BasePrice.product_uuid, BasePrice.runsize_uuid, BasePrice.colorspec_uuid)
