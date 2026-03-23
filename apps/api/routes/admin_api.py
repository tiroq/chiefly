"""
Admin action API routes for task management: retry, re-classify, re-send.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.auth import require_admin
from apps.api.config import get_settings
from apps.api.dependencies import get_session
from apps.api.services.admin_tasks_service import AdminTasksService, build_task_view
from apps.api.services.classification_service import ClassificationService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from apps.api.services.revision_service import RevisionService
from apps.api.services.rollback_service import RollbackService
from apps.api.services.system_event_service import SystemEventService
from apps.api.services.telegram_service import TelegramService
from core.domain import notes_codec
from core.domain.enums import ProcessingReason, WorkflowStatus
from core.domain.exceptions import (
    LockAcquisitionError,
    RollbackDriftError,
    RollbackError,
    TaskNotFoundError,
)
from core.schemas.llm import TaskClassificationResult
from db.repositories.project_alias_repo import ProjectAliasRepo
from db.repositories.project_repo import ProjectRepository
from db.repositories.processing_queue_repo import ProcessingQueueRepository
from db.repositories.source_task_repo import SourceTaskRepository
from db.repositories.system_event_repo import SystemEventRepo
from db.repositories.task_record_repo import TaskRecordRepository
from db.repositories.task_revision_repo import TaskRevisionRepository
from db.repositories.task_snapshot_repo import TaskSnapshotRepository

logger = structlog.get_logger(__name__)

templates = Jinja2Templates(directory="apps/api/templates")

settings = get_settings()
router = APIRouter(
    prefix="/tasks",
    tags=["admin-api"],
    dependencies=[Depends(require_admin(settings.admin_token))],
)


@router.post("/{stable_id}/retry")
async def retry_task(
    stable_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Reset a FAILED task back to PENDING for re-processing."""
    try:
        record_repo = TaskRecordRepository(session)
        record = await record_repo.get_by_stable_id(stable_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")

        if record.processing_status != WorkflowStatus.FAILED.value:
            raise HTTPException(
                status_code=400,
                detail="Task must be in FAILED state to retry",
            )

        await record_repo.update_processing_status(stable_id, WorkflowStatus.PENDING, error=None)
        await session.commit()

        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "task_retried",
            f"Task {stable_id} retried",
        )

        return JSONResponse(
            content={"success": True, "message": "Task queued for retry"},
            headers={"HX-Trigger": '{"showToast": "Task queued for retry"}'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("retry_task_failed", stable_id=str(stable_id), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to retry task: {exc}"},
        )


@router.post("/{stable_id}/reclassify")
async def reclassify_task(
    stable_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Re-run classification on a task."""
    try:
        record_repo = TaskRecordRepository(session)
        record = await record_repo.get_by_stable_id(stable_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")

        snapshot_repo = TaskSnapshotRepository(session)
        snapshot = await snapshot_repo.get_latest_by_stable_id(stable_id)
        raw_text = snapshot.payload.get("title", "") if snapshot and snapshot.payload else ""
        if not raw_text:
            raise HTTPException(status_code=400, detail="No raw text found for task")

        project_repo = ProjectRepository(session)
        active_projects = await project_repo.list_active()

        llm_svc = LLMService(
            provider=settings.llm_provider,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        routing_svc = ProjectRoutingService()
        alias_repo = ProjectAliasRepo(session)
        classification_svc = ClassificationService(
            llm_svc,
            routing_svc,
            alias_repo=alias_repo,
        )

        classification, project = await classification_svc.classify(
            raw_text,
            active_projects,
            task_id=str(stable_id),
        )

        revision_svc = RevisionService(session)
        await revision_svc.create_classification_revision(
            stable_id=stable_id,
            raw_text=raw_text,
            classification=classification,
            project_id=project.id if project else None,
        )

        await record_repo.update_processing_status(stable_id, WorkflowStatus.PENDING)
        await session.commit()

        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "task_reclassified",
            f"Task {stable_id} re-classified",
        )

        return JSONResponse(
            content={"success": True, "message": "Task re-classified successfully"},
            headers={"HX-Trigger": '{"showToast": "Task re-classified"}'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("reclassify_task_failed", stable_id=str(stable_id), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to re-classify task: {exc}"},
        )


@router.post("/{stable_id}/resend")
async def resend_proposal(
    stable_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Re-send a Telegram proposal for a classified task."""
    try:
        record_repo = TaskRecordRepository(session)
        record = await record_repo.get_by_stable_id(stable_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")

        if record.processing_status == WorkflowStatus.PENDING.value:
            raise HTTPException(
                status_code=400,
                detail="Task has not been processed yet. Cannot resend proposal.",
            )

        rev_repo = TaskRevisionRepository(session)
        revisions = await rev_repo.list_by_stable_id(stable_id)
        if not revisions:
            raise HTTPException(
                status_code=400,
                detail="No revisions found for task. Cannot resend proposal.",
            )

        latest_revision = revisions[-1]
        classification = TaskClassificationResult.model_validate(latest_revision.proposal_json)

        snapshot_repo = TaskSnapshotRepository(session)
        snapshot = await snapshot_repo.get_latest_by_stable_id(stable_id)
        raw_text = snapshot.payload.get("title", "") if snapshot and snapshot.payload else ""
        meta = (
            notes_codec.parse(snapshot.payload.get("notes", ""))
            if snapshot and snapshot.payload
            else {}
        )
        project_name = (meta or {}).get("project_name")

        if not project_name and classification.project_guess:
            project_name = classification.project_guess

        telegram_svc = TelegramService(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
        )
        await telegram_svc.send_proposal(
            task_id=str(stable_id),
            raw_text=raw_text,
            classification=classification,
            project_name=project_name,
        )

        await session.commit()

        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "proposal_resent",
            f"Proposal for task {stable_id} re-sent via Telegram",
        )

        return JSONResponse(
            content={"success": True, "message": "Proposal re-sent via Telegram"},
            headers={"HX-Trigger": '{"showToast": "Proposal re-sent"}'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("resend_proposal_failed", stable_id=str(stable_id), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to resend proposal: {exc}"},
        )


@router.post("/{stable_id}/rewrite")
async def rewrite_task_title(
    stable_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Use LLM to rewrite the raw task text into a clean normalized title."""
    try:
        record_repo = TaskRecordRepository(session)
        record = await record_repo.get_by_stable_id(stable_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")

        snapshot_repo = TaskSnapshotRepository(session)
        snapshot = await snapshot_repo.get_latest_by_stable_id(stable_id)
        raw_text = snapshot.payload.get("title", "") if snapshot and snapshot.payload else ""
        if not raw_text:
            raise HTTPException(status_code=400, detail="No raw text found for task")

        llm_svc = LLMService(
            provider=settings.llm_provider,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        rewritten = await llm_svc.rewrite_title(raw_text)

        if record.current_tasklist_id and record.current_task_id:
            try:
                gtasks = GoogleTasksService(settings.google_credentials_file)
                gtasks.patch_task(
                    record.current_tasklist_id, record.current_task_id, title=rewritten
                )
            except Exception as exc:
                logger.warning(
                    "google_tasks_patch_failed", stable_id=str(stable_id), error=str(exc)
                )

        await session.commit()

        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "task_title_rewritten",
            f"Task {stable_id} title rewritten by LLM",
        )

        return JSONResponse(
            content={"success": True, "normalized_title": rewritten},
            headers={"HX-Trigger": '{"showToast": "Title rewritten by LLM"}'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("rewrite_task_title_failed", stable_id=str(stable_id), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Rewrite failed: {exc}"},
        )


@router.post("/import-from-google")
async def import_tasks_from_google(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Import existing tasks from all active project Google Task lists into the DB."""
    try:
        google_svc = GoogleTasksService(settings.google_credentials_file)
        project_repo = ProjectRepository(session)
        record_repo = TaskRecordRepository(session)
        snapshot_repo = TaskSnapshotRepository(session)
        projects = await project_repo.list_active()
        imported = 0
        skipped = 0

        for project in projects:
            if not project.google_tasklist_id:
                continue
            if project.google_tasklist_id == settings.google_tasks_inbox_list_id:
                continue

            try:
                gtasks = google_svc.list_tasks(project.google_tasklist_id)
            except Exception as exc:
                logger.warning(
                    "import_tasks_list_failed",
                    project_id=str(project.id),
                    error=str(exc),
                )
                continue

            for gtask in gtasks:
                if not gtask.title:
                    continue

                existing = await record_repo.get_by_pointer(project.google_tasklist_id, gtask.id)
                if existing:
                    skipped += 1
                    continue

                stable_id = uuid.uuid4()
                await record_repo.create(
                    stable_id=stable_id,
                    current_tasklist_id=project.google_tasklist_id,
                    current_task_id=gtask.id,
                )

                payload = {
                    "title": gtask.title,
                    "status": getattr(gtask, "status", "needsAction"),
                    "notes": notes_codec.format(
                        stable_id=stable_id,
                        metadata={"project_name": project.name, "project_id": str(project.id)},
                    ),
                }
                import hashlib

                content_hash = hashlib.sha256(
                    f"{gtask.title}|{getattr(gtask, 'notes', '')}".encode()
                ).hexdigest()
                await snapshot_repo.create(
                    stable_id=stable_id,
                    tasklist_id=project.google_tasklist_id,
                    task_id=gtask.id,
                    payload=payload,
                    content_hash=content_hash,
                )

                imported += 1

        await session.commit()

        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "tasks_imported",
            f"Imported {imported} tasks from Google Tasks ({skipped} already existed)",
        )

        revision_repo = TaskRevisionRepository(session)
        svc = AdminTasksService(record_repo, revision_repo)
        result = await svc.list_tasks(session=session)
        active_projects = await project_repo.list_active()
        msg = f"Imported {imported} task(s). {skipped} already in DB."
        return templates.TemplateResponse(
            request=request,
            name="admin/partials/_task_table.html",
            context={
                "request": request,
                "result": result,
                "projects": active_projects,
                "statuses": [s.value for s in WorkflowStatus],
                "kinds": [],
            },
            headers={"HX-Trigger": f'{{"showToast": "{msg}"}}'},
        )
    except Exception as exc:
        logger.error("import_tasks_from_google_failed", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Import failed: {exc}"},
        )


@router.post("/{stable_id}/edit")
async def edit_task(
    stable_id: uuid.UUID,
    normalized_title: str = Form(""),
    next_action: str = Form(""),
    kind: str = Form(""),
    project_id: str = Form(""),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Manually edit task fields via Google Tasks API."""
    try:
        record_repo = TaskRecordRepository(session)
        record = await record_repo.get_by_stable_id(stable_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")

        snapshot_repo = TaskSnapshotRepository(session)
        snapshot = await snapshot_repo.get_latest_by_stable_id(stable_id)
        payload = snapshot.payload if snapshot and snapshot.payload else {}
        current_notes = payload.get("notes", "")
        meta = notes_codec.parse(current_notes) or {}

        if normalized_title.strip():
            meta["normalized_title"] = normalized_title.strip()
        if next_action.strip():
            meta["next_action"] = next_action.strip()
        elif "next_action" in meta:
            del meta["next_action"]

        if kind.strip():
            meta["kind"] = kind.strip()
        elif "kind" in meta:
            del meta["kind"]

        new_project_id: uuid.UUID | None = None
        if project_id.strip():
            try:
                new_project_id = uuid.UUID(project_id.strip())
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid project_id")

        old_project_id_str = meta.get("project_id")
        if new_project_id:
            meta["project_id"] = str(new_project_id)
            project_repo = ProjectRepository(session)
            new_project = await project_repo.get_by_id(new_project_id)
            if new_project:
                meta["project_name"] = new_project.name
        elif "project_id" in meta:
            del meta["project_id"]
            meta.pop("project_name", None)

        updated_notes = (
            notes_codec.format(
                stable_id=record.stable_id,
                metadata={k: v for k, v in meta.items() if k != "stable_id"},
                existing_notes=notes_codec.extract_user_notes(current_notes)
                if current_notes
                else None,
            )
            if meta
            else ""
        )

        if record.current_tasklist_id and record.current_task_id:
            try:
                gtasks = GoogleTasksService(settings.google_credentials_file)
                patch_title = normalized_title.strip() if normalized_title.strip() else None
                gtasks.patch_task(
                    record.current_tasklist_id,
                    record.current_task_id,
                    title=patch_title,
                    notes=updated_notes,
                )

                if new_project_id and str(new_project_id) != str(old_project_id_str or ""):
                    project_repo = ProjectRepository(session)
                    new_project = (
                        await project_repo.get_by_id(new_project_id) if new_project_id else None
                    )
                    if (
                        new_project
                        and new_project.google_tasklist_id
                        and new_project.google_tasklist_id != record.current_tasklist_id
                    ):
                        moved = gtasks.move_task(
                            record.current_tasklist_id,
                            record.current_task_id,
                            new_project.google_tasklist_id,
                        )
                        await record_repo.update_pointer(
                            stable_id,
                            moved.tasklist_id,
                            moved.id,
                        )
                        if patch_title:
                            gtasks.patch_task(
                                moved.tasklist_id, moved.id, title=patch_title, notes=updated_notes
                            )
            except Exception as exc:
                logger.warning("google_tasks_edit_failed", stable_id=str(stable_id), error=str(exc))

        await session.commit()

        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "task_edited",
            f"Task {stable_id} edited manually",
        )

        return JSONResponse(
            content={"success": True, "message": "Task updated"},
            headers={"HX-Trigger": '{"showToast": "Task updated"}'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("edit_task_failed", stable_id=str(stable_id), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to edit task: {exc}"},
        )


@router.post("/{stable_id}/rollback/{revision_id}")
async def rollback_task(
    stable_id: uuid.UUID,
    revision_id: uuid.UUID,
    force: bool = False,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    try:
        google_svc = GoogleTasksService(settings.google_credentials_file)
        rollback_svc = RollbackService(session, google_svc)

        rollback_revision = await rollback_svc.rollback(stable_id, revision_id, force=force)
        await session.commit()

        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "task_rolled_back",
            f"Task {stable_id} rolled back to revision {revision_id}",
            stable_id=stable_id,
        )

        return JSONResponse(
            content={
                "success": True,
                "message": "Task rolled back successfully",
                "revision_no": rollback_revision.revision_no,
            },
            headers={"HX-Trigger": '{"showToast": "Task rolled back successfully"}'},
        )
    except TaskNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content={"error": str(exc)},
        )
    except RollbackDriftError as exc:
        return JSONResponse(
            status_code=409,
            content={"error": str(exc), "drift": True},
        )
    except LockAcquisitionError:
        return JSONResponse(
            status_code=409,
            content={"error": "Task is currently being processed. Try again later."},
        )
    except RollbackError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc)},
        )
    except Exception as exc:
        logger.error("rollback_task_failed", stable_id=str(stable_id), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Rollback failed: {exc}"},
        )


@router.get("/processing/queue")
async def get_processing_queue(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    queue_repo = ProcessingQueueRepository(session)
    source_repo = SourceTaskRepository(session)

    pending = await queue_repo.list_pending(limit=50)
    items = []
    for entry in pending:
        source = await source_repo.get_by_id(entry.source_task_id)
        items.append(
            {
                "id": str(entry.id),
                "source_task_id": str(entry.source_task_id),
                "title": source.title_raw if source else None,
                "processing_status": entry.processing_status,
                "processing_reason": entry.processing_reason,
                "retry_count": entry.retry_count,
                "max_retries": entry.max_retries,
                "error_message": entry.error_message,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
        )

    total_pending = await queue_repo.count_pending()

    return JSONResponse(
        content={
            "total_pending": total_pending,
            "items": items,
        }
    )


@router.post("/processing/reprocess/{source_task_id}")
async def reprocess_source_task(
    source_task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    source_repo = SourceTaskRepository(session)
    source = await source_repo.get_by_id(source_task_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source task not found")

    queue_repo = ProcessingQueueRepository(session)

    await queue_repo.enqueue(
        source_task_id=source.id,
        reason=ProcessingReason.MANUAL_REPROCESS,
    )
    await session.commit()

    event_svc = SystemEventService(SystemEventRepo(session))
    await event_svc.log_admin_action(
        session,
        "manual_reprocess",
        f"Source task {source_task_id} queued for reprocessing",
    )

    return JSONResponse(
        content={"success": True, "message": "Queued for reprocessing"},
        headers={"HX-Trigger": '{"showToast": "Queued for reprocessing"}'},
    )
