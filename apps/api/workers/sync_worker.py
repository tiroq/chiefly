from __future__ import annotations

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.alert_service import AlertService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.project_sync_service import ProjectSyncService
from apps.api.services.sync_service import SyncService
from apps.api.services.task_change_monitor import TaskChangeMonitor
from apps.api.services.telegram_service import TelegramService
from db.repositories.project_repo import ProjectRepository
from db.repositories.system_event_repo import SystemEventRepo
from db.session import get_session_factory

logger = get_logger(__name__)


async def run_sync() -> None:
    settings = get_settings()
    google_tasks = GoogleTasksService(settings.google_credentials_file)
    telegram = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    factory = get_session_factory()
    try:
        async with factory() as session:
            project_repo = ProjectRepository(session)
            event_repo = SystemEventRepo(session)
            project_sync = ProjectSyncService(google_tasks, project_repo, event_repo)
            sync_service = SyncService(session=session, google_tasks=google_tasks)
            change_monitor = TaskChangeMonitor(session)
            alert_service = AlertService(telegram, session)

            try:
                project_result = await project_sync.sync_from_google(
                    session,
                    inbox_list_id=settings.default_tasklist_id,
                )
                project_changes = (
                    len(project_result["created"])
                    + len(project_result["updated"])
                    + len(project_result["deactivated"])
                )
                if project_changes > 0:
                    logger.info(
                        "sync_worker_project_sync",
                        created=len(project_result["created"]),
                        updated=len(project_result["updated"]),
                        deactivated=len(project_result["deactivated"]),
                    )

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
                if summary.total_synced > 0 or change_count > 0 or project_changes > 0:
                    parts = [
                        f"🔄 Sync complete: {summary.tasklists_scanned} list(s) scanned, "
                        f"{summary.tasks_scanned} task(s) seen, "
                        f"{summary.new_count} new, {summary.updated_count} updated, "
                        f"{summary.moved_count} moved, {summary.deleted_count} deleted.",
                    ]
                    if project_result["created"]:
                        parts.append(f"📁 New projects: {', '.join(project_result['created'])}")
                    if project_result["updated"]:
                        parts.append(f"✏️ Updated projects: {', '.join(project_result['updated'])}")
                    if project_result["deactivated"]:
                        parts.append(
                            f"🗑 Removed projects: {', '.join(project_result['deactivated'])}"
                        )
                    await telegram.send_text("\n".join(parts))

            except Exception as e:
                logger.error("sync_worker_failed", error=str(e))
                await session.rollback()
    finally:
        await telegram.aclose()
