# db.py
import os
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Railway will set DATABASE_URL for Postgres.
# Local fallback uses SQLite.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway Postgres sometimes uses postgres:// which SQLAlchemy expects as postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# -------------------
# Models
# -------------------

class CatalogSize(Base):
    __tablename__ = "catalog_sizes"

    id = Column(Integer, primary_key=True)
    display = Column(String(50), nullable=False, unique=True)  # e.g. 2" x 3.5"
    code = Column(String(50), nullable=True)                   # e.g. 2X3.5

    products = relationship("CatalogProduct", back_populates="size")


class CatalogLine(Base):
    __tablename__ = "catalog_lines"

    id = Column(Integer, primary_key=True)
    family = Column(String(50), nullable=False)                # e.g. Business Cards
    name = Column(String(140), nullable=False)                 # e.g. 14pt Matte/Dull

    products = relationship("CatalogProduct", back_populates="line")

    __table_args__ = (
        UniqueConstraint("family", "name", name="uq_family_line"),
    )


class CatalogProduct(Base):
    __tablename__ = "catalog_products"

    id = Column(Integer, primary_key=True)

    product_uuid = Column(String(64), nullable=False, unique=True)
    product_code = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)

    size_id = Column(Integer, ForeignKey("catalog_sizes.id"), nullable=False)
    line_id = Column(Integer, ForeignKey("catalog_lines.id"), nullable=False)

    size = relationship("CatalogSize", back_populates="products")
    line = relationship("CatalogLine", back_populates="products")


# -------------------
# Helpers
# -------------------

def init_db() -> None:
    """Create tables if they do not exist."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency generator."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
