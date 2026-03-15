"""
Background worker that generates and sends the daily review.
"""

from __future__ import annotations

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.llm_service import LLMService
from apps.api.services.review_service import DailyReviewService
from apps.api.services.telegram_service import TelegramService
from db.session import get_session_factory

logger = get_logger(__name__)


async def run_daily_review() -> None:
    """Entry point called by the scheduler."""
    settings = get_settings()

    telegram = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)
    llm = LLMService(settings.llm_provider, settings.llm_model, settings.llm_api_key)

    factory = get_session_factory()
    async with factory() as session:
        service = DailyReviewService(
            session=session,
            telegram=telegram,
            llm=llm,
        )
        try:
            snapshot = await service.generate_and_send()
            logger.info("daily_review_complete", snapshot_id=str(snapshot.id))
        except Exception as e:
            logger.error("daily_review_failed", error=str(e))
            await session.rollback()
