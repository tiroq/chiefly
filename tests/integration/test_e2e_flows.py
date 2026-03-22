# pyright: reportArgumentType=false, reportOptionalMemberAccess=false
"""
End-to-end service-level tests for complete product flows.
Tests the full lifecycle with mocked external services.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.domain.enums import ConfidenceBand, ProjectType, ReviewAction, TaskKind, TaskStatus
from core.domain.state_machine import transition
from core.schemas.llm import PipelineResult, TaskClassificationResult
from db.base import Base
from db.models import Project, TaskItem, TelegramReviewSession


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


@pytest_asyncio.fixture
async def seeded_session(db_session):
    """Session with pre-seeded projects."""
    nft = Project(
        id=uuid.uuid4(),
        name="NFT Gateway",
        slug="nft-gateway",
        google_tasklist_id="nft-tasklist-id",
        project_type=ProjectType.CLIENT,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    personal = Project(
        id=uuid.uuid4(),
        name="Personal",
        slug="personal",
        google_tasklist_id="personal-tasklist-id",
        project_type=ProjectType.PERSONAL,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(nft)
    db_session.add(personal)
    await db_session.commit()
    return db_session


@pytest.fixture
def classification_result():
    return PipelineResult(
        type=TaskKind.WAITING,
        title="Wait for Alex to send certificates",
        project="NFT Gateway",
        next_action="Prepare follow-up message",
        confidence=ConfidenceBand.HIGH,
        steps=["Draft email", "Set reminder"],
    )


@pytest.fixture
def google_task():
    from apps.api.services.google_tasks_service import GoogleTask

    return GoogleTask(
        id="gtask-e2e-001",
        title="жду от alex сертификаты",
        notes=None,
        status="needsAction",
        tasklist_id="inbox-list-id",
    )


class TestE2EHappyPath:
    """FLOW 1: inbox -> proposal -> confirm -> routed -> history saved."""

    @pytest.mark.asyncio
    async def test_full_intake_confirm_cycle(
        self, seeded_session, google_task, classification_result
    ):
        from apps.api.services.classification_service import ClassificationService
        from apps.api.services.google_tasks_service import GoogleTasksService
        from apps.api.services.intake_service import IntakeService
        from apps.api.services.llm_service import LLMService
        from apps.api.services.project_routing_service import ProjectRoutingService
        from apps.api.services.revision_service import RevisionService
        from apps.api.services.telegram_service import TelegramService
        from core.utils.datetime import utcnow
        from db.repositories.project_repo import ProjectRepository
        from db.repositories.review_session_repo import ReviewSessionRepository
        from db.repositories.task_item_repo import TaskItemRepository
        from db.repositories.task_revision_repo import TaskRevisionRepository

        # ── Step 1: Intake ─────────────────────
        mock_google = MagicMock(spec=GoogleTasksService)
        mock_google.list_tasks.return_value = [google_task]

        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.run_pipeline.return_value = classification_result

        mock_tg = AsyncMock(spec=TelegramService)
        mock_tg.send_proposal.return_value = 42

        routing = ProjectRoutingService()
        classification_svc = ClassificationService(mock_llm, routing)

        with patch("apps.api.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                google_tasks_inbox_list_id="inbox-list-id",
                telegram_chat_id="123456",
                llm_model="gpt-4o",
            )
            intake = IntakeService(
                session=seeded_session,
                google_tasks=mock_google,
                classification=classification_svc,
                telegram=mock_tg,
            )
            count = await intake.poll_and_process()

        assert count == 1

        # Verify task item created
        task_repo = TaskItemRepository(seeded_session)
        task = await task_repo.get_by_source_google_task_id("gtask-e2e-001")
        assert task is not None
        assert task.status == TaskStatus.PROPOSED
        assert task.kind == TaskKind.WAITING
        assert task.normalized_title == "Wait for Alex to send certificates"
        assert task.project_id is not None

        # Verify initial classification revision created
        rev_repo = TaskRevisionRepository(seeded_session)
        revisions = await rev_repo.list_by_task(task.id)
        assert len(revisions) == 1
        assert revisions[0].revision_no == 1
        assert revisions[0].final_kind == TaskKind.WAITING

        # Verify review session created
        session_repo = ReviewSessionRepository(seeded_session)
        review_session = await session_repo.get_active_by_task(task.id)
        assert review_session is not None
        assert review_session.status == "pending"
        assert review_session.telegram_message_id == 42

        # ── Step 2: Confirm ─────────────────────
        # Simulate what the confirm handler does
        task.status = transition(task.status, TaskStatus.CONFIRMED)
        task.confirmed_at = utcnow()
        task.is_processed = True
        task.status = transition(TaskStatus.CONFIRMED, TaskStatus.ROUTED)
        await task_repo.save(task)

        review_session.status = "resolved"
        review_session.resolved_at = utcnow()
        await session_repo.save(review_session)

        revision_svc = RevisionService(seeded_session)
        cls_result = TaskClassificationResult(
            kind=task.kind,
            normalized_title=task.normalized_title,
            confidence=task.confidence_band or "medium",
            next_action=task.next_action,
        )
        await revision_svc.create_decision_revision(
            task_item_id=task.id,
            raw_text=task.raw_text,
            decision=ReviewAction.CONFIRM,
            classification=cls_result,
            project_id=task.project_id,
        )
        await seeded_session.commit()

        # ── Verify final state ─────────────────────
        final_task = await task_repo.get_by_id(task.id)
        assert final_task.status == TaskStatus.ROUTED
        assert final_task.confirmed_at is not None
        assert final_task.is_processed is True

        final_session = await session_repo.get_active_by_task(task.id)
        assert final_session is None  # Resolved, no longer pending

        all_revisions = await rev_repo.list_by_task(task.id)
        assert len(all_revisions) == 2
        assert all_revisions[0].revision_no == 1  # Classification
        assert all_revisions[1].revision_no == 2  # Confirm
        assert all_revisions[1].user_decision == ReviewAction.CONFIRM


class TestE2EDiscardPath:
    """FLOW 2: proposed item -> discard -> marked DISCARDED."""

    @pytest.mark.asyncio
    async def test_intake_then_discard(self, seeded_session, google_task, classification_result):
        from apps.api.services.classification_service import ClassificationService
        from apps.api.services.google_tasks_service import GoogleTasksService
        from apps.api.services.intake_service import IntakeService
        from apps.api.services.llm_service import LLMService
        from apps.api.services.project_routing_service import ProjectRoutingService
        from apps.api.services.revision_service import RevisionService
        from apps.api.services.telegram_service import TelegramService
        from core.utils.datetime import utcnow
        from db.repositories.review_session_repo import ReviewSessionRepository
        from db.repositories.task_item_repo import TaskItemRepository
        from db.repositories.task_revision_repo import TaskRevisionRepository

        mock_google = MagicMock(spec=GoogleTasksService)
        mock_google.list_tasks.return_value = [google_task]
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.run_pipeline.return_value = classification_result
        mock_tg = AsyncMock(spec=TelegramService)
        mock_tg.send_proposal.return_value = 55
        routing = ProjectRoutingService()

        with patch("apps.api.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                google_tasks_inbox_list_id="inbox-list-id",
                telegram_chat_id="123456",
                llm_model="gpt-4o",
            )
            intake = IntakeService(
                session=seeded_session,
                google_tasks=mock_google,
                classification=ClassificationService(mock_llm, routing),
                telegram=mock_tg,
            )
            await intake.poll_and_process()

        task_repo = TaskItemRepository(seeded_session)
        task = await task_repo.get_by_source_google_task_id("gtask-e2e-001")

        # Discard
        task.status = transition(task.status, TaskStatus.DISCARDED)
        task.is_processed = True
        await task_repo.save(task)

        session_repo = ReviewSessionRepository(seeded_session)
        review_session = await session_repo.get_active_by_task(task.id)
        if review_session:
            review_session.status = "resolved"
            review_session.resolved_at = utcnow()
            await session_repo.save(review_session)

        revision_svc = RevisionService(seeded_session)
        cls_result = TaskClassificationResult(
            kind=task.kind,
            normalized_title=task.normalized_title or task.raw_text,
            confidence=task.confidence_band or "medium",
        )
        await revision_svc.create_decision_revision(
            task_item_id=task.id,
            raw_text=task.raw_text,
            decision=ReviewAction.DISCARD,
            classification=cls_result,
            project_id=task.project_id,
        )
        await seeded_session.commit()

        # Verify
        final_task = await task_repo.get_by_id(task.id)
        assert final_task.status == TaskStatus.DISCARDED
        assert final_task.is_processed is True

        rev_repo = TaskRevisionRepository(seeded_session)
        revisions = await rev_repo.list_by_task(task.id)
        assert len(revisions) == 2
        assert revisions[-1].user_decision == ReviewAction.DISCARD

        # No routing should have occurred
        assert final_task.current_google_task_id == google_task.id


class TestE2EEditThenConfirm:
    """FLOW 3: propose -> edit title -> confirm with edited title."""

    @pytest.mark.asyncio
    async def test_edit_then_confirm(self, seeded_session, google_task, classification_result):
        from apps.api.services.classification_service import ClassificationService
        from apps.api.services.google_tasks_service import GoogleTasksService
        from apps.api.services.intake_service import IntakeService
        from apps.api.services.llm_service import LLMService
        from apps.api.services.project_routing_service import ProjectRoutingService
        from apps.api.services.revision_service import RevisionService
        from apps.api.services.telegram_service import TelegramService
        from core.utils.datetime import utcnow
        from db.repositories.review_session_repo import ReviewSessionRepository
        from db.repositories.task_item_repo import TaskItemRepository
        from db.repositories.task_revision_repo import TaskRevisionRepository

        mock_google = MagicMock(spec=GoogleTasksService)
        mock_google.list_tasks.return_value = [google_task]
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.run_pipeline.return_value = classification_result
        mock_tg = AsyncMock(spec=TelegramService)
        mock_tg.send_proposal.return_value = 77
        routing = ProjectRoutingService()

        with patch("apps.api.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                google_tasks_inbox_list_id="inbox-list-id",
                telegram_chat_id="123456",
                llm_model="gpt-4o",
            )
            intake = IntakeService(
                session=seeded_session,
                google_tasks=mock_google,
                classification=ClassificationService(mock_llm, routing),
                telegram=mock_tg,
            )
            await intake.poll_and_process()

        task_repo = TaskItemRepository(seeded_session)
        session_repo = ReviewSessionRepository(seeded_session)
        revision_svc = RevisionService(seeded_session)
        rev_repo = TaskRevisionRepository(seeded_session)

        task = await task_repo.get_by_source_google_task_id("gtask-e2e-001")

        # Edit title
        new_title = "Ожидаю сертификаты от Алекса"
        task.normalized_title = new_title
        await task_repo.save(task)

        cls_result = TaskClassificationResult(
            kind=task.kind,
            normalized_title=new_title,
            confidence=task.confidence_band or "medium",
        )
        await revision_svc.create_decision_revision(
            task_item_id=task.id,
            raw_text=task.raw_text,
            decision=ReviewAction.EDIT,
            classification=cls_result,
            project_id=task.project_id,
            user_notes=f"Title changed to: {new_title}",
        )
        await seeded_session.flush()

        # Confirm with edited title
        task.status = transition(task.status, TaskStatus.CONFIRMED)
        task.confirmed_at = utcnow()
        task.is_processed = True
        task.status = transition(TaskStatus.CONFIRMED, TaskStatus.ROUTED)
        await task_repo.save(task)

        review_session = await session_repo.get_active_by_task(task.id)
        if review_session:
            review_session.status = "resolved"
            review_session.resolved_at = utcnow()
            await session_repo.save(review_session)

        cls_result_confirm = TaskClassificationResult(
            kind=task.kind,
            normalized_title=task.normalized_title,
            confidence=task.confidence_band or "medium",
        )
        await revision_svc.create_decision_revision(
            task_item_id=task.id,
            raw_text=task.raw_text,
            decision=ReviewAction.CONFIRM,
            classification=cls_result_confirm,
            project_id=task.project_id,
        )
        await seeded_session.commit()

        # Verify
        final_task = await task_repo.get_by_id(task.id)
        assert final_task.status == TaskStatus.ROUTED
        assert final_task.normalized_title == new_title

        revisions = await rev_repo.list_by_task(task.id)
        assert len(revisions) == 3  # classification + edit + confirm
        assert revisions[1].user_decision == ReviewAction.EDIT
        assert revisions[1].final_title == new_title
        assert revisions[2].user_decision == ReviewAction.CONFIRM
        assert revisions[2].final_title == new_title


class TestE2EDuplicatePoll:
    """FLOW 7: duplicate poll => no duplicate work."""

    @pytest.mark.asyncio
    async def test_duplicate_poll_no_duplicate_processing(
        self, seeded_session, google_task, classification_result
    ):
        from apps.api.services.classification_service import ClassificationService
        from apps.api.services.google_tasks_service import GoogleTasksService
        from apps.api.services.intake_service import IntakeService
        from apps.api.services.llm_service import LLMService
        from apps.api.services.project_routing_service import ProjectRoutingService
        from apps.api.services.telegram_service import TelegramService
        from db.repositories.task_item_repo import TaskItemRepository
        from db.repositories.task_revision_repo import TaskRevisionRepository

        mock_google = MagicMock(spec=GoogleTasksService)
        mock_google.list_tasks.return_value = [google_task]
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.run_pipeline.return_value = classification_result
        mock_tg = AsyncMock(spec=TelegramService)
        mock_tg.send_proposal.return_value = 88
        routing = ProjectRoutingService()

        with patch("apps.api.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                google_tasks_inbox_list_id="inbox-list-id",
                telegram_chat_id="123456",
                llm_model="gpt-4o",
            )
            intake = IntakeService(
                session=seeded_session,
                google_tasks=mock_google,
                classification=ClassificationService(mock_llm, routing),
                telegram=mock_tg,
            )
            count1 = await intake.poll_and_process()
            count2 = await intake.poll_and_process()
            count3 = await intake.poll_and_process()

        assert count1 == 1
        assert count2 == 0
        assert count3 == 0

        # Only one proposal sent
        mock_tg.send_proposal.assert_called_once()
        # LLM only called once
        mock_llm.run_pipeline.assert_called_once()

        # Only one task in DB
        task_repo = TaskItemRepository(seeded_session)
        task = await task_repo.get_by_source_google_task_id("gtask-e2e-001")
        assert task is not None

        # Only one revision
        rev_repo = TaskRevisionRepository(seeded_session)
        revisions = await rev_repo.list_by_task(task.id)
        assert len(revisions) == 1


class TestE2EMultipleInboxItems:
    """Test processing multiple inbox items in one poll."""

    @pytest.mark.asyncio
    async def test_processes_multiple_items(self, seeded_session, classification_result):
        from apps.api.services.classification_service import ClassificationService
        from apps.api.services.google_tasks_service import GoogleTask, GoogleTasksService
        from apps.api.services.intake_service import IntakeService
        from apps.api.services.llm_service import LLMService
        from apps.api.services.project_routing_service import ProjectRoutingService
        from apps.api.services.telegram_service import TelegramService
        from db.repositories.task_item_repo import TaskItemRepository

        tasks = [
            GoogleTask(
                id=f"gt-{i}",
                title=f"Task {i}",
                notes=None,
                status="needsAction",
                tasklist_id="inbox",
            )
            for i in range(3)
        ]
        mock_google = MagicMock(spec=GoogleTasksService)
        mock_google.list_tasks.return_value = tasks
        mock_llm = AsyncMock(spec=LLMService)
        mock_llm.run_pipeline.return_value = classification_result
        mock_tg = AsyncMock(spec=TelegramService)
        mock_tg.send_proposal.return_value = 99
        routing = ProjectRoutingService()

        with patch("apps.api.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                google_tasks_inbox_list_id="inbox",
                telegram_chat_id="123456",
                llm_model="gpt-4o",
            )
            intake = IntakeService(
                session=seeded_session,
                google_tasks=mock_google,
                classification=ClassificationService(mock_llm, routing),
                telegram=mock_tg,
            )
            count = await intake.poll_and_process()

        assert count == 3
        # With the review queue, only the first item is sent to Telegram immediately;
        # the remaining items stay queued until the active review is resolved.
        assert mock_tg.send_proposal.call_count == 1
        assert mock_llm.run_pipeline.call_count == 3

        task_repo = TaskItemRepository(seeded_session)
        for i in range(3):
            t = await task_repo.get_by_source_google_task_id(f"gt-{i}")
            assert t is not None
            assert t.status == TaskStatus.PROPOSED
