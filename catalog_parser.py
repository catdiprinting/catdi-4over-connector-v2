import json

def extract_items(payload: dict) -> list[dict]:
    """
    4over /printproducts response typically has:
      payload["data"] = list of products
    but we guard for variations.
    """
    if not isinstance(payload, dict):
        return []

    if "data" in payload and isinstance(payload["data"], list):
        return payload["data"]

    # Sometimes APIs return "items"
    if "items" in payload and isinstance(payload["items"], list):
        return payload["items"]

    return []

def item_id(item: dict) -> str | None:
    if not isinstance(item, dict):
        return None
    return item.get("id") or item.get("uuid") or item.get("product_id")

def item_name(item: dict) -> str | None:
    if not isinstance(item, dict):
        return None
    return item.get("name") or item.get("title")

def to_raw_json(item: dict) -> str:
    return json.dumps(item, ensure_ascii=False)
