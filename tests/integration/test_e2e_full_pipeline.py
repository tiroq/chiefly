from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.services.google_tasks_service import GoogleTask, GoogleTasksService
from apps.api.services.review_queue_service import ReviewQueueService
from apps.api.services.sync_service import SyncService
from apps.api.workers.processing_worker import _process_entry
from core.domain.enums import (
    ConfidenceBand,
    ProcessingReason,
    ProcessingStatus,
    ReviewAction,
    TaskKind,
    TaskRecordState,
    WorkflowStatus,
)
from core.schemas.llm import PipelineResult, TaskClassificationResult
from db.base import Base
from db.models import (
    Project,
    TaskRevision,
)
from db.repositories.processing_queue_repo import ProcessingQueueRepository
from db.repositories.project_repo import ProjectRepository
from db.repositories.review_session_repo import ReviewSessionRepository
from db.repositories.source_task_repo import SourceTaskRepository
from db.repositories.task_record_repo import TaskRecordRepository
from db.repositories.task_revision_repo import TaskRevisionRepository
from db.repositories.task_snapshot_repo import TaskSnapshotRepository


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_bigint_for_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


PROJECT_ID = uuid.uuid4()

RAW_TITLE = "жду от alex сертификаты"
NORMALIZED_TITLE = "Wait for Alex to send certificates"


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


def _make_google_task(
    *,
    task_id: str,
    tasklist_id: str,
    title: str,
    notes: str | None,
    updated: str,
) -> GoogleTask:
    return GoogleTask(
        id=task_id,
        title=title,
        notes=notes,
        status="needsAction",
        tasklist_id=tasklist_id,
        updated=updated,
        raw_payload={
            "id": task_id,
            "title": title,
            "notes": notes,
            "status": "needsAction",
            "updated": updated,
        },
    )


def _mock_google_tasks_svc() -> MagicMock:
    svc = MagicMock(spec=GoogleTasksService)

    storage: dict[tuple[str, str], GoogleTask] = {
        ("inbox-list", "g-001"): _make_google_task(
            task_id="g-001",
            tasklist_id="inbox-list",
            title=RAW_TITLE,
            notes=None,
            updated="2024-06-01T09:00:00.000Z",
        )
    }
    move_counter = {"value": 1}
    patch_counter = {"value": 0}

    def list_tasklists() -> list[dict[str, str]]:
        return [{"id": "inbox-list", "title": "Inbox"}]

    def list_tasks(tasklist_id: str) -> list[GoogleTask]:
        return [task for (tl, _), task in storage.items() if tl == tasklist_id]

    def get_task(tasklist_id: str, task_id: str) -> GoogleTask | None:
        return storage.get((tasklist_id, task_id))

    def patch_task(
        tasklist_id: str,
        task_id: str,
        title: str | None = None,
        notes: str | None = None,
        due: str | None = None,
    ) -> GoogleTask:
        key = (tasklist_id, task_id)
        current = storage[key]
        patch_counter["value"] += 1
        updated = f"2024-06-01T09:0{patch_counter['value']}:00.000Z"

        patched = _make_google_task(
            task_id=current.id,
            tasklist_id=current.tasklist_id,
            title=title if title is not None else current.title,
            notes=notes if notes is not None else current.notes,
            updated=updated,
        )
        if due is not None:
            patched.due = due
            if patched.raw_payload is not None:
                patched.raw_payload["due"] = due
        storage[key] = patched
        return patched

    def move_task(
        source_tasklist_id: str, task_id: str, destination_tasklist_id: str
    ) -> GoogleTask:
        source_key = (source_tasklist_id, task_id)
        original = storage.pop(source_key)
        move_counter["value"] += 1
        new_id = f"g-{move_counter['value']:03d}"
        moved = _make_google_task(
            task_id=new_id,
            tasklist_id=destination_tasklist_id,
            title=original.title,
            notes=original.notes,
            updated="2024-06-01T09:10:00.000Z",
        )
        storage[(destination_tasklist_id, new_id)] = moved
        return moved

    svc.list_tasklists.side_effect = list_tasklists
    svc.list_tasks.side_effect = list_tasks
    svc.get_task.side_effect = get_task
    svc.patch_task.side_effect = patch_task
    svc.move_task.side_effect = move_task
    return svc


def _mock_llm_svc() -> AsyncMock:
    svc = AsyncMock()
    svc.classify_task.return_value = TaskClassificationResult(
        kind=TaskKind.WAITING,
        normalized_title=NORMALIZED_TITLE,
        project_guess="NFT Gateway",
        project_confidence=ConfidenceBand.HIGH,
        next_action="Prepare follow-up message",
        confidence=ConfidenceBand.HIGH,
        substeps=["Send reminder email", "Check status next week"],
    )
    svc.run_pipeline.return_value = PipelineResult(
        type=TaskKind.WAITING,
        project="NFT Gateway",
        title=NORMALIZED_TITLE,
        next_action="Prepare follow-up message",
        confidence=ConfidenceBand.HIGH,
        steps=["Send reminder email", "Check status next week"],
    )
    return svc


def _mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.telegram_bot_token = "fake-token"
    settings.telegram_chat_id = "chat-123"
    settings.google_credentials_file = "/fake/creds.json"
    settings.llm_provider = "openai"
    settings.llm_model = "gpt-4o"
    settings.llm_api_key = "fake-key"
    settings.llm_base_url = ""
    return settings


async def _seed_project_only(session: AsyncSession) -> None:
    project = Project(
        id=PROJECT_ID,
        name="NFT Gateway",
        slug="nft-gateway",
        google_tasklist_id="nft-tasklist",
        project_type="client",
        is_active=True,
    )
    session.add(project)
    await session.commit()


class TestFullPipelineE2E:
    @pytest.mark.asyncio
    async def test_sync_to_confirm_full_cycle(self, db_session):
        await _seed_project_only(db_session)

        mock_gtasks = _mock_google_tasks_svc()
        mock_llm = _mock_llm_svc()
        mock_telegram = AsyncMock()
        mock_telegram.send_proposal = AsyncMock(return_value=42)
        mock_telegram.send_text = AsyncMock(return_value=43)
        mock_telegram.aclose = AsyncMock()
        settings = _mock_settings()

        sync_service = SyncService(db_session, mock_gtasks)
        summary = await sync_service.sync_all()
        assert summary.tasklists_scanned == 1
        assert summary.tasks_scanned == 1
        assert summary.new_count == 1
        assert summary.queued_count == 1

        source_repo = SourceTaskRepository(db_session)
        record_repo = TaskRecordRepository(db_session)
        queue_repo = ProcessingQueueRepository(db_session)
        snapshot_repo = TaskSnapshotRepository(db_session)

        source_task = await source_repo.get_by_google_task_id("g-001")
        assert source_task is not None
        assert source_task.google_tasklist_id == "inbox-list"

        record = await record_repo.get_by_pointer("inbox-list", "g-001")
        assert record is not None
        assert record.state == TaskRecordState.UNADOPTED.value
        assert record.processing_status == WorkflowStatus.PENDING.value

        latest_snapshot = await snapshot_repo.get_latest_by_stable_id(record.stable_id)
        assert latest_snapshot is not None
        assert latest_snapshot.tasklist_id == "inbox-list"
        assert latest_snapshot.task_id == "g-001"
        latest_snapshot.stable_id = None
        await db_session.flush()

        pending_entries = await queue_repo.list_pending(limit=10)
        assert len(pending_entries) == 1
        pending_entry = pending_entries[0]
        assert pending_entry.processing_status == ProcessingStatus.PENDING
        assert pending_entry.processing_reason == ProcessingReason.NEW_TASK

        claimed_entry = await queue_repo.claim_next()
        assert claimed_entry is not None
        assert claimed_entry.processing_status == ProcessingStatus.LOCKED
        await db_session.commit()

        from apps.api.services.review_pause import _reset_cache

        _reset_cache()
        with (
            patch(
                "apps.api.workers.processing_worker.GoogleTasksService",
                return_value=mock_gtasks,
            ),
            patch(
                "apps.api.workers.processing_worker.LLMService",
            ) as MockLLMService,
            patch(
                "apps.api.workers.processing_worker.TelegramService",
                return_value=mock_telegram,
            ),
            patch(
                "apps.api.workers.processing_worker.get_effective_llm_config",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
        ):
            MockLLMService.from_effective_config.return_value = mock_llm
            await _process_entry(
                db_session,
                claimed_entry.id,
                claimed_entry.source_task_id,
                claimed_entry.stable_id,
                settings,
            )

        processed_record = await record_repo.get_by_stable_id(record.stable_id)
        assert processed_record is not None
        assert processed_record.processing_status == WorkflowStatus.AWAITING_REVIEW.value

        session_repo = ReviewSessionRepository(db_session)
        review = await session_repo.get_active_by_stable_id(record.stable_id)
        assert review is not None
        assert review.status == "active"
        assert review.telegram_message_id == 42
        assert review.proposed_changes is not None
        assert review.proposed_changes["normalized_title"] == NORMALIZED_TITLE
        assert review.proposed_changes["kind"] == str(TaskKind.WAITING)

        updated_queue_entry = await queue_repo.get_by_id(claimed_entry.id)
        assert updated_queue_entry is not None
        assert updated_queue_entry.processing_status == ProcessingStatus.COMPLETED

        mock_telegram.send_proposal.assert_awaited_once()

        review_queue = ReviewQueueService(db_session, mock_telegram)
        sent = await review_queue.send_next()
        from apps.api.services.review_queue_service import SendNextResult

        assert sent == SendNextResult.ACTIVE_EXISTS

        revision_repo = TaskRevisionRepository(db_session)
        revisions_after_processing = await revision_repo.list_by_stable_id(record.stable_id)
        assert len(revisions_after_processing) >= 2

        project_repo = ProjectRepository(db_session)
        project = await project_repo.get_by_id(PROJECT_ID)
        assert project is not None

        proposed = review.proposed_changes or {}
        current_google = mock_gtasks.get_task("inbox-list", "g-001")
        assert current_google is not None

        before_state = current_google.raw_payload or {}

        moved = mock_gtasks.move_task("inbox-list", "g-001", project.google_tasklist_id)
        new_tasklist_id = moved.tasklist_id
        new_gtask_id = moved.id

        mock_gtasks.patch_task(new_tasklist_id, new_gtask_id, title=NORMALIZED_TITLE)

        after_google = mock_gtasks.get_task(new_tasklist_id, new_gtask_id)
        assert after_google is not None
        after_state = after_google.raw_payload or {}

        now = datetime.now(tz=timezone.utc)
        rev_no = await revision_repo.get_next_revision_no_by_stable_id(record.stable_id)
        confirm_revision = TaskRevision(
            id=uuid.uuid4(),
            stable_id=record.stable_id,
            revision_no=rev_no,
            raw_text=current_google.title or "",
            proposal_json=proposed,
            user_decision=ReviewAction.CONFIRM,
            action="confirm",
            actor_type="user",
            actor_id="telegram",
            before_tasklist_id="inbox-list",
            before_task_id="g-001",
            before_state_json=before_state,
            after_tasklist_id=new_tasklist_id,
            after_task_id=new_gtask_id,
            after_state_json=after_state,
            started_at=now,
            finished_at=now,
            success=True,
            final_title=proposed.get("normalized_title"),
            final_kind=proposed.get("kind"),
            final_project_id=project.id,
            final_next_action=proposed.get("next_action"),
        )
        await revision_repo.create(confirm_revision)

        await record_repo.update_pointer(
            record.stable_id,
            new_tasklist_id,
            new_gtask_id,
            google_updated=after_google.updated,
        )
        await record_repo.update_processing_status(record.stable_id, WorkflowStatus.APPLIED)

        review.status = "resolved"
        review.resolved_at = now
        await session_repo.save(review)

        await db_session.commit()

        final_record = await record_repo.get_by_stable_id(record.stable_id)
        assert final_record is not None
        assert final_record.processing_status == WorkflowStatus.APPLIED.value
        assert final_record.current_tasklist_id == project.google_tasklist_id
        assert final_record.current_task_id == new_gtask_id

        final_review = await session_repo.get_by_id(review.id)
        assert final_review is not None
        assert final_review.status == "resolved"
        assert final_review.resolved_at is not None

        all_revisions = await revision_repo.list_by_stable_id(record.stable_id)
        assert len(all_revisions) >= 3
        confirm_revs = [r for r in all_revisions if r.user_decision == ReviewAction.CONFIRM]
        assert len(confirm_revs) == 1
