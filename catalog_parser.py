import json

def extract_catalog_fields(item: dict) -> dict:
    """
    Pulls the known flattened fields you confirmed exist on /products.
    Keeps raw JSON too.
    """
    def g(*keys):
        for k in keys:
            if k in item and item[k] is not None:
                return item[k]
        return None

    return {
        "product_uuid": g("id", "uuid", "productid"),
        "group_id": g("groupid"),
        "group_name": g("groupname"),
        "size_id": g("sizeid"),
        "size_name": g("sizename"),
        "stock_id": g("stockid"),
        "stock_name": g("stockname"),
        "coating_id": g("coatingid"),
        "coating_name": g("coatingname"),
        "raw_json": json.dumps(item, ensure_ascii=False),
    }
