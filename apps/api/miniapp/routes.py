from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_session
from apps.api.miniapp.auth import verify_miniapp_auth
from apps.api.miniapp.schemas import (
    ActionResponse,
    ChangeProjectRequest,
    ChangeProjectTypeRequest,
    ChangeTypeRequest,
    ClarifyRequest,
    DraftResponse,
    EditTitleRequest,
    ProjectListItem,
    ReviewDetail,
    ReviewQueueItem,
    ReviewQueueResponse,
    UserSettingsResponse,
    UserSettingsUpdateRequest,
)
from core.domain.enums import ProjectType
from apps.api.services.miniapp_review_service import MiniAppReviewService
from apps.api.services.user_settings_service import get_user_settings, save_user_settings
from db.repositories.project_repo import ProjectRepository

router = APIRouter(
    prefix="/api/app",
    tags=["miniapp"],
    dependencies=[Depends(verify_miniapp_auth)],
)


def _to_settings_response(settings: dict[str, bool | int]) -> UserSettingsResponse:
    return UserSettingsResponse(
        auto_next=bool(settings["auto_next"]),
        batch_size=int(settings["batch_size"]),
        paused=bool(settings["paused"]),
        sync_summary=bool(settings["sync_summary"]),
        daily_brief=bool(settings["daily_brief"]),
        show_confidence=bool(settings["show_confidence"]),
        show_raw_input=bool(settings["show_raw_input"]),
        draft_suggestions=bool(settings["draft_suggestions"]),
        ambiguity_prompts=bool(settings["ambiguity_prompts"]),
        show_steps_auto=bool(settings["show_steps_auto"]),
        changes_only=bool(settings["changes_only"]),
    )


@router.get("/review/queue", response_model=ReviewQueueResponse)
async def get_review_queue(
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> ReviewQueueResponse:
    if status not in {None, "queued", "active", "ambiguous"}:
        raise HTTPException(status_code=400, detail="Invalid status filter")

    service = MiniAppReviewService(session)
    items, counts = await service.get_queue_items(status_filter=status)
    return ReviewQueueResponse(
        items=[ReviewQueueItem(**item) for item in items],
        total=counts["total"],
        pending=counts["active"],
        queued=counts["queued"],
    )


@router.get("/review/{stable_id}", response_model=ReviewDetail)
async def get_review_detail(
    stable_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ReviewDetail:
    service = MiniAppReviewService(session)
    detail = await service.get_review_detail(stable_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return ReviewDetail(**detail)


@router.post("/review/{stable_id}/confirm", response_model=ActionResponse)
async def confirm_review_item(
    stable_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ActionResponse:
    service = MiniAppReviewService(session)
    result = await service.confirm_task(stable_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return ActionResponse(success=True, message=result["message"])


@router.post("/review/{stable_id}/discard", response_model=ActionResponse)
async def discard_review_item(
    stable_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ActionResponse:
    service = MiniAppReviewService(session)
    result = await service.discard_task(stable_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return ActionResponse(success=True, message=result["message"])


@router.post("/review/{stable_id}/edit-title", response_model=ActionResponse)
async def edit_review_title(
    stable_id: uuid.UUID,
    payload: EditTitleRequest,
    session: AsyncSession = Depends(get_session),
) -> ActionResponse:
    service = MiniAppReviewService(session)
    result = await service.edit_title(stable_id, payload.title)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return ActionResponse(success=True, message=result["message"])


@router.post("/review/{stable_id}/change-project", response_model=ActionResponse)
async def change_review_project(
    stable_id: uuid.UUID,
    payload: ChangeProjectRequest,
    session: AsyncSession = Depends(get_session),
) -> ActionResponse:
    service = MiniAppReviewService(session)
    result = await service.change_project(stable_id, payload.project_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return ActionResponse(success=True, message=result["message"])


@router.post("/review/{stable_id}/change-type", response_model=ActionResponse)
async def change_review_type(
    stable_id: uuid.UUID,
    payload: ChangeTypeRequest,
    session: AsyncSession = Depends(get_session),
) -> ActionResponse:
    service = MiniAppReviewService(session)
    result = await service.change_type(stable_id, payload.kind)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return ActionResponse(success=True, message=result["message"])


@router.post("/review/{stable_id}/clarify", response_model=ActionResponse)
async def clarify_review_item(
    stable_id: uuid.UUID,
    payload: ClarifyRequest,
    session: AsyncSession = Depends(get_session),
) -> ActionResponse:
    service = MiniAppReviewService(session)
    result = await service.resolve_ambiguity(stable_id, payload.option_index)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return ActionResponse(success=True, message=result["message"])


@router.post("/review/{stable_id}/draft", response_model=DraftResponse)
async def generate_draft(
    stable_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> DraftResponse:
    service = MiniAppReviewService(session)
    result = await service.generate_draft(stable_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return DraftResponse(
        success=True,
        draft_text=result.get("draft_text"),
        message=result["message"],
    )


@router.get("/settings", response_model=UserSettingsResponse)
async def get_settings_endpoint(
    session: AsyncSession = Depends(get_session),
) -> UserSettingsResponse:
    settings = await get_user_settings(session)
    return _to_settings_response(settings)


@router.put("/settings", response_model=UserSettingsResponse)
async def update_settings_endpoint(
    payload: UserSettingsUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> UserSettingsResponse:
    settings = await get_user_settings(session)
    updates = payload.model_dump(exclude_none=True)
    settings.update(updates)
    await save_user_settings(session, settings)
    await session.commit()
    return _to_settings_response(settings)


@router.patch("/projects/{project_id}", response_model=ActionResponse)
async def update_project_type(
    project_id: uuid.UUID,
    payload: ChangeProjectTypeRequest,
    session: AsyncSession = Depends(get_session),
) -> ActionResponse:
    try:
        new_type = ProjectType(payload.project_type.lower())
    except ValueError:
        valid = [t.value for t in ProjectType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid project_type. Valid values: {', '.join(valid)}",
        )
    repo = ProjectRepository(session)
    project = await repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project.project_type = new_type
    await repo.save(project)
    await session.commit()
    return ActionResponse(success=True, message="Project type updated")


@router.get("/projects", response_model=list[ProjectListItem])
async def list_projects(
    session: AsyncSession = Depends(get_session),
) -> list[ProjectListItem]:
    repo = ProjectRepository(session)
    projects = await repo.list_active()
    return [
        ProjectListItem(
            id=project.id,
            name=project.name,
            slug=project.slug,
            project_type=project.project_type,
            description=project.description,
            is_active=project.is_active,
        )
        for project in projects
    ]
