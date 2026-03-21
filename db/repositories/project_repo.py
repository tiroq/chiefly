import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.project import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        result = await self._session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Project | None:
        result = await self._session.execute(select(Project).where(Project.slug == slug))
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Project]:
        result = await self._session.execute(
            select(Project).where(Project.is_active.is_(True)).order_by(Project.name)
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[Project]:
        result = await self._session.execute(select(Project).order_by(Project.name))
        return list(result.scalars().all())

    async def get_by_google_tasklist_id(self, tasklist_id: str) -> Project | None:
        result = await self._session.execute(
            select(Project).where(Project.google_tasklist_id == tasklist_id)
        )
        return result.scalar_one_or_none()

    async def create(self, project: Project) -> Project:
        self._session.add(project)
        await self._session.flush()
        return project

    async def save(self, project: Project) -> Project:
        self._session.add(project)
        await self._session.flush()
        return project
