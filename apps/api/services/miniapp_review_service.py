from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, NotRequired, TypedDict, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.google_tasks_service import GoogleTasksService
from apps.api.services.llm_service import LLMService
from apps.api.services.model_settings_service import get_effective_llm_config
from core.domain.enums import ReviewAction, ReviewSessionStatus, TaskKind, WorkflowStatus
from core.utils.datetime import utcnow
from db.models.task_revision import TaskRevision
from db.models.telegram_review_session import TelegramReviewSession
from db.repositories.project_repo import ProjectRepository
from db.repositories.review_session_repo import ReviewSessionRepository
from db.repositories.task_record_repo import TaskRecordRepository
from db.repositories.task_revision_repo import TaskRevisionRepository
from db.repositories.task_snapshot_repo import TaskSnapshotRepository

logger = get_logger(__name__)

_REVIEWABLE_STATUSES = [ReviewSessionStatus.QUEUED.value, ReviewSessionStatus.ACTIVE.value]


class QueueItemData(TypedDict):
    stable_id: uuid.UUID
    raw_text: str
    normalized_title: str
    project_name: str | None
    kind: str
    confidence: str
    has_ambiguity: bool
    created_at: datetime


class QueueCounts(TypedDict):
    total: int
    queued: int
    active: int


class ReviewDetailData(TypedDict):
    stable_id: uuid.UUID
    raw_text: str
    normalized_title: str
    kind: str
    confidence: str
    project_name: str | None
    project_id: str | None
    next_action: str | None
    due_hint: str | None
    substeps: list[str]
    ambiguities: list[str]
    disambiguation_options: list[dict[str, Any]]
    telegram_message_id: int | None
    created_at: datetime


class ServiceResult(TypedDict):
    success: bool
    message: str
    google_update_failed: NotRequired[bool]
    draft_text: NotRequired[str | None]
    proposed_changes: NotRequired[dict[str, Any]]


class MiniAppReviewService:
    def __init__(self, session: AsyncSession):
        self._session: AsyncSession = session

    async def get_queue_items(
        self, status_filter: str | None = None
    ) -> tuple[list[QueueItemData], QueueCounts]:
        stmt = (
            select(TelegramReviewSession)
            .where(TelegramReviewSession.status.in_(_REVIEWABLE_STATUSES))
            .order_by(TelegramReviewSession.created_at.asc())
        )
        result = await self._session.execute(stmt)
        sessions = list(result.scalars().all())

        queued_count = sum(1 for rs in sessions if rs.status == ReviewSessionStatus.QUEUED.value)
        active_count = sum(1 for rs in sessions if rs.status == ReviewSessionStatus.ACTIVE.value)
        counts: QueueCounts = {
            "total": queued_count + active_count,
            "queued": queued_count,
            "active": active_count,
        }

        filtered: list[TelegramReviewSession]
        if status_filter == "queued":
            filtered = [rs for rs in sessions if rs.status == ReviewSessionStatus.QUEUED.value]
        elif status_filter == "active":
            filtered = [rs for rs in sessions if rs.status == ReviewSessionStatus.ACTIVE.value]
        elif status_filter == "ambiguous":
            filtered = [
                rs
                for rs in sessions
                if bool((rs.proposed_changes or {}).get("disambiguation_options"))
            ]
        else:
            filtered = sessions

        snapshot_repo = TaskSnapshotRepository(self._session)
        items: list[QueueItemData] = []
        for review_session in filtered:
            if review_session.stable_id is None:
                continue
            proposed = cast(dict[str, Any], review_session.proposed_changes or {})
            snapshot = await snapshot_repo.get_latest_by_stable_id(review_session.stable_id)
            raw_text = ""
            if snapshot and snapshot.payload:
                raw_text = str(snapshot.payload.get("title", ""))
            items.append(
                {
                    "stable_id": review_session.stable_id,
                    "raw_text": raw_text,
                    "normalized_title": proposed.get("normalized_title", ""),
                    "project_name": proposed.get("project_name"),
                    "kind": proposed.get("kind", "task"),
                    "confidence": proposed.get("confidence", "medium"),
                    "has_ambiguity": bool(proposed.get("disambiguation_options")),
                    "created_at": review_session.created_at,
                }
            )

        return items, counts

    async def get_review_detail(self, stable_id: uuid.UUID) -> ReviewDetailData | None:
        review_session = await self._get_review_session_for_action(stable_id)
        if review_session is None:
            return None

        snapshot_repo = TaskSnapshotRepository(self._session)
        snapshot = await snapshot_repo.get_latest_by_stable_id(stable_id)
        raw_text = ""
        if snapshot and snapshot.payload:
            raw_text = str(snapshot.payload.get("title", ""))

        proposed = cast(dict[str, Any], review_session.proposed_changes or {})
        return {
            "stable_id": stable_id,
            "raw_text": raw_text,
            "normalized_title": proposed.get("normalized_title", ""),
            "kind": proposed.get("kind", "task"),
            "confidence": proposed.get("confidence", "medium"),
            "project_name": proposed.get("project_name"),
            "project_id": proposed.get("project_id"),
            "next_action": proposed.get("next_action"),
            "due_hint": proposed.get("due_hint"),
            "substeps": [str(step) for step in proposed.get("substeps", [])],
            "ambiguities": [str(item) for item in proposed.get("ambiguities", [])],
            "disambiguation_options": proposed.get("disambiguation_options", []),
            "telegram_message_id": review_session.telegram_message_id,
            "created_at": review_session.created_at,
        }

    async def confirm_task(self, stable_id: uuid.UUID) -> ServiceResult:
        session_repo = ReviewSessionRepository(self._session)
        record_repo = TaskRecordRepository(self._session)
        revision_repo = TaskRevisionRepository(self._session)
        project_repo = ProjectRepository(self._session)

        review_session = await self._get_review_session_for_action(stable_id)
        if review_session is None:
            return {
                "success": False,
                "message": "Review session not found",
                "google_update_failed": False,
            }

        record = await record_repo.get_by_stable_id(stable_id)
        if record is None:
            return {
                "success": False,
                "message": "Task record not found",
                "google_update_failed": False,
            }

        tl_id = record.current_tasklist_id
        t_id = record.current_task_id
        if not tl_id or not t_id:
            return {
                "success": False,
                "message": "Task location unknown",
                "google_update_failed": False,
            }

        proposed = cast(dict[str, Any], dict(review_session.proposed_changes or {}))
        project = None
        project_id_raw = proposed.get("project_id")
        if project_id_raw:
            try:
                project = await project_repo.get_by_id(uuid.UUID(str(project_id_raw)))
            except (TypeError, ValueError):
                project = None

        settings = get_settings()
        gtasks = GoogleTasksService(settings.google_credentials_file)
        current_google = gtasks.get_task(tl_id, t_id)
        if current_google is None:
            return {
                "success": False,
                "message": "Google task not found",
                "google_update_failed": False,
            }

        before_state = current_google.raw_payload or {
            "id": current_google.id,
            "title": current_google.title,
            "notes": current_google.notes,
            "status": current_google.status,
            "due": current_google.due,
            "updated": current_google.updated,
        }

        new_gtask_id = t_id
        new_tasklist_id = tl_id
        normalized_title = proposed.get("normalized_title")
        google_update_failed = False

        if project and project.google_tasklist_id and project.google_tasklist_id != tl_id:
            try:
                moved = gtasks.move_task(tl_id, t_id, project.google_tasklist_id)
                new_gtask_id = moved.id
                new_tasklist_id = moved.tasklist_id
                if normalized_title and normalized_title != current_google.title:
                    gtasks.patch_task(new_tasklist_id, new_gtask_id, title=normalized_title)
            except Exception as exc:
                logger.warning("miniapp_google_tasks_move_failed", error=str(exc))
                google_update_failed = True
        elif normalized_title and normalized_title != current_google.title:
            try:
                gtasks.patch_task(tl_id, t_id, title=normalized_title)
            except Exception as exc:
                logger.warning("miniapp_google_tasks_patch_failed", error=str(exc))
                google_update_failed = True

        after_google = gtasks.get_task(new_tasklist_id, new_gtask_id)
        after_state = (after_google.raw_payload if after_google else None) or {
            "id": new_gtask_id,
            "title": normalized_title or current_google.title,
            "notes": current_google.notes,
            "status": current_google.status,
            "due": current_google.due,
            "updated": after_google.updated if after_google else current_google.updated,
        }

        now = utcnow()
        rev_no = await revision_repo.get_next_revision_no_by_stable_id(stable_id)
        confirm_revision = TaskRevision(
            id=uuid.uuid4(),
            stable_id=stable_id,
            revision_no=rev_no,
            raw_text=current_google.title or "",
            proposal_json=proposed,
            user_decision=ReviewAction.CONFIRM,
            action="confirm",
            actor_type="user",
            actor_id="miniapp",
            before_tasklist_id=tl_id,
            before_task_id=t_id,
            before_state_json=before_state,
            after_tasklist_id=new_tasklist_id,
            after_task_id=new_gtask_id,
            after_state_json=after_state,
            started_at=now,
            finished_at=now,
            success=True,
            final_title=normalized_title,
            final_kind=proposed.get("kind"),
            final_project_id=project.id if project else None,
            final_next_action=proposed.get("next_action"),
        )
        await revision_repo.create(confirm_revision)

        await record_repo.update_pointer(
            stable_id,
            new_tasklist_id,
            new_gtask_id,
            google_updated=after_google.updated if after_google else None,
        )
        await record_repo.update_processing_status(stable_id, WorkflowStatus.APPLIED)

        review_session.status = ReviewSessionStatus.RESOLVED.value
        review_session.resolved_at = now
        await session_repo.save(review_session)
        await self._session.commit()

        await self.update_telegram_message(review_session, "confirm")

        if google_update_failed:
            return {
                "success": True,
                "message": "Task confirmed; Google Tasks update failed",
                "google_update_failed": True,
            }
        return {"success": True, "message": "Task confirmed", "google_update_failed": False}

    async def discard_task(self, stable_id: uuid.UUID) -> ServiceResult:
        session_repo = ReviewSessionRepository(self._session)
        record_repo = TaskRecordRepository(self._session)
        revision_repo = TaskRevisionRepository(self._session)

        review_session = await self._get_review_session_for_action(stable_id)
        if review_session is None:
            return {"success": False, "message": "Review session not found"}

        proposed = cast(dict[str, Any], dict(review_session.proposed_changes or {}))
        now = utcnow()

        rev_no = await revision_repo.get_next_revision_no_by_stable_id(stable_id)
        discard_revision = TaskRevision(
            id=uuid.uuid4(),
            stable_id=stable_id,
            revision_no=rev_no,
            raw_text=proposed.get("normalized_title", ""),
            proposal_json=proposed,
            user_decision=ReviewAction.DISCARD,
            action="discard",
            actor_type="user",
            actor_id="miniapp",
            started_at=now,
            finished_at=now,
            success=True,
            final_title=proposed.get("normalized_title"),
            final_kind=proposed.get("kind"),
            final_next_action=proposed.get("next_action"),
        )
        await revision_repo.create(discard_revision)
        await record_repo.update_processing_status(stable_id, WorkflowStatus.DISCARDED)

        review_session.status = ReviewSessionStatus.RESOLVED.value
        review_session.resolved_at = now
        await session_repo.save(review_session)
        await self._session.commit()

        await self.update_telegram_message(review_session, "discard")

        return {"success": True, "message": "Task discarded"}

    async def edit_title(self, stable_id: uuid.UUID, new_title: str) -> ServiceResult:
        review_session = await self._get_review_session_for_action(stable_id)
        if review_session is None:
            return {"success": False, "message": "Review session not found"}

        title = new_title.strip()
        if not title:
            return {"success": False, "message": "Title cannot be empty"}

        proposed = cast(dict[str, Any], dict(review_session.proposed_changes or {}))
        proposed["normalized_title"] = title
        review_session.proposed_changes = proposed
        await self._session.flush()
        await self._session.commit()
        return {
            "success": True,
            "message": "Title updated",
            "proposed_changes": proposed,
        }

    async def change_project(self, stable_id: uuid.UUID, project_id: str) -> ServiceResult:
        review_session = await self._get_review_session_for_action(stable_id)
        if review_session is None:
            return {"success": False, "message": "Review session not found"}

        try:
            project_uuid = uuid.UUID(project_id)
        except ValueError:
            return {"success": False, "message": "Invalid project ID"}

        project_repo = ProjectRepository(self._session)
        project = await project_repo.get_by_id(project_uuid)
        if project is None:
            return {"success": False, "message": "Project not found"}

        proposed = cast(dict[str, Any], dict(review_session.proposed_changes or {}))
        proposed["project_id"] = str(project.id)
        proposed["project_name"] = project.name
        review_session.proposed_changes = proposed
        await self._session.flush()
        await self._session.commit()
        return {
            "success": True,
            "message": f"Project changed to {project.name}",
            "proposed_changes": proposed,
        }

    async def change_type(self, stable_id: uuid.UUID, kind: str) -> ServiceResult:
        review_session = await self._get_review_session_for_action(stable_id)
        if review_session is None:
            return {"success": False, "message": "Review session not found"}

        try:
            new_kind = TaskKind(kind)
        except ValueError:
            return {"success": False, "message": "Invalid task kind"}

        proposed = cast(dict[str, Any], dict(review_session.proposed_changes or {}))
        proposed["kind"] = new_kind.value
        review_session.proposed_changes = proposed
        await self._session.flush()
        await self._session.commit()
        return {
            "success": True,
            "message": f"Type changed to {new_kind.value}",
            "proposed_changes": proposed,
        }

    async def resolve_ambiguity(self, stable_id: uuid.UUID, option_index: int) -> ServiceResult:
        review_session = await self._get_review_session_for_action(stable_id)
        if review_session is None:
            return {"success": False, "message": "Review session not found"}

        proposed = cast(dict[str, Any], dict(review_session.proposed_changes or {}))
        options = cast(Any, proposed.get("disambiguation_options"))
        if not isinstance(options, list):
            return {"success": False, "message": "No alternatives found"}

        if option_index < 0 or option_index >= len(options):
            return {"success": False, "message": "Invalid option"}

        selected = cast(Any, options[option_index])
        if not isinstance(selected, dict):
            return {"success": False, "message": "Invalid option"}

        selected_kind = str(selected.get("kind") or selected.get("type") or "task")
        selected_title = str(
            selected.get("title")
            or selected.get("normalized_title")
            or proposed.get("normalized_title", "")
        )

        proposed["kind"] = selected_kind
        proposed["normalized_title"] = selected_title
        proposed["ambiguities"] = []
        proposed["disambiguation_options"] = []
        review_session.proposed_changes = proposed
        await self._session.flush()
        await self._session.commit()
        return {
            "success": True,
            "message": "Updated",
            "proposed_changes": proposed,
        }

    async def generate_draft(self, stable_id: uuid.UUID) -> ServiceResult:
        review_session = await self._get_review_session_for_action(stable_id)
        if review_session is None:
            return {"success": False, "draft_text": None, "message": "Review session not found"}

        proposed = cast(dict[str, Any], review_session.proposed_changes or {})
        task_title = str(proposed.get("normalized_title", ""))
        task_kind = str(proposed.get("kind", "task"))
        next_action = proposed.get("next_action")

        settings = get_settings()
        llm_config = await get_effective_llm_config(self._session, settings)

        try:
            llm = LLMService.from_effective_config(llm_config)
            draft_text = await llm.generate_draft_message(
                task_title=task_title,
                task_kind=task_kind,
                next_action=str(next_action) if next_action else None,
            )
            return {"success": True, "draft_text": draft_text, "message": "Draft generated"}
        except Exception as exc:
            logger.warning("miniapp_draft_generation_failed", error=str(exc))
            fallback = f"Follow up on: {task_title}" if task_title else None
            return {
                "success": True,
                "draft_text": fallback,
                "message": "AI draft unavailable; fallback generated",
            }

    async def update_telegram_message(
        self,
        review_session: TelegramReviewSession,
        action: str,
        bot: object | None = None,
    ) -> None:
        msg_id = review_session.telegram_message_id
        if not msg_id:
            return

        settings = get_settings()
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            return

        from apps.api.services.telegram_service import TelegramService

        suffix_map = {
            "confirm": "\n\n✅ <b>Confirmed via Mini App.</b>",
            "discard": "\n\n🗑 <b>Discarded via Mini App.</b>",
        }
        suffix = suffix_map.get(action)
        if not suffix:
            return

        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)
        try:
            tg_bot = tg._get_bot()
            original_text = ""
            try:
                from aiogram.types import Message as AiogramMessage

                result = await tg_bot.edit_message_reply_markup(
                    chat_id=settings.telegram_chat_id,
                    message_id=msg_id,
                    reply_markup=None,
                )
                if isinstance(result, AiogramMessage):
                    original_text = result.text or ""
            except Exception:
                pass

            if original_text:
                try:
                    await tg_bot.edit_message_text(
                        chat_id=settings.telegram_chat_id,
                        message_id=msg_id,
                        text=original_text + suffix,
                    )
                except Exception as exc:
                    logger.warning("miniapp_telegram_message_update_failed", error=str(exc))
        finally:
            await tg.aclose()

    async def _get_review_session_for_action(
        self, stable_id: uuid.UUID
    ) -> TelegramReviewSession | None:
        stmt = (
            select(TelegramReviewSession)
            .where(
                TelegramReviewSession.stable_id == stable_id,
                TelegramReviewSession.status.in_(_REVIEWABLE_STATUSES),
            )
            .order_by(TelegramReviewSession.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
