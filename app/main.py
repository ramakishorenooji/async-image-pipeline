from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.routes import images, metrics
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.init_db import init_db
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    Path(settings.storage_path).mkdir(parents=True, exist_ok=True)
    await init_db()

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = redis

    try:
        yield
    finally:
        await redis.close()
        await engine.dispose()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(images.router, prefix=settings.api_v1_prefix)
app.include_router(metrics.router, prefix=settings.api_v1_prefix)


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
