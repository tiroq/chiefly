from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.domain.enums import TaskRecordState, WorkflowStatus
from tests.unit.test_processing_worker import (
    _apply_patches,
    _make_classification,
    _make_google_task,
    _make_project,
    _make_queue_entry,
    _make_snapshot,
    _make_source_task,
    _make_task_record,
    _multi_patch,
    _setup_process_entry_mocks,
)


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.google_credentials_file = "/tmp/creds.json"
    settings.llm_provider = "openai"
    settings.llm_model = "gpt-4o"
    settings.llm_api_key = "key"
    settings.llm_base_url = ""
    settings.telegram_bot_token = "bot-token"
    settings.telegram_chat_id = "123"
    return settings


@pytest.mark.asyncio
async def test_run_processing_classification_failure_marks_failed():
    from apps.api.workers.processing_worker import run_processing

    stable_id = uuid.uuid4()
    entry = _make_queue_entry(stable_id=stable_id)
    source_task = _make_source_task(id=entry.source_task_id)
    record = _make_task_record(
        state=TaskRecordState.ACTIVE,
        stable_id=stable_id,
        current_tasklist_id=source_task.google_tasklist_id,
        current_task_id=source_task.google_task_id,
    )

    p, mocks, *_ = _setup_process_entry_mocks(source_task=source_task, record=record)
    mocks["classification_svc"].classify = AsyncMock(
        side_effect=RuntimeError("LLM classification exploded")
    )
    mocks["queue_repo"].claim_next = AsyncMock(return_value=entry)

    def make_session():
        session = MagicMock()
        session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    with _multi_patch(
        {
            **_apply_patches(p),
            "get_settings": patch(
                "apps.api.workers.processing_worker.get_settings",
                return_value=_make_settings(),
            ),
            "get_session_factory": patch(
                "apps.api.workers.processing_worker.get_session_factory",
                return_value=MagicMock(side_effect=make_session),
            ),
        }
    ):
        await run_processing()

    mocks["queue_repo"].fail.assert_awaited_once()
    fail_args = mocks["queue_repo"].fail.await_args[0]
    assert fail_args[0] == entry.id
    assert "LLM classification exploded" in fail_args[1]

    mocks["record_repo"].update_processing_status.assert_any_await(
        stable_id,
        WorkflowStatus.FAILED,
        error="LLM classification exploded",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_mode", "error_text"),
    [
        ("classify", "classification failed"),
        ("snapshot", "snapshot failed"),
        ("review", "review creation failed"),
    ],
)
async def test_process_entry_propagates_failures(failure_mode, error_text):
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.ACTIVE)
    stable_id = record.stable_id
    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=record)

    if failure_mode == "classify":
        mocks["classification_svc"].classify = AsyncMock(side_effect=RuntimeError(error_text))
    elif failure_mode == "snapshot":
        mocks["snapshot_repo"].create = AsyncMock(side_effect=RuntimeError(error_text))
    elif failure_mode == "review":
        mocks["review_repo"].create = AsyncMock(side_effect=RuntimeError(error_text))

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()

        with pytest.raises(RuntimeError, match=error_text):
            await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, _make_settings())


@pytest.mark.asyncio
async def test_process_entry_telegram_send_failure_is_graceful():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.ACTIVE)
    stable_id = record.stable_id
    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=record)

    mocks["review_queue_svc"].send_next = AsyncMock(side_effect=RuntimeError("telegram down"))
    mocks["review_repo"].save = AsyncMock()

    event_repo = MagicMock()
    event_repo.create = AsyncMock()

    with _multi_patch(
        {
            **_apply_patches(p),
            "SystemEventRepo": patch(
                "db.repositories.system_event_repo.SystemEventRepo",
                return_value=event_repo,
            ),
        }
    ):
        session = MagicMock()
        session.commit = AsyncMock()

        await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, _make_settings())

    review_session = mocks["review_repo"].create.await_args[0][0]
    assert review_session.status == "send_failed"
    mocks["review_repo"].save.assert_awaited_once_with(review_session)
    mocks["queue_repo"].complete.assert_awaited_once()
    mocks["queue_repo"].fail.assert_not_awaited()
    assert session.commit.await_count == 2

    event_repo.create.assert_awaited_once()
    event = event_repo.create.await_args[0][0]
    assert event.event_type == "telegram_send_failed"
    assert event.severity == "error"
    assert event.subsystem == "processing"
    assert event.stable_id == stable_id


@pytest.mark.asyncio
async def test_process_entry_adopt_google_task_gone_sets_deleted_and_continues():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.UNADOPTED)
    stable_id = record.stable_id
    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=record)

    mocks["google_tasks_svc"].get_task = MagicMock(
        side_effect=[None, _make_google_task(tasklist_id=source_task.google_tasklist_id)]
    )

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()

        await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, _make_settings())

    mocks["record_repo"].update_state.assert_any_await(stable_id, TaskRecordState.DELETED)
    mocks["record_repo"].update_processing_status.assert_any_await(
        stable_id, WorkflowStatus.AWAITING_REVIEW
    )
    mocks["classification_svc"].classify.assert_awaited_once()
    mocks["queue_repo"].complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_entry_adopt_patch_failure_propagates():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.UNADOPTED)
    stable_id = record.stable_id
    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=record)

    mocks["google_tasks_svc"].patch_task = MagicMock(side_effect=RuntimeError("adopt patch failed"))

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()

        with pytest.raises(RuntimeError, match="adopt patch failed"):
            await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, _make_settings())


@pytest.mark.asyncio
async def test_process_entry_classification_without_project_keeps_null_project_fields():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.ACTIVE)
    stable_id = record.stable_id
    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=record)
    classification = _make_classification()
    mocks["classification_svc"].classify = AsyncMock(return_value=(classification, None))

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()

        await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, _make_settings())

    review_session = mocks["review_repo"].create.await_args[0][0]
    assert review_session.proposed_changes["project_name"] is None
    assert review_session.proposed_changes["project_id"] is None
    mocks["queue_repo"].complete.assert_awaited_once()
