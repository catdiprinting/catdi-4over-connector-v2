from sqlalchemy import Column, String, Numeric
from db import Base

class ProductBasePrice(Base):
    __tablename__ = "product_base_prices"

    base_price_uuid = Column(String, primary_key=True)
    product_uuid = Column(String, index=True)
    runsize = Column(String)
    colorspec = Column(String)
    product_baseprice = Column(Numeric)
