def _client() -> FourOverClient:
    return FourOverClient(
        base_url=os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com"),
        apikey=os.getenv("FOUR_OVER_APIKEY", ""),
        private_key=os.getenv("FOUR_OVER_PRIVATE_KEY", ""),
        timeout_seconds=int(os.getenv("FOUR_OVER_TIMEOUT", "30")),
    )
