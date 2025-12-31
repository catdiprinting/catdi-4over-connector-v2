# models.py
from sqlalchemy import Column, Integer, String, Text
from db import Base

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    category_uuid = Column(String(64), unique=True, index=True, nullable=False)
    category_name = Column(String(255), nullable=False)
    category_description = Column(Text, nullable=True)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    product_uuid = Column(String(64), unique=True, index=True, nullable=False)
    product_code = Column(String(128), nullable=True)
    product_description = Column(Text, nullable=True)
    category_uuid = Column(String(64), index=True, nullable=True)
