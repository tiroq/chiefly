from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from db.models.project_prompt_version import ProjectPromptVersion
from db.models.system_event import SystemEvent
from db.repositories.prompt_version_repo import ProjectPromptVersionRepo
from db.repositories.system_event_repo import SystemEventRepo

logger = get_logger(__name__)


class PromptVersioningService:
    def __init__(self, version_repo: ProjectPromptVersionRepo, event_repo: SystemEventRepo) -> None:
        self._version_repo: ProjectPromptVersionRepo = version_repo
        self._event_repo: SystemEventRepo = event_repo

    async def create_version(
        self,
        _session: AsyncSession,
        project_id: uuid.UUID,
        title: str | None = None,
        description_text: str | None = None,
        classification_prompt_text: str | None = None,
        routing_prompt_text: str | None = None,
        examples_json: dict[str, object] | None = None,
        created_by: str | None = None,
        change_note: str | None = None,
    ) -> ProjectPromptVersion:
        current_active = await self._version_repo.get_active_for_project(project_id)
        if current_active is not None:
            current_active.is_active = False
            _ = await self._version_repo.save(current_active)

        next_no = await self._version_repo.get_next_version_no(project_id)

        new_version = ProjectPromptVersion(
            id=uuid.uuid4(),
            project_id=project_id,
            version_no=next_no,
            title=title,
            description_text=description_text,
            classification_prompt_text=classification_prompt_text,
            routing_prompt_text=routing_prompt_text,
            examples_json=examples_json,
            is_active=True,
            created_by=created_by,
            change_note=change_note,
        )
        created_version = await self._version_repo.create(new_version)

        event = SystemEvent(
            id=uuid.uuid4(),
            event_type="prompt_version_created",
            severity="info",
            subsystem="admin",
            message=f"Prompt version {next_no} created for project {project_id}",
            project_id=project_id,
        )
        _ = await self._event_repo.create(event)

        logger.info("prompt_version_created", project_id=str(project_id), version_no=next_no)
        return created_version

    async def activate_version(
        self, _session: AsyncSession, version_id: uuid.UUID
    ) -> ProjectPromptVersion:
        target = await self._version_repo.get_by_id(version_id)
        if target is None:
            raise ValueError(f"Version {version_id} not found")

        current_active = await self._version_repo.get_active_for_project(target.project_id)
        if current_active is not None and current_active.id != version_id:
            current_active.is_active = False
            _ = await self._version_repo.save(current_active)

        target.is_active = True
        saved_target = await self._version_repo.save(target)

        event = SystemEvent(
            id=uuid.uuid4(),
            event_type="prompt_version_activated",
            severity="info",
            subsystem="admin",
            message=(
                f"Prompt version {target.version_no} activated for project {target.project_id}"
            ),
            project_id=target.project_id,
        )
        _ = await self._event_repo.create(event)

        logger.info("prompt_version_activated", version_id=str(version_id))
        return saved_target

    async def deactivate_version(
        self, _session: AsyncSession, version_id: uuid.UUID
    ) -> ProjectPromptVersion:
        target = await self._version_repo.get_by_id(version_id)
        if target is None:
            raise ValueError(f"Version {version_id} not found")

        target.is_active = False
        saved_target = await self._version_repo.save(target)

        event = SystemEvent(
            id=uuid.uuid4(),
            event_type="prompt_version_deactivated",
            severity="info",
            subsystem="admin",
            message=f"Prompt version {target.version_no} deactivated",
            project_id=target.project_id,
        )
        _ = await self._event_repo.create(event)

        logger.info("prompt_version_deactivated", version_id=str(version_id))
        return saved_target

    async def get_active_for_project(
        self, _session: AsyncSession, project_id: uuid.UUID
    ) -> ProjectPromptVersion | None:
        return await self._version_repo.get_active_for_project(project_id)

    async def list_versions(
        self, _session: AsyncSession, project_id: uuid.UUID
    ) -> list[ProjectPromptVersion]:
        return await self._version_repo.list_by_project(project_id)
