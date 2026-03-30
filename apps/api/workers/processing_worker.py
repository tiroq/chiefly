from __future__ import annotations

import uuid
from datetime import datetime, timezone

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.classification_service import ClassificationService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from apps.api.services.revision_service import RevisionService
from apps.api.services.telegram_service import TelegramService
from core.domain import notes_codec
from core.domain.enums import (
    ProcessingStatus,
    TaskRecordState,
    WorkflowStatus,
)
from db.models.task_record import TaskRecord
from db.models.task_revision import TaskRevision
from db.models.telegram_review_session import TelegramReviewSession
from db.repositories.processing_queue_repo import ProcessingQueueRepository
from db.repositories.project_alias_repo import ProjectAliasRepo
from db.repositories.project_repo import ProjectRepository
from db.repositories.review_session_repo import ReviewSessionRepository
from db.repositories.source_task_repo import SourceTaskRepository
from db.repositories.task_record_repo import TaskRecordRepository
from db.repositories.task_revision_repo import TaskRevisionRepository
from db.repositories.task_snapshot_repo import TaskSnapshotRepository
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
        stable_id = entry.stable_id

    logger.info(
        "processing_entry_claimed",
        entry_id=str(entry_id),
        source_task_id=str(source_task_id),
        stable_id=str(stable_id) if stable_id else None,
    )

    try:
        async with factory() as session:
            await _process_entry(session, entry_id, source_task_id, stable_id, settings)
    except Exception as e:
        logger.error("processing_worker_failed", entry_id=str(entry_id), error=str(e))
        async with factory() as session:
            queue_repo = ProcessingQueueRepository(session)
            await queue_repo.fail(entry_id, str(e))
            if stable_id:
                record_repo = TaskRecordRepository(session)
                await record_repo.update_processing_status(
                    stable_id, WorkflowStatus.FAILED, error=str(e)
                )
            await session.commit()


async def _process_entry(
    session,
    entry_id: uuid.UUID,
    source_task_id: uuid.UUID,
    stable_id: uuid.UUID | None,
    settings,
) -> None:
    source_repo = SourceTaskRepository(session)
    project_repo = ProjectRepository(session)
    review_repo = ReviewSessionRepository(session)
    queue_repo = ProcessingQueueRepository(session)
    record_repo = TaskRecordRepository(session)
    snapshot_repo = TaskSnapshotRepository(session)
    revision_repo = TaskRevisionRepository(session)
    revision_service = RevisionService(session)
    alias_repo = ProjectAliasRepo(session)

    correlation_id = uuid.uuid4()

    source_task = await source_repo.get_by_id(source_task_id)
    if source_task is None:
        logger.warning("processing_source_task_missing", source_task_id=str(source_task_id))
        await queue_repo.complete(entry_id)
        await session.commit()
        return

    logger.info(
        "processing_source_task_loaded",
        entry_id=str(entry_id),
        source_task_id=str(source_task_id),
        google_task_id=source_task.google_task_id,
    )

    google_tasks_svc = GoogleTasksService(settings.google_credentials_file)

    record = await record_repo.get_by_stable_id(stable_id) if stable_id else None

    # --- Phase 3a: Adoption (if unadopted) ---
    if record and record.state == TaskRecordState.UNADOPTED.value:
        logger.info(
            "processing_adoption_start",
            entry_id=str(entry_id),
            stable_id=str(stable_id),
        )
        stable_id = await _adopt_task(
            record=record,
            google_tasks_svc=google_tasks_svc,
            record_repo=record_repo,
            snapshot_repo=snapshot_repo,
            revision_repo=revision_repo,
        )
        logger.info(
            "processing_adoption_complete",
            entry_id=str(entry_id),
            stable_id=str(stable_id),
        )
    elif record:
        stable_id = record.stable_id
    else:
        stable_id = stable_id

    if stable_id is None:
        logger.warning("processing_no_stable_id", entry_id=str(entry_id))
        await queue_repo.complete(entry_id)
        await session.commit()
        return

    logger.info(
        "processing_status_update",
        entry_id=str(entry_id),
        stable_id=str(stable_id),
        workflow_status=WorkflowStatus.PROCESSING,
    )
    await record_repo.update_processing_status(stable_id, WorkflowStatus.PROCESSING)
    await queue_repo.mark_processing(entry_id, source_task.content_hash)

    # --- Phase 3b: Fetch current state for LLM ---
    _tasklist = source_task.google_tasklist_id
    _task_id = source_task.google_task_id
    if record and record.current_tasklist_id and record.current_task_id:
        _tasklist = record.current_tasklist_id
        _task_id = record.current_task_id

    logger.info(
        "processing_fetching_google_task",
        entry_id=str(entry_id),
        stable_id=str(stable_id),
        tasklist_id=_tasklist,
        task_id=_task_id,
    )
    current_task = google_tasks_svc.get_task(_tasklist, _task_id)

    if current_task is None:
        logger.warning("processing_google_task_gone", stable_id=str(stable_id))
        await record_repo.update_processing_status(
            stable_id, WorkflowStatus.FAILED, error="Google task not found"
        )
        await queue_repo.fail(entry_id, "Google task not found during processing")
        await session.commit()
        return

    user_notes = notes_codec.extract_user_notes(current_task.notes)
    raw_text = current_task.title
    # Description = user notes stripped of chiefly envelope, or source_task.notes_raw
    raw_description = user_notes or source_task.notes_raw or ""

    # --- Phase 3c: LLM Classification ---
    llm = LLMService(
        settings.llm_provider, settings.llm_model, settings.llm_api_key, settings.llm_base_url
    )
    routing = ProjectRoutingService()
    classification_svc = ClassificationService(llm, routing, alias_repo=alias_repo)
    projects = await project_repo.list_active()

    logger.info(
        "processing_classification_start",
        entry_id=str(entry_id),
        stable_id=str(stable_id),
        raw_text_preview=raw_text[:120],
        raw_description_preview=raw_description[:120] if raw_description else None,
        project_count=len(projects),
    )
    classification, project = await classification_svc.classify(
        raw_text,
        projects,
        raw_description=raw_description,
        task_id=_task_id,
    )
    logger.info(
        "processing_classification_done",
        entry_id=str(entry_id),
        stable_id=str(stable_id),
        kind=str(classification.kind),
        confidence=str(classification.confidence),
        project=project.name if project else None,
        normalized_title=classification.normalized_title,
    )

    await revision_service.create_classification_revision(
        stable_id=stable_id,
        raw_text=raw_text,
        classification=classification,
        project_id=project.id if project else None,
    )

    # --- Phase 3e: Patch Google notes with full metadata ---
    metadata = _build_metadata(classification, project)
    before_task = current_task

    logger.info(
        "processing_metadata_patch_start",
        entry_id=str(entry_id),
        stable_id=str(stable_id),
        tasklist_id=before_task.tasklist_id,
        task_id=before_task.id,
    )

    new_notes = notes_codec.format(
        stable_id=stable_id,
        metadata=metadata,
        existing_notes=current_task.notes,
    )

    before_revision_no = await revision_repo.get_next_revision_no_by_stable_id(stable_id)
    before_revision = TaskRevision(
        id=uuid.uuid4(),
        stable_id=stable_id,
        revision_no=before_revision_no,
        raw_text=raw_text,
        proposal_json=classification.model_dump(),
        action="annotate_metadata",
        actor_type="system",
        actor_id="processing_worker",
        correlation_id=correlation_id,
        before_tasklist_id=before_task.tasklist_id,
        before_task_id=before_task.id,
        before_state_json=before_task.raw_payload or _task_to_dict(before_task),
        started_at=datetime.now(tz=timezone.utc),
        final_title=classification.normalized_title,
        final_kind=classification.kind,
        final_project_id=project.id if project else None,
        final_next_action=classification.next_action,
    )

    try:
        patched = google_tasks_svc.patch_task(
            tasklist_id=before_task.tasklist_id,
            task_id=before_task.id,
            notes=new_notes,
        )

        before_revision.after_tasklist_id = patched.tasklist_id
        before_revision.after_task_id = patched.id
        before_revision.after_state_json = patched.raw_payload or _task_to_dict(patched)
        before_revision.finished_at = datetime.now(tz=timezone.utc)
        before_revision.success = True
        await revision_repo.create(before_revision)
        logger.info(
            "processing_metadata_patch_done",
            entry_id=str(entry_id),
            stable_id=str(stable_id),
            after_task_id=patched.id,
        )

    except Exception as patch_err:
        logger.error(
            "processing_metadata_patch_failed",
            entry_id=str(entry_id),
            stable_id=str(stable_id),
            error=str(patch_err),
        )
        before_revision.finished_at = datetime.now(tz=timezone.utc)
        before_revision.success = False
        before_revision.error = str(patch_err)
        await revision_repo.create(before_revision)
        await session.commit()
        raise

    # --- Phase 3f: Create snapshot after metadata patch ---
    logger.info(
        "processing_snapshot_create",
        entry_id=str(entry_id),
        stable_id=str(stable_id),
    )
    from apps.api.services.sync_service import compute_content_hash

    new_hash = compute_content_hash(patched.title, patched.notes)
    await snapshot_repo.create(
        tasklist_id=patched.tasklist_id,
        task_id=patched.id,
        payload=patched.raw_payload or _task_to_dict(patched),
        content_hash=new_hash,
        stable_id=stable_id,
        google_updated=patched.updated,
    )

    # --- Phase 3g: Review session creation ---
    logger.info(
        "processing_review_session_create",
        entry_id=str(entry_id),
        stable_id=str(stable_id),
    )
    proposed_changes = {
        "normalized_title": classification.normalized_title,
        "kind": str(classification.kind),
        "next_action": classification.next_action,
        "due_hint": classification.due_hint,
        "confidence": str(classification.confidence),
        "project_name": project.name if project else None,
        "project_id": str(project.id) if project else None,
        "substeps": classification.substeps if hasattr(classification, "substeps") else [],
    }

    latest_snapshot = await snapshot_repo.get_latest_by_stable_id(stable_id)

    review_session = TelegramReviewSession(
        id=uuid.uuid4(),
        stable_id=stable_id,
        telegram_chat_id=settings.telegram_chat_id,
        telegram_message_id=0,
        status="queued",
        base_snapshot_id=latest_snapshot.id if latest_snapshot else None,
        base_google_updated=patched.updated,
        proposed_changes=proposed_changes,
    )
    await review_repo.create(review_session)

    logger.info(
        "processing_status_update",
        entry_id=str(entry_id),
        stable_id=str(stable_id),
        workflow_status=WorkflowStatus.AWAITING_REVIEW,
    )
    await record_repo.update_processing_status(stable_id, WorkflowStatus.AWAITING_REVIEW)
    await queue_repo.complete(entry_id)
    await session.commit()

    # --- Phase 3h: Trigger Telegram send ---
    logger.info(
        "processing_telegram_notify",
        entry_id=str(entry_id),
        stable_id=str(stable_id),
    )
    telegram = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)
    from apps.api.services.review_queue_service import ReviewQueueService

    queue_svc = ReviewQueueService(session, telegram)
    try:
        await queue_svc.send_next()
    finally:
        await telegram.aclose()

    logger.info(
        "processing_complete",
        entry_id=str(entry_id),
        stable_id=str(stable_id),
        source_task_id=str(source_task_id),
    )


async def _adopt_task(
    *,
    record: TaskRecord,
    google_tasks_svc: GoogleTasksService,
    record_repo: TaskRecordRepository,
    snapshot_repo: TaskSnapshotRepository,
    revision_repo: TaskRevisionRepository,
) -> uuid.UUID:
    correlation_id = uuid.uuid4()
    new_stable_id = uuid.uuid4()
    old_stable_id = record.stable_id

    tl_id = record.current_tasklist_id
    t_id = record.current_task_id
    if tl_id is None or t_id is None:
        logger.warning("adoption_missing_pointer", old_stable_id=str(old_stable_id))
        await record_repo.update_state(old_stable_id, TaskRecordState.DELETED)
        return old_stable_id

    current_task = google_tasks_svc.get_task(tl_id, t_id)
    if current_task is None:
        logger.warning(
            "adoption_google_task_gone",
            old_stable_id=str(old_stable_id),
        )
        await record_repo.update_state(old_stable_id, TaskRecordState.DELETED)
        return old_stable_id

    before_state = current_task.raw_payload or _task_to_dict(current_task)

    initial_notes = notes_codec.format(
        stable_id=new_stable_id,
        metadata={},
        existing_notes=current_task.notes,
    )

    patched = google_tasks_svc.patch_task(
        tasklist_id=tl_id,
        task_id=t_id,
        notes=initial_notes,
    )

    after_state = patched.raw_payload or _task_to_dict(patched)
    now = datetime.now(tz=timezone.utc)

    adoption_revision = TaskRevision(
        id=uuid.uuid4(),
        stable_id=old_stable_id,
        revision_no=1,
        raw_text=current_task.title or "",
        proposal_json={},
        action="adopt",
        actor_type="system",
        actor_id="processing_worker",
        correlation_id=correlation_id,
        before_tasklist_id=tl_id,
        before_task_id=t_id,
        before_state_json=before_state,
        after_tasklist_id=patched.tasklist_id,
        after_task_id=patched.id,
        after_state_json=after_state,
        started_at=now,
        finished_at=now,
        success=True,
    )
    await revision_repo.create(adoption_revision)

    await record_repo.update_state(old_stable_id, TaskRecordState.ACTIVE)

    latest_snapshot = await snapshot_repo.get_latest_by_stable_id(old_stable_id)
    if latest_snapshot:
        await snapshot_repo.update_stable_id(latest_snapshot.id, old_stable_id)

    await record_repo.update_pointer(
        old_stable_id, patched.tasklist_id, patched.id, patched.updated
    )

    return old_stable_id


def _build_metadata(classification, project) -> dict[str, str]:
    metadata: dict[str, str] = {
        "kind": str(classification.kind),
        "normalized_title": classification.normalized_title,
    }
    if project:
        metadata["project"] = project.name
    if classification.confidence:
        metadata["confidence"] = str(classification.confidence)
    if classification.next_action:
        metadata["next_action"] = classification.next_action
    return metadata


def _task_to_dict(task) -> dict[str, object]:
    result: dict[str, object] = {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "tasklist_id": task.tasklist_id,
    }
    if task.notes:
        result["notes"] = task.notes
    if task.due:
        result["due"] = task.due
    if task.updated:
        result["updated"] = task.updated
    return result
