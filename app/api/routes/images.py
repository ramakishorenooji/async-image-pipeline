from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_redis_client, get_settings_dep
from app.core.config import Settings
from app.models.image_job import JobStatus
from app.schemas.image_job import (
    ImageJobCreate,
    ImageJobListResponse,
    ImageJobRead,
)
from app.schemas.pagination import Pagination
from app.services.jobs import (
    DuplicateJobError,
    create_job,
    get_job,
    list_jobs,
)

router = APIRouter(prefix="/images", tags=["images"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=ImageJobRead)
async def submit_image_job(
    payload: ImageJobCreate,
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_settings_dep),
) -> ImageJobRead:
    try:
        job = await create_job(
            session=session, redis=redis, settings=settings, url=str(payload.url)
        )
    except DuplicateJobError as exc:  # pragma: no cover - thin wrapper
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Job already active", "job_id": str(exc.job.id)},
        ) from exc
    return ImageJobRead.model_validate(job)


@router.get("", response_model=ImageJobListResponse)
async def list_image_jobs(
    status_filter: JobStatus | None = Query(None, alias="status"),
    created_before: datetime | None = Query(None),
    created_after: datetime | None = Query(None),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
) -> ImageJobListResponse:
    requested_limit = limit or settings.default_page_size
    page_size = min(requested_limit, settings.max_page_size)
    jobs, total = await list_jobs(
        session=session,
        status=status_filter,
        created_before=created_before,
        created_after=created_after,
        limit=page_size,
        offset=offset,
    )
    pagination = Pagination(
        total=total,
        limit=page_size,
        offset=offset,
        has_more=offset + len(jobs) < total,
    )
    items = [ImageJobRead.model_validate(job) for job in jobs]
    return ImageJobListResponse(items=items, pagination=pagination)


@router.get("/{job_id}", response_model=ImageJobRead)
async def get_image_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> ImageJobRead:
    job = await get_job(session=session, job_id=job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    return ImageJobRead.model_validate(job)


@router.get("/{job_id}/thumbnail")
async def get_job_thumbnail(
    job_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    job = await get_job(session=session, job_id=job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    if job.result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail unavailable"
        )

    thumbnail_path = job.result.get("thumbnail_path")
    if not thumbnail_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail unavailable"
        )

    path = Path(thumbnail_path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail missing"
        )

    return FileResponse(path, media_type="image/jpeg", filename=f"{job_id}.jpg")
