"""
Background worker that polls the Google Tasks inbox at a configured interval.
"""

from __future__ import annotations

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.classification_service import ClassificationService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.intake_service import IntakeService
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from apps.api.services.telegram_service import TelegramService
from db.session import get_session_factory

logger = get_logger(__name__)


async def run_inbox_poll() -> None:
    """Entry point called by the scheduler."""
    settings = get_settings()

    google_tasks = GoogleTasksService(settings.google_credentials_file)
    llm = LLMService(settings.llm_provider, settings.llm_model, settings.llm_api_key, settings.llm_base_url)
    routing = ProjectRoutingService()
    classification = ClassificationService(llm, routing)
    telegram = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    factory = get_session_factory()
    async with factory() as session:
        service = IntakeService(
            session=session,
            google_tasks=google_tasks,
            classification=classification,
            telegram=telegram,
        )
        try:
            count = await service.poll_and_process()
            logger.info("inbox_poll_complete", processed=count)
        except Exception as e:
            logger.error("inbox_poll_failed", error=str(e))
            await session.rollback()
