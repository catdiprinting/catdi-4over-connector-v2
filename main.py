from fastapi import FastAPI

app = FastAPI(title="Catdi 4over Connector", version="0.0.1")

@app.get("/")
def root():
    return {"ok": True, "hint": "try /health and /version"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/version")
def version():
    return {"service": "catdi-4over-connector", "phase": "0", "build": "fresh-start"}
