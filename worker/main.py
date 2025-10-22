from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

import aiohttp
from PIL import Image
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.models.image_job import JobStatus
from app.services.jobs import (
    mark_job_completed,
    mark_job_failed,
    mark_job_processing,
)

logger = get_logger("thumbforge.worker")

DEFAULT_HTTP_HEADERS = {
    "User-Agent": (
        "ThumbForgeWorker/1.0 (+https://example.com; contact=ops@example.com)"
    ),
    "Accept": "image/*,application/octet-stream;q=0.9,*/*;q=0.8",
}


def _process_image(data: bytes, size: int, destination: str) -> dict[str, Any]:
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(BytesIO(data)) as img:
        img.load()
        original_width, original_height = img.size
        fmt = (img.format or "JPEG").upper()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((size, size))
        img.save(destination_path, format="JPEG", quality=90)

    return {
        "width": original_width,
        "height": original_height,
        "format": fmt,
        "size_bytes": len(data),
        "thumbnail_path": str(destination_path),
    }


async def process_job(
    *,
    job_id: UUID,
    http: aiohttp.ClientSession,
    executor: ProcessPoolExecutor,
    settings: Settings,
) -> None:
    async with SessionLocal() as session:
        job = await mark_job_processing(session=session, job_id=job_id)
        if job is None:
            logger.warning("worker.job_missing", job_id=str(job_id))
            return
        if job.status != JobStatus.processing:
            logger.info(
                "worker.job_skipped", job_id=str(job_id), status=job.status.value
            )
            return

        try:
            async with http.get(
                job.url,
                timeout=settings.http_timeout_seconds,
                headers=DEFAULT_HTTP_HEADERS,
            ) as response:
                if response.status >= 400:
                    raise RuntimeError(
                        f"Failed to fetch image: status={response.status}"
                    )
                payload = await response.read()
                content_type = response.headers.get("Content-Type")
        except Exception as exc:  # pragma: no cover - network errors
            await mark_job_failed(
                session=session, job_id=job_id, error_message=str(exc)
            )
            logger.exception(
                "worker.download_failed", job_id=str(job_id), error=str(exc)
            )
            return

        loop = asyncio.get_running_loop()
        destination = Path(settings.storage_path) / f"{job_id}.jpg"
        try:
            metadata = await loop.run_in_executor(
                executor,
                _process_image,
                payload,
                settings.thumbnail_size,
                str(destination),
            )
        except Exception as exc:  # pragma: no cover - CPU errors
            await mark_job_failed(
                session=session, job_id=job_id, error_message=str(exc)
            )
            logger.exception(
                "worker.processing_failed", job_id=str(job_id), error=str(exc)
            )
            return

        metadata.update({"source_content_type": content_type, "source_url": job.url})
        await mark_job_completed(
            session=session, job_id=job_id, result_payload=metadata
        )
        logger.info("worker.job_completed", job_id=str(job_id))


async def consume(settings: Settings) -> None:
    configure_logging(settings.log_level)
    Path(settings.storage_path).mkdir(parents=True, exist_ok=True)

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    executor = ProcessPoolExecutor(max_workers=settings.worker_processes)

    timeout = settings.worker_poll_timeout
    client_timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)
    try:
        async with aiohttp.ClientSession(
            timeout=client_timeout, headers=DEFAULT_HTTP_HEADERS
        ) as http:
            while True:
                try:
                    item = await redis.brpop(settings.queue_name, timeout=timeout)
                    if item is None:
                        continue
                    _, job_id_raw = item
                    job_id = UUID(job_id_raw)
                    await process_job(
                        job_id=job_id, http=http, executor=executor, settings=settings
                    )
                except asyncio.CancelledError:
                    break
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.exception("worker.loop_error", error=str(exc))
    finally:
        executor.shutdown(wait=True)
        await redis.close()


def main() -> None:
    settings = get_settings()
    asyncio.run(consume(settings))


if __name__ == "__main__":
    main()
