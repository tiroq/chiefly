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

                synced = await sync_service.sync_inbox(settings.google_tasks_inbox_list_id)
                logger.info("sync_worker_complete", synced=synced)

                changes = await change_monitor.detect_changes()
                if changes:
                    await change_monitor.log_all_changes()
                    alert_result = await alert_service.alert_task_changes(changes, operation="sync")
                    logger.info("sync_worker_alert_sent", alert_result=alert_result)

            except Exception as e:
                logger.error("sync_worker_failed", error=str(e))
                await session.rollback()
    finally:
        await telegram.aclose()
