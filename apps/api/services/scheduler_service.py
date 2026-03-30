from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from apps.api.logging import get_logger

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def setup_scheduler(
    poll_interval_seconds: int,
    processing_interval_seconds: int,
    daily_review_cron: str,
    project_sync_cron: str,
    timezone: str,
    poll_job,
    processing_job,
    review_job,
    project_sync_job,
) -> AsyncIOScheduler:
    scheduler = get_scheduler()

    scheduler.add_job(
        poll_job,
        trigger=IntervalTrigger(seconds=poll_interval_seconds),
        id="task_sync",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    scheduler.add_job(
        processing_job,
        trigger=IntervalTrigger(seconds=processing_interval_seconds),
        id="task_processing",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    cron_parts = daily_review_cron.split()
    if len(cron_parts) == 5:
        minute, hour, day, month, day_of_week = cron_parts
    else:
        minute, hour, day, month, day_of_week = "0", "9", "*", "*", "*"

    scheduler.add_job(
        review_job,
        trigger=CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=timezone,
        ),
        id="daily_review",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    logger.info(
        "scheduler_configured",
        poll_interval=poll_interval_seconds,
        processing_interval=processing_interval_seconds,
        daily_review_cron=daily_review_cron,
    )

    sync_parts = project_sync_cron.split()
    if len(sync_parts) == 5:
        s_minute, s_hour, s_day, s_month, s_dow = sync_parts
    else:
        s_minute, s_hour, s_day, s_month, s_dow = "0", "*", "*", "*", "*"

    scheduler.add_job(
        project_sync_job,
        trigger=CronTrigger(
            minute=s_minute,
            hour=s_hour,
            day=s_day,
            month=s_month,
            day_of_week=s_dow,
            timezone=timezone,
        ),
        id="project_sync",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    return scheduler
