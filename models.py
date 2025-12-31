# models.py
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Text, BigInteger

class Base(DeclarativeBase):
    pass

class BasePriceCache(Base):
    __tablename__ = "baseprice_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_uuid: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
