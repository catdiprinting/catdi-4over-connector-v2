# catalog_sync.py
from sqlalchemy.orm import Session
from db import CatalogSize, CatalogLine, CatalogProduct
from catalog_parser import (
    parse_product_code, size_code_to_display, infer_family, build_line_name
)

def upsert_catalog(db: Session, entities: list[dict]) -> dict:
    created = {"sizes": 0, "lines": 0, "products": 0}

    for e in entities:
        code = e.get("product_code") or ""
        desc = e.get("product_description") or ""
        uuid = e.get("product_uuid")

        parsed = parse_product_code(code)
        if not parsed or not uuid:
            continue

        stock, finish_code, size_code = parsed
        size_display = size_code_to_display(size_code)
        family = infer_family(desc)
        line_name = build_line_name(stock, finish_code, desc)

        # Size
        size = db.query(CatalogSize).filter_by(display=size_display).one_or_none()
        if not size:
            size = CatalogSize(display=size_display, code=size_code)
            db.add(size)
            db.flush()
            created["sizes"] += 1

        # Line
        line = db.query(CatalogLine).filter_by(family=family, name=line_name).one_or_none()
        if not line:
            line = CatalogLine(family=family, name=line_name)
            db.add(line)
            db.flush()
            created["lines"] += 1

        # Product
        prod = db.query(CatalogProduct).filter_by(product_uuid=uuid).one_or_none()
        if not prod:
            prod = CatalogProduct(
                product_uuid=uuid,
                product_code=code,
                description=desc,
                size_id=size.id,
                line_id=line.id,
            )
            db.add(prod)
            created["products"] += 1
        else:
            prod.product_code = code
            prod.description = desc
            prod.size_id = size.id
            prod.line_id = line.id

    db.commit()
    return created
