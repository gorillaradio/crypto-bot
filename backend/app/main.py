import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from app.core.config import settings
from app.api.routes import router
from app.api.auth import router as auth_router
from app.scheduler.jobs import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.secret_key:
        raise RuntimeError("SECRET_KEY must be set; refusing to start without a session signing key.")
    start_scheduler()
    yield


app = FastAPI(title="crypto-bot", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key or "insecure-dev-key-change-me",
    session_cookie="crypto_session",
    https_only=settings.session_https_only,
    same_site="lax",
    max_age=settings.session_max_age_seconds,
)
app.include_router(router)
app.include_router(auth_router)


@app.get("/health")
def health():
    return {"status": "ok"}


_static = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static):
    app.mount("/", StaticFiles(directory=_static, html=True), name="static")
