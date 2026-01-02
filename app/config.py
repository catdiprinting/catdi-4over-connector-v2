import os

def require(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if not val or not val.strip():
        raise RuntimeError(f"Missing required env var: {name}")
    return val.strip()

FOUR_OVER_BASE_URL = require(
    "FOUR_OVER_BASE_URL",
    "https://api.4over.com"
).rstrip("/")

FOUR_OVER_APIKEY = require("FOUR_OVER_APIKEY")
FOUR_OVER_PRIVATE_KEY = require("FOUR_OVER_PRIVATE_KEY")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

FOUR_OVER_TIMEOUT = int(os.getenv("FOUR_OVER_TIMEOUT", "30"))
