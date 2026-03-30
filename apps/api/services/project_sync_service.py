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
from db.models.system_event import SystemEvent
from db.repositories.project_repo import ProjectRepository
from db.repositories.system_event_repo import SystemEventRepo

logger = get_logger(__name__)

_TYPE_KEYWORDS: list[tuple[re.Pattern[str], ProjectType]] = [
    (re.compile(r"\b(client|customer|freelance|contract)\b", re.I), ProjectType.CLIENT),
    (re.compile(r"\b(family|home|house|kids?|partner)\b", re.I), ProjectType.FAMILY),
    (re.compile(r"\b(ops|devops|infra|deploy|server|monitoring)\b", re.I), ProjectType.OPS),
    (re.compile(r"\b(writ(e|ing)|blog|article|newsletter|draft)\b", re.I), ProjectType.WRITING),
    (re.compile(r"\b(internal|admin|backoffice|tooling)\b", re.I), ProjectType.INTERNAL),
]

EVENT_PROJECT_DISCOVERED = "project_discovered"
EVENT_PROJECT_RENAMED = "project_renamed"
EVENT_PROJECT_DELETED = "project_deleted"
EVENT_PROJECT_REACTIVATED = "project_reactivated"


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
        event_repo: SystemEventRepo | None = None,
    ) -> None:
        self._google_tasks = google_tasks
        self._project_repo = project_repo
        self._event_repo = event_repo

    @staticmethod
    def _classify_type(name: str) -> ProjectType:
        for pattern, project_type in _TYPE_KEYWORDS:
            if pattern.search(name):
                return project_type
        return ProjectType.PERSONAL

    async def _emit_event(
        self,
        event_type: str,
        message: str,
        project_id: uuid.UUID,
        payload: dict[str, object] | None = None,
    ) -> None:
        if self._event_repo is None:
            return
        event = SystemEvent(
            id=uuid.uuid4(),
            event_type=event_type,
            severity="info",
            subsystem="project_sync",
            message=message,
            project_id=project_id,
            payload_json=payload,
        )
        await self._event_repo.create(event)

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
                existing.last_seen_at = now
                changes: list[str] = []

                if not existing.is_active:
                    existing.is_active = True
                    existing.deleted_at = None
                    changes.append("reactivated")
                    await self._emit_event(
                        EVENT_PROJECT_REACTIVATED,
                        f"Project '{tl_title}' reappeared in Google Tasks",
                        existing.id,
                        {"google_tasklist_id": tl_id},
                    )

                if existing.name != tl_title:
                    old_name = existing.name
                    existing.last_synced_name = old_name
                    existing.name = tl_title
                    existing.slug = new_slug
                    changes.append("renamed")
                    await self._emit_event(
                        EVENT_PROJECT_RENAMED,
                        f"Project renamed from '{old_name}' to '{tl_title}'",
                        existing.id,
                        {
                            "old_name": old_name,
                            "new_name": tl_title,
                            "google_tasklist_id": tl_id,
                        },
                    )

                if changes:
                    existing.updated_at = now
                    await self._project_repo.save(existing)
                    updated.append(tl_title)
                    logger.info("project_sync_updated", name=tl_title, changes=changes)
                else:
                    await self._project_repo.save(existing)
                    skipped.append(tl_title)
            else:
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
                    first_seen_at=now,
                    last_seen_at=now,
                    created_at=now,
                    updated_at=now,
                )
                await self._project_repo.create(project)
                created.append(tl_title)
                logger.info("project_sync_created", name=tl_title, type=project_type.value)

                await self._emit_event(
                    EVENT_PROJECT_DISCOVERED,
                    f"New project '{tl_title}' discovered from Google Tasks",
                    project.id,
                    {"google_tasklist_id": tl_id, "project_type": project_type.value},
                )

        all_projects = await self._project_repo.list_all()
        for proj in all_projects:
            if proj.is_active and proj.google_tasklist_id not in seen_ids:
                proj.is_active = False
                proj.deleted_at = now
                proj.updated_at = now
                await self._project_repo.save(proj)
                deactivated.append(proj.name)
                logger.info("project_sync_deactivated", name=proj.name)

                await self._emit_event(
                    EVENT_PROJECT_DELETED,
                    f"Project '{proj.name}' no longer found in Google Tasks",
                    proj.id,
                    {"google_tasklist_id": proj.google_tasklist_id},
                )

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
