from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.schemas.image_job import ImageJobMetrics
from app.services.jobs import get_metrics

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=ImageJobMetrics)
async def read_metrics(
    session: AsyncSession = Depends(get_db_session),
) -> ImageJobMetrics:
    metrics = await get_metrics(session=session)
    return ImageJobMetrics(
        total=metrics.get("total", 0),
        pending=metrics.get("pending", 0),
        processing=metrics.get("processing", 0),
        completed=metrics.get("completed", 0),
        failed=metrics.get("failed", 0),
    )
