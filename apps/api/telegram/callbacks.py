from __future__ import annotations

import html as html_mod
import uuid
from importlib import import_module

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.review_queue_service import SendNextResult
from apps.api.services.review_pause import toggle_review_pause
from apps.api.services.telegram_service import TelegramService
from apps.api.services.user_settings_service import (
    cycle_batch_size,
    get_user_settings,
    toggle_bool_setting,
)
from apps.api.telegram.keyboards import (
    backlog_keyboard,
    disambiguation_keyboard,
    discard_confirm_keyboard,
    kind_picker_keyboard,
    project_picker_keyboard,
    settings_keyboard,
)
from apps.api.telegram.states import ReviewStates
from core.domain.enums import ConfidenceBand, ReviewAction, TaskKind, WorkflowStatus
from core.domain.exceptions import TaskNotFoundError
from core.schemas.telegram import (
    CallbackPayload,
    DisambiguationPayload,
    DraftActionPayload,
    KindSelectPayload,
    ProjectSelectPayload,
    QueueActionPayload,
    SettingPayload,
)
from core.utils.ids import parse_uuid
from db.models.telegram_review_session import TelegramReviewSession
from db.repositories.project_repo import ProjectRepository
from db.repositories.review_session_repo import ReviewSessionRepository
from db.session import get_session_factory

logger = get_logger(__name__)

callback_router = Router(name="callbacks")


async def _get_review_session(stable_id_hex: str, db_session) -> TelegramReviewSession:
    session_repo = ReviewSessionRepository(db_session)
    stable_id = parse_uuid(stable_id_hex)
    review_session = await session_repo.get_active_by_stable_id(stable_id)
    if review_session is None:
        raise TaskNotFoundError(f"No active review for: {stable_id_hex}")
    return review_session


def _queue_service(session, tg):
    mod = import_module("apps.api.services.review_queue_service")
    return mod.ReviewQueueService(session, tg)


async def _rebuild_proposal_card(callback, review_session, db_session):
    """Edit the original message to reflect updated proposed_changes."""
    from apps.api.services.telegram_service import _build_proposal_text, TelegramService
    from apps.api.telegram.keyboards import proposal_keyboard
    from core.schemas.llm import TaskClassificationResult
    from db.repositories.task_snapshot_repo import TaskSnapshotRepository

    proposed = review_session.proposed_changes or {}
    kind = TaskKind(proposed.get("kind", "task"))
    confidence = ConfidenceBand(proposed.get("confidence", "medium"))

    classification = TaskClassificationResult(
        kind=kind,
        normalized_title=proposed.get("normalized_title", ""),
        confidence=confidence,
        next_action=proposed.get("next_action"),
        due_hint=proposed.get("due_hint"),
        substeps=proposed.get("substeps", []),
        ambiguities=proposed.get("ambiguities", []),
    )

    raw_text = ""
    if review_session.stable_id:
        snapshot_repo = TaskSnapshotRepository(db_session)
        snapshot = await snapshot_repo.get_latest_by_stable_id(review_session.stable_id)
        if snapshot and snapshot.payload:
            raw_text = snapshot.payload.get("title", "")
    if not raw_text:
        raw_text = classification.normalized_title

    text = _build_proposal_text(raw_text, classification, proposed.get("project_name"))
    short_id = (
        str(review_session.stable_id).replace("-", "")
        if review_session.stable_id
        else str(review_session.id).replace("-", "")
    )
    keyboard = proposal_keyboard(
        short_id, has_disambiguation=bool(proposed.get("disambiguation_options"))
    )

    msg = callback.message
    if msg:
        try:
            await msg.edit_text(text, reply_markup=keyboard)
        except Exception as exc:
            logger.warning("proposal_card_rebuild_failed", error=str(exc))


@callback_router.callback_query(F.data.startswith("confirm:"))
async def handle_confirm(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = CallbackPayload.decode(callback.data)
    factory = get_session_factory()
    settings = get_settings()
    tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    try:
        async with factory() as session:
            from apps.api.services.google_tasks_service import GoogleTasksService
            from core.utils.datetime import utcnow
            from db.models.task_revision import TaskRevision
            from db.repositories.task_record_repo import TaskRecordRepository
            from db.repositories.task_revision_repo import TaskRevisionRepository

            session_repo = ReviewSessionRepository(session)
            record_repo = TaskRecordRepository(session)
            revision_repo = TaskRevisionRepository(session)

            try:
                review_session = await _get_review_session(payload.task_id, session)
            except TaskNotFoundError:
                await callback.answer("Task not found!", show_alert=True)
                return

            stable_id = review_session.stable_id
            if stable_id is None:
                await callback.answer("Missing stable ID.", show_alert=True)
                return

            record = await record_repo.get_by_stable_id(stable_id)
            if record is None:
                await callback.answer("Task record not found!", show_alert=True)
                return

            proposed = review_session.proposed_changes or {}

            project_repo = ProjectRepository(session)
            project_id_str = proposed.get("project_id")
            project = None
            if project_id_str:
                try:
                    project = await project_repo.get_by_id(uuid.UUID(project_id_str))
                except (ValueError, TypeError):
                    pass

            gtasks = GoogleTasksService(settings.google_credentials_file)
            tl_id = record.current_tasklist_id
            t_id = record.current_task_id

            if not tl_id or not t_id:
                await callback.answer("Task location unknown.", show_alert=True)
                return

            current_google = gtasks.get_task(tl_id, t_id)
            if current_google is None:
                await callback.answer("Google task not found.", show_alert=True)
                return

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
                except Exception as e:
                    logger.warning("google_tasks_move_failed", error=str(e))
                    google_update_failed = True
            elif normalized_title and normalized_title != current_google.title:
                try:
                    gtasks.patch_task(tl_id, t_id, title=normalized_title)
                except Exception as e:
                    logger.warning("google_tasks_patch_failed", error=str(e))
                    google_update_failed = True

            after_google = gtasks.get_task(new_tasklist_id, new_gtask_id)
            after_state = {}
            if after_google:
                after_state = after_google.raw_payload or {
                    "id": after_google.id,
                    "title": after_google.title,
                    "notes": after_google.notes,
                    "status": after_google.status,
                    "due": after_google.due,
                    "updated": after_google.updated,
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
                actor_id="telegram",
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

            review_session.status = "resolved"
            review_session.resolved_at = now
            await session_repo.save(review_session)

            await session.commit()

        if google_update_failed:
            await callback.answer(
                "⚠️ Task confirmed but Google Tasks update failed. The task may need manual attention.",
                show_alert=True,
            )
        else:
            await callback.answer("✅ Task confirmed and routed!")
        msg = callback.message
        if isinstance(msg, Message):
            msg_text = msg.text or ""
            await msg.edit_text(msg_text + "\n\n✅ <b>Confirmed and routed.</b>")

        async with factory() as session:
            queue_svc = _queue_service(session, tg)
            await queue_svc.send_next()
    finally:
        await tg.aclose()


@callback_router.callback_query(F.data.startswith("discard:"))
async def handle_discard(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = CallbackPayload.decode(callback.data)
    msg = callback.message
    title = "this task"
    if isinstance(msg, Message):
        msg_text = msg.text or ""
        for line in msg_text.splitlines():
            if "Title:" in line:
                title = line.split("Title:", 1)[1].strip()
                break

        keyboard = discard_confirm_keyboard(payload.task_id)
        await msg.edit_text(f"⚠️ Discard this task?\n\n{title}", reply_markup=keyboard)

    await callback.answer("Are you sure?")


@callback_router.callback_query(F.data.startswith("discard_confirm:"))
async def handle_discard_confirm(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    task_id = callback.data.split(":", 1)[1]
    factory = get_session_factory()
    settings = get_settings()
    tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    try:
        async with factory() as session:
            from core.utils.datetime import utcnow
            from db.models.task_revision import TaskRevision
            from db.repositories.task_record_repo import TaskRecordRepository
            from db.repositories.task_revision_repo import TaskRevisionRepository

            session_repo = ReviewSessionRepository(session)
            record_repo = TaskRecordRepository(session)
            revision_repo = TaskRevisionRepository(session)

            try:
                review_session = await _get_review_session(task_id, session)
            except TaskNotFoundError:
                await callback.answer("Task not found!", show_alert=True)
                return

            stable_id = review_session.stable_id
            proposed = review_session.proposed_changes or {}
            now = utcnow()

            if stable_id:
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
                    actor_id="telegram",
                    started_at=now,
                    finished_at=now,
                    success=True,
                    final_title=proposed.get("normalized_title"),
                    final_kind=proposed.get("kind"),
                    final_next_action=proposed.get("next_action"),
                )
                await revision_repo.create(discard_revision)

                await record_repo.update_processing_status(stable_id, WorkflowStatus.DISCARDED)

            review_session.status = "resolved"
            review_session.resolved_at = now
            await session_repo.save(review_session)

            await session.commit()

        await callback.answer("🗑 Task discarded.")
        msg = callback.message
        if isinstance(msg, Message):
            msg_text = msg.text or ""
            await msg.edit_text(msg_text + "\n\n🗑 <b>Discarded.</b>")

        async with factory() as session:
            queue_svc = _queue_service(session, tg)
            await queue_svc.send_next()
    finally:
        await tg.aclose()


@callback_router.callback_query(F.data.startswith("discard_cancel:"))
async def handle_discard_cancel(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    task_id = callback.data.split(":", 1)[1]
    factory = get_session_factory()
    async with factory() as session:
        try:
            review_session = await _get_review_session(task_id, session)
        except TaskNotFoundError:
            await callback.answer("Task not found!", show_alert=True)
            return
        await _rebuild_proposal_card(callback, review_session, session)

    await callback.answer("Cancelled")


@callback_router.callback_query(F.data.startswith("change_project:"))
async def handle_change_project(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = CallbackPayload.decode(callback.data)
    factory = get_session_factory()

    async with factory() as session:
        project_repo = ProjectRepository(session)

        try:
            review_session = await _get_review_session(payload.task_id, session)
        except TaskNotFoundError:
            await callback.answer("Task not found!", show_alert=True)
            return

        proposed = review_session.proposed_changes or {}
        projects = await project_repo.list_active()

        current = proposed.get("project_name")
        suggested = proposed.get("project_name")
        projects_with_desc = [(p.name, p.slug, p.description) for p in projects]

        msg = callback.message
        if isinstance(msg, Message):
            keyboard = project_picker_keyboard(
                payload.task_id, projects_with_desc, current, suggested
            )
            await msg.edit_text("📁 <b>Select a project:</b>", reply_markup=keyboard)

    await callback.answer()


@callback_router.callback_query(F.data.startswith("change_type:"))
async def handle_change_type(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = CallbackPayload.decode(callback.data)
    msg = callback.message
    if isinstance(msg, Message):
        keyboard = kind_picker_keyboard(payload.task_id)
        await msg.edit_text("🔄 <b>Select task type:</b>", reply_markup=keyboard)
    await callback.answer()


@callback_router.callback_query(F.data.startswith("edit:"))
async def handle_edit(callback: CallbackQuery, state: FSMContext):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = CallbackPayload.decode(callback.data)
    factory = get_session_factory()

    async with factory() as session:
        session_repo = ReviewSessionRepository(session)
        try:
            review_session = await _get_review_session(payload.task_id, session)
        except TaskNotFoundError:
            await callback.answer("Task not found!", show_alert=True)
            return

        review_session.status = "awaiting_edit"
        await session_repo.save(review_session)
        await session.commit()

    await state.set_state(ReviewStates.awaiting_title_edit)
    await state.update_data(task_id=payload.task_id)
    await callback.answer("✏️ Send me the new title:")


@callback_router.callback_query(F.data.startswith("show_steps:"))
async def handle_show_steps(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = CallbackPayload.decode(callback.data)
    factory = get_session_factory()

    async with factory() as session:
        from db.repositories.task_revision_repo import TaskRevisionRepository

        revision_repo = TaskRevisionRepository(session)

        try:
            review_session = await _get_review_session(payload.task_id, session)
        except TaskNotFoundError:
            await callback.answer("Task not found!", show_alert=True)
            return

        proposed = review_session.proposed_changes or {}
        raw_substeps = proposed.get("substeps")
        substeps: list[str] = []
        if isinstance(raw_substeps, list):
            substeps = [str(step) for step in raw_substeps]

        if not substeps and review_session.stable_id:
            revisions = await revision_repo.list_by_stable_id(review_session.stable_id)
            for rev in revisions:
                raw_revision_substeps = (
                    rev.proposal_json.get("substeps") if rev.proposal_json else []
                )
                if isinstance(raw_revision_substeps, list):
                    substeps = [str(step) for step in raw_revision_substeps]
                    break

    if substeps:
        lines = ["📋 <b>Sub-steps:</b>"]
        for i, step in enumerate(substeps, 1):
            lines.append(f"{i}. {step}")
        if callback.message:
            await callback.message.answer("\n".join(lines))
    else:
        if callback.message:
            await callback.message.answer("No sub-steps recorded for this task.")
    await callback.answer()


@callback_router.callback_query(F.data.startswith("proj:"))
async def handle_project_selection(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = ProjectSelectPayload.decode(callback.data)
    factory = get_session_factory()

    async with factory() as session:
        session_repo = ReviewSessionRepository(session)
        project_repo = ProjectRepository(session)

        stable_id = parse_uuid(payload.task_id)
        review_session = await session_repo.get_active_by_stable_id(stable_id)
        if review_session is None:
            await callback.answer("Review session not found.", show_alert=True)
            return

        project = await project_repo.get_by_slug(payload.project_slug)
        if not project:
            await callback.answer("Project not found.", show_alert=True)
            return

        proposed = dict(review_session.proposed_changes or {})
        proposed["project_id"] = str(project.id)
        proposed["project_name"] = project.name
        review_session.proposed_changes = proposed
        await session_repo.save(review_session)
        await session.commit()

        await _rebuild_proposal_card(callback, review_session, session)

    await callback.answer(f"Project changed to {project.name}")


@callback_router.callback_query(F.data.startswith("kind:"))
async def handle_kind_selection(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = KindSelectPayload.decode(callback.data)
    factory = get_session_factory()

    async with factory() as session:
        session_repo = ReviewSessionRepository(session)

        stable_id = parse_uuid(payload.task_id)
        review_session = await session_repo.get_active_by_stable_id(stable_id)
        if review_session is None:
            await callback.answer("Review session not found.", show_alert=True)
            return

        try:
            new_kind = TaskKind(payload.kind)
        except ValueError:
            await callback.answer("Invalid task kind.", show_alert=True)
            return

        proposed = dict(review_session.proposed_changes or {})
        proposed["kind"] = str(new_kind.value)
        review_session.proposed_changes = proposed
        await session_repo.save(review_session)
        await session.commit()

        await _rebuild_proposal_card(callback, review_session, session)

    await callback.answer(f"Type changed to {payload.kind}")


@callback_router.callback_query(F.data.startswith("skip:"))
async def handle_skip(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = CallbackPayload.decode(callback.data)
    factory = get_session_factory()
    settings = get_settings()
    tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    try:
        async with factory() as session:
            session_repo = ReviewSessionRepository(session)
            try:
                review_session = await _get_review_session(payload.task_id, session)
            except TaskNotFoundError:
                await callback.answer("Task not found!", show_alert=True)
                return

            review_session.status = "skipped"
            await session_repo.save(review_session)
            await session.commit()

        msg = callback.message
        if isinstance(msg, Message):
            msg_text = msg.text or ""
            await msg.edit_text(msg_text + "\n\n⏭ <b>Skipped.</b>")

        await callback.answer("⏭ Skipped.")

        async with factory() as session:
            queue_svc = _queue_service(session, tg)
            await queue_svc.send_next()
    finally:
        await tg.aclose()


@callback_router.callback_query(F.data.startswith("clarify:"))
async def handle_clarify(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = CallbackPayload.decode(callback.data)
    factory = get_session_factory()

    async with factory() as session:
        try:
            review_session = await _get_review_session(payload.task_id, session)
        except TaskNotFoundError:
            await callback.answer("Task not found!", show_alert=True)
            return

        proposed = review_session.proposed_changes or {}
        raw_options = proposed.get("disambiguation_options")
        options: list[tuple[str, str, int]] = []
        if isinstance(raw_options, list):
            for idx, opt in enumerate(raw_options):
                if isinstance(opt, dict):
                    kind_value = str(opt.get("kind") or opt.get("type") or "task")
                    title = str(opt.get("title") or opt.get("normalized_title") or "")
                    if title:
                        options.append((kind_value, title, idx))

    msg = callback.message
    if options and isinstance(msg, Message):
        await msg.edit_text(
            "❓ <b>Select interpretation:</b>",
            reply_markup=disambiguation_keyboard(payload.task_id, options),
        )
    elif isinstance(msg, Message):
        await msg.answer("No alternative interpretations available for this item.")

    await callback.answer()


@callback_router.callback_query(F.data.startswith("disambig:"))
async def handle_disambiguation_select(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = DisambiguationPayload.decode(callback.data)
    factory = get_session_factory()

    async with factory() as session:
        session_repo = ReviewSessionRepository(session)

        stable_id = parse_uuid(payload.task_id)
        review_session = await session_repo.get_active_by_stable_id(stable_id)
        if review_session is None:
            await callback.answer("Review session not found.", show_alert=True)
            return

        proposed = dict(review_session.proposed_changes or {})
        raw_options = proposed.get("disambiguation_options")
        if not isinstance(raw_options, list):
            await callback.answer("No alternatives found.", show_alert=True)
            return

        idx = payload.option_index
        if idx < 0 or idx >= len(raw_options):
            await callback.answer("Invalid option.", show_alert=True)
            return

        selected = raw_options[idx]
        if not isinstance(selected, dict):
            await callback.answer("Invalid option.", show_alert=True)
            return

        selected_kind = str(selected.get("kind") or selected.get("type") or "task")
        selected_title = str(
            selected.get("title")
            or selected.get("normalized_title")
            or proposed.get("normalized_title", "")
        )

        proposed["kind"] = selected_kind
        proposed["normalized_title"] = selected_title
        review_session.proposed_changes = proposed
        await session_repo.save(review_session)
        await session.commit()

        await _rebuild_proposal_card(callback, review_session, session)

    await callback.answer("Updated")


@callback_router.callback_query(F.data.startswith("draft_message:"))
async def handle_draft_message(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = CallbackPayload.decode(callback.data)
    factory = get_session_factory()

    async with factory() as session:
        try:
            review_session = await _get_review_session(payload.task_id, session)
        except TaskNotFoundError:
            await callback.answer("Task not found!", show_alert=True)
            return

        proposed = review_session.proposed_changes or {}
        task_title = proposed.get("normalized_title", "")
        task_kind = proposed.get("kind", "task")
        next_action = proposed.get("next_action")

        from apps.api.services.llm_service import LLMService
        from apps.api.services.model_settings_service import get_effective_llm_config

        settings = get_settings()
        llm_config = await get_effective_llm_config(session, settings)

    from apps.api.telegram.keyboards import draft_keyboard

    fallback_note = ""
    try:
        llm = LLMService.from_effective_config(llm_config)
        draft_text = await llm.generate_draft_message(
            task_title=task_title,
            task_kind=task_kind,
            next_action=next_action,
        )
    except Exception as exc:
        logger.warning("draft_generation_failed", error=str(exc))
        draft_text = f"Follow up on: {task_title}"
        fallback_note = "\n\n<i>(AI draft unavailable — showing original title)</i>"

    if callback.message:
        await callback.message.answer(
            f"💬 <b>Draft message:</b>\n\n{draft_text}{fallback_note}",
            reply_markup=draft_keyboard(payload.task_id),
        )
    await callback.answer()


@callback_router.callback_query(F.data.startswith("draft_use:"))
async def handle_draft_use(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = DraftActionPayload.decode(callback.data)
    await callback.answer("Draft applied.")

    factory = get_session_factory()
    async with factory() as session:
        try:
            review_session = await _get_review_session(payload.task_id, session)
        except TaskNotFoundError:
            return
        await _rebuild_proposal_card(callback, review_session, session)


@callback_router.callback_query(F.data.startswith("draft_shorter:"))
async def handle_draft_shorter(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = DraftActionPayload.decode(callback.data)
    factory = get_session_factory()

    async with factory() as session:
        try:
            review_session = await _get_review_session(payload.task_id, session)
        except TaskNotFoundError:
            await callback.answer("Task not found!", show_alert=True)
            return
        proposed = review_session.proposed_changes or {}

        from apps.api.services.llm_service import LLMService
        from apps.api.services.model_settings_service import get_effective_llm_config

        settings = get_settings()
        llm_config = await get_effective_llm_config(session, settings)

    from apps.api.telegram.keyboards import draft_keyboard

    fallback_note = ""
    try:
        llm = LLMService.from_effective_config(llm_config)
        draft_text = await llm.generate_draft_message(
            task_title=proposed.get("normalized_title", ""),
            task_kind=proposed.get("kind", "task"),
            next_action=proposed.get("next_action"),
            tone="shorter",
        )
    except Exception as exc:
        logger.warning("draft_shorter_failed", error=str(exc))
        draft_text = proposed.get("normalized_title", "")
        fallback_note = "\n\n<i>(AI draft unavailable — showing original title)</i>"

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"💬 <b>Draft (shorter):</b>\n\n{draft_text}{fallback_note}",
            reply_markup=draft_keyboard(payload.task_id),
        )
    await callback.answer()


@callback_router.callback_query(F.data.startswith("draft_formal:"))
async def handle_draft_formal(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = DraftActionPayload.decode(callback.data)
    factory = get_session_factory()

    async with factory() as session:
        try:
            review_session = await _get_review_session(payload.task_id, session)
        except TaskNotFoundError:
            await callback.answer("Task not found!", show_alert=True)
            return
        proposed = review_session.proposed_changes or {}

        from apps.api.services.llm_service import LLMService
        from apps.api.services.model_settings_service import get_effective_llm_config

        settings = get_settings()
        llm_config = await get_effective_llm_config(session, settings)

    from apps.api.telegram.keyboards import draft_keyboard

    fallback_note = ""
    try:
        llm = LLMService.from_effective_config(llm_config)
        draft_text = await llm.generate_draft_message(
            task_title=proposed.get("normalized_title", ""),
            task_kind=proposed.get("kind", "task"),
            next_action=proposed.get("next_action"),
            tone="formal",
        )
    except Exception as exc:
        logger.warning("draft_formal_failed", error=str(exc))
        draft_text = proposed.get("normalized_title", "")
        fallback_note = "\n\n<i>(AI draft unavailable — showing original title)</i>"

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"💬 <b>Draft (formal):</b>\n\n{draft_text}{fallback_note}",
            reply_markup=draft_keyboard(payload.task_id),
        )
    await callback.answer()


@callback_router.callback_query(F.data.startswith("back_to_card:"))
async def handle_back_to_card(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    task_id = callback.data.split(":", 1)[1]
    factory = get_session_factory()
    async with factory() as session:
        try:
            review_session = await _get_review_session(task_id, session)
        except TaskNotFoundError:
            await callback.answer("Task not found!", show_alert=True)
            return
        await _rebuild_proposal_card(callback, review_session, session)
    await callback.answer()


@callback_router.callback_query(F.data == "queue:start")
async def handle_queue_start(callback: CallbackQuery):
    settings = get_settings()
    factory = get_session_factory()
    tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    try:
        async with factory() as session:
            queue_svc = _queue_service(session, tg)
            result = await queue_svc.send_next()
        if result == SendNextResult.SENT:
            await callback.answer("Sending next item...")
        elif result == SendNextResult.PAUSED:
            await callback.answer("⏸ Review queue is paused.")
        elif result == SendNextResult.ACTIVE_EXISTS:
            await callback.answer("📋 Active review exists. Finish it first.")
        elif result == SendNextResult.QUEUE_EMPTY:
            await callback.answer("✅ No more items in queue.")
    finally:
        await tg.aclose()


@callback_router.callback_query(F.data.startswith("queue:batch:"))
async def handle_queue_batch(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = QueueActionPayload.decode(callback.data)
    batch_size = payload.batch_size or 1

    settings = get_settings()
    factory = get_session_factory()
    tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    sent_count = 0
    try:
        for _ in range(batch_size):
            async with factory() as session:
                queue_svc = _queue_service(session, tg)
                result = await queue_svc.send_next()
            if result != SendNextResult.SENT:
                break
            sent_count += 1
    finally:
        await tg.aclose()

    await callback.answer(f"📦 Sent {sent_count}/{batch_size} item(s).")


@callback_router.callback_query(F.data == "queue:ambiguous")
async def handle_queue_ambiguous(callback: CallbackQuery):
    await callback.answer("Ambiguous-only filter coming soon.")


@callback_router.callback_query(F.data == "queue:pause")
async def handle_queue_pause(callback: CallbackQuery):
    factory = get_session_factory()
    async with factory() as session:
        paused = await toggle_review_pause(session)

    if paused:
        await callback.answer("⏸ Review queue paused.")
    else:
        await callback.answer("▶️ Review queue resumed.")


@callback_router.callback_query(F.data.startswith("setting:"))
async def handle_setting_toggle(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Invalid callback.", show_alert=True)
        return

    payload = SettingPayload.decode(callback.data)
    factory = get_session_factory()
    async with factory() as session:
        if payload.key == "batch_size":
            user_settings = await cycle_batch_size(session)
        else:
            user_settings = await toggle_bool_setting(session, payload.key)
        await session.commit()
        user_settings = await get_user_settings(session)

    msg = callback.message
    if isinstance(msg, Message):
        text = msg.text or "⚙️ <b>Settings</b>"
        await msg.edit_text(text, reply_markup=settings_keyboard(user_settings))
    await callback.answer("Updated")


@callback_router.callback_query(F.data == "settings:test_llm")
async def handle_test_llm_connection(callback: CallbackQuery):
    import asyncio
    from apps.api.services.model_settings_service import get_effective_llm_config
    from apps.api.services.llm_service import LLMService

    await callback.answer("Testing connection...", show_alert=False)

    settings = get_settings()
    factory = get_session_factory()

    try:
        async with factory() as session:
            llm_config = await get_effective_llm_config(session, settings)

        llm_svc = LLMService.from_effective_config(llm_config)
        client = llm_svc._get_client()
        await asyncio.to_thread(
            client.chat.completions.create,
            model=llm_config.model,
            messages=[{"role": "user", "content": "Say OK."}],
            max_tokens=5,
        )
        result_text = f"✅ LLM connection successful!\nProvider: {llm_config.provider}\nModel: {llm_config.model}"
    except Exception as exc:
        result_text = f"❌ LLM connection failed:\n{exc}"

    if callback.message:
        await callback.message.answer(result_text)


@callback_router.callback_query(F.data == "settings:close")
async def handle_settings_close(callback: CallbackQuery):
    msg = callback.message
    if isinstance(msg, Message):
        try:
            await msg.delete()
        except Exception:
            await msg.edit_text("⚙️ Settings closed.")
    await callback.answer()


@callback_router.callback_query(F.data == "nav:backlog")
async def handle_nav_backlog(callback: CallbackQuery):
    settings = get_settings()
    factory = get_session_factory()
    tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    try:
        async with factory() as session:
            queue_svc = _queue_service(session, tg)
            status = await queue_svc.get_queue_status()
    finally:
        await tg.aclose()

    total_queued = status["total_queued"] if isinstance(status["total_queued"], int) else 0
    has_active = bool(status["has_active"])
    items = status["items"] if isinstance(status["items"], list) else []

    if total_queued == 0 and not has_active:
        if callback.message:
            await callback.message.answer("✅ Queue is empty. Nothing to review.")
        await callback.answer()
        return

    lines = [f"📋 <b>Pending review backlog: {total_queued} items</b>"]
    if has_active:
        lines.append("🔵 1 item currently under review")
    lines.append("")
    for i, title in enumerate(items, 1):
        lines.append(f"  {i}. {html_mod.escape(str(title))}")
    if total_queued > len(items):
        lines.append(f"  ... and {total_queued - len(items)} more")

    if callback.message:
        await callback.message.answer("\n".join(lines), reply_markup=backlog_keyboard())
    await callback.answer()
