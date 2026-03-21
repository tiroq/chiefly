import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.project_prompt_version import ProjectPromptVersion


class ProjectPromptVersionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, version_id: uuid.UUID) -> ProjectPromptVersion | None:
        result = await self._session.execute(
            select(ProjectPromptVersion).where(ProjectPromptVersion.id == version_id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[ProjectPromptVersion]:
        result = await self._session.execute(
            select(ProjectPromptVersion)
            .where(ProjectPromptVersion.project_id == project_id)
            .order_by(ProjectPromptVersion.version_no.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_active_for_project(self, project_id: uuid.UUID) -> ProjectPromptVersion | None:
        result = await self._session.execute(
            select(ProjectPromptVersion).where(
                ProjectPromptVersion.project_id == project_id,
                ProjectPromptVersion.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> list[ProjectPromptVersion]:
        result = await self._session.execute(
            select(ProjectPromptVersion).where(ProjectPromptVersion.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def get_next_version_no(self, project_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(ProjectPromptVersion.version_no), 0)).where(
                ProjectPromptVersion.project_id == project_id
            )
        )
        return (result.scalar() or 0) + 1

    async def create(self, prompt_version: ProjectPromptVersion) -> ProjectPromptVersion:
        self._session.add(prompt_version)
        await self._session.flush()
        return prompt_version

    async def save(self, prompt_version: ProjectPromptVersion) -> ProjectPromptVersion:
        self._session.add(prompt_version)
        await self._session.flush()
        return prompt_version
