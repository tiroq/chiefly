"""
Admin routes for internal debugging and manual triggers.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_session
from apps.api.logging import get_logger
from core.schemas.api import DailyReviewResponse, TaskItemResponse
from db.repositories.daily_review_repo import DailyReviewRepository
from db.repositories.task_item_repo import TaskItemRepository

router = APIRouter(prefix="/admin", tags=["admin"])
logger = get_logger(__name__)


@router.get("/tasks/{task_id}", response_model=TaskItemResponse)
async def get_task(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> TaskItemResponse:
    repo = TaskItemRepository(session)
    task = await repo.get_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskItemResponse.model_validate(task)


@router.get("/reviews/latest", response_model=DailyReviewResponse)
async def get_latest_review(
    session: AsyncSession = Depends(get_session),
) -> DailyReviewResponse:
    repo = DailyReviewRepository(session)
    review = await repo.get_latest()
    if review is None:
        raise HTTPException(status_code=404, detail="No review found")
    return DailyReviewResponse.model_validate(review)


@router.post("/poll-inbox-now")
async def poll_inbox_now() -> dict:
    """Manually trigger an inbox poll."""
    from apps.api.services.scheduler_service import get_scheduler
    scheduler = get_scheduler()
    job = scheduler.get_job("inbox_poll")
    if job:
        scheduler.modify_job("inbox_poll", next_run_time=None)
        from apscheduler.util import datetime_to_utc_timestamp
        import datetime
        scheduler.modify_job(
            "inbox_poll",
            next_run_time=datetime.datetime.now(datetime.timezone.utc),
        )
    return {"status": "triggered"}


@router.post("/send-review-now")
async def send_review_now() -> dict:
    """Manually trigger a daily review."""
    from apps.api.services.scheduler_service import get_scheduler
    import datetime
    scheduler = get_scheduler()
    job = scheduler.get_job("daily_review")
    if job:
        scheduler.modify_job(
            "daily_review",
            next_run_time=datetime.datetime.now(datetime.timezone.utc),
        )
    return {"status": "triggered"}
