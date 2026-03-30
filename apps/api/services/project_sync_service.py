from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.google_tasks_service import GoogleTasksService
from core.domain.enums import ProjectType
from core.utils.text import slugify
from db.models.project import Project
from db.repositories.project_repo import ProjectRepository

logger = get_logger(__name__)

# Keyword-based project type classification.
# Sync must be read-only with no LLM calls (ARCHITECTURE_CONTRACT).
_TYPE_KEYWORDS: list[tuple[re.Pattern[str], ProjectType]] = [
    (re.compile(r"\b(client|customer|freelance|contract)\b", re.I), ProjectType.CLIENT),
    (re.compile(r"\b(family|home|house|kids?|partner)\b", re.I), ProjectType.FAMILY),
    (re.compile(r"\b(ops|devops|infra|deploy|server|monitoring)\b", re.I), ProjectType.OPS),
    (re.compile(r"\b(writ(e|ing)|blog|article|newsletter|draft)\b", re.I), ProjectType.WRITING),
    (re.compile(r"\b(internal|admin|backoffice|tooling)\b", re.I), ProjectType.INTERNAL),
]


class ProjectSyncResult(TypedDict):
    created: list[str]
    updated: list[str]
    deactivated: list[str]
    skipped: list[str]


class ProjectSyncService:
    def __init__(
        self,
        google_tasks: GoogleTasksService,
        project_repo: ProjectRepository,
    ) -> None:
        self._google_tasks = google_tasks
        self._project_repo = project_repo

    @staticmethod
    def _classify_type(name: str) -> ProjectType:
        """Classify project type from list name using keyword heuristics.

        No LLM call — sync must stay read-only per ARCHITECTURE_CONTRACT.
        Falls back to PERSONAL when no keywords match.
        """
        for pattern, project_type in _TYPE_KEYWORDS:
            if pattern.search(name):
                return project_type
        return ProjectType.PERSONAL

    async def sync_from_google(
        self,
        session: AsyncSession,
        inbox_list_id: str,
    ) -> ProjectSyncResult:
        tasklists: list[dict] = self._google_tasks.list_tasklists()  # type: ignore[assignment]
        seen_ids: set[str] = set()
        created: list[str] = []
        updated: list[str] = []
        deactivated: list[str] = []
        skipped: list[str] = []
        now = datetime.now(tz=timezone.utc)

        for tl in tasklists:
            tl_id = tl.get("id")
            if not isinstance(tl_id, str):
                continue
            tl_title: str = tl.get("title", "Untitled")  # type: ignore[assignment]
            seen_ids.add(tl_id)

            existing = await self._project_repo.get_by_google_tasklist_id(tl_id)
            new_slug = slugify(tl_title)

            if existing is not None:
                changes: list[str] = []
                if not existing.is_active:
                    existing.is_active = True
                    changes.append("reactivated")
                if existing.name != tl_title:
                    existing.name = tl_title
                    existing.slug = new_slug
                    changes.append("renamed")
                if changes:
                    existing.updated_at = now
                    await self._project_repo.save(existing)
                    updated.append(tl_title)
                    logger.info("project_sync_updated", name=tl_title, changes=changes)
                else:
                    skipped.append(tl_title)
            else:
                # Avoid slug collision
                slug = new_slug
                if await self._project_repo.get_by_slug(slug) is not None:
                    slug = f"{slug}-{tl_id[:6].lower()}"

                project_type = (
                    ProjectType.PERSONAL
                    if tl_id == inbox_list_id
                    else self._classify_type(tl_title)
                )
                project = Project(
                    id=uuid.uuid4(),
                    name=tl_title,
                    slug=slug,
                    google_tasklist_id=tl_id,
                    project_type=project_type,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                await self._project_repo.create(project)
                created.append(tl_title)
                logger.info("project_sync_created", name=tl_title, type=project_type.value)

        # Deactivate projects whose tasklists no longer exist in Google Tasks
        all_projects = await self._project_repo.list_all()
        for proj in all_projects:
            if proj.is_active and proj.google_tasklist_id not in seen_ids:
                proj.is_active = False
                proj.updated_at = now
                await self._project_repo.save(proj)
                deactivated.append(proj.name)
                logger.info("project_sync_deactivated", name=proj.name)

        await session.commit()
        logger.info(
            "project_sync_complete",
            created=len(created),
            updated=len(updated),
            deactivated=len(deactivated),
            skipped=len(skipped),
        )
        return {
            "created": created,
            "updated": updated,
            "deactivated": deactivated,
            "skipped": skipped,
        }
