# catalog_parser.py
import re

SIZE_RE = re.compile(r'(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)')

def size_code_to_display(size_code: str) -> str:
    m = SIZE_RE.search(size_code or "")
    if not m:
        return size_code or ""
    w, h = m.group(1), m.group(2)
    return f'{w}" x {h}"'

def parse_product_code(code: str):
    """
    4over codes often look like:
    14PT-BCMATT-2X3.5
    100GLC-BCAQ-2X3.5
    """
    parts = (code or "").split("-")
    if len(parts) < 3:
        return None
    stock = parts[0].strip()
    finish_code = parts[1].strip()
    size_code = parts[-1].strip()
    return stock, finish_code, size_code

def normalize_stock(stock: str) -> str:
    if not stock:
        return ""
    if stock.endswith("PT"):
        return stock.replace("PT", "pt")  # 14PT -> 14pt
    if stock == "100GLC":
        return "100lb Gloss Cover"
    if stock == "100LB":
        return "100lb Cover"
    return stock

def normalize_finish(finish_code: str) -> str:
    mapping = {
        "BCAQ": "AQ",
        "BCUC": "No Coating",
        "BCMATT": "Matte/Dull",
        "BCUV": "UV",
        "BCLIN": "Linen",
        "RCBCMATT": "Matte/Dull (Round Corner)",
        "RCBCUV": "UV (Round Corner)",
    }
    return mapping.get(finish_code, finish_code or "")

def infer_family(description: str) -> str:
    d = (description or "").lower()
    if "business card" in d:
        return "Business Cards"
    if "social card" in d:
        return "Social Cards"
    if "fold" in d:
        return "Fold Over Cards"
    return "Cards"

def build_line_name(stock: str, finish_code: str, description: str) -> str:
    """
    Produces the "product dropdown label" after size is selected.
    Example: 14pt Matte/Dull, 100lb Gloss Cover (AQ)
    """
    stock_name = normalize_stock(stock)
    finish_name = normalize_finish(finish_code)
    if not stock_name:
        return finish_name or "Unknown"

    # if finish is AQ / No Coating, show as parentheses on gloss types
    if "Gloss" in stock_name and finish_name in ("AQ", "No Coating"):
        return f"{stock_name} ({finish_name})"

    # typical: "14pt Matte/Dull"
    if finish_name:
        return f"{stock_name} {finish_name}"

    return stock_name
