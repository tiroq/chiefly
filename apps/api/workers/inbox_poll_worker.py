"""
Background worker that polls the Google Tasks inbox at a configured interval.
Monitors all task changes during polling for comprehensive change awareness.
"""

from __future__ import annotations

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.alert_service import AlertService
from apps.api.services.classification_service import ClassificationService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.intake_service import IntakeService
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from apps.api.services.task_change_monitor import TaskChangeMonitor
from apps.api.services.telegram_service import TelegramService
from db.repositories.project_alias_repo import ProjectAliasRepo
from db.session import get_session_factory

logger = get_logger(__name__)


async def run_inbox_poll() -> None:
    """Entry point called by the scheduler."""
    settings = get_settings()

    google_tasks = GoogleTasksService(settings.google_credentials_file)
    llm = LLMService(
        settings.llm_provider, settings.llm_model, settings.llm_api_key, settings.llm_base_url
    )
    routing = ProjectRoutingService()
    telegram = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    factory = get_session_factory()
    try:
        async with factory() as session:
            alias_repo = ProjectAliasRepo(session)
            classification = ClassificationService(llm, routing, alias_repo=alias_repo)
            intake_service = IntakeService(
                session=session,
                google_tasks=google_tasks,
                classification=classification,
                telegram=telegram,
            )
            
            # Initialize change monitoring
            change_monitor = TaskChangeMonitor(session)
            alert_service = AlertService(telegram, session)
            
            try:
                # Capture baseline state before pulling
                await change_monitor.capture_baseline()
                logger.info("inbox_poll_baseline_captured")
                
                # Process inbox
                count = await intake_service.poll_and_process()
                logger.info("inbox_poll_complete", processed=count)
                
                # Detect changes after processing
                changes = await change_monitor.detect_changes()
                logger.info("inbox_poll_changes_detected", changes_count=len(changes))
                
                # Log all changes to SystemEvent
                if changes:
                    await change_monitor.log_all_changes()
                    
                    # Send alerts about changes
                    alert_result = await alert_service.alert_task_changes(
                        changes,
                        operation="inbox_poll",
                    )
                    logger.info("inbox_poll_alert_sent", alert_result=alert_result)
                    
            except Exception as e:
                logger.error("inbox_poll_failed", error=str(e))
                await session.rollback()
    finally:
        await telegram.aclose()
