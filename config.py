# config.py
import os

FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "")

APP_PHASE = os.getenv("APP_PHASE", "0.6")
APP_BUILD = os.getenv("APP_BUILD", "4over-ping-enabled")
SERVICE_NAME = os.getenv("SERVICE_NAME", "catdi-4over-connector")
