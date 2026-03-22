from __future__ import annotations

import uuid

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.classification_service import ClassificationService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from apps.api.services.revision_service import RevisionService
from apps.api.services.telegram_service import TelegramService
from core.domain.enums import ProcessingStatus, TaskStatus
from core.domain.state_machine import transition
from db.models.task_item import TaskItem
from db.models.telegram_review_session import TelegramReviewSession
from db.repositories.processing_queue_repo import ProcessingQueueRepository
from db.repositories.project_alias_repo import ProjectAliasRepo
from db.repositories.project_repo import ProjectRepository
from db.repositories.review_session_repo import ReviewSessionRepository
from db.repositories.source_task_repo import SourceTaskRepository
from db.repositories.task_item_repo import TaskItemRepository
from db.session import get_session_factory

logger = get_logger(__name__)


async def run_processing() -> None:
    settings = get_settings()
    factory = get_session_factory()

    async with factory() as session:
        review_repo = ReviewSessionRepository(session)
        if await review_repo.has_active_review():
            logger.debug("processing_worker_skip_active_review")
            return

    async with factory() as session:
        queue_repo = ProcessingQueueRepository(session)
        entry = await queue_repo.claim_next()
        if entry is None:
            return

        await session.commit()
        entry_id = entry.id
        source_task_id = entry.source_task_id

    try:
        async with factory() as session:
            await _process_entry(session, entry_id, source_task_id, settings)
    except Exception as e:
        logger.error("processing_worker_failed", entry_id=str(entry_id), error=str(e))
        async with factory() as session:
            queue_repo = ProcessingQueueRepository(session)
            await queue_repo.fail(entry_id, str(e))
            await session.commit()


async def _process_entry(session, entry_id, source_task_id, settings) -> None:
    source_repo = SourceTaskRepository(session)
    task_repo = TaskItemRepository(session)
    project_repo = ProjectRepository(session)
    review_repo = ReviewSessionRepository(session)
    queue_repo = ProcessingQueueRepository(session)
    revision_service = RevisionService(session)
    alias_repo = ProjectAliasRepo(session)

    source_task = await source_repo.get_by_id(source_task_id)
    if source_task is None:
        logger.warning("processing_source_task_missing", source_task_id=str(source_task_id))
        await queue_repo.complete(entry_id)
        await session.commit()
        return

    await queue_repo.mark_processing(entry_id, source_task.content_hash)

    raw_text = source_task.title_raw
    if source_task.notes_raw:
        raw_text = f"{raw_text}\n{source_task.notes_raw}"

    existing_task = await task_repo.get_by_source_google_task_id(source_task.google_task_id)
    if existing_task is not None and existing_task.status != TaskStatus.NEW:
        task_item = existing_task
        task_item.raw_text = raw_text
    else:
        task_item = existing_task or TaskItem(
            id=uuid.uuid4(),
            source_google_task_id=source_task.google_task_id,
            source_google_tasklist_id=source_task.google_tasklist_id,
            current_google_task_id=source_task.google_task_id,
            current_google_tasklist_id=source_task.google_tasklist_id,
            raw_text=raw_text,
            status=TaskStatus.NEW,
            source_task_id=source_task.id,
        )
        if existing_task is None:
            task_item = await task_repo.create(task_item)
        else:
            task_item.raw_text = raw_text
            task_item.source_task_id = source_task.id

    await session.commit()

    llm = LLMService(
        settings.llm_provider, settings.llm_model, settings.llm_api_key, settings.llm_base_url
    )
    routing = ProjectRoutingService()
    classification_svc = ClassificationService(llm, routing, alias_repo=alias_repo)
    projects = await project_repo.list_active()
    classification, project = await classification_svc.classify(raw_text, projects)

    task_item.normalized_title = classification.normalized_title
    task_item.kind = classification.kind
    task_item.next_action = classification.next_action
    task_item.due_hint = classification.due_hint
    task_item.confidence_band = classification.confidence
    task_item.project_id = project.id if project else None
    task_item.llm_model = settings.llm_model
    task_item.status = transition(TaskStatus.NEW, TaskStatus.PROPOSED)
    await task_repo.save(task_item)
    await session.commit()

    await revision_service.create_classification_revision(
        task_item_id=task_item.id,
        raw_text=raw_text,
        classification=classification,
        project_id=project.id if project else None,
    )

    if await review_repo.has_active_review():
        review_status = "queued"
    else:
        review_status = "queued"

    review_session = TelegramReviewSession(
        id=uuid.uuid4(),
        task_item_id=task_item.id,
        telegram_chat_id=settings.telegram_chat_id,
        telegram_message_id=0,
        status=review_status,
    )
    await ReviewSessionRepository(session).create(review_session)

    await queue_repo.complete(entry_id, task_item_id=task_item.id)
    await session.commit()

    telegram = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)
    from apps.api.services.review_queue_service import ReviewQueueService

    queue_svc = ReviewQueueService(session, telegram)
    await queue_svc.send_next()

    logger.info(
        "processing_complete",
        entry_id=str(entry_id),
        task_item_id=str(task_item.id),
        source_task_id=str(source_task_id),
    )
