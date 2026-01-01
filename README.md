# catdi-4over-connector-v2

## Endpoints
- GET /ping
- GET /debug/auth
- GET /4over/whoami

## Local Run
1) Create .env from .env.example
2) Install deps:
   pip install -r requirements.txt
3) Run:
   uvicorn app.main:app --reload

## Railway
- Ensure Procfile exists at repo root:
  web: uvicorn app.main:app --host 0.0.0.0 --port $PORT

- Set env vars in Railway:
  FOUR_OVER_BASE_URL
  FOUR_OVER_APIKEY
  FOUR_OVER_PRIVATE_KEY
  FOUR_OVER_TIMEOUT

## Test
curl -i "https://web-production-009a.up.railway.app/ping"
curl -i "https://web-production-009a.up.railway.app/debug/auth"
curl -i "https://web-production-009a.up.railway.app/4over/whoami"
