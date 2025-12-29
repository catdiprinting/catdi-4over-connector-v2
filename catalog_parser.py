import json

def parse_product_row(row: dict) -> dict:
    """
    Normalizes a single 4over /products item into fields we store.
    Keeps raw_json for debugging and future parsing.
    """
    def pick(*keys):
        for k in keys:
            if k in row and row[k] not in (None, ""):
                return row[k]
        return None

    product_id = pick("id", "productid", "uuid")
    if not product_id:
        # If 4over changes naming, fallback
        product_id = row.get("product_uuid") or row.get("productId")

    out = {
        "id": str(product_id) if product_id else None,

        "groupid": pick("groupid", "groupId"),
        "groupname": pick("groupname", "groupName"),

        "sizeid": pick("sizeid", "sizeId"),
        "sizename": pick("sizename", "sizeName"),

        "stockid": pick("stockid", "stockId"),
        "stockname": pick("stockname", "stockName"),

        "coatingid": pick("coatingid", "coatingId"),
        "coatingname": pick("coatingname", "coatingName"),

        "raw_json": json.dumps(row, ensure_ascii=False),
    }
    return out
