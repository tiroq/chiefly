from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.classification_service import ClassificationService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.telegram_service import TelegramService

logger = get_logger(__name__)


class IntakeService:
    def __init__(
        self,
        session: AsyncSession,
        google_tasks: GoogleTasksService,
        classification: ClassificationService,
        telegram: TelegramService,
    ) -> None:
        self._session = session
        self._google_tasks = google_tasks
        self._classification = classification
        self._telegram = telegram

    async def poll_and_process(self) -> int:
        logger.info("intake_service_deprecated_noop")
        return 0
