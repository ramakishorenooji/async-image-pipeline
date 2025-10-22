from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict

from app.models.image_job import JobStatus
from app.schemas.pagination import Pagination


class ImageJobCreate(BaseModel):
    url: AnyHttpUrl


class ImageJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: AnyHttpUrl
    status: JobStatus
    attempts: int
    created_at: datetime
    updated_at: datetime
    result: dict[str, Any] | None
    error: str | None


class ImageJobListResponse(BaseModel):
    items: list[ImageJobRead]
    pagination: Pagination


class ImageJobMetrics(BaseModel):
    total: int
    pending: int
    processing: int
    completed: int
    failed: int
