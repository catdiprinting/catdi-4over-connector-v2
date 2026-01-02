from sqlalchemy import Column, String, Integer, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db import Base

class Category(Base):
    __tablename__ = "categories"
    category_uuid = Column(String, primary_key=True, index=True)
    category_name = Column(String, nullable=False)
    category_description = Column(Text, nullable=True)

class Product(Base):
    __tablename__ = "products"
    product_uuid = Column(String, primary_key=True, index=True)
    product_code = Column(String, nullable=True, index=True)
    product_description = Column(Text, nullable=True)

    category_uuid = Column(String, ForeignKey("categories.category_uuid"), nullable=True)
    category = relationship("Category")

class OptionGroup(Base):
    __tablename__ = "option_groups"
    product_option_group_uuid = Column(String, primary_key=True, index=True)
    product_uuid = Column(String, ForeignKey("products.product_uuid"), nullable=False, index=True)
    name = Column(String, nullable=True)
    minoccurs = Column(String, nullable=True)
    maxoccurs = Column(String, nullable=True)

class Option(Base):
    __tablename__ = "options"
    option_uuid = Column(String, primary_key=True, index=True)
    group_uuid = Column(String, ForeignKey("option_groups.product_option_group_uuid"), nullable=False, index=True)
    option_name = Column(String, nullable=True)
    option_description = Column(Text, nullable=True)
    prices_url = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("group_uuid", "option_uuid", name="uq_group_option"),)
