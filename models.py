from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Integer, Text, DateTime, func, UniqueConstraint, Index

Base = declarative_base()

class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id = Column(Integer, primary_key=True, index=True)
    fourover_id = Column(String(64), nullable=False)
    name = Column(String(255), nullable=True)
    raw_json = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("fourover_id", name="uq_catalog_items_fourover_id"),
        Index("ix_catalog_items_fourover_id", "fourover_id"),
    )
