def extract_fields(item: dict) -> dict:
    """
    Best-effort extraction for indexing/search.
    We still store raw_json for everything.
    """
    name = item.get("name") or item.get("title") or item.get("product_name")
    sku = item.get("sku") or item.get("code") or item.get("product_code")
    category = None
    status = item.get("status") or item.get("state")

    # common patterns
    if isinstance(item.get("category"), dict):
        category = item["category"].get("name") or item["category"].get("title")
    elif isinstance(item.get("category"), str):
        category = item.get("category")

    if not category:
        # sometimes nested
        cat = item.get("printproduct_category") or item.get("printproductCategory")
        if isinstance(cat, dict):
            category = cat.get("name") or cat.get("title")

    return {
        "name": name,
        "sku": sku,
        "category": category,
        "status": status,
    }
