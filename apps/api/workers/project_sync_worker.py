"""
Background worker that syncs Google Tasklists → Projects on a schedule.
"""

from __future__ import annotations

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.llm_service import LLMService
from apps.api.services.project_sync_service import ProjectSyncService
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

    factory = get_session_factory()
    async with factory() as session:
        project_repo = ProjectRepository(session)
        service = ProjectSyncService(google_tasks, project_repo, llm=llm)
        try:
            result = await service.sync_from_google(session, settings.google_tasks_inbox_list_id)
            logger.info("project_sync_complete", **result)
        except Exception as e:
            logger.error("project_sync_failed", error=str(e))
            await session.rollback()
