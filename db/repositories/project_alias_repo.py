import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.project_alias import ProjectAlias


class ProjectAliasRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_alias(self, alias: str) -> ProjectAlias | None:
        result = await self._session.execute(
            select(ProjectAlias).where(func.lower(ProjectAlias.alias) == alias.lower())
        )
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: uuid.UUID) -> list[ProjectAlias]:
        result = await self._session.execute(
            select(ProjectAlias).where(ProjectAlias.project_id == project_id)
        )
        return list(result.scalars().all())

    async def create(self, project_alias: ProjectAlias) -> ProjectAlias:
        self._session.add(project_alias)
        await self._session.flush()
        return project_alias

    async def delete(self, alias_id: uuid.UUID) -> None:
        result = await self._session.execute(
            select(ProjectAlias).where(ProjectAlias.id == alias_id)
        )
        alias = result.scalar_one_or_none()
        if alias is not None:
            await self._session.delete(alias)
            await self._session.flush()

    async def get_all_aliases_map(self) -> dict[str, uuid.UUID]:
        result = await self._session.execute(select(ProjectAlias.alias, ProjectAlias.project_id))
        return {row[0]: row[1] for row in result.all()}
