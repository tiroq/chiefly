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

from apps.api.services.google_tasks_service import GoogleTask
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
    SourceTask,
    TaskProcessingQueue,
    TaskRecord,
    TaskRevision,
    TaskSnapshot,
    TelegramReviewSession,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_bigint_for_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


STABLE_ID = uuid.uuid4()
SOURCE_TASK_ID = uuid.uuid4()
ENTRY_ID = uuid.uuid4()
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
    task_id: str = "g-001",
    tasklist_id: str = "inbox-list",
    title: str = RAW_TITLE,
    notes: str | None = None,
    updated: str = "2024-06-01T09:00:00.000Z",
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


def _make_classification() -> TaskClassificationResult:
    return TaskClassificationResult(
        kind=TaskKind.WAITING,
        normalized_title=NORMALIZED_TITLE,
        project_guess="NFT Gateway",
        project_confidence=ConfidenceBand.HIGH,
        next_action="Prepare follow-up message",
        confidence=ConfidenceBand.HIGH,
        substeps=["Send reminder email", "Check status next week"],
    )


def _make_pipeline_result() -> PipelineResult:
    return PipelineResult(
        type=TaskKind.WAITING,
        project="NFT Gateway",
        title=NORMALIZED_TITLE,
        next_action="Prepare follow-up message",
        confidence=ConfidenceBand.HIGH,
        steps=["Send reminder email", "Check status next week"],
    )


async def _seed_db(session: AsyncSession) -> None:
    project = Project(
        id=PROJECT_ID,
        name="NFT Gateway",
        slug="nft-gateway",
        google_tasklist_id="nft-tasklist",
        project_type="client",
        is_active=True,
    )
    session.add(project)

    source_task = SourceTask(
        id=SOURCE_TASK_ID,
        google_task_id="g-001",
        google_tasklist_id="inbox-list",
        title_raw=RAW_TITLE,
        notes_raw=None,
        google_status="needsAction",
        content_hash="abc123",
    )
    session.add(source_task)

    record = TaskRecord(
        stable_id=STABLE_ID,
        current_tasklist_id="inbox-list",
        current_task_id="g-001",
        state=TaskRecordState.ACTIVE.value,
        processing_status=WorkflowStatus.PENDING.value,
    )
    session.add(record)

    queue_entry = TaskProcessingQueue(
        id=ENTRY_ID,
        source_task_id=SOURCE_TASK_ID,
        stable_id=STABLE_ID,
        processing_status=ProcessingStatus.LOCKED,
        processing_reason=ProcessingReason.NEW_TASK,
    )
    session.add(queue_entry)

    await session.commit()


def _mock_google_tasks_svc() -> MagicMock:
    svc = MagicMock()
    initial_task = _make_google_task()
    patched_task = _make_google_task(notes="--- chiefly:v1 ---\n{}\n--- /chiefly ---")
    moved_task = _make_google_task(
        task_id="g-002",
        tasklist_id="nft-tasklist",
        title=NORMALIZED_TITLE,
        updated="2024-06-01T09:01:00.000Z",
    )

    svc.get_task.side_effect = lambda tl, tid: {
        ("inbox-list", "g-001"): initial_task,
        ("nft-tasklist", "g-002"): moved_task,
    }.get((tl, tid), initial_task)

    svc.patch_task.return_value = _make_google_task(
        notes="--- chiefly:v1 ---\n{}\n--- /chiefly ---",
        updated="2024-06-01T09:00:30.000Z",
    )

    svc.move_task.return_value = moved_task
    return svc


def _mock_llm_svc() -> AsyncMock:
    svc = AsyncMock()
    classification = _make_classification()
    svc.classify_task.return_value = classification
    svc.run_pipeline.return_value = _make_pipeline_result()
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


class TestMainLoopE2E:
    @pytest.mark.asyncio
    async def test_full_processing_then_confirm_cycle(self, db_session):
        await _seed_db(db_session)

        mock_gtasks = _mock_google_tasks_svc()
        mock_llm = _mock_llm_svc()
        mock_telegram = AsyncMock()
        mock_telegram.send_proposal = AsyncMock(return_value=42)
        mock_telegram.send_text = AsyncMock(return_value=43)
        mock_telegram.aclose = AsyncMock()
        settings = _mock_settings()

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
            from apps.api.workers.processing_worker import _process_entry

            await _process_entry(db_session, ENTRY_ID, SOURCE_TASK_ID, STABLE_ID, settings)

        from db.repositories.task_record_repo import TaskRecordRepository

        record_repo = TaskRecordRepository(db_session)
        record = await record_repo.get_by_stable_id(STABLE_ID)
        assert record is not None
        assert record.processing_status == WorkflowStatus.AWAITING_REVIEW.value

        from db.repositories.review_session_repo import ReviewSessionRepository

        session_repo = ReviewSessionRepository(db_session)
        review = await session_repo.get_active_by_stable_id(STABLE_ID)
        assert review is not None
        assert review.status == "pending"
        assert review.telegram_message_id == 42
        assert review.proposed_changes is not None
        assert review.proposed_changes["normalized_title"] == NORMALIZED_TITLE
        assert review.proposed_changes["kind"] == str(TaskKind.WAITING)

        mock_telegram.send_proposal.assert_awaited_once()

        from db.repositories.task_revision_repo import TaskRevisionRepository

        revision_repo = TaskRevisionRepository(db_session)
        revisions = await revision_repo.list_by_stable_id(STABLE_ID)
        assert len(revisions) >= 1
        classification_rev = revisions[0]
        assert classification_rev.final_title == NORMALIZED_TITLE

        from db.repositories.processing_queue_repo import ProcessingQueueRepository

        queue_repo = ProcessingQueueRepository(db_session)
        entry = await queue_repo.get_by_id(ENTRY_ID)
        assert entry is not None
        assert entry.processing_status == ProcessingStatus.COMPLETED

        # GIVEN: processing completed, WHEN: user confirms

        from db.models.project import Project as ProjectModel
        from db.repositories.project_repo import ProjectRepository

        project_repo = ProjectRepository(db_session)
        project = await project_repo.get_by_id(PROJECT_ID)

        proposed = review.proposed_changes
        current_google = mock_gtasks.get_task("inbox-list", "g-001")

        before_state = current_google.raw_payload or {}

        moved = mock_gtasks.move_task("inbox-list", "g-001", project.google_tasklist_id)
        new_tasklist_id = moved.tasklist_id
        new_gtask_id = moved.id

        mock_gtasks.patch_task(new_tasklist_id, new_gtask_id, title=NORMALIZED_TITLE)

        after_google = mock_gtasks.get_task(new_tasklist_id, new_gtask_id)
        after_state = after_google.raw_payload or {}

        now = datetime.now(tz=timezone.utc)
        rev_no = await revision_repo.get_next_revision_no_by_stable_id(STABLE_ID)
        confirm_revision = TaskRevision(
            id=uuid.uuid4(),
            stable_id=STABLE_ID,
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
            STABLE_ID,
            new_tasklist_id,
            new_gtask_id,
            google_updated=after_google.updated,
        )

        await record_repo.update_processing_status(STABLE_ID, WorkflowStatus.APPLIED)

        review.status = "resolved"
        review.resolved_at = now
        await session_repo.save(review)

        await db_session.commit()

        # THEN: final state is consistent

        final_record = await record_repo.get_by_stable_id(STABLE_ID)
        assert final_record is not None
        assert final_record.processing_status == WorkflowStatus.APPLIED.value
        assert final_record.current_tasklist_id == "nft-tasklist"
        assert final_record.current_task_id == "g-002"

        final_review = await session_repo.get_by_id(review.id)
        assert final_review is not None
        assert final_review.status == "resolved"
        assert final_review.resolved_at is not None

        all_revisions = await revision_repo.list_by_stable_id(STABLE_ID)
        confirm_revs = [r for r in all_revisions if r.user_decision == ReviewAction.CONFIRM]
        assert len(confirm_revs) == 1
        cr = confirm_revs[0]
        assert cr.final_title == NORMALIZED_TITLE
        assert cr.after_tasklist_id == "nft-tasklist"
        assert cr.after_task_id == "g-002"
        assert cr.success is True

        total_revisions = len(all_revisions)
        assert total_revisions >= 3
