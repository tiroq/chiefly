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
from apps.api.workers.project_sync_worker import run_project_sync

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
    from core.domain.enums import ReviewAction, TaskKind, TaskStatus
    from core.domain.exceptions import TaskNotFoundError
    from core.domain.state_machine import transition
    from core.schemas.telegram import (
        CallbackPayload,
        KindSelectPayload,
        ProjectSelectPayload,
    )
    from core.utils.ids import parse_uuid
    from db.models.task_item import TaskItem
    from db.models.telegram_review_session import TelegramReviewSession
    from db.repositories.project_repo import ProjectRepository
    from db.repositories.review_session_repo import ReviewSessionRepository
    from db.repositories.task_item_repo import TaskItemRepository
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
            repo = TaskItemRepository(session)
            tasks = await repo.list_by_status(TaskStatus.PROPOSED)
            if not tasks:
                await message.answer("✅ Inbox is empty! No pending proposals.")
                return
            lines = [f"📬 <b>Pending proposals ({len(tasks)}):</b>"]
            for t in tasks[:10]:
                lines.append(f"  • {t.normalized_title or t.raw_text}")
            await message.answer("\n".join(lines))

    @dp.message(Command("today"))
    async def cmd_today(message: Message):
        factory = get_session_factory()
        async with factory() as session:
            repo = TaskItemRepository(session)
            tasks = await repo.list_active_routed(limit=10)
            if not tasks:
                await message.answer("📭 No active tasks routed today.")
                return
            lines = [f"📋 <b>Active tasks ({len(tasks)}):</b>"]
            for t in tasks:
                lines.append(f"  • {t.normalized_title or t.raw_text}")
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
            repo = TaskItemRepository(session)
            lines = ["📊 <b>Task Statistics:</b>"]
            for status in TaskStatus:
                tasks = await repo.list_by_status(status)
                if tasks:
                    lines.append(f"  {status}: {len(tasks)}")
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

    async def _get_task_and_session(
        task_short_id: str, db_session
    ) -> tuple[TaskItem, TelegramReviewSession | None]:
        task_repo = TaskItemRepository(db_session)
        session_repo = ReviewSessionRepository(db_session)
        task_uuid = parse_uuid(task_short_id)
        task = await task_repo.get_by_id(task_uuid)
        if task is None:
            raise TaskNotFoundError(f"Task not found: {task_short_id}")
        review_session = await session_repo.get_active_by_task(task_uuid)
        return task, review_session

    @dp.callback_query(F.data.startswith("confirm:"))
    async def handle_confirm(callback: CallbackQuery):
        payload = CallbackPayload.decode(callback.data)
        factory = get_session_factory()
        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

        async with factory() as session:
            from apps.api.services.revision_service import RevisionService
            from core.schemas.llm import TaskClassificationResult

            task_repo = TaskItemRepository(session)
            session_repo = ReviewSessionRepository(session)

            try:
                task, review_session = await _get_task_and_session(payload.task_id, session)
            except TaskNotFoundError:
                await callback.answer("Task not found!", show_alert=True)
                return

            if task.status != TaskStatus.PROPOSED:
                await callback.answer("Task already processed.", show_alert=True)
                return

            # Get project info for routing
            project_repo = ProjectRepository(session)
            project = await project_repo.get_by_id(task.project_id) if task.project_id else None

            # Move task in Google Tasks
            gtasks = GoogleTasksService(settings.google_credentials_file)
            new_gtask_id = task.current_google_task_id
            new_tasklist_id = task.current_google_tasklist_id

            if project and project.google_tasklist_id != task.source_google_tasklist_id:
                try:
                    moved = gtasks.move_task(
                        task.current_google_tasklist_id or task.source_google_tasklist_id,
                        task.current_google_task_id or task.source_google_task_id,
                        project.google_tasklist_id,
                    )
                    new_gtask_id = moved.id
                    new_tasklist_id = moved.tasklist_id
                    # Patch title if normalized
                    if task.normalized_title and task.normalized_title != task.raw_text:
                        gtasks.patch_task(
                            new_tasklist_id, new_gtask_id, title=task.normalized_title
                        )
                except Exception as e:
                    logger.warning("google_tasks_move_failed", error=str(e))

            from core.utils.datetime import utcnow

            task.status = transition(task.status, TaskStatus.CONFIRMED)
            task.confirmed_at = utcnow()
            task.current_google_task_id = new_gtask_id
            task.current_google_tasklist_id = new_tasklist_id
            task.is_processed = True
            task.status = transition(TaskStatus.CONFIRMED, TaskStatus.ROUTED)
            await task_repo.save(task)

            if review_session:
                review_session.status = "resolved"
                review_session.resolved_at = utcnow()
                await session_repo.save(review_session)

            # Revision
            revision_svc = RevisionService(session)
            cls_result = TaskClassificationResult(
                kind=task.kind or "task",
                normalized_title=task.normalized_title or task.raw_text,
                confidence=task.confidence_band or "medium",
                next_action=task.next_action,
            )
            await revision_svc.create_decision_revision(
                task_item_id=task.id,
                raw_text=task.raw_text,
                decision=ReviewAction.CONFIRM,
                classification=cls_result,
                project_id=task.project_id,
            )
            await session.commit()

        await callback.answer("✅ Task confirmed and routed!")
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ <b>Confirmed and routed.</b>"
        )

        async with factory() as session:
            queue_svc = _queue_service(session, tg)
            await queue_svc.send_next()

    @dp.callback_query(F.data.startswith("discard:"))
    async def handle_discard(callback: CallbackQuery):
        payload = CallbackPayload.decode(callback.data)
        factory = get_session_factory()
        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

        async with factory() as session:
            from apps.api.services.revision_service import RevisionService
            from core.schemas.llm import TaskClassificationResult
            from core.utils.datetime import utcnow

            task_repo = TaskItemRepository(session)
            session_repo = ReviewSessionRepository(session)

            try:
                task, review_session = await _get_task_and_session(payload.task_id, session)
            except TaskNotFoundError:
                await callback.answer("Task not found!", show_alert=True)
                return

            task.status = transition(task.status, TaskStatus.DISCARDED)
            task.is_processed = True
            await task_repo.save(task)

            if review_session:
                review_session.status = "resolved"
                review_session.resolved_at = utcnow()
                await session_repo.save(review_session)

            revision_svc = RevisionService(session)
            cls_result = TaskClassificationResult(
                kind=task.kind or "task",
                normalized_title=task.normalized_title or task.raw_text,
                confidence=task.confidence_band or "medium",
            )
            await revision_svc.create_decision_revision(
                task_item_id=task.id,
                raw_text=task.raw_text,
                decision=ReviewAction.DISCARD,
                classification=cls_result,
                project_id=task.project_id,
            )
            await session.commit()

        await callback.answer("🗑 Task discarded.")
        await callback.message.edit_text(callback.message.text + "\n\n🗑 <b>Discarded.</b>")

        async with factory() as session:
            queue_svc = _queue_service(session, tg)
            await queue_svc.send_next()

    @dp.callback_query(F.data.startswith("change_project:"))
    async def handle_change_project(callback: CallbackQuery):
        payload = CallbackPayload.decode(callback.data)
        factory = get_session_factory()
        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

        async with factory() as session:
            task_repo = TaskItemRepository(session)
            project_repo = ProjectRepository(session)

            task_uuid = parse_uuid(payload.task_id)
            task = await task_repo.get_by_id(task_uuid)
            projects = await project_repo.list_active()

            current_project_name = None
            if task and task.project_id:
                current_project = await project_repo.get_by_id(task.project_id)
                if current_project:
                    current_project_name = current_project.name

        project_list = [(p.name, p.slug) for p in projects]
        task_title = task.normalized_title or task.raw_text if task else None
        await tg.send_project_picker(
            task_id=payload.task_id,
            projects=project_list,
            task_title=task_title,
            current_project=current_project_name,
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("change_type:"))
    async def handle_change_type(callback: CallbackQuery):
        payload = CallbackPayload.decode(callback.data)
        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)
        await tg.send_kind_picker(task_id=payload.task_id)
        await callback.answer()

    @dp.callback_query(F.data.startswith("edit:"))
    async def handle_edit(callback: CallbackQuery):
        payload = CallbackPayload.decode(callback.data)
        factory = get_session_factory()

        async with factory() as session:
            session_repo = ReviewSessionRepository(session)
            try:
                task, review_session = await _get_task_and_session(payload.task_id, session)
            except TaskNotFoundError:
                await callback.answer("Task not found!", show_alert=True)
                return

            if review_session:
                review_session.status = "awaiting_edit"
                await session_repo.save(review_session)
                await session.commit()

        await callback.answer()
        await callback.message.answer("✏️ Please send me the new title for this task:")

    @dp.callback_query(F.data.startswith("show_steps:"))
    async def handle_show_steps(callback: CallbackQuery):
        payload = CallbackPayload.decode(callback.data)
        factory = get_session_factory()

        async with factory() as session:
            from db.repositories.task_revision_repo import TaskRevisionRepository

            try:
                task, _ = await _get_task_and_session(payload.task_id, session)
            except TaskNotFoundError:
                await callback.answer("Task not found!", show_alert=True)
                return

            revision_repo = TaskRevisionRepository(session)
            revisions = await revision_repo.list_by_task(task.id)

        substeps: list[str] = []
        for rev in revisions:
            if rev.proposal_json and isinstance(rev.proposal_json.get("substeps"), list):
                substeps = rev.proposal_json["substeps"]
                break

        if substeps:
            lines = ["📋 <b>Sub-steps:</b>"]
            for i, step in enumerate(substeps, 1):
                lines.append(f"{i}. {step}")
            await callback.message.answer("\n".join(lines))
        else:
            await callback.message.answer("No sub-steps recorded for this task.")
        await callback.answer()

    @dp.callback_query(F.data.startswith("proj:"))
    async def handle_project_selection(callback: CallbackQuery):
        payload = ProjectSelectPayload.decode(callback.data)
        factory = get_session_factory()

        async with factory() as session:
            from apps.api.services.revision_service import RevisionService
            from core.schemas.llm import TaskClassificationResult

            task_repo = TaskItemRepository(session)
            project_repo = ProjectRepository(session)

            try:
                task_uuid = parse_uuid(payload.task_id)
            except ValueError:
                await callback.answer("Invalid task.", show_alert=True)
                return

            task = await task_repo.get_by_id(task_uuid)
            if task is None:
                await callback.answer("Task not found!", show_alert=True)
                return

            project = await project_repo.get_by_slug(payload.project_slug)
            if project:
                task.project_id = project.id
                await task_repo.save(task)

                revision_svc = RevisionService(session)
                cls_result = TaskClassificationResult(
                    kind=task.kind or "task",
                    normalized_title=task.normalized_title or task.raw_text,
                    confidence=task.confidence_band or "medium",
                    next_action=task.next_action,
                )
                await revision_svc.create_decision_revision(
                    task_item_id=task.id,
                    raw_text=task.raw_text,
                    decision=ReviewAction.CHANGE_PROJECT,
                    classification=cls_result,
                    project_id=project.id,
                )

                await session.commit()
                await callback.answer(f"Project changed to {project.name}")
            else:
                await callback.answer("Project not found.", show_alert=True)

    @dp.callback_query(F.data.startswith("kind:"))
    async def handle_kind_selection(callback: CallbackQuery):
        payload = KindSelectPayload.decode(callback.data)
        factory = get_session_factory()

        async with factory() as session:
            from apps.api.services.revision_service import RevisionService
            from core.schemas.llm import TaskClassificationResult

            task_repo = TaskItemRepository(session)

            try:
                task_uuid = parse_uuid(payload.task_id)
            except ValueError:
                await callback.answer("Invalid task.", show_alert=True)
                return

            task = await task_repo.get_by_id(task_uuid)
            if task is None:
                await callback.answer("Task not found!", show_alert=True)
                return

            try:
                new_kind = TaskKind(payload.kind)
            except ValueError:
                await callback.answer("Invalid task kind.", show_alert=True)
                return

            task.kind = new_kind
            await task_repo.save(task)

            revision_svc = RevisionService(session)
            cls_result = TaskClassificationResult(
                kind=new_kind,
                normalized_title=task.normalized_title or task.raw_text,
                confidence=task.confidence_band or "medium",
                next_action=task.next_action,
            )
            await revision_svc.create_decision_revision(
                task_item_id=task.id,
                raw_text=task.raw_text,
                decision=ReviewAction.CHANGE_TYPE,
                classification=cls_result,
                project_id=task.project_id,
                final_kind=new_kind,
            )

            await session.commit()
            await callback.answer(f"Type changed to {payload.kind}")

    # ── Text message handler (for edit flow) ─────────────────────────────────

    @dp.message(F.text & ~F.text.startswith("/"))
    async def handle_text_message(message: Message):
        """Handle free-text messages – used for the edit title flow."""
        import html as html_mod

        chat_id = str(message.chat.id)
        factory = get_session_factory()

        async with factory() as session:
            from apps.api.services.revision_service import RevisionService
            from core.schemas.llm import TaskClassificationResult

            session_repo = ReviewSessionRepository(session)
            task_repo = TaskItemRepository(session)
            pending = await session_repo.get_pending_edit_by_chat(chat_id)

            if pending is None:
                return  # Not in an edit flow, ignore

            task = await task_repo.get_by_id(pending.task_item_id)
            if task is None:
                return

            new_title = message.text.strip()
            task.normalized_title = new_title[:500]
            await task_repo.save(task)

            revision_svc = RevisionService(session)
            cls_result = TaskClassificationResult(
                kind=task.kind or "task",
                normalized_title=new_title[:500],
                confidence=task.confidence_band or "medium",
                next_action=task.next_action,
            )
            await revision_svc.create_decision_revision(
                task_item_id=task.id,
                raw_text=task.raw_text,
                decision=ReviewAction.EDIT,
                classification=cls_result,
                project_id=task.project_id,
                user_notes=f"Title changed to: {new_title[:500]}",
            )

            pending.status = "pending"  # Back to normal pending
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
    polling_task: asyncio.Task | None = None
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
        daily_review_cron=settings.daily_review_cron,
        project_sync_cron=settings.project_sync_cron,
        timezone=settings.timezone,
        poll_job=run_inbox_poll,
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
