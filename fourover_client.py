import requests
import hashlib
import time
from config import FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY, FOUR_OVER_BASE_URL

class FourOverClient:
    def _signed_get(self, path: str):
        ts = str(int(time.time()))
        canonical = f"{path}?apikey={FOUR_OVER_APIKEY}"
        sig = hashlib.sha1((canonical + FOUR_OVER_PRIVATE_KEY).encode()).hexdigest()

        url = f"{FOUR_OVER_BASE_URL}{canonical}&signature={sig}"
        return requests.get(url, timeout=30).json()

    def whoami(self):
        return self._signed_get("/whoami")

    def product_optiongroups(self, product_uuid):
        return self._signed_get(f"/printproducts/products/{product_uuid}/optiongroups")

    def product_baseprices(self, product_uuid):
        return self._signed_get(f"/printproducts/products/{product_uuid}/baseprices")
