"""Unit tests for run_processing() worker — Phase 3 refactor."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.domain.enums import (
    ConfidenceBand,
    ProcessingReason,
    ProcessingStatus,
    TaskKind,
    TaskRecordState,
    WorkflowStatus,
)
from core.domain.exceptions import RateLimitError


def _make_source_task(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "google_task_id": "gtask-001",
        "google_tasklist_id": "inbox-list",
        "title_raw": "Buy groceries",
        "notes_raw": None,
        "google_status": "needsAction",
        "google_updated_at": None,
        "content_hash": "abc123def456",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_queue_entry(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "source_task_id": uuid.uuid4(),
        "stable_id": uuid.uuid4(),
        "processing_status": ProcessingStatus.LOCKED,
        "processing_reason": ProcessingReason.NEW_TASK,
        "content_hash_at_processing": None,
        "retry_count": 0,
        "max_retries": 3,
        "error_message": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_task_record(state=TaskRecordState.UNADOPTED, **overrides):
    defaults = {
        "stable_id": uuid.uuid4(),
        "current_tasklist_id": "inbox-list",
        "current_task_id": "gtask-001",
        "state": state.value,
        "processing_status": WorkflowStatus.PENDING.value,
        "consecutive_misses": 0,
        "pointer_updated_at": None,
        "last_seen_at": None,
        "last_google_updated": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_google_task(**overrides):
    defaults = {
        "id": "gtask-001",
        "title": "Buy groceries",
        "notes": None,
        "status": "needsAction",
        "tasklist_id": "inbox-list",
        "due": None,
        "updated": "2026-03-22T10:00:00Z",
        "raw_payload": {
            "id": "gtask-001",
            "title": "Buy groceries",
            "status": "needsAction",
            "updated": "2026-03-22T10:00:00Z",
        },
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_classification(**overrides):
    defaults = {
        "kind": TaskKind.TASK,
        "normalized_title": "Buy groceries",
        "confidence": ConfidenceBand.HIGH,
        "next_action": "Go to the store",
        "due_hint": None,
        "substeps": [],
    }
    defaults.update(overrides)
    result = SimpleNamespace(**defaults)
    result.model_dump = lambda: {
        k: str(v) if hasattr(v, "value") else v for k, v in defaults.items()
    }
    return result


def _make_project(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "name": "Personal",
        "slug": "personal",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_snapshot(**overrides):
    defaults = {
        "id": 1,
        "stable_id": None,
        "tasklist_id": "inbox-list",
        "task_id": "gtask-001",
        "content_hash": "abc123",
        "payload": {},
        "is_latest": True,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_proceeds_even_with_active_review(mock_settings, mock_factory):
    """Processing must NOT be blocked by an active Telegram review.
    The review gate was removed to allow buffered pre-processing.
    Processing creates queued sessions; only send_next() is gated on active review.
    """
    from apps.api.workers.processing_worker import run_processing

    mock_settings.return_value = MagicMock()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)

    with patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls:
        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=None)
        mock_queue_cls.return_value = queue_repo

        await run_processing()

        # Processing attempted to claim work — the review gate no longer blocks it
        queue_repo.claim_next.assert_awaited_once()


@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_returns_when_queue_empty(mock_settings, mock_factory):
    from apps.api.workers.processing_worker import run_processing

    mock_settings.return_value = MagicMock()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)

    with patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls:
        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=None)
        mock_queue_cls.return_value = queue_repo

        await run_processing()

        queue_repo.claim_next.assert_awaited_once()


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_calls_process_entry(mock_settings, mock_factory, mock_process_entry):
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    entry = _make_queue_entry()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.return_value = None
    mock_process_entry.side_effect = None

    with patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls:
        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        mock_queue_cls.return_value = queue_repo

        await run_processing()

        mock_process_entry.assert_awaited_once()
        call_args = mock_process_entry.await_args
        assert call_args[0][1] == entry.id
        assert call_args[0][2] == entry.source_task_id
        assert call_args[0][3] == entry.stable_id


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_fails_entry_on_exception(
    mock_settings, mock_factory, mock_process_entry
):
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    entry = _make_queue_entry()
    fail_mock = AsyncMock()
    update_status_mock = AsyncMock()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RuntimeError("LLM timeout")

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.TaskRecordRepository") as mock_record_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.fail = fail_mock
        mock_queue_cls.return_value = queue_repo

        record_repo = MagicMock()
        record_repo.update_processing_status = update_status_mock
        mock_record_cls.return_value = record_repo

        await run_processing()

        fail_mock.assert_awaited_once()
        fail_args = fail_mock.await_args
        assert fail_args is not None
        assert fail_args[0][0] == entry.id
        assert "LLM timeout" in fail_args[0][1]

        update_status_mock.assert_awaited_once()
        status_args = update_status_mock.await_args
        assert status_args is not None
        assert status_args[0][0] == entry.stable_id
        assert status_args[0][1] == WorkflowStatus.FAILED


# --- _process_entry tests ---


def _setup_process_entry_mocks(
    source_task=None,
    record=None,
    google_task=None,
    patched_task=None,
    classification=None,
    project=None,
    snapshot=None,
):
    source_task = source_task or _make_source_task()
    google_task = google_task or _make_google_task()
    patched_task = patched_task or _make_google_task(
        notes="--- chiefly:v1 ---\n{}\n--- /chiefly ---",
        raw_payload={
            "id": "gtask-001",
            "title": "Buy groceries",
            "notes": "--- chiefly:v1 ---\n{}\n--- /chiefly ---",
        },
    )
    classification = classification or _make_classification()
    project = project or _make_project()
    snapshot = snapshot or _make_snapshot()

    patches = {}
    mocks = {}

    source_repo = MagicMock()
    source_repo.get_by_id = AsyncMock(return_value=source_task)
    patches["SourceTaskRepository"] = source_repo
    mocks["source_repo"] = source_repo

    project_repo = MagicMock()
    project_repo.list_active = AsyncMock(return_value=[project])
    patches["ProjectRepository"] = project_repo
    mocks["project_repo"] = project_repo

    review_repo = MagicMock()
    review_repo.has_active_review = AsyncMock(return_value=False)
    review_repo.create = AsyncMock(side_effect=lambda r: r)
    patches["ReviewSessionRepository"] = review_repo
    mocks["review_repo"] = review_repo

    queue_repo = MagicMock()
    queue_repo.complete = AsyncMock()
    queue_repo.mark_processing = AsyncMock()
    queue_repo.fail = AsyncMock()
    patches["ProcessingQueueRepository"] = queue_repo
    mocks["queue_repo"] = queue_repo

    record_repo = MagicMock()
    record_repo.get_by_stable_id = AsyncMock(return_value=record)
    record_repo.update_processing_status = AsyncMock()
    record_repo.update_state = AsyncMock()
    record_repo.update_pointer = AsyncMock()
    patches["TaskRecordRepository"] = record_repo
    mocks["record_repo"] = record_repo

    snapshot_repo = MagicMock()
    snapshot_repo.get_latest_by_stable_id = AsyncMock(return_value=snapshot)
    snapshot_repo.create = AsyncMock(return_value=snapshot)
    snapshot_repo.update_stable_id = AsyncMock()
    patches["TaskSnapshotRepository"] = snapshot_repo
    mocks["snapshot_repo"] = snapshot_repo

    revision_repo = MagicMock()
    revision_repo.get_next_revision_no_by_stable_id = AsyncMock(return_value=1)
    revision_repo.get_by_correlation_id = AsyncMock(return_value=None)
    revision_repo.create = AsyncMock(side_effect=lambda r: r)
    patches["TaskRevisionRepository"] = revision_repo
    mocks["revision_repo"] = revision_repo

    revision_service = MagicMock()
    revision_service.create_classification_revision = AsyncMock()
    patches["RevisionService"] = revision_service
    mocks["revision_service"] = revision_service

    alias_repo = MagicMock()
    patches["ProjectAliasRepo"] = alias_repo
    mocks["alias_repo"] = alias_repo

    google_tasks_svc = MagicMock()
    google_tasks_svc.get_task = MagicMock(return_value=google_task)
    google_tasks_svc.patch_task = MagicMock(return_value=patched_task)
    patches["GoogleTasksService"] = google_tasks_svc
    mocks["google_tasks_svc"] = google_tasks_svc

    classification_svc = MagicMock()
    classification_svc.classify = AsyncMock(return_value=(classification, project))
    patches["ClassificationService"] = classification_svc
    mocks["classification_svc"] = classification_svc

    llm_service = MagicMock()
    patches["LLMService"] = llm_service
    mocks["llm_service"] = llm_service

    routing_service = MagicMock()
    patches["ProjectRoutingService"] = routing_service
    mocks["routing_service"] = routing_service

    review_queue_svc = MagicMock()
    review_queue_svc.send_next = AsyncMock()
    patches["ReviewQueueService"] = review_queue_svc
    mocks["review_queue_svc"] = review_queue_svc

    telegram_svc = MagicMock()
    telegram_svc.aclose = AsyncMock()
    patches["TelegramService"] = telegram_svc
    mocks["telegram_svc"] = telegram_svc

    return patches, mocks, source_task, classification, project


def _apply_patches(patches):
    prefix = "apps.api.workers.processing_worker."
    applied = {}
    applied["SourceTaskRepository"] = patch(
        prefix + "SourceTaskRepository", return_value=patches["SourceTaskRepository"]
    )
    applied["ProjectRepository"] = patch(
        prefix + "ProjectRepository", return_value=patches["ProjectRepository"]
    )
    applied["ReviewSessionRepository"] = patch(
        prefix + "ReviewSessionRepository", return_value=patches["ReviewSessionRepository"]
    )
    applied["ProcessingQueueRepository"] = patch(
        prefix + "ProcessingQueueRepository", return_value=patches["ProcessingQueueRepository"]
    )
    applied["TaskRecordRepository"] = patch(
        prefix + "TaskRecordRepository", return_value=patches["TaskRecordRepository"]
    )
    applied["TaskSnapshotRepository"] = patch(
        prefix + "TaskSnapshotRepository", return_value=patches["TaskSnapshotRepository"]
    )
    applied["TaskRevisionRepository"] = patch(
        prefix + "TaskRevisionRepository", return_value=patches["TaskRevisionRepository"]
    )
    applied["RevisionService"] = patch(
        prefix + "RevisionService", return_value=patches["RevisionService"]
    )
    applied["ProjectAliasRepo"] = patch(
        prefix + "ProjectAliasRepo", return_value=patches["ProjectAliasRepo"]
    )
    applied["GoogleTasksService"] = patch(
        prefix + "GoogleTasksService", return_value=patches["GoogleTasksService"]
    )
    applied["ClassificationService"] = patch(
        prefix + "ClassificationService", return_value=patches["ClassificationService"]
    )
    applied["LLMService"] = patch(prefix + "LLMService")
    applied["get_effective_llm_config"] = patch(
        prefix + "get_effective_llm_config",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    )
    applied["ProjectRoutingService"] = patch(
        prefix + "ProjectRoutingService", return_value=patches["ProjectRoutingService"]
    )
    applied["TelegramService"] = patch(
        prefix + "TelegramService", return_value=patches["TelegramService"]
    )
    applied["ReviewQueueService"] = patch(
        "apps.api.services.review_queue_service.ReviewQueueService",
        return_value=patches["ReviewQueueService"],
    )
    return applied


@pytest.mark.asyncio
async def test_process_entry_source_task_missing():
    from apps.api.workers.processing_worker import _process_entry

    p, mocks, *_ = _setup_process_entry_mocks()
    mocks["source_repo"].get_by_id = AsyncMock(return_value=None)

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()
        settings = MagicMock()
        settings.google_credentials_file = "/tmp/creds.json"

        await _process_entry(session, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), settings)

        mocks["queue_repo"].complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_entry_unadopted_task_adopts_and_classifies():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.UNADOPTED)
    stable_id = record.stable_id

    p, mocks, source_task, classification, project = _setup_process_entry_mocks(record=record)

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()
        settings = MagicMock()
        settings.google_credentials_file = "/tmp/creds.json"
        settings.llm_provider = "openai"
        settings.llm_model = "gpt-4o"
        settings.llm_api_key = "key"
        settings.llm_base_url = ""
        settings.telegram_bot_token = "bot-token"
        settings.telegram_chat_id = "123"

        await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, settings)

        mocks["google_tasks_svc"].patch_task.assert_called()
        patch_calls = mocks["google_tasks_svc"].patch_task.call_args_list
        assert len(patch_calls) >= 1

        mocks["record_repo"].update_state.assert_any_await(stable_id, TaskRecordState.ACTIVE)

        mocks["classification_svc"].classify.assert_awaited_once()

        mocks["record_repo"].update_processing_status.assert_any_await(
            stable_id, WorkflowStatus.PROCESSING
        )
        mocks["record_repo"].update_processing_status.assert_any_await(
            stable_id, WorkflowStatus.AWAITING_REVIEW
        )

        mocks["review_repo"].create.assert_awaited_once()
        review_session = mocks["review_repo"].create.await_args[0][0]
        assert review_session.stable_id == stable_id
        assert review_session.proposed_changes is not None
        assert review_session.proposed_changes["normalized_title"] == "Buy groceries"

        mocks["queue_repo"].complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_entry_active_task_content_changed():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.ACTIVE)
    stable_id = record.stable_id

    p, mocks, source_task, classification, project = _setup_process_entry_mocks(record=record)

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()
        settings = MagicMock()
        settings.google_credentials_file = "/tmp/creds.json"
        settings.llm_provider = "openai"
        settings.llm_model = "gpt-4o"
        settings.llm_api_key = "key"
        settings.llm_base_url = ""
        settings.telegram_bot_token = "bot-token"
        settings.telegram_chat_id = "123"

        await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, settings)

        mocks["record_repo"].update_state.assert_not_awaited()

        mocks["classification_svc"].classify.assert_awaited_once()
        mocks["review_repo"].create.assert_awaited_once()
        mocks["queue_repo"].complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_entry_google_task_gone():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.ACTIVE)
    stable_id = record.stable_id

    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=record)
    mocks["google_tasks_svc"].get_task = MagicMock(return_value=None)

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()
        settings = MagicMock()
        settings.google_credentials_file = "/tmp/creds.json"
        settings.llm_provider = "openai"
        settings.llm_model = "gpt-4o"
        settings.llm_api_key = "key"
        settings.llm_base_url = ""

        await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, settings)

        mocks["record_repo"].update_processing_status.assert_any_await(
            stable_id, WorkflowStatus.FAILED, error="Google task not found"
        )
        mocks["queue_repo"].fail.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_entry_patch_failure_records_failed_revision():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.ACTIVE)
    stable_id = record.stable_id

    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=record)

    first_get_call = [True]
    original_get = mocks["google_tasks_svc"].get_task

    def get_task_then_fail(*args, **kwargs):
        return original_get(*args, **kwargs)

    mocks["google_tasks_svc"].get_task = MagicMock(side_effect=get_task_then_fail)
    mocks["google_tasks_svc"].patch_task = MagicMock(side_effect=RuntimeError("API quota exceeded"))

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()
        settings = MagicMock()
        settings.google_credentials_file = "/tmp/creds.json"
        settings.llm_provider = "openai"
        settings.llm_model = "gpt-4o"
        settings.llm_api_key = "key"
        settings.llm_base_url = ""
        settings.telegram_bot_token = "bot-token"
        settings.telegram_chat_id = "123"

        with pytest.raises(RuntimeError, match="API quota exceeded"):
            await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, settings)

        mocks["revision_repo"].create.assert_awaited_once()
        revision = mocks["revision_repo"].create.await_args[0][0]
        assert revision.success is False
        assert "API quota exceeded" in revision.error


@pytest.mark.asyncio
async def test_process_entry_creates_classification_revision_by_stable_id():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.ACTIVE)
    stable_id = record.stable_id

    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=record)

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()
        settings = MagicMock()
        settings.google_credentials_file = "/tmp/creds.json"
        settings.llm_provider = "openai"
        settings.llm_model = "gpt-4o"
        settings.llm_api_key = "key"
        settings.llm_base_url = ""
        settings.telegram_bot_token = "bot-token"
        settings.telegram_chat_id = "123"

        await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, settings)

        mocks["revision_service"].create_classification_revision.assert_awaited_once()
        kwargs = mocks["revision_service"].create_classification_revision.await_args.kwargs
        assert kwargs["stable_id"] == stable_id


@pytest.mark.asyncio
async def test_process_entry_review_session_has_proposed_changes():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.ACTIVE)
    stable_id = record.stable_id

    p, mocks, source_task, classification, project = _setup_process_entry_mocks(record=record)

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()
        settings = MagicMock()
        settings.google_credentials_file = "/tmp/creds.json"
        settings.llm_provider = "openai"
        settings.llm_model = "gpt-4o"
        settings.llm_api_key = "key"
        settings.llm_base_url = ""
        settings.telegram_bot_token = "bot-token"
        settings.telegram_chat_id = "123"

        await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, settings)

        review_session = mocks["review_repo"].create.await_args[0][0]
        changes = review_session.proposed_changes
        assert changes["kind"] == str(TaskKind.TASK)
        assert changes["confidence"] == str(ConfidenceBand.HIGH)
        assert changes["project_name"] == "Personal"
        assert changes["project_id"] == str(project.id)
        assert review_session.base_snapshot_id is not None
        assert review_session.base_google_updated is not None


@pytest.mark.asyncio
async def test_process_entry_metadata_revision_has_before_after():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.ACTIVE)
    stable_id = record.stable_id

    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=record)

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()
        settings = MagicMock()
        settings.google_credentials_file = "/tmp/creds.json"
        settings.llm_provider = "openai"
        settings.llm_model = "gpt-4o"
        settings.llm_api_key = "key"
        settings.llm_base_url = ""
        settings.telegram_bot_token = "bot-token"
        settings.telegram_chat_id = "123"

        await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, settings)

        mocks["revision_repo"].create.assert_awaited_once()
        revision = mocks["revision_repo"].create.await_args[0][0]
        assert revision.action == "annotate_metadata"
        assert revision.before_state_json is not None
        assert revision.after_state_json is not None
        assert revision.before_tasklist_id is not None
        assert revision.after_tasklist_id is not None
        assert revision.success is True
        assert revision.stable_id == stable_id
        assert revision.correlation_id is not None


@pytest.mark.asyncio
async def test_process_entry_no_stable_id_completes_early():
    from apps.api.workers.processing_worker import _process_entry

    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=None)
    mocks["record_repo"].get_by_stable_id = AsyncMock(return_value=None)

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()
        settings = MagicMock()
        settings.google_credentials_file = "/tmp/creds.json"

        await _process_entry(session, uuid.uuid4(), source_task.id, None, settings)

        mocks["queue_repo"].complete.assert_awaited_once()
        mocks["classification_svc"].classify.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_entry_adoption_creates_revision():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.UNADOPTED)
    stable_id = record.stable_id

    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=record)

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()
        settings = MagicMock()
        settings.google_credentials_file = "/tmp/creds.json"
        settings.llm_provider = "openai"
        settings.llm_model = "gpt-4o"
        settings.llm_api_key = "key"
        settings.llm_base_url = ""
        settings.telegram_bot_token = "bot-token"
        settings.telegram_chat_id = "123"

        await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, settings)

        create_calls = mocks["revision_repo"].create.await_args_list
        adoption_revisions = [
            call[0][0]
            for call in create_calls
            if hasattr(call[0][0], "action") and call[0][0].action == "adopt"
        ]
        assert len(adoption_revisions) == 1
        adoption_rev = adoption_revisions[0]
        assert adoption_rev.success is True
        assert adoption_rev.before_state_json is not None
        assert adoption_rev.after_state_json is not None


@pytest.mark.asyncio
async def test_process_entry_creates_snapshot_after_metadata_patch():
    from apps.api.workers.processing_worker import _process_entry

    record = _make_task_record(state=TaskRecordState.ACTIVE)
    stable_id = record.stable_id

    p, mocks, source_task, *_ = _setup_process_entry_mocks(record=record)

    with _multi_patch(_apply_patches(p)):
        session = MagicMock()
        session.commit = AsyncMock()
        settings = MagicMock()
        settings.google_credentials_file = "/tmp/creds.json"
        settings.llm_provider = "openai"
        settings.llm_model = "gpt-4o"
        settings.llm_api_key = "key"
        settings.llm_base_url = ""
        settings.telegram_bot_token = "bot-token"
        settings.telegram_chat_id = "123"

        await _process_entry(session, uuid.uuid4(), source_task.id, stable_id, settings)

        mocks["snapshot_repo"].create.assert_awaited_once()
        create_kwargs = mocks["snapshot_repo"].create.await_args
        assert (
            create_kwargs.kwargs.get("stable_id") == stable_id
            or create_kwargs[1].get("stable_id") == stable_id
        )


def _multi_patch(patch_dict):
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        entered = []
        try:
            for p in patch_dict.values():
                entered.append(p.__enter__())
            yield
        finally:
            for p in reversed(list(patch_dict.values())):
                p.__exit__(None, None, None)

    return _ctx()


# --- Rate limit handling tests ---


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_requeues_on_rate_limit(
    mock_settings, mock_factory, mock_process_entry
):
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    entry = _make_queue_entry()
    requeue_mock = AsyncMock()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RateLimitError(provider="openai", retry_after_seconds=30.0)

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.TaskRecordRepository") as mock_record_cls,
        patch("apps.api.workers.processing_worker.SystemEventRepo") as mock_event_repo_cls,
        patch("apps.api.workers.processing_worker.SystemEvent"),
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.requeue_with_delay = requeue_mock
        mock_queue_cls.return_value = queue_repo

        record_repo = MagicMock()
        record_repo.update_processing_status = AsyncMock()
        mock_record_cls.return_value = record_repo

        event_repo = MagicMock()
        event_repo.create = AsyncMock()
        mock_event_repo_cls.return_value = event_repo

        await run_processing()

        requeue_mock.assert_awaited_once()
        requeue_args = requeue_mock.await_args
        assert requeue_args is not None
        assert requeue_args[0][0] == entry.id

        record_repo.update_processing_status.assert_awaited_once_with(
            entry.stable_id, WorkflowStatus.PENDING
        )


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_rate_limit_emits_system_event(
    mock_settings, mock_factory, mock_process_entry
):
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    entry = _make_queue_entry()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RateLimitError(
        provider="github_models", retry_after_seconds=30.0
    )

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.TaskRecordRepository") as mock_record_cls,
        patch("apps.api.workers.processing_worker.SystemEvent") as mock_event_cls,
        patch("apps.api.workers.processing_worker.SystemEventRepo") as mock_event_repo_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.requeue_with_delay = AsyncMock()
        mock_queue_cls.return_value = queue_repo

        record_repo = MagicMock()
        record_repo.update_processing_status = AsyncMock()
        mock_record_cls.return_value = record_repo

        event_repo = MagicMock()
        event_repo.create = AsyncMock()
        mock_event_repo_cls.return_value = event_repo

        await run_processing()

        mock_event_cls.assert_called_once()
        event_kwargs = mock_event_cls.call_args
        assert event_kwargs.kwargs.get("event_type") == "llm_rate_limited"
        assert event_kwargs.kwargs.get("severity") == "warning"

        event_repo.create.assert_awaited_once()


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_rate_limit_resets_to_pending_not_failed(
    mock_settings, mock_factory, mock_process_entry
):
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    entry = _make_queue_entry()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RateLimitError(provider="openai", retry_after_seconds=30.0)

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.TaskRecordRepository") as mock_record_cls,
        patch("apps.api.workers.processing_worker.SystemEvent"),
        patch("apps.api.workers.processing_worker.SystemEventRepo") as mock_event_repo_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.requeue_with_delay = AsyncMock()
        mock_queue_cls.return_value = queue_repo

        record_repo = MagicMock()
        record_repo.update_processing_status = AsyncMock()
        mock_record_cls.return_value = record_repo

        event_repo = MagicMock()
        event_repo.create = AsyncMock()
        mock_event_repo_cls.return_value = event_repo

        await run_processing()

        record_repo.update_processing_status.assert_awaited_once_with(
            entry.stable_id, WorkflowStatus.PENDING
        )
        for call in record_repo.update_processing_status.await_args_list:
            assert call[0][1] != WorkflowStatus.FAILED


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_rate_limit_commits_session(
    mock_settings, mock_factory, mock_process_entry
):
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    entry = _make_queue_entry()
    commit_mock = AsyncMock()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = commit_mock
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RateLimitError(provider="openai", retry_after_seconds=30.0)

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.TaskRecordRepository") as mock_record_cls,
        patch("apps.api.workers.processing_worker.SystemEvent"),
        patch("apps.api.workers.processing_worker.SystemEventRepo") as mock_event_repo_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.requeue_with_delay = AsyncMock()
        mock_queue_cls.return_value = queue_repo

        record_repo = MagicMock()
        record_repo.update_processing_status = AsyncMock()
        mock_record_cls.return_value = record_repo

        event_repo = MagicMock()
        event_repo.create = AsyncMock()
        mock_event_repo_cls.return_value = event_repo

        await run_processing()

        assert commit_mock.await_count >= 2


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_rate_limit_passes_not_before_to_requeue(
    mock_settings, mock_factory, mock_process_entry
):
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    entry = _make_queue_entry()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RateLimitError(provider="openai", retry_after_seconds=30.0)

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.TaskRecordRepository") as mock_record_cls,
        patch("apps.api.workers.processing_worker.SystemEvent"),
        patch("apps.api.workers.processing_worker.SystemEventRepo") as mock_event_repo_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.requeue_with_delay = AsyncMock()
        mock_queue_cls.return_value = queue_repo

        record_repo = MagicMock()
        record_repo.update_processing_status = AsyncMock()
        mock_record_cls.return_value = record_repo

        event_repo = MagicMock()
        event_repo.create = AsyncMock()
        mock_event_repo_cls.return_value = event_repo

        before = datetime.now(tz=timezone.utc)
        await run_processing()

        queue_repo.requeue_with_delay.assert_awaited_once()
        call_kwargs = queue_repo.requeue_with_delay.call_args
        assert call_kwargs.kwargs.get("not_before") is not None
        not_before_val = call_kwargs.kwargs["not_before"]
        assert not_before_val > before
        expected_not_before = before + timedelta(seconds=30.0)
        assert abs((not_before_val - expected_not_before).total_seconds()) < 2.0


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_rate_limit_resets_processing_status_to_pending(
    mock_settings, mock_factory, mock_process_entry
):
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    stable_id = uuid.uuid4()
    entry = _make_queue_entry(stable_id=stable_id)

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RateLimitError(provider="openai", retry_after_seconds=30.0)

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.TaskRecordRepository") as mock_record_cls,
        patch("apps.api.workers.processing_worker.SystemEvent"),
        patch("apps.api.workers.processing_worker.SystemEventRepo") as mock_event_repo_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.requeue_with_delay = AsyncMock()
        mock_queue_cls.return_value = queue_repo

        record_repo = MagicMock()
        record_repo.update_processing_status = AsyncMock()
        mock_record_cls.return_value = record_repo

        event_repo = MagicMock()
        event_repo.create = AsyncMock()
        mock_event_repo_cls.return_value = event_repo

        await run_processing()

        record_repo.update_processing_status.assert_awaited_once_with(
            stable_id, WorkflowStatus.PENDING
        )


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_rate_limit_no_stable_id_skips_status_reset(
    mock_settings, mock_factory, mock_process_entry
):
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    entry = _make_queue_entry(stable_id=None)

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RateLimitError(provider="openai", retry_after_seconds=30.0)

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.TaskRecordRepository") as mock_record_cls,
        patch("apps.api.workers.processing_worker.SystemEvent"),
        patch("apps.api.workers.processing_worker.SystemEventRepo") as mock_event_repo_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.requeue_with_delay = AsyncMock()
        mock_queue_cls.return_value = queue_repo

        record_repo = MagicMock()
        record_repo.update_processing_status = AsyncMock()
        mock_record_cls.return_value = record_repo

        event_repo = MagicMock()
        event_repo.create = AsyncMock()
        mock_event_repo_cls.return_value = event_repo

        await run_processing()

        record_repo.update_processing_status.assert_not_awaited()


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_rate_limit_does_not_consume_retries(
    mock_settings, mock_factory, mock_process_entry
):
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    stable_id = uuid.uuid4()
    entry = _make_queue_entry(stable_id=stable_id, retry_count=2, max_retries=3)

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RateLimitError(provider="openai", retry_after_seconds=30.0)

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.TaskRecordRepository") as mock_record_cls,
        patch("apps.api.workers.processing_worker.SystemEvent"),
        patch("apps.api.workers.processing_worker.SystemEventRepo") as mock_event_repo_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.requeue_with_delay = AsyncMock()
        queue_repo.fail = AsyncMock()
        mock_queue_cls.return_value = queue_repo

        record_repo = MagicMock()
        record_repo.update_processing_status = AsyncMock()
        mock_record_cls.return_value = record_repo

        event_repo = MagicMock()
        event_repo.create = AsyncMock()
        mock_event_repo_cls.return_value = event_repo

        await run_processing()

        queue_repo.requeue_with_delay.assert_awaited_once()
        queue_repo.fail.assert_not_awaited()
        record_repo.update_processing_status.assert_awaited_once_with(
            stable_id, WorkflowStatus.PENDING
        )


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_rate_limit_queue_unlocked_even_if_side_effects_fail(
    mock_settings, mock_factory, mock_process_entry
):
    """requeue_with_delay() commits in its own transaction; if the side-effect
    session (TaskRecord update / SystemEvent) raises, the queue entry is
    still safely unlocked (PENDING), not stranded as LOCKED."""
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    stable_id = uuid.uuid4()
    entry = _make_queue_entry(stable_id=stable_id)
    requeue_mock = AsyncMock()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RateLimitError(provider="openai", retry_after_seconds=30.0)

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.TaskRecordRepository") as mock_record_cls,
        patch("apps.api.workers.processing_worker.SystemEvent"),
        patch("apps.api.workers.processing_worker.SystemEventRepo") as mock_event_repo_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.requeue_with_delay = requeue_mock
        mock_queue_cls.return_value = queue_repo

        record_repo = MagicMock()
        record_repo.update_processing_status = AsyncMock(
            side_effect=RuntimeError("DB connection lost")
        )
        mock_record_cls.return_value = record_repo

        event_repo = MagicMock()
        event_repo.create = AsyncMock()
        mock_event_repo_cls.return_value = event_repo

        await run_processing()

        requeue_mock.assert_awaited_once()

        record_repo.update_processing_status.assert_awaited_once()


@patch("apps.api.workers.processing_worker._process_entry")
@patch("apps.api.workers.processing_worker.get_session_factory")
@patch("apps.api.workers.processing_worker.get_settings")
@pytest.mark.asyncio
async def test_run_processing_rate_limit_event_failure_does_not_lose_queue_unlock(
    mock_settings, mock_factory, mock_process_entry
):
    """If SystemEventRepo.create raises, the queue entry must already be
    committed as PENDING from the first transaction."""
    from apps.api.workers.processing_worker import run_processing

    settings = MagicMock()
    mock_settings.return_value = settings

    entry = _make_queue_entry(stable_id=None)
    requeue_mock = AsyncMock()

    def make_session():
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    mock_factory.return_value = MagicMock(side_effect=make_session)
    mock_process_entry.side_effect = RateLimitError(provider="openai", retry_after_seconds=30.0)

    with (
        patch("apps.api.workers.processing_worker.ReviewSessionRepository") as mock_review_cls,
        patch("apps.api.workers.processing_worker.ProcessingQueueRepository") as mock_queue_cls,
        patch("apps.api.workers.processing_worker.TaskRecordRepository") as mock_record_cls,
        patch("apps.api.workers.processing_worker.SystemEvent"),
        patch("apps.api.workers.processing_worker.SystemEventRepo") as mock_event_repo_cls,
    ):
        review_repo = MagicMock()
        review_repo.has_active_review = AsyncMock(return_value=False)
        mock_review_cls.return_value = review_repo

        queue_repo = MagicMock()
        queue_repo.claim_next = AsyncMock(return_value=entry)
        queue_repo.requeue_with_delay = requeue_mock
        mock_queue_cls.return_value = queue_repo

        record_repo = MagicMock()
        record_repo.update_processing_status = AsyncMock()
        mock_record_cls.return_value = record_repo

        event_repo = MagicMock()
        event_repo.create = AsyncMock(side_effect=RuntimeError("Event table locked"))
        mock_event_repo_cls.return_value = event_repo

        await run_processing()

        requeue_mock.assert_awaited_once()
