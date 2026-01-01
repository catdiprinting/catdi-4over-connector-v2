from fastapi import FastAPI

app = FastAPI()

@app.get("/ping")
def ping():
    return {"ok": True, "service": "catdi-4over-connector-v2", "phase": "boot-clean"}
