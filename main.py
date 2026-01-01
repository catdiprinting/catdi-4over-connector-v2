import os
import hashlib

@app.get("/debug/auth")
def debug_auth():
    apikey = os.getenv("FOUR_OVER_APIKEY", "")
    pkey = os.getenv("FOUR_OVER_PRIVATE_KEY", "")
    base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")

    def fp(s: str) -> str:
        if not s:
            return ""
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]

    return {
        "ok": True,
        "base_url": base_url,
        "apikey_present": bool(apikey),
        "apikey_len": len(apikey),
        "apikey_preview": (apikey[:4] + "…" + apikey[-2:]) if apikey else "",
        "private_key_present": bool(pkey),
        "private_key_len": len(pkey),
        "private_key_sha256_12": fp(pkey),
    }
