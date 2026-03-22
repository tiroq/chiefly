"""
Main FastAPI application entry point.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from apps.api.config import get_settings
from apps.api.logging import configure_logging, get_logger
from apps.api.routes import admin, health, telegram_webhook
from apps.api.routes.admin_ui import router as admin_ui_router
from apps.api.routes.admin_api import router as admin_api_router
from apps.api.admin.auth import create_login_router, htmx_exception_handler
from apps.api.services.scheduler_service import setup_scheduler
from apps.api.workers.daily_review_worker import run_daily_review
from apps.api.workers.inbox_poll_worker import run_inbox_poll
from apps.api.workers.processing_worker import run_processing
from apps.api.workers.project_sync_worker import run_project_sync
from apps.api.workers.sync_worker import run_sync

logger = get_logger(__name__)


def _build_telegram_dispatcher():
    """Build aiogram Dispatcher with all handlers registered."""
    from importlib import import_module

    from aiogram import Dispatcher, F
    from aiogram.filters import Command
    from aiogram.types import CallbackQuery, Message

    from apps.api.services.classification_service import ClassificationService
    from apps.api.services.google_tasks_service import GoogleTasksService
    from apps.api.services.llm_service import LLMService
    from apps.api.services.project_routing_service import ProjectRoutingService
    from apps.api.services.telegram_service import TelegramService
    from core.domain.enums import ReviewAction, TaskKind, WorkflowStatus
    from core.domain.exceptions import TaskNotFoundError
    from core.schemas.telegram import (
        CallbackPayload,
        KindSelectPayload,
        ProjectSelectPayload,
    )
    from core.utils.ids import parse_uuid
    from db.models.task_revision import TaskRevision
    from db.models.telegram_review_session import TelegramReviewSession
    from db.repositories.project_repo import ProjectRepository
    from db.repositories.review_session_repo import ReviewSessionRepository
    from db.repositories.task_record_repo import TaskRecordRepository
    from db.session import get_session_factory

    dp = Dispatcher()
    settings = get_settings()

    def _queue_service(session, tg):
        queue_service_module = import_module("apps.api.services.review_queue_service")
        return queue_service_module.ReviewQueueService(session, tg)

    # ── Commands ──────────────────────────────────────────────────────────────

    @dp.message(Command("start"))
    async def cmd_start(message: Message):
        await message.answer(
            "👋 Hi! I'm <b>Chiefly</b>, your AI Chief of Staff.\n\n"
            "I process tasks from your Google Tasks inbox and help you stay organized.\n\n"
            "Commands:\n"
            "/help – show this help\n"
            "/inbox – show pending proposals\n"
            "/today – show today's tasks\n"
            "/next – show next item to review\n"
            "/backlog – show review queue\n"
            "/review – generate and send daily review\n"
            "/stats – show task statistics"
        )

    @dp.message(Command("help"))
    async def cmd_help(message: Message):
        await message.answer(
            "<b>Chiefly Commands</b>\n\n"
            "/start – welcome message\n"
            "/inbox – pending tasks awaiting review\n"
            "/today – active tasks for today\n"
            "/projects – list available projects\n"
            "/next – show next item to review\n"
            "/backlog – show review queue\n"
            "/review – trigger daily review now\n"
            "/stats – task counts by status"
        )

    @dp.message(Command("inbox"))
    async def cmd_inbox(message: Message):
        factory = get_session_factory()
        async with factory() as session:
            repo = TaskRecordRepository(session)
            rows = await repo.list_filtered(
                processing_status=WorkflowStatus.AWAITING_REVIEW,
                limit=10,
                offset=0,
            )
            if not rows:
                await message.answer("✅ Inbox is empty! No pending proposals.")
                return
            lines = [f"📬 <b>Pending proposals ({len(rows)}):</b>"]
            for record, snapshot in rows:
                payload = snapshot.payload if snapshot and snapshot.payload else {}
                title = payload.get("title") or str(record.stable_id)
                lines.append(f"  • {title}")
            await message.answer("\n".join(lines))

    @dp.message(Command("today"))
    async def cmd_today(message: Message):
        factory = get_session_factory()
        async with factory() as session:
            repo = TaskRecordRepository(session)
            rows = await repo.list_filtered(
                processing_status=WorkflowStatus.APPLIED,
                limit=10,
                offset=0,
            )
            if not rows:
                await message.answer("📭 No active tasks routed today.")
                return
            lines = [f"📋 <b>Active tasks ({len(rows)}):</b>"]
            for record, snapshot in rows:
                payload = snapshot.payload if snapshot and snapshot.payload else {}
                title = payload.get("title") or str(record.stable_id)
                lines.append(f"  • {title}")
            await message.answer("\n".join(lines))

    @dp.message(Command("projects"))
    async def cmd_projects(message: Message):
        factory = get_session_factory()
        async with factory() as session:
            repo = ProjectRepository(session)
            projects = await repo.list_active()
            if not projects:
                await message.answer("No projects configured.")
                return
            lines = [f"📁 <b>Projects ({len(projects)}):</b>"]
            for p in projects:
                lines.append(f"  • {p.name} ({p.project_type})")
            await message.answer("\n".join(lines))

    @dp.message(Command("review"))
    async def cmd_review(message: Message):
        await message.answer("🔄 Generating daily review...")
        await run_daily_review()

    @dp.message(Command("stats"))
    async def cmd_stats(message: Message):
        factory = get_session_factory()
        async with factory() as session:
            repo = TaskRecordRepository(session)
            lines = ["📊 <b>Task Statistics:</b>"]
            for status in WorkflowStatus:
                count = await repo.count_filtered(processing_status=status)
                if count:
                    lines.append(f"  {status.value}: {count}")
            await message.answer("\n".join(lines))

    @dp.message(Command("next"))
    async def cmd_next(message: Message):
        factory = get_session_factory()
        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

        async with factory() as session:
            queue_svc = _queue_service(session, tg)
            sent = await queue_svc.send_next()

        if not sent:
            await message.answer("✅ No more items in the review queue.")

    @dp.message(Command("backlog"))
    async def cmd_backlog(message: Message):
        factory = get_session_factory()
        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

        async with factory() as session:
            queue_svc = _queue_service(session, tg)
            status = await queue_svc.get_queue_status()

        total_queued = status["total_queued"] if isinstance(status["total_queued"], int) else 0
        has_active = bool(status["has_active"])
        items = status["items"] if isinstance(status["items"], list) else []

        if total_queued == 0 and not has_active:
            await message.answer("✅ Queue is empty. Nothing to review.")
            return

        lines = [f"📋 <b>Review Queue ({total_queued} pending):</b>"]
        if has_active:
            lines.append("🔵 1 item currently under review")
        for i, title in enumerate(items, 1):
            lines.append(f"  {i}. {title}")
        if total_queued > len(items):
            lines.append(f"  ... and {total_queued - len(items)} more")
        await message.answer("\n".join(lines))

    # ── Callback Handlers ─────────────────────────────────────────────────────

    async def _get_review_session(stable_id_hex: str, db_session) -> TelegramReviewSession:
        session_repo = ReviewSessionRepository(db_session)
        stable_id = parse_uuid(stable_id_hex)
        review_session = await session_repo.get_active_by_stable_id(stable_id)
        if review_session is None:
            raise TaskNotFoundError(f"No active review for: {stable_id_hex}")
        return review_session

    @dp.callback_query(F.data.startswith("confirm:"))
    async def handle_confirm(callback: CallbackQuery):
        if not callback.data:
            await callback.answer("Invalid callback.", show_alert=True)
            return
        payload = CallbackPayload.decode(callback.data)
        factory = get_session_factory()
        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

        async with factory() as session:
            from core.utils.datetime import utcnow
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

            if project and project.google_tasklist_id and project.google_tasklist_id != tl_id:
                try:
                    moved = gtasks.move_task(tl_id, t_id, project.google_tasklist_id)
                    new_gtask_id = moved.id
                    new_tasklist_id = moved.tasklist_id
                    if normalized_title and normalized_title != current_google.title:
                        gtasks.patch_task(new_tasklist_id, new_gtask_id, title=normalized_title)
                except Exception as e:
                    logger.warning("google_tasks_move_failed", error=str(e))
            elif normalized_title and normalized_title != current_google.title:
                try:
                    gtasks.patch_task(tl_id, t_id, title=normalized_title)
                except Exception as e:
                    logger.warning("google_tasks_patch_failed", error=str(e))

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

            from core.domain.enums import WorkflowStatus

            await record_repo.update_processing_status(stable_id, WorkflowStatus.APPLIED)

            review_session.status = "resolved"
            review_session.resolved_at = now
            await session_repo.save(review_session)

            await session.commit()

        await callback.answer("✅ Task confirmed and routed!")
        msg = callback.message
        if isinstance(msg, Message):
            msg_text = msg.text or ""
            await msg.edit_text(msg_text + "\n\n✅ <b>Confirmed and routed.</b>")

        async with factory() as session:
            queue_svc = _queue_service(session, tg)
            await queue_svc.send_next()

    @dp.callback_query(F.data.startswith("discard:"))
    async def handle_discard(callback: CallbackQuery):
        if not callback.data:
            await callback.answer("Invalid callback.", show_alert=True)
            return
        payload = CallbackPayload.decode(callback.data)
        factory = get_session_factory()
        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

        async with factory() as session:
            from core.utils.datetime import utcnow
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

                from core.domain.enums import WorkflowStatus

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

    @dp.callback_query(F.data.startswith("change_project:"))
    async def handle_change_project(callback: CallbackQuery):
        if not callback.data:
            await callback.answer("Invalid callback.", show_alert=True)
            return
        payload = CallbackPayload.decode(callback.data)
        factory = get_session_factory()
        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

        async with factory() as session:
            session_repo = ReviewSessionRepository(session)
            project_repo = ProjectRepository(session)

            try:
                review_session = await _get_review_session(payload.task_id, session)
            except TaskNotFoundError:
                await callback.answer("Task not found!", show_alert=True)
                return

            proposed = review_session.proposed_changes or {}
            projects = await project_repo.list_active()
            current_project_name = proposed.get("project_name")

        project_list = [(p.name, p.slug) for p in projects]
        task_title = proposed.get("normalized_title")
        await tg.send_project_picker(
            task_id=payload.task_id,
            projects=project_list,
            task_title=task_title,
            current_project=current_project_name,
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("change_type:"))
    async def handle_change_type(callback: CallbackQuery):
        if not callback.data:
            await callback.answer("Invalid callback.", show_alert=True)
            return
        payload = CallbackPayload.decode(callback.data)
        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)
        await tg.send_kind_picker(task_id=payload.task_id)
        await callback.answer()

    @dp.callback_query(F.data.startswith("edit:"))
    async def handle_edit(callback: CallbackQuery):
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

        await callback.answer()
        if callback.message:
            await callback.message.answer("✏️ Please send me the new title for this task:")

    @dp.callback_query(F.data.startswith("show_steps:"))
    async def handle_show_steps(callback: CallbackQuery):
        if not callback.data:
            await callback.answer("Invalid callback.", show_alert=True)
            return
        payload = CallbackPayload.decode(callback.data)
        factory = get_session_factory()

        async with factory() as session:
            from db.repositories.task_revision_repo import TaskRevisionRepository

            session_repo = ReviewSessionRepository(session)
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

    @dp.callback_query(F.data.startswith("proj:"))
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
            if project:
                proposed = dict(review_session.proposed_changes or {})
                proposed["project_id"] = str(project.id)
                proposed["project_name"] = project.name
                review_session.proposed_changes = proposed
                await session_repo.save(review_session)

                await session.commit()
                await callback.answer(f"Project changed to {project.name}")
            else:
                await callback.answer("Project not found.", show_alert=True)

    @dp.callback_query(F.data.startswith("kind:"))
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
            await callback.answer(f"Type changed to {payload.kind}")

    # ── Text message handler (for edit flow) ─────────────────────────────────

    @dp.message(F.text & ~F.text.startswith("/"))
    async def handle_text_message(message: Message):
        import html as html_mod

        chat_id = str(message.chat.id)
        factory = get_session_factory()

        async with factory() as session:
            session_repo = ReviewSessionRepository(session)
            pending = await session_repo.get_pending_edit_by_chat(chat_id)

            if pending is None:
                return

            new_title = message.text.strip() if message.text else ""
            if not new_title:
                return

            proposed = dict(pending.proposed_changes or {})
            proposed["normalized_title"] = new_title[:500]
            pending.proposed_changes = proposed

            pending.status = "pending"
            await session_repo.save(pending)

            await session.commit()

        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)
        safe_title = html_mod.escape(new_title)
        await tg.send_text(f"✅ Title updated to: <i>{safe_title}</i>")

    return dp


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    configure_logging()
    settings = get_settings()
    logger.info("starting_chiefly", env=settings.app_env)

    # Build and start Telegram bot
    polling_task: asyncio.Task[None] | None = None
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dp = _build_telegram_dispatcher()
        app.state.bot = bot
        app.state.dispatcher = dp

        # Start long polling as a background task (works without a public URL)
        polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
        logger.info("telegram_polling_started")
    except Exception as e:
        logger.warning("telegram_init_failed", error=str(e))
        app.state.bot = None
        app.state.dispatcher = None

    # Set up scheduler
    scheduler = setup_scheduler(
        poll_interval_seconds=settings.inbox_poll_interval_seconds,
        processing_interval_seconds=settings.processing_interval_seconds,
        daily_review_cron=settings.daily_review_cron,
        project_sync_cron=settings.project_sync_cron,
        timezone=settings.timezone,
        poll_job=run_sync,
        processing_job=run_processing,
        review_job=run_daily_review,
        project_sync_job=run_project_sync,
    )
    scheduler.start()
    logger.info("scheduler_started")

    # Run project sync immediately on startup so projects are available from the first poll
    try:
        await run_project_sync()
        logger.info("project_sync_startup_completed")
    except Exception as e:
        logger.warning("project_sync_startup_failed", error=str(e))

    yield

    if scheduler:
        scheduler.shutdown()
    if polling_task and not polling_task.done():
        polling_task.cancel()
        try:
            await polling_task
        except Exception:
            pass
    if app.state.bot:
        await app.state.bot.session.close()
    logger.info("chiefly_shutdown")


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Chiefly",
        description="AI Chief of Staff for task intake and execution",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(telegram_webhook.router)

    # Mount static files for admin UI
    app.mount("/static/admin", StaticFiles(directory="apps/api/static/admin"), name="admin_static")

    # Register HTMX exception handler
    app.add_exception_handler(Exception, htmx_exception_handler)

    # Include admin UI router BEFORE old admin router to avoid route conflicts
    app.include_router(admin_ui_router, prefix="/admin")

    # Include admin API router
    app.include_router(admin_api_router, prefix="/admin/api")

    # Include login router (has its own /admin/login prefix)
    settings = get_settings()
    app.include_router(create_login_router(settings.admin_token))

    # Legacy admin JSON API routes (after UI routes to avoid conflicts)
    app.include_router(admin.router)

    return app


app = create_app()
