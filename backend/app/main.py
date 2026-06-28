from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.routes import router
from app.scheduler.jobs import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield


app = FastAPI(title="crypto-bot", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
