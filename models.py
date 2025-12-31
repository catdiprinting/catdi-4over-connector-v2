from sqlalchemy import Column, Integer, String, Text
from db import Base

class RawPayload(Base):
    __tablename__ = "raw_payloads"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(50), index=True)          # e.g. "whoami", "categories", "product"
    ref_id = Column(String(100), index=True)       # e.g. product_uuid / category_uuid
    payload_json = Column(Text)                    # raw JSON string
