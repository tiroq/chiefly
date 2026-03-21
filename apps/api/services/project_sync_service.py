from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.llm_service import LLMService
from core.domain.enums import ProjectType
from core.utils.text import slugify
from db.models.project import Project
from db.repositories.project_repo import ProjectRepository

logger = get_logger(__name__)

_ALL_TYPES = list(ProjectType)

_TYPE_CLASSIFY_PROMPT = """Classify a Google Tasks list into a project type.

List name: "{name}"

Available types:
{types}

Return ONLY valid JSON: {{"recommended_type": "<type value>", "reasoning": "<brief>"}}"""


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
        llm: LLMService | None = None,
    ) -> None:
        self._google_tasks = google_tasks
        self._project_repo = project_repo
        self._llm = llm

    def _classify_type(self, name: str) -> ProjectType:
        """Use LLM to classify the project type; fall back to PERSONAL."""
        if self._llm is None:
            return ProjectType.PERSONAL
        types_block = "\n".join(f"- {t.value}" for t in _ALL_TYPES)
        prompt = _TYPE_CLASSIFY_PROMPT.format(name=name, types=types_block)
        try:
            raw = self._llm._call_llm_sync(prompt).strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:-1])
            data = json.loads(raw)
            return ProjectType(data.get("recommended_type", "personal"))
        except Exception as e:
            logger.warning("project_type_classify_failed", name=name, error=str(e))
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

                project_type = ProjectType.PERSONAL if tl_id == inbox_list_id else self._classify_type(tl_title)
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
        return {"created": created, "updated": updated, "deactivated": deactivated, "skipped": skipped}
