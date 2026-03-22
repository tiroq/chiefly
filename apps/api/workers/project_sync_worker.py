"""
Background worker that syncs Google Tasklists → Projects on a schedule.
Monitors all task changes during sync for comprehensive change awareness.
"""

from __future__ import annotations

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.alert_service import AlertService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.llm_service import LLMService
from apps.api.services.project_sync_service import ProjectSyncService
from apps.api.services.task_change_monitor import TaskChangeMonitor
from apps.api.services.telegram_service import TelegramService
from db.repositories.project_repo import ProjectRepository
from db.session import get_session_factory

logger = get_logger(__name__)


async def run_project_sync() -> None:
    """Entry point called by the scheduler."""
    settings = get_settings()

    google_tasks = GoogleTasksService(settings.google_credentials_file)
    llm = LLMService(
        settings.llm_provider,
        settings.llm_model,
        settings.llm_api_key,
        settings.llm_base_url,
    )
    telegram = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    factory = get_session_factory()
    async with factory() as session:
        project_repo = ProjectRepository(session)
        sync_service = ProjectSyncService(google_tasks, project_repo, llm=llm)
        
        # Initialize change monitoring
        change_monitor = TaskChangeMonitor(session)
        alert_service = AlertService(telegram, session)
        
        try:
            # Capture baseline state before syncing
            await change_monitor.capture_baseline()
            logger.info("project_sync_baseline_captured")
            
            # Sync projects and tasks
            result = await sync_service.sync_from_google(session, settings.google_tasks_inbox_list_id)
            logger.info("project_sync_complete", **result)
            
            # Detect changes after sync
            changes = await change_monitor.detect_changes()
            logger.info("project_sync_changes_detected", changes_count=len(changes))
            
            # Log all changes to SystemEvent
            if changes:
                await change_monitor.log_all_changes()
                
                # Send alerts about changes
                alert_result = await alert_service.alert_task_changes(
                    changes,
                    operation="project_sync",
                )
                logger.info("project_sync_alert_sent", alert_result=alert_result)
                
        except Exception as e:
            logger.error("project_sync_failed", error=str(e))
            await session.rollback()
