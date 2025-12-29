import json


def extract_items(payload: dict) -> list[dict]:
    """
    4over productsfeed payload typically includes:
      - items: [...]
      - totalResults: N
    We'll handle either:
      payload["items"] OR payload["data"]["items"]
    """
    if isinstance(payload, dict):
        if "items" in payload and isinstance(payload["items"], list):
            return payload["items"]
        if "data" in payload and isinstance(payload["data"], dict) and isinstance(payload["data"].get("items"), list):
            return payload["data"]["items"]
    return []


def extract_total_results(payload: dict) -> int | None:
    """
    tries payload["totalResults"] or payload["data"]["totalResults"]
    """
    if isinstance(payload, dict):
        tr = payload.get("totalResults")
        if isinstance(tr, int):
            return tr
        if "data" in payload and isinstance(payload["data"], dict):
            tr2 = payload["data"].get("totalResults")
            if isinstance(tr2, int):
                return tr2
    return None


def get_item_uuid(item: dict) -> str | None:
    """
    Productsfeed items tend to include uuid keys like:
      - id
      - uuid
      - product_uuid
    We'll try a few.
    """
    for k in ("id", "uuid", "product_uuid", "productUuid"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def serialize_item(item: dict) -> str:
    return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
