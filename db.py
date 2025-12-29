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
    Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway Postgres URLs sometimes start with postgres:// which SQLAlchemy wants as postgresql://
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
# Catalog models (Phase 1: Groups only)
# -------------------

class CatalogGroup(Base):
    __tablename__ = "catalog_groups"
    id = Column(Integer, primary_key=True)

    group_uuid = Column(String(64), nullable=False, unique=True)  # 4over groupid
    group_name = Column(String(180), nullable=False)              # 4over groupname
    sample_product_uuid = Column(String(64), nullable=True)       # optional
    sample_product_name = Column(String(200), nullable=True)      # optional

    __table_args__ = (
        Index("ix_catalog_groups_group_name", "group_name"),
    )


# -------------------
# Helpers
# -------------------

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
