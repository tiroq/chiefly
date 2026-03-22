from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.schemas.admin import ProjectDetailResult, ProjectListResult, ProjectWithStats
from db.models.project import Project
from db.models.project_alias import ProjectAlias


@pytest.fixture
def mock_project_repo():
    repo = MagicMock()
    repo.list_active = AsyncMock(return_value=[])
    repo.get_by_id = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_alias_repo():
    repo = MagicMock()
    repo.list_by_project = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_session():
    session = AsyncMock()
    return session


@pytest.fixture
def service(mock_project_repo, mock_alias_repo):
    from apps.api.services.admin_projects_service import AdminProjectsService

    return AdminProjectsService(
        project_repo=mock_project_repo,
        alias_repo=mock_alias_repo,
    )


def _mock_scalar_one(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


class TestListProjects:
    async def test_list_projects_returns_projects_with_task_counts(
        self, service, mock_session, mock_project_repo
    ):
        project_a = MagicMock(spec=Project)
        project_a.id = uuid.uuid4()
        project_b = MagicMock(spec=Project)
        project_b.id = uuid.uuid4()

        mock_project_repo.list_active.return_value = [project_a, project_b]
        mock_session.execute = AsyncMock(
            side_effect=[
                _mock_scalar_one(5),
                _mock_scalar_one(12),
            ]
        )

        result = await service.list_projects(mock_session)

        assert isinstance(result, ProjectListResult)
        assert result.total == 2
        assert len(result.items) == 2
        assert result.items[0].project is project_a
        assert result.items[0].task_count == 5
        assert result.items[1].project is project_b
        assert result.items[1].task_count == 12

    async def test_list_projects_returns_empty_list_when_no_projects(
        self, service, mock_session, mock_project_repo
    ):
        mock_project_repo.list_active.return_value = []

        result = await service.list_projects(mock_session)

        assert isinstance(result, ProjectListResult)
        assert result.total == 0
        assert result.items == []


class TestGetProjectDetail:
    async def test_get_project_detail_returns_none_for_missing_project(
        self, service, mock_session, mock_project_repo
    ):
        mock_project_repo.get_by_id.return_value = None
        project_id = uuid.uuid4()

        result = await service.get_project_detail(mock_session, project_id)

        assert result is None
        mock_project_repo.get_by_id.assert_called_once_with(project_id)

    async def test_get_project_detail_returns_project_with_aliases(
        self, service, mock_session, mock_project_repo, mock_alias_repo
    ):
        project_id = uuid.uuid4()
        project = MagicMock(spec=Project)
        project.id = project_id

        alias_a = MagicMock(spec=ProjectAlias)
        alias_a.alias = "proj-alias-1"
        alias_b = MagicMock(spec=ProjectAlias)
        alias_b.alias = "proj-alias-2"

        mock_project_repo.get_by_id.return_value = project
        mock_alias_repo.list_by_project.return_value = [alias_a, alias_b]
        mock_session.execute = AsyncMock(side_effect=[_mock_scalar_one(7)])

        result = await service.get_project_detail(mock_session, project_id)

        assert isinstance(result, ProjectDetailResult)
        assert result.project is project
        assert result.aliases == [alias_a, alias_b]
        mock_alias_repo.list_by_project.assert_called_once_with(project_id)

    async def test_get_project_detail_returns_task_count(
        self, service, mock_session, mock_project_repo, mock_alias_repo
    ):
        project_id = uuid.uuid4()
        project = MagicMock(spec=Project)
        project.id = project_id

        mock_project_repo.get_by_id.return_value = project
        mock_alias_repo.list_by_project.return_value = []
        mock_session.execute = AsyncMock(side_effect=[_mock_scalar_one(23)])

        result = await service.get_project_detail(mock_session, project_id)

        assert isinstance(result, ProjectDetailResult)
        assert result.task_count == 23
