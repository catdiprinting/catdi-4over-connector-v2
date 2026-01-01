"""Compatibility shim.

This project historically referenced a module named ``models.py``.

In v2, pricing tables live in ``models_pricing.py``. Keeping this file avoids
Railway crashes from stale imports (e.g., ``from models import ...``).
"""

from models_pricing import Base, BasePriceCache, BasePriceRow
