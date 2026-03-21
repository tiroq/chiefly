import json
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.enums import TaskKind, TaskStatus
from apps.api.admin.auth import is_htmx, require_admin
from apps.api.config import get_settings
from apps.api.dependencies import get_session
from apps.api.services.admin_dashboard_service import AdminDashboardService
from apps.api.services.admin_logs_service import AdminLogsService
from apps.api.services.admin_projects_service import AdminProjectsService
from apps.api.services.admin_tasks_service import AdminTasksService
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.project_sync_service import ProjectSyncService
from apps.api.services.prompt_versioning_service import PromptVersioningService
from apps.api.services.system_event_service import SystemEventService
from db.models.project_alias import ProjectAlias
from db.repositories.project_alias_repo import ProjectAliasRepo
from db.repositories.project_repo import ProjectRepository
from db.repositories.prompt_version_repo import ProjectPromptVersionRepo
from db.repositories.system_event_repo import SystemEventRepo
from db.repositories.task_item_repo import TaskItemRepository
from db.repositories.task_revision_repo import TaskRevisionRepository

settings = get_settings()
router = APIRouter(dependencies=[Depends(require_admin(settings.admin_token))])
templates = Jinja2Templates(directory="apps/api/templates")


@router.get("/")
async def admin_dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    task_repo = TaskItemRepository(session)
    project_repo = ProjectRepository(session)
    event_repo = SystemEventRepo(session)
    svc = AdminDashboardService(task_repo, project_repo, event_repo)

    stats = await svc.get_dashboard_stats(session)

    context = {
        "request": request,
        "stats": stats,
        "title": "Dashboard",
    }

    if is_htmx(request):
        return templates.TemplateResponse("admin/partials/_dashboard.html", context)
    return templates.TemplateResponse("admin/pages/dashboard.html", context)


@router.get("/projects")
async def admin_projects(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    project_repo = ProjectRepository(session)
    alias_repo = ProjectAliasRepo(session)
    svc = AdminProjectsService(project_repo, alias_repo)

    result = await svc.list_projects(session)

    context = {
        "request": request,
        "result": result,
        "title": "Projects",
    }

    if is_htmx(request):
        return templates.TemplateResponse("admin/partials/_project_table.html", context)
    return templates.TemplateResponse("admin/pages/projects.html", context)


@router.post("/projects/sync")
async def sync_projects(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    settings_val = get_settings()
    google_tasks = GoogleTasksService(settings_val.google_credentials_file)
    project_repo = ProjectRepository(session)
    sync_svc = ProjectSyncService(google_tasks, project_repo)

    result = await sync_svc.sync_from_google(
        session,
        inbox_list_id=settings_val.google_tasks_inbox_list_id,
    )

    alias_repo = ProjectAliasRepo(session)
    projects_svc = AdminProjectsService(project_repo, alias_repo)
    project_result = await projects_svc.list_projects(session)

    context = {
        "request": request,
        "result": project_result,
        "sync_result": result,
        "title": "Projects",
    }

    if is_htmx(request):
        return templates.TemplateResponse("admin/partials/_project_table.html", context)
    return RedirectResponse("/admin/projects?msg=Sync+complete", status_code=303)


@router.get("/events")
async def admin_events(
    request: Request,
    event_type: str | None = None,
    severity: str | None = None,
    subsystem: str | None = None,
    page: int = 1,
    session: AsyncSession = Depends(get_session),
):
    event_repo = SystemEventRepo(session)
    svc = AdminLogsService(event_repo)

    result = await svc.list_events(
        session, event_type=event_type, severity=severity, subsystem=subsystem, page=page
    )
    severity_summary = await svc.get_severity_summary(session)

    context = {
        "request": request,
        "result": result,
        "severity_summary": severity_summary,
        "title": "Events",
    }

    if is_htmx(request):
        return templates.TemplateResponse("admin/partials/_event_table.html", context)
    return templates.TemplateResponse("admin/pages/events.html", context)


@router.get("/tasks")
async def admin_tasks_list(
    request: Request,
    status: str | None = None,
    kind: str | None = None,
    project_id: str | None = None,
    search: str | None = None,
    page: int = 1,
    session: AsyncSession = Depends(get_session),
):
    task_repo = TaskItemRepository(session)
    revision_repo = TaskRevisionRepository(session)
    project_repo = ProjectRepository(session)
    svc = AdminTasksService(task_repo, revision_repo)

    parsed_status = None
    if status:
        try:
            parsed_status = TaskStatus(status)
        except ValueError:
            pass

    parsed_kind = None
    if kind:
        try:
            parsed_kind = TaskKind(kind)
        except ValueError:
            pass

    parsed_project_id = None
    if project_id:
        try:
            parsed_project_id = uuid.UUID(project_id)
        except ValueError:
            pass

    result = await svc.list_tasks(
        session=session,
        status=parsed_status,
        kind=parsed_kind,
        project_id=parsed_project_id,
        search=search,
        page=page,
    )

    projects = await project_repo.list_active()
    statuses = [s.value for s in TaskStatus]
    kinds = [k.value for k in TaskKind]

    context = {
        "request": request,
        "result": result,
        "projects": projects,
        "statuses": statuses,
        "kinds": kinds,
        "title": "Tasks",
    }

    if is_htmx(request):
        return templates.TemplateResponse("admin/partials/_task_table.html", context)
    return templates.TemplateResponse("admin/pages/tasks.html", context)


@router.get("/tasks/{task_id}")
async def admin_task_detail(
    request: Request,
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    task_repo = TaskItemRepository(session)
    revision_repo = TaskRevisionRepository(session)
    project_repo = ProjectRepository(session)
    svc = AdminTasksService(task_repo, revision_repo)

    result = await svc.get_task_detail(session, task_id)
    if result is None or result.task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    project = None
    if result.task.project_id:
        project = await project_repo.get_by_id(result.task.project_id)

    context = {
        "request": request,
        "result": result,
        "project": project,
        "title": "Task Detail",
    }

    if is_htmx(request):
        return templates.TemplateResponse("admin/partials/_task_detail.html", context)
    return templates.TemplateResponse("admin/pages/task_detail.html", context)


@router.get("/projects/{project_id}")
async def project_detail(
    request: Request,
    project_id: uuid.UUID,
    msg: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    project_repo = ProjectRepository(session)
    alias_repo = ProjectAliasRepo(session)
    version_repo = ProjectPromptVersionRepo(session)
    event_repo = SystemEventRepo(session)

    projects_svc = AdminProjectsService(project_repo, alias_repo)
    prompt_svc = PromptVersioningService(version_repo, event_repo)

    result = await projects_svc.get_project_detail(session, project_id)
    if result is None or result.project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    versions = await prompt_svc.list_versions(session, project_id)

    context = {
        "request": request,
        "result": result,
        "versions": versions,
        "title": result.project.name,
        "msg": msg,
    }

    if is_htmx(request):
        return templates.TemplateResponse("admin/partials/_project_detail.html", context)
    return templates.TemplateResponse("admin/pages/project_detail.html", context)


@router.post("/projects/{project_id}/prompts")
async def create_prompt_version(
    request: Request,
    project_id: uuid.UUID,
    title: str = Form(None),
    description_text: str = Form(None),
    classification_prompt_text: str = Form(None),
    routing_prompt_text: str = Form(None),
    examples_json: str = Form(None),
    change_note: str = Form(None),
    session: AsyncSession = Depends(get_session),
):
    version_repo = ProjectPromptVersionRepo(session)
    event_repo = SystemEventRepo(session)
    prompt_svc = PromptVersioningService(version_repo, event_repo)

    parsed_examples = None
    if examples_json:
        try:
            parsed_examples = json.loads(examples_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in examples")

    await prompt_svc.create_version(
        session,
        project_id,
        title=title,
        description_text=description_text,
        classification_prompt_text=classification_prompt_text,
        routing_prompt_text=routing_prompt_text,
        examples_json=parsed_examples,
        change_note=change_note,
    )

    await session.commit()

    if is_htmx(request):
        return Response(
            status_code=200,
            headers={"HX-Redirect": f"/admin/projects/{project_id}?msg=Prompt+version+created"},
        )
    return RedirectResponse(
        f"/admin/projects/{project_id}?msg=Prompt+version+created", status_code=303
    )


@router.post("/projects/{project_id}/prompts/{version_id}/activate")
async def activate_prompt_version(
    request: Request,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    version_repo = ProjectPromptVersionRepo(session)
    event_repo = SystemEventRepo(session)
    prompt_svc = PromptVersioningService(version_repo, event_repo)

    try:
        await prompt_svc.activate_version(session, version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await session.commit()

    if is_htmx(request):
        return Response(
            status_code=200,
            headers={"HX-Redirect": f"/admin/projects/{project_id}?msg=Prompt+version+activated"},
        )
    return RedirectResponse(
        f"/admin/projects/{project_id}?msg=Prompt+version+activated", status_code=303
    )


@router.post("/projects/{project_id}/aliases")
async def add_project_alias(
    request: Request,
    project_id: uuid.UUID,
    alias: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    alias_repo = ProjectAliasRepo(session)
    event_repo = SystemEventRepo(session)
    event_svc = SystemEventService(event_repo)

    new_alias = ProjectAlias(id=uuid.uuid4(), project_id=project_id, alias=alias)
    await alias_repo.create(new_alias)

    await event_svc.log_admin_action(
        session,
        action="alias_added",
        message=f"Alias '{alias}' added to project {project_id}",
        project_id=project_id,
    )

    await session.commit()

    if is_htmx(request):
        return Response(
            status_code=200,
            headers={"HX-Redirect": f"/admin/projects/{project_id}?msg=Alias+added"},
        )
    return RedirectResponse(f"/admin/projects/{project_id}?msg=Alias+added", status_code=303)


@router.post("/projects/{project_id}/aliases/{alias_id}/delete")
async def delete_project_alias(
    request: Request,
    project_id: uuid.UUID,
    alias_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    alias_repo = ProjectAliasRepo(session)
    event_repo = SystemEventRepo(session)
    event_svc = SystemEventService(event_repo)

    await alias_repo.delete(alias_id)

    await event_svc.log_admin_action(
        session,
        action="alias_deleted",
        message=f"Alias {alias_id} deleted from project {project_id}",
        project_id=project_id,
    )

    await session.commit()

    if is_htmx(request):
        return Response(
            status_code=200,
            headers={"HX-Redirect": f"/admin/projects/{project_id}?msg=Alias+deleted"},
        )
    return RedirectResponse(f"/admin/projects/{project_id}?msg=Alias+deleted", status_code=303)


@router.post("/projects/{project_id}/generate-description")
async def generate_project_description(
    request: Request,
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    from apps.api.services.llm_service import LLMService
    from apps.api.services.prompt_versioning_service import PromptVersioningService

    settings_val = get_settings()
    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    google_tasks = GoogleTasksService(settings_val.google_credentials_file)
    gtasks = google_tasks.list_tasks(project.google_tasklist_id)
    sample_titles = [t.title for t in gtasks[:20] if t.title]

    if not sample_titles:
        if is_htmx(request):
            return Response(
                status_code=200,
                headers={
                    "HX-Redirect": f"/admin/projects/{project_id}?msg=No+tasks+found+in+project+list"
                },
            )
        return RedirectResponse(f"/admin/projects/{project_id}?msg=No+tasks+found", status_code=303)

    llm_svc = LLMService(
        provider=settings_val.llm_provider,
        model=settings_val.llm_model,
        api_key=settings_val.llm_api_key,
        base_url=settings_val.llm_base_url,
    )
    generated = await llm_svc.generate_project_description(project.name, sample_titles)
    description_text = generated.get("description")
    description_value = description_text if isinstance(description_text, str) else ""
    example_patterns = generated.get("example_patterns")
    examples_json: dict[str, object] = {
        "example_patterns": (example_patterns if isinstance(example_patterns, list) else [])
    }

    version_repo = ProjectPromptVersionRepo(session)
    event_repo = SystemEventRepo(session)
    prompt_svc = PromptVersioningService(version_repo, event_repo)
    previous_active = await version_repo.get_active_for_project(project_id)

    created_version = await prompt_svc.create_version(
        session,
        project_id,
        title=f"Auto-generated from {len(sample_titles)} tasks",
        description_text=description_value,
        examples_json=examples_json,
        change_note="Generated by LLM from project tasks. Review and activate manually.",
    )
    created_version.is_active = False
    await version_repo.save(created_version)
    if previous_active is not None:
        previous_active.is_active = True
        await version_repo.save(previous_active)

    if not project.description and description_value:
        project.description = description_value
        await project_repo.save(project)

    await session.commit()

    if is_htmx(request):
        return Response(
            status_code=200,
            headers={
                "HX-Redirect": f"/admin/projects/{project_id}?msg=Description+generated+as+draft"
            },
        )
    return RedirectResponse(
        f"/admin/projects/{project_id}?msg=Description+generated+as+draft", status_code=303
    )
