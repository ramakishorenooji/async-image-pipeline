from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.image_job import ImageJob, JobStatus


class DuplicateJobError(Exception):
    def __init__(self, job: ImageJob) -> None:
        super().__init__("A job for this URL already exists.")
        self.job = job


def normalize_url(url: str) -> str:
    return url.strip()


def compute_url_hash(url: str) -> str:
    normalized = normalize_url(url).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def enqueue_job(redis: Redis, queue_name: str, job_id: UUID) -> None:
    await redis.lpush(queue_name, str(job_id))


async def create_job(
    *,
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    url: str,
) -> ImageJob:
    url_hash = compute_url_hash(url)

    existing_stmt: Select[tuple[ImageJob]] = (
        select(ImageJob)
        .where(ImageJob.url_hash == url_hash)
        .order_by(ImageJob.created_at.desc())
        .limit(1)
    )
    existing_result = await session.execute(existing_stmt)
    existing_job = existing_result.scalars().first()

    if existing_job:
        if (
            settings.duplicate_handling == "reuse-completed"
            and existing_job.status == JobStatus.completed
        ):
            return existing_job
        if settings.duplicate_handling == "reject-active" and existing_job.status in {
            JobStatus.pending,
            JobStatus.processing,
        }:
            raise DuplicateJobError(existing_job)

    job = ImageJob(url=url, url_hash=url_hash, status=JobStatus.pending)
    session.add(job)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # Re-fetch job in case of race condition
        retry_result = await session.execute(existing_stmt)
        retry_job = retry_result.scalars().first()
        if retry_job is None:
            raise
        if settings.duplicate_handling == "reject-active" and retry_job.status in {
            JobStatus.pending,
            JobStatus.processing,
        }:
            raise DuplicateJobError(retry_job)
        return retry_job

    await session.refresh(job)
    await enqueue_job(redis, settings.queue_name, job.id)
    return job


async def list_jobs(
    *,
    session: AsyncSession,
    status: JobStatus | None,
    created_before: datetime | None,
    created_after: datetime | None,
    limit: int,
    offset: int,
) -> tuple[list[ImageJob], int]:
    stmt: Select[tuple[ImageJob]] = select(ImageJob)
    filters = []
    if status:
        filters.append(ImageJob.status == status)
    if created_before:
        filters.append(ImageJob.created_at <= created_before)
    if created_after:
        filters.append(ImageJob.created_at >= created_after)

    if filters:
        stmt = stmt.where(*filters)

    stmt = stmt.order_by(ImageJob.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    jobs = list(result.scalars())

    count_stmt = select(func.count()).select_from(ImageJob)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = (await session.execute(count_stmt)).scalar_one()
    return jobs, int(total)


async def get_job(*, session: AsyncSession, job_id: UUID) -> ImageJob | None:
    result = await session.get(ImageJob, job_id)
    return result


async def mark_job_processing(
    *, session: AsyncSession, job_id: UUID
) -> ImageJob | None:
    job = await session.get(ImageJob, job_id, with_for_update=True)
    if job is None:
        return None
    if job.status not in {JobStatus.pending, JobStatus.failed}:
        return job
    job.status = JobStatus.processing
    job.attempts += 1
    job.error = None
    job.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(job)
    return job


async def mark_job_completed(
    *, session: AsyncSession, job_id: UUID, result_payload: dict[str, Any]
) -> ImageJob | None:
    job = await session.get(ImageJob, job_id, with_for_update=True)
    if job is None:
        return None
    job.status = JobStatus.completed
    job.result = result_payload
    job.error = None
    job.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(job)
    return job


async def mark_job_failed(
    *, session: AsyncSession, job_id: UUID, error_message: str
) -> ImageJob | None:
    job = await session.get(ImageJob, job_id, with_for_update=True)
    if job is None:
        return None
    job.status = JobStatus.failed
    job.result = None
    job.error = error_message
    job.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(job)
    return job


async def get_metrics(*, session: AsyncSession) -> dict[str, int]:
    result = await session.execute(
        select(ImageJob.status, func.count(ImageJob.id)).group_by(ImageJob.status)
    )
    counts: dict[str, int] = {status.value: 0 for status in JobStatus}
    for status, count in result.all():
        counts[status.value] = int(count)
    counts["total"] = sum(counts.values())
    return counts
