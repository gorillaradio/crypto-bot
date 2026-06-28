from fastapi import FastAPI

app = FastAPI(title="crypto-bot")


@app.get("/health")
def health():
    return {"status": "ok"}
