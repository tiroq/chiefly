from __future__ import annotations

import uuid
from importlib import import_module
from unittest.mock import AsyncMock, MagicMock

import pytest

from db.models.project_prompt_version import ProjectPromptVersion
from db.models.system_event import SystemEvent


@pytest.fixture
def version_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_active_for_project = AsyncMock()
    repo.get_next_version_no = AsyncMock()
    repo.create = AsyncMock()
    repo.save = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.list_by_project = AsyncMock()
    return repo


@pytest.fixture
def event_repo() -> MagicMock:
    repo = MagicMock()
    repo.create = AsyncMock()
    return repo


@pytest.fixture
def service(version_repo: MagicMock, event_repo: MagicMock):
    service_class = import_module(
        "apps.api.services.prompt_versioning_service"
    ).PromptVersioningService
    return service_class(version_repo=version_repo, event_repo=event_repo)


@pytest.fixture
def mock_session() -> MagicMock:
    return MagicMock()


async def test_create_version_auto_increments_with_next_version_no(
    service,
    version_repo: MagicMock,
    event_repo: MagicMock,
    mock_session: MagicMock,
) -> None:
    project_id = uuid.uuid4()
    version_repo.get_active_for_project.return_value = None
    version_repo.get_next_version_no.return_value = 3
    version_repo.create.side_effect = lambda model: model
    event_repo.create.side_effect = lambda model: model

    result = await service.create_version(mock_session, project_id=project_id, title="v3")

    assert result.version_no == 3
    version_repo.get_next_version_no.assert_awaited_once_with(project_id)


async def test_create_version_deactivates_existing_active_before_new_activation(
    service,
    version_repo: MagicMock,
    event_repo: MagicMock,
    mock_session: MagicMock,
) -> None:
    project_id = uuid.uuid4()
    existing_active = MagicMock(spec=ProjectPromptVersion)
    existing_active.id = uuid.uuid4()
    existing_active.is_active = True
    version_repo.get_active_for_project.return_value = existing_active
    version_repo.get_next_version_no.return_value = 2
    version_repo.create.side_effect = lambda model: model
    event_repo.create.side_effect = lambda model: model

    await service.create_version(mock_session, project_id=project_id, title="v2")

    assert existing_active.is_active is False
    version_repo.save.assert_awaited_once_with(existing_active)


async def test_create_version_creates_prompt_version_created_event(
    service,
    version_repo: MagicMock,
    event_repo: MagicMock,
    mock_session: MagicMock,
) -> None:
    project_id = uuid.uuid4()
    version_repo.get_active_for_project.return_value = None
    version_repo.get_next_version_no.return_value = 1
    version_repo.create.side_effect = lambda model: model
    event_repo.create.side_effect = lambda model: model

    await service.create_version(mock_session, project_id=project_id, title="v1")

    event_repo.create.assert_awaited_once()
    created_event = event_repo.create.call_args[0][0]
    assert isinstance(created_event, SystemEvent)
    assert created_event.event_type == "prompt_version_created"
    assert created_event.project_id == project_id


async def test_create_version_sets_new_version_active(
    service,
    version_repo: MagicMock,
    event_repo: MagicMock,
    mock_session: MagicMock,
) -> None:
    project_id = uuid.uuid4()
    version_repo.get_active_for_project.return_value = None
    version_repo.get_next_version_no.return_value = 4
    version_repo.create.side_effect = lambda model: model
    event_repo.create.side_effect = lambda model: model

    result = await service.create_version(mock_session, project_id=project_id, title="v4")

    assert result.is_active is True
    created_version = version_repo.create.call_args[0][0]
    assert created_version.is_active is True


async def test_activate_version_deactivates_current_then_activates_target(
    service,
    version_repo: MagicMock,
    event_repo: MagicMock,
    mock_session: MagicMock,
) -> None:
    project_id = uuid.uuid4()
    target_id = uuid.uuid4()
    target = MagicMock(spec=ProjectPromptVersion)
    target.id = target_id
    target.project_id = project_id
    target.version_no = 5
    target.is_active = False
    current_active = MagicMock(spec=ProjectPromptVersion)
    current_active.id = uuid.uuid4()
    current_active.project_id = project_id
    current_active.is_active = True
    version_repo.get_by_id.return_value = target
    version_repo.get_active_for_project.return_value = current_active
    version_repo.save.side_effect = lambda model: model
    event_repo.create.side_effect = lambda model: model

    result = await service.activate_version(mock_session, target_id)

    assert current_active.is_active is False
    assert result.is_active is True
    assert version_repo.save.await_count == 2
    saved_first = version_repo.save.await_args_list[0].args[0]
    saved_second = version_repo.save.await_args_list[1].args[0]
    assert saved_first is current_active
    assert saved_second is target


async def test_activate_version_creates_prompt_version_activated_event(
    service,
    version_repo: MagicMock,
    event_repo: MagicMock,
    mock_session: MagicMock,
) -> None:
    project_id = uuid.uuid4()
    target_id = uuid.uuid4()
    target = MagicMock(spec=ProjectPromptVersion)
    target.id = target_id
    target.project_id = project_id
    target.version_no = 6
    target.is_active = False
    version_repo.get_by_id.return_value = target
    version_repo.get_active_for_project.return_value = None
    version_repo.save.side_effect = lambda model: model
    event_repo.create.side_effect = lambda model: model

    await service.activate_version(mock_session, target_id)

    event_repo.create.assert_awaited_once()
    created_event = event_repo.create.call_args[0][0]
    assert created_event.event_type == "prompt_version_activated"
    assert created_event.project_id == project_id


async def test_deactivate_version_sets_inactive_and_creates_event(
    service,
    version_repo: MagicMock,
    event_repo: MagicMock,
    mock_session: MagicMock,
) -> None:
    project_id = uuid.uuid4()
    version_id = uuid.uuid4()
    target = MagicMock(spec=ProjectPromptVersion)
    target.id = version_id
    target.project_id = project_id
    target.version_no = 7
    target.is_active = True
    version_repo.get_by_id.return_value = target
    version_repo.save.side_effect = lambda model: model
    event_repo.create.side_effect = lambda model: model

    result = await service.deactivate_version(mock_session, version_id)

    assert result.is_active is False
    version_repo.save.assert_awaited_once_with(target)
    event_repo.create.assert_awaited_once()
    created_event = event_repo.create.call_args[0][0]
    assert created_event.event_type == "prompt_version_deactivated"


async def test_activate_already_active_version_succeeds_without_deactivate_other(
    service,
    version_repo: MagicMock,
    event_repo: MagicMock,
    mock_session: MagicMock,
) -> None:
    project_id = uuid.uuid4()
    version_id = uuid.uuid4()
    target = MagicMock(spec=ProjectPromptVersion)
    target.id = version_id
    target.project_id = project_id
    target.version_no = 8
    target.is_active = True
    version_repo.get_by_id.return_value = target
    version_repo.get_active_for_project.return_value = target
    version_repo.save.side_effect = lambda model: model
    event_repo.create.side_effect = lambda model: model

    result = await service.activate_version(mock_session, version_id)

    assert result.is_active is True
    version_repo.save.assert_awaited_once_with(target)
    event_repo.create.assert_awaited_once()


async def test_activate_version_raises_for_missing_version(
    service,
    version_repo: MagicMock,
    mock_session: MagicMock,
) -> None:
    missing_id = uuid.uuid4()
    version_repo.get_by_id.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await service.activate_version(mock_session, missing_id)


async def test_deactivate_version_raises_for_missing_version(
    service,
    version_repo: MagicMock,
    mock_session: MagicMock,
) -> None:
    missing_id = uuid.uuid4()
    version_repo.get_by_id.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await service.deactivate_version(mock_session, missing_id)
