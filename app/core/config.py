from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="THUMBFORGE_", extra="ignore"
    )

    app_name: str = Field(default="ThumbForge")
    api_v1_prefix: str = Field(default="/v1")
    database_url: str = Field(
        default="postgresql+asyncpg://thumbforge:thumbforge@localhost:5432/thumbforge"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    queue_name: str = Field(default="thumbforge:image_jobs")
    default_page_size: int = Field(default=20, ge=1)
    max_page_size: int = Field(default=100, ge=1)
    thumbnail_size: int = Field(default=256, ge=16)
    storage_path: Path = Field(default=Path("storage/thumbnails"))
    log_level: str = Field(default="INFO")
    worker_poll_timeout: int = Field(default=5, ge=1)
    worker_processes: int = Field(default=2, ge=1)
    http_timeout_seconds: int = Field(default=30, ge=1)
    duplicate_handling: Literal["allow-retry", "reuse-completed", "reject-active"] = (
        Field(
            default="allow-retry",
            description=(
                "Strategy for handling duplicate URLs: 'allow-retry' creates a new job,\n"
                "'reuse-completed' returns existing completed jobs, 'reject-active' rejects when processing."
            ),
        )
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
