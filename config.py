import os

SERVICE_NAME = "catdi-4over-connector"
PHASE = "0.9"
BUILD = "ROOT_MAIN_PY_V2"

FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY")
FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")
