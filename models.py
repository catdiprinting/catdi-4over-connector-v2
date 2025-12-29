from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, func

Base = declarative_base()

class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(80), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    category = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
