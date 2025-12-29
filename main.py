from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True, "status": "booted"}

@app.get("/version")
def version():
    return {"service": "catdi-4over-connector", "phase": "BOOT_SAFE"}
