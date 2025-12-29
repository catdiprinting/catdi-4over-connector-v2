from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, UniqueConstraint, Index

class Base(DeclarativeBase):
    pass

class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 4over product UUID (string)
    product_uuid: Mapped[str] = mapped_column(String(64), nullable=False)

    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    size_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    stock_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stock_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    coating_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    coating_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # keep full raw record for later parsing
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("product_uuid", name="uq_catalog_product_uuid"),
        Index("ix_catalog_group", "group_id"),
        Index("ix_catalog_stock", "stock_id"),
        Index("ix_catalog_size", "size_id"),
    )
