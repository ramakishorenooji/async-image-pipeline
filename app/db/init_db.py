import asyncio

from app.db.session import engine
from app.models import ImageJob  # noqa: F401  Ensures models are registered
from app.models.base import Base


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def init_db_sync() -> None:
    asyncio.run(init_db())
