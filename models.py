# models.py
from sqlalchemy import (
    Column, String, Integer, Numeric, Boolean, ForeignKey,
    UniqueConstraint, Index, Text
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Product(Base):
    __tablename__ = "products"
    product_uuid = Column(String, primary_key=True)
    product_code = Column(String, index=True, nullable=False)
    product_description = Column(Text, nullable=True)

    option_groups = relationship("OptionGroup", back_populates="product", cascade="all, delete-orphan")
    base_prices = relationship("BasePrice", back_populates="product", cascade="all, delete-orphan")


class OptionGroup(Base):
    __tablename__ = "option_groups"
    id = Column(Integer, primary_key=True, autoincrement=True)

    product_uuid = Column(String, ForeignKey("products.product_uuid", ondelete="CASCADE"), nullable=False, index=True)
    group_uuid = Column(String, nullable=False)
    group_name = Column(String, nullable=False)
    minoccurs = Column(Integer, nullable=True)
    maxoccurs = Column(Integer, nullable=True)

    product = relationship("Product", back_populates="option_groups")
    options = relationship("Option", back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("product_uuid", "group_uuid", name="uq_option_groups_product_group"),
        Index("ix_option_groups_product_name", "product_uuid", "group_name"),
    )


class Option(Base):
    __tablename__ = "options"
    id = Column(Integer, primary_key=True, autoincrement=True)

    group_id = Column(Integer, ForeignKey("option_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    option_uuid = Column(String, nullable=False)
    option_name = Column(String, nullable=False)
    option_description = Column(Text, nullable=True)

    # IMPORTANT: Turnaround options are tied to runsize/colorspec (as you saw)
    runsize_uuid = Column(String, nullable=True, index=True)
    colorspec_uuid = Column(String, nullable=True, index=True)

    group = relationship("OptionGroup", back_populates="options")

    __table_args__ = (
        UniqueConstraint("group_id", "option_uuid", name="uq_options_group_option"),
        Index("ix_options_group_name", "group_id", "option_name"),
    )


class BasePrice(Base):
    __tablename__ = "base_prices"
    base_price_uuid = Column(String, primary_key=True)

    product_uuid = Column(String, ForeignKey("products.product_uuid", ondelete="CASCADE"), nullable=False, index=True)
    runsize_uuid = Column(String, nullable=False, index=True)
    runsize = Column(String, nullable=False)

    colorspec_uuid = Column(String, nullable=False, index=True)
    colorspec = Column(String, nullable=False)

    product_baseprice = Column(Numeric(18, 6), nullable=False)
    can_group_ship = Column(Boolean, nullable=True)

    product = relationship("Product", back_populates="base_prices")

    __table_args__ = (
        UniqueConstraint("product_uuid", "runsize_uuid", "colorspec_uuid", name="uq_price_matrix"),
        Index("ix_price_lookup", "product_uuid", "runsize_uuid", "colorspec_uuid"),
    )
