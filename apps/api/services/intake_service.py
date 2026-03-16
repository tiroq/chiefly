"""
Intake service - orchestrates the full task intake pipeline.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.classification_service import ClassificationService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.idempotency_service import IdempotencyService
from apps.api.services.revision_service import RevisionService
from apps.api.services.telegram_service import TelegramService
from core.domain.enums import ConfidenceBand, TaskStatus
from core.domain.exceptions import DuplicateTaskError, LockAcquisitionError
from core.domain.state_machine import transition
from core.utils.ids import short_id
from db.models.task_item import TaskItem
from db.models.telegram_review_session import TelegramReviewSession
from db.repositories.project_repo import ProjectRepository
from db.repositories.review_session_repo import ReviewSessionRepository
from db.repositories.task_item_repo import TaskItemRepository

logger = get_logger(__name__)


class IntakeService:
    def __init__(
        self,
        session: AsyncSession,
        google_tasks: GoogleTasksService,
        classification: ClassificationService,
        telegram: TelegramService,
    ) -> None:
        self._session = session
        self._google_tasks = google_tasks
        self._classification = classification
        self._telegram = telegram

    async def poll_and_process(self) -> int:
        """
        Poll the inbox list and process new tasks.
        Returns the number of tasks processed.
        """
        settings = get_settings()
        inbox_list_id = settings.google_tasks_inbox_list_id

        tasks = self._google_tasks.list_tasks(inbox_list_id)
        logger.info("inbox_poll", count=len(tasks), tasklist_id=inbox_list_id)

        processed = 0
        for gtask in tasks:
            if not gtask.title:
                continue
            try:
                result = await self._process_single_task(gtask, inbox_list_id)
                if result:
                    processed += 1
            except Exception as e:
                logger.error(
                    "intake_task_error",
                    google_task_id=gtask.id,
                    error=str(e),
                )
        return processed

    async def _process_single_task(self, gtask, inbox_list_id: str) -> bool:
        task_repo = TaskItemRepository(self._session)
        project_repo = ProjectRepository(self._session)
        revision_service = RevisionService(self._session)
        session_repo = ReviewSessionRepository(self._session)
        idempotency = IdempotencyService(self._session)
        settings = get_settings()

        # Idempotency: skip if already processed
        existing = await task_repo.get_by_source_google_task_id(gtask.id)
        if existing is not None:
            logger.debug("task_already_exists", google_task_id=gtask.id)
            return False

        lock_key = f"intake:{gtask.id}"
        try:
            await idempotency.require_lock(lock_key)
        except LockAcquisitionError:
            return False

        try:
            # Build raw text from title + notes
            raw_text = gtask.title
            if gtask.notes:
                raw_text = f"{raw_text}\n{gtask.notes}"

            # Create TaskItem
            task_item = TaskItem(
                id=uuid.uuid4(),
                source_google_task_id=gtask.id,
                source_google_tasklist_id=inbox_list_id,
                current_google_task_id=gtask.id,
                current_google_tasklist_id=inbox_list_id,
                raw_text=raw_text,
                status=TaskStatus.NEW,
            )
            task_item = await task_repo.create(task_item)
            # Note: no early commit here — the full pipeline runs in one transaction.
            # If anything fails, rollback will undo the task creation too, allowing
            # re-processing on the next poll.

            logger.info(
                "task_item_created",
                task_item_id=str(task_item.id),
                source_google_task_id=gtask.id,
            )

            # Classify
            projects = await project_repo.list_active()
            classification, project = await self._classification.classify(raw_text, projects)

            # Update task item with classification
            task_item.normalized_title = classification.normalized_title
            task_item.kind = classification.kind
            task_item.next_action = classification.next_action
            task_item.due_hint = classification.due_hint
            task_item.confidence_band = classification.confidence
            task_item.project_id = project.id if project else None
            task_item.llm_model = settings.llm_model
            task_item.status = transition(TaskStatus.NEW, TaskStatus.PROPOSED)
            await task_repo.save(task_item)

            # Create revision
            await revision_service.create_classification_revision(
                task_item_id=task_item.id,
                raw_text=raw_text,
                classification=classification,
                project_id=project.id if project else None,
            )

            # Send Telegram proposal
            msg_id = await self._telegram.send_proposal(
                task_id=str(task_item.id),
                raw_text=raw_text,
                classification=classification,
                project_name=project.name if project else None,
            )

            # Create review session
            review_session = TelegramReviewSession(
                id=uuid.uuid4(),
                task_item_id=task_item.id,
                telegram_chat_id=settings.telegram_chat_id,
                telegram_message_id=msg_id,
                status="pending",
            )
            await session_repo.create(review_session)

            await self._session.commit()

            logger.info(
                "intake_complete",
                task_item_id=str(task_item.id),
                telegram_message_id=msg_id,
                status=task_item.status,
            )
            return True

        except Exception:
            await self._session.rollback()
            raise
        finally:
            await idempotency.release_lock(lock_key)
