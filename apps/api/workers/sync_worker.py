from __future__ import annotations

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.alert_service import AlertService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.sync_service import SyncService
from apps.api.services.task_change_monitor import TaskChangeMonitor
from apps.api.services.telegram_service import TelegramService
from db.session import get_session_factory

logger = get_logger(__name__)


async def run_sync() -> None:
    settings = get_settings()
    google_tasks = GoogleTasksService(settings.google_credentials_file)
    telegram = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    factory = get_session_factory()
    try:
        async with factory() as session:
            sync_service = SyncService(session=session, google_tasks=google_tasks)
            change_monitor = TaskChangeMonitor(session)
            alert_service = AlertService(telegram, session)

            try:
                await change_monitor.capture_baseline()

                summary = await sync_service.sync_all()
                logger.info(
                    "sync_worker_complete",
                    tasklists_scanned=summary.tasklists_scanned,
                    tasks_scanned=summary.tasks_scanned,
                    new_count=summary.new_count,
                    updated_count=summary.updated_count,
                    moved_count=summary.moved_count,
                    deleted_count=summary.deleted_count,
                    queued_count=summary.queued_count,
                )

                changes = await change_monitor.detect_changes()
                if changes:
                    await change_monitor.log_all_changes()
                    alert_result = await alert_service.alert_task_changes(changes, operation="sync")
                    logger.info("sync_worker_alert_sent", alert_result=alert_result)

                change_count = len(changes)
                if summary.total_synced > 0 or change_count > 0:
                    msg = (
                        f"🔄 Sync complete: {summary.tasklists_scanned} list(s) scanned, "
                        f"{summary.tasks_scanned} task(s) seen, "
                        f"{summary.new_count} new, {summary.updated_count} updated, "
                        f"{summary.moved_count} moved, {summary.deleted_count} deleted."
                    )
                    await telegram.send_text(msg)

            except Exception as e:
                logger.error("sync_worker_failed", error=str(e))
                await session.rollback()
    finally:
        await telegram.aclose()
