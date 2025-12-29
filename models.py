from sqlalchemy import Column, String, Text, DateTime, func
from db import Base


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    # 4over UUIDs are strings; store them as the PK
    id = Column(String(64), primary_key=True, index=True)
    raw_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
