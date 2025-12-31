from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from db import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    category_uuid = Column(String(64), nullable=False, unique=True, index=True)
    category_name = Column(String(255), nullable=True)
    category_description = Column(Text, nullable=True)

    products = relationship("Product", back_populates="category")

    def as_dict(self):
        return {
            "category_uuid": self.category_uuid,
            "category_name": self.category_name,
            "category_description": self.category_description,
        }


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    product_uuid = Column(String(64), nullable=False, unique=True, index=True)
    product_code = Column(String(128), nullable=True, index=True)
    product_description = Column(Text, nullable=True)

    category_uuid = Column(String(64), ForeignKey("categories.category_uuid"), nullable=True, index=True)
    category = relationship("Category", back_populates="products")

    option_groups = relationship("ProductOptionGroup", back_populates="product", cascade="all, delete-orphan")

    def as_dict(self):
        return {
            "product_uuid": self.product_uuid,
            "product_code": self.product_code,
            "product_description": self.product_description,
            "category_uuid": self.category_uuid,
        }


class ProductOptionGroup(Base):
    __tablename__ = "product_option_groups"

    id = Column(Integer, primary_key=True)
    product_uuid = Column(String(64), ForeignKey("products.product_uuid"), nullable=False, index=True)

    product_option_group_uuid = Column(String(64), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    minoccurs = Column(String(32), nullable=True)
    maxoccurs = Column(String(32), nullable=True)

    product = relationship("Product", back_populates="option_groups")
    values = relationship("ProductOptionValue", back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("product_uuid", "product_option_group_uuid", name="uq_product_group"),
        Index("ix_group_uuid", "product_option_group_uuid"),
    )

    def as_dict(self):
        return {
            "product_option_group_uuid": self.product_option_group_uuid,
            "name": self.name,
            "minoccurs": self.minoccurs,
            "maxoccurs": self.maxoccurs,
            "values": [v.as_dict() for v in self.values],
        }


class ProductOptionValue(Base):
    __tablename__ = "product_option_values"

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("product_option_groups.id"), nullable=False, index=True)

    value_uuid = Column(String(64), nullable=True, index=True)
    value = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)

    group = relationship("ProductOptionGroup", back_populates="values")

    def as_dict(self):
        return {
            "value_uuid": self.value_uuid,
            "value": self.value,
            "description": self.description,
        }
