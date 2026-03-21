"""
Admin action API routes for task management: retry, re-classify, re-send.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.auth import require_admin
from apps.api.config import get_settings
from apps.api.dependencies import get_session
from apps.api.services.classification_service import ClassificationService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.llm_service import LLMService
from apps.api.services.project_routing_service import ProjectRoutingService
from apps.api.services.revision_service import RevisionService
from apps.api.services.system_event_service import SystemEventService
from apps.api.services.telegram_service import TelegramService
from core.domain.enums import TaskKind, TaskStatus
from core.domain.state_machine import can_transition
from core.schemas.llm import TaskClassificationResult
from db.models.task_item import TaskItem
from db.repositories.project_repo import ProjectRepository
from db.repositories.project_alias_repo import ProjectAliasRepo
from db.repositories.system_event_repo import SystemEventRepo
from db.repositories.task_item_repo import TaskItemRepository
from db.repositories.task_revision_repo import TaskRevisionRepository

logger = structlog.get_logger(__name__)

settings = get_settings()
router = APIRouter(
    prefix="/tasks",
    tags=["admin-api"],
    dependencies=[Depends(require_admin(settings.admin_token))],
)


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Reset an ERROR task back to NEW for re-processing."""
    try:
        repo = TaskItemRepository(session)
        task = await repo.get_by_id(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        if task.status != TaskStatus.ERROR.value:
            raise HTTPException(
                status_code=400,
                detail="Task must be in ERROR state to retry",
            )

        if not can_transition(TaskStatus(task.status), TaskStatus.NEW):
            raise HTTPException(
                status_code=400,
                detail="Transition from ERROR to NEW is not allowed",
            )

        task.status = TaskStatus.NEW.value
        await repo.save(task)
        await session.commit()

        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "task_retried",
            f"Task {task_id} retried",
            task_item_id=task_id,
        )

        return JSONResponse(
            content={"success": True, "message": "Task queued for retry"},
            headers={"HX-Trigger": '{"showToast": "Task queued for retry"}'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("retry_task_failed", task_id=str(task_id), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to retry task: {exc}"},
        )


@router.post("/{task_id}/reclassify")
async def reclassify_task(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Re-run classification on a task."""
    try:
        task_repo = TaskItemRepository(session)
        task = await task_repo.get_by_id(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        # Load active projects
        project_repo = ProjectRepository(session)
        active_projects = await project_repo.list_active()

        # Build classification service
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

        # Classify
        classification, project = await classification_svc.classify(task.raw_text, active_projects)

        # Update task fields
        task.normalized_title = classification.normalized_title
        task.kind = classification.kind
        task.next_action = classification.next_action
        task.due_hint = classification.due_hint
        task.confidence_band = classification.confidence
        task.project_id = project.id if project else None
        task.llm_model = settings.llm_model
        await task_repo.save(task)

        # Create revision
        revision_svc = RevisionService(session)
        await revision_svc.create_classification_revision(
            task_item_id=task.id,
            raw_text=task.raw_text,
            classification=classification,
            project_id=project.id if project else None,
        )

        await session.commit()

        # Log system event
        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "task_reclassified",
            f"Task {task_id} re-classified",
            task_item_id=task_id,
        )

        return JSONResponse(
            content={"success": True, "message": "Task re-classified successfully"},
            headers={"HX-Trigger": '{"showToast": "Task re-classified"}'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("reclassify_task_failed", task_id=str(task_id), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to re-classify task: {exc}"},
        )


@router.post("/{task_id}/resend")
async def resend_proposal(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Re-send a Telegram proposal for a classified task."""
    try:
        task_repo = TaskItemRepository(session)
        task = await task_repo.get_by_id(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        # Task must have been classified (not still NEW)
        if task.status == TaskStatus.NEW.value:
            raise HTTPException(
                status_code=400,
                detail="Task has not been classified yet. Cannot resend proposal.",
            )

        # Get latest revision to reconstruct classification
        rev_repo = TaskRevisionRepository(session)
        revisions = await rev_repo.list_by_task(task_id)
        if not revisions:
            raise HTTPException(
                status_code=400,
                detail="No revisions found for task. Cannot resend proposal.",
            )

        latest_revision = revisions[-1]
        classification = TaskClassificationResult.model_validate(latest_revision.proposal_json)

        # Get project name for proposal
        project_name = None
        if task.project_id:
            project_repo = ProjectRepository(session)
            project = await project_repo.get_by_id(task.project_id)
            project_name = project.name if project else None

        # Send via Telegram
        telegram_svc = TelegramService(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
        )
        await telegram_svc.send_proposal(
            task_id=str(task.id),
            raw_text=task.raw_text,
            classification=classification,
            project_name=project_name,
        )

        await session.commit()

        # Log system event
        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "proposal_resent",
            f"Proposal for task {task_id} re-sent via Telegram",
            task_item_id=task_id,
        )

        return JSONResponse(
            content={"success": True, "message": "Proposal re-sent via Telegram"},
            headers={"HX-Trigger": '{"showToast": "Proposal re-sent"}'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("resend_proposal_failed", task_id=str(task_id), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to resend proposal: {exc}"},
        )


@router.post("/{task_id}/rewrite")
async def rewrite_task_title(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Use LLM to rewrite the raw task text into a clean normalized title."""
    try:
        task_repo = TaskItemRepository(session)
        task = await task_repo.get_by_id(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        llm_svc = LLMService(
            provider=settings.llm_provider,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        rewritten = await llm_svc.rewrite_title(task.raw_text)
        task.normalized_title = rewritten
        task.llm_model = settings.llm_model
        await task_repo.save(task)
        await session.commit()

        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "task_title_rewritten",
            f"Task {task_id} title rewritten by LLM",
            task_item_id=task_id,
        )

        return JSONResponse(
            content={"success": True, "normalized_title": rewritten},
            headers={"HX-Trigger": '{"showToast": "Title rewritten by LLM"}'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("rewrite_task_title_failed", task_id=str(task_id), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Rewrite failed: {exc}"},
        )


@router.post("/import-from-google")
async def import_tasks_from_google(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Import existing tasks from all active project Google Task lists into the DB."""
    try:
        google_svc = GoogleTasksService(settings.google_credentials_file)
        project_repo = ProjectRepository(session)
        task_repo = TaskItemRepository(session)

        projects = await project_repo.list_active()
        imported = 0
        skipped = 0

        for project in projects:
            if not project.google_tasklist_id:
                continue
            # Inbox is polled by the intake service; skip it here
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
                existing = await task_repo.get_by_source_google_task_id(gtask.id)
                if existing:
                    skipped += 1
                    continue
                task = TaskItem(
                    source_google_task_id=gtask.id,
                    source_google_tasklist_id=project.google_tasklist_id,
                    raw_text=gtask.title,
                    status=TaskStatus.ROUTED.value,
                    project_id=project.id,
                    is_processed=True,
                )
                await task_repo.create(task)
                imported += 1

        await session.commit()

        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "tasks_imported",
            f"Imported {imported} tasks from Google Tasks ({skipped} already existed)",
        )

        msg = f"Imported {imported} task(s). {skipped} already in DB."
        return JSONResponse(
            content={"success": True, "imported": imported, "skipped": skipped},
            headers={"HX-Trigger": f'{{"showToast": "{msg}"}}'},
        )
    except Exception as exc:
        logger.error("import_tasks_from_google_failed", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Import failed: {exc}"},
        )


@router.post("/{task_id}/edit")
async def edit_task(
    task_id: uuid.UUID,
    normalized_title: str = Form(""),
    kind: str = Form(""),
    project_id: str = Form(""),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Manually edit task fields: normalized title, kind, project."""
    try:
        task_repo = TaskItemRepository(session)
        task = await task_repo.get_by_id(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        if normalized_title.strip():
            task.normalized_title = normalized_title.strip()

        if kind.strip():
            try:
                task.kind = TaskKind(kind.strip()).value
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid kind: {kind!r}")
        else:
            task.kind = None

        if project_id.strip():
            try:
                task.project_id = uuid.UUID(project_id.strip())
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid project_id")
        else:
            task.project_id = None

        await task_repo.save(task)
        await session.commit()

        event_svc = SystemEventService(SystemEventRepo(session))
        await event_svc.log_admin_action(
            session,
            "task_edited",
            f"Task {task_id} edited manually",
            task_item_id=task_id,
        )

        return JSONResponse(
            content={"success": True, "message": "Task updated"},
            headers={"HX-Trigger": '{"showToast": "Task updated"}'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("edit_task_failed", task_id=str(task_id), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to edit task: {exc}"},
        )
