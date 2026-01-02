import os

FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")
# This SHOULD be "printproducts" for catalog endpoints; whoami lives at root.
FOUR_OVER_API_PREFIX = os.getenv("FOUR_OVER_API_PREFIX", "printproducts")
FOUR_OVER_TIMEOUT = os.getenv("FOUR_OVER_TIMEOUT", "30")
