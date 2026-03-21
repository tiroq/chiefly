from __future__ import annotations

import uuid
from typing import Callable, TypedDict, cast

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.google_tasks_service import GoogleTasksService
from core.utils.text import slugify
from db.models.project import Project
from db.repositories.project_repo import ProjectRepository

logger = get_logger(__name__)


class ProjectSyncResult(TypedDict):
    created: list[str]
    updated: list[str]
    skipped: list[str]


class ProjectSyncService:
    def __init__(
        self,
        google_tasks: GoogleTasksService,
        project_repo: ProjectRepository,
    ) -> None:
        self._google_tasks: GoogleTasksService
        self._project_repo: ProjectRepository
        self._google_tasks = google_tasks
        self._project_repo = project_repo

    async def sync_from_google(
        self,
        session: AsyncSession,
        inbox_list_id: str,
    ) -> ProjectSyncResult:
        list_tasklists = cast(
            Callable[[], list[dict[str, object]]],
            self._google_tasks.list_tasklists,
        )
        tasklists = list_tasklists()

        created: list[str] = []
        updated: list[str] = []
        skipped: list[str] = []

        for tl in tasklists:
            tl_id_obj = tl.get("id")
            if not isinstance(tl_id_obj, str):
                continue

            tl_title_obj = tl.get("title", "Untitled")
            tl_title = tl_title_obj if isinstance(tl_title_obj, str) else "Untitled"
            tl_id = tl_id_obj

            if tl_id == inbox_list_id:
                skipped.append(tl_title)
                continue

            existing = await self._project_repo.get_by_google_tasklist_id(tl_id)

            if existing is not None:
                if existing.name != tl_title:
                    existing.name = tl_title
                    existing.slug = slugify(tl_title)
                    _ = await self._project_repo.save(existing)
                    updated.append(tl_title)
                else:
                    skipped.append(tl_title)
            else:
                project = Project(
                    id=uuid.uuid4(),
                    name=tl_title,
                    slug=slugify(tl_title),
                    google_tasklist_id=tl_id,
                    project_type="personal",
                    is_active=True,
                )
                _ = await self._project_repo.create(project)
                created.append(tl_title)

        await session.commit()

        logger.info(
            "project_sync_complete",
            created=len(created),
            updated=len(updated),
            skipped=len(skipped),
        )

        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
        }
