from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services.rollback_service import RollbackService
from core.domain.exceptions import (
    LockAcquisitionError,
    RollbackDriftError,
    RollbackError,
    TaskNotFoundError,
)

STABLE_ID = uuid.uuid4()
REVISION_ID = uuid.uuid4()
TASKLIST = "list-A"
TASK_ID = "gtask-001"


def _make_google_task(
    tasklist_id: str = TASKLIST,
    task_id: str = TASK_ID,
    title: str = "Current title",
    notes: str | None = None,
    updated: str = "2026-03-22T12:00:00Z",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=task_id,
        tasklist_id=tasklist_id,
        title=title,
        notes=notes,
        status="needsAction",
        due=None,
        updated=updated,
    )


def _make_task_record(
    tasklist_id: str = TASKLIST,
    task_id: str = TASK_ID,
) -> SimpleNamespace:
    return SimpleNamespace(
        stable_id=STABLE_ID,
        current_tasklist_id=tasklist_id,
        current_task_id=task_id,
    )


def _make_revision(
    revision_id: uuid.UUID = REVISION_ID,
    revision_no: int = 1,
    before_state: dict | None = None,
    after_state: dict | None = None,
    action: str | None = None,
) -> SimpleNamespace:
    if before_state is None:
        before_state = {
            "task_id": TASK_ID,
            "tasklist_id": TASKLIST,
            "title": "Old title",
            "notes": "Old notes",
            "status": "needsAction",
            "due": None,
            "updated": "2026-03-22T10:00:00Z",
        }
    return SimpleNamespace(
        id=revision_id,
        stable_id=STABLE_ID,
        revision_no=revision_no,
        before_state_json=before_state,
        after_state_json=after_state
        or {
            "task_id": TASK_ID,
            "tasklist_id": TASKLIST,
            "title": "Current title",
            "notes": None,
            "status": "needsAction",
            "due": None,
            "updated": "2026-03-22T12:00:00Z",
        },
        action=action,
    )


def _setup_service():
    session = AsyncMock()
    google_svc = MagicMock()

    with (
        patch("apps.api.services.rollback_service.TaskRecordRepository") as MockRecordRepo,
        patch("apps.api.services.rollback_service.TaskRevisionRepository") as MockRevisionRepo,
        patch("apps.api.services.rollback_service.IdempotencyService") as MockLockSvc,
    ):
        record_repo = AsyncMock()
        revision_repo = AsyncMock()
        lock_svc = AsyncMock()

        MockRecordRepo.return_value = record_repo
        MockRevisionRepo.return_value = revision_repo
        MockLockSvc.return_value = lock_svc

        svc = RollbackService(session, google_svc)

    svc._record_repo = record_repo
    svc._revision_repo = revision_repo
    svc._lock_svc = lock_svc

    return svc, google_svc, record_repo, revision_repo, lock_svc


@pytest.mark.asyncio
async def test_successful_rollback():
    svc, google_svc, record_repo, revision_repo, lock_svc = _setup_service()

    record_repo.get_by_stable_id.return_value = _make_task_record()
    google_svc.get_task.return_value = _make_google_task()

    target_rev = _make_revision()
    revision_repo.list_by_stable_id.return_value = [target_rev]
    revision_repo.get_next_revision_no_by_stable_id.return_value = 2

    patched = _make_google_task(
        title="Old title", notes="Old notes", updated="2026-03-22T12:01:00Z"
    )
    google_svc.patch_task.return_value = patched

    created_revisions: list = []

    async def capture_create(rev):
        created_revisions.append(rev)
        return rev

    revision_repo.create.side_effect = capture_create

    result = await svc.rollback(STABLE_ID, REVISION_ID)

    assert result.action == "rollback"
    assert result.revision_no == 2
    assert result.success is True
    assert result.before_state_json is not None
    assert result.after_state_json is not None

    google_svc.patch_task.assert_called_once_with(
        TASKLIST,
        TASK_ID,
        title="Old title",
        notes="Old notes",
        due=None,
    )
    google_svc.move_task.assert_not_called()

    lock_svc.require_lock.assert_awaited_once_with(f"task:{STABLE_ID}")
    lock_svc.release_lock.assert_awaited_once_with(f"task:{STABLE_ID}")

    record_repo.update_pointer.assert_not_awaited()


@pytest.mark.asyncio
async def test_rollback_with_list_move():
    svc, google_svc, record_repo, revision_repo, lock_svc = _setup_service()

    record_repo.get_by_stable_id.return_value = _make_task_record(
        tasklist_id="list-B", task_id="gtask-002"
    )
    google_svc.get_task.return_value = _make_google_task(tasklist_id="list-B", task_id="gtask-002")

    target_rev = _make_revision(
        before_state={
            "task_id": TASK_ID,
            "tasklist_id": "list-A",
            "title": "Old title",
            "notes": None,
            "status": "needsAction",
            "due": None,
            "updated": "2026-03-22T10:00:00Z",
        },
        after_state={
            "task_id": "gtask-002",
            "tasklist_id": "list-B",
            "title": "Current title",
            "notes": None,
            "status": "needsAction",
            "due": None,
            "updated": "2026-03-22T12:00:00Z",
        },
    )
    revision_repo.list_by_stable_id.return_value = [target_rev]
    revision_repo.get_next_revision_no_by_stable_id.return_value = 2

    moved = _make_google_task(tasklist_id="list-A", task_id="gtask-003")
    google_svc.move_task.return_value = moved

    patched = _make_google_task(
        tasklist_id="list-A", task_id="gtask-003", title="Old title", updated="2026-03-22T12:01:00Z"
    )
    google_svc.patch_task.return_value = patched

    revision_repo.create.side_effect = lambda rev: rev

    result = await svc.rollback(STABLE_ID, REVISION_ID)

    google_svc.move_task.assert_called_once_with("list-B", "gtask-002", "list-A")
    google_svc.patch_task.assert_called_once_with(
        "list-A",
        "gtask-003",
        title="Old title",
        notes=None,
        due=None,
    )

    record_repo.update_pointer.assert_awaited_once_with(
        STABLE_ID,
        "list-A",
        "gtask-003",
        google_updated="2026-03-22T12:01:00Z",
    )

    assert result.action == "rollback"
    assert result.success is True


@pytest.mark.asyncio
async def test_drift_detection_aborts_without_force():
    svc, google_svc, record_repo, revision_repo, lock_svc = _setup_service()

    record_repo.get_by_stable_id.return_value = _make_task_record()
    google_svc.get_task.return_value = _make_google_task(updated="2026-03-22T14:00:00Z")

    target_rev = _make_revision(
        after_state={
            "task_id": TASK_ID,
            "tasklist_id": TASKLIST,
            "title": "Current title",
            "notes": None,
            "status": "needsAction",
            "due": None,
            "updated": "2026-03-22T12:00:00Z",
        },
    )
    revision_repo.list_by_stable_id.return_value = [target_rev]

    with pytest.raises(RollbackDriftError, match="modified externally"):
        await svc.rollback(STABLE_ID, REVISION_ID)

    google_svc.patch_task.assert_not_called()
    google_svc.move_task.assert_not_called()
    lock_svc.release_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_rollback_despite_drift():
    svc, google_svc, record_repo, revision_repo, lock_svc = _setup_service()

    record_repo.get_by_stable_id.return_value = _make_task_record()
    google_svc.get_task.return_value = _make_google_task(updated="2026-03-22T14:00:00Z")

    target_rev = _make_revision(
        after_state={
            "task_id": TASK_ID,
            "tasklist_id": TASKLIST,
            "title": "Current title",
            "notes": None,
            "status": "needsAction",
            "due": None,
            "updated": "2026-03-22T12:00:00Z",
        },
    )
    revision_repo.list_by_stable_id.return_value = [target_rev]
    revision_repo.get_next_revision_no_by_stable_id.return_value = 2

    patched = _make_google_task(title="Old title", updated="2026-03-22T14:01:00Z")
    google_svc.patch_task.return_value = patched
    revision_repo.create.side_effect = lambda rev: rev

    result = await svc.rollback(STABLE_ID, REVISION_ID, force=True)

    assert result.action == "rollback"
    assert result.success is True
    google_svc.patch_task.assert_called_once()


@pytest.mark.asyncio
async def test_task_record_not_found():
    svc, google_svc, record_repo, revision_repo, lock_svc = _setup_service()

    record_repo.get_by_stable_id.return_value = None

    with pytest.raises(TaskNotFoundError, match="TaskRecord not found"):
        await svc.rollback(STABLE_ID, REVISION_ID)

    google_svc.get_task.assert_not_called()
    lock_svc.release_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_google_task_not_found():
    svc, google_svc, record_repo, revision_repo, lock_svc = _setup_service()

    record_repo.get_by_stable_id.return_value = _make_task_record()
    google_svc.get_task.return_value = None

    with pytest.raises(TaskNotFoundError, match="Google Task not found"):
        await svc.rollback(STABLE_ID, REVISION_ID)

    lock_svc.release_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_revision_without_before_state():
    svc, google_svc, record_repo, revision_repo, lock_svc = _setup_service()

    record_repo.get_by_stable_id.return_value = _make_task_record()
    google_svc.get_task.return_value = _make_google_task()

    target_rev = _make_revision()
    target_rev.before_state_json = None
    revision_repo.list_by_stable_id.return_value = [target_rev]

    with pytest.raises(RollbackError, match="no before_state_json"):
        await svc.rollback(STABLE_ID, REVISION_ID)

    lock_svc.release_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_double_rollback():
    svc, google_svc, record_repo, revision_repo, lock_svc = _setup_service()

    record_repo.get_by_stable_id.return_value = _make_task_record()
    google_svc.get_task.return_value = _make_google_task(
        title="Rolled-back title", updated="2026-03-22T13:00:00Z"
    )

    first_rollback_id = uuid.uuid4()
    first_rollback = _make_revision(
        revision_id=first_rollback_id,
        revision_no=2,
        before_state={
            "task_id": TASK_ID,
            "tasklist_id": TASKLIST,
            "title": "Before first rollback",
            "notes": None,
            "status": "needsAction",
            "due": None,
            "updated": "2026-03-22T12:00:00Z",
        },
        after_state={
            "task_id": TASK_ID,
            "tasklist_id": TASKLIST,
            "title": "Rolled-back title",
            "notes": None,
            "status": "needsAction",
            "due": None,
            "updated": "2026-03-22T13:00:00Z",
        },
        action="rollback",
    )

    original = _make_revision(
        revision_id=REVISION_ID,
        revision_no=1,
        before_state={
            "task_id": TASK_ID,
            "tasklist_id": TASKLIST,
            "title": "Original title",
            "notes": "Original notes",
            "status": "needsAction",
            "due": None,
            "updated": "2026-03-22T10:00:00Z",
        },
        after_state={
            "task_id": TASK_ID,
            "tasklist_id": TASKLIST,
            "title": "Before first rollback",
            "notes": None,
            "status": "needsAction",
            "due": None,
            "updated": "2026-03-22T12:00:00Z",
        },
    )

    revision_repo.list_by_stable_id.return_value = [original, first_rollback]
    revision_repo.get_next_revision_no_by_stable_id.return_value = 3

    patched = _make_google_task(
        title="Original title", notes="Original notes", updated="2026-03-22T13:01:00Z"
    )
    google_svc.patch_task.return_value = patched
    revision_repo.create.side_effect = lambda rev: rev

    result = await svc.rollback(STABLE_ID, REVISION_ID)

    assert result.action == "rollback"
    assert result.revision_no == 3
    assert result.success is True

    google_svc.patch_task.assert_called_once_with(
        TASKLIST,
        TASK_ID,
        title="Original title",
        notes="Original notes",
        due=None,
    )


@pytest.mark.asyncio
async def test_lock_acquisition_failure():
    svc, google_svc, record_repo, revision_repo, lock_svc = _setup_service()

    lock_svc.require_lock.side_effect = LockAcquisitionError("Could not acquire lock")

    with pytest.raises(LockAcquisitionError):
        await svc.rollback(STABLE_ID, REVISION_ID)

    google_svc.get_task.assert_not_called()
    record_repo.get_by_stable_id.assert_not_awaited()
