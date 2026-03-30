from __future__ import annotations

import html as html_mod
from importlib import import_module

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BotCommand, Message

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.review_queue_service import SendNextResult
from apps.api.services.review_pause import load_pause_state, toggle_review_pause
from apps.api.services.telegram_service import TelegramService
from apps.api.telegram.keyboards import (
    backlog_keyboard,
    main_menu_keyboard,
    queue_summary_keyboard,
    settings_keyboard,
    today_keyboard,
)
from core.domain.enums import WorkflowStatus
from db.repositories.project_repo import ProjectRepository
from db.repositories.review_session_repo import ReviewSessionRepository
from db.repositories.task_record_repo import TaskRecordRepository
from db.session import get_session_factory

logger = get_logger(__name__)

command_router = Router(name="commands")

BOT_COMMANDS = [
    BotCommand(command="menu", description="Show main menu"),
    BotCommand(command="next", description="Next review item"),
    BotCommand(command="backlog", description="Show review queue"),
    BotCommand(command="today", description="Today's tasks"),
    BotCommand(command="projects", description="List projects"),
    BotCommand(command="pause", description="Pause/resume review"),
    BotCommand(command="review", description="Trigger daily review"),
    BotCommand(command="settings", description="Bot settings"),
    BotCommand(command="stats", description="Task statistics"),
    BotCommand(command="help", description="Show help"),
]


def _queue_service(session, tg):
    mod = import_module("apps.api.services.review_queue_service")
    return mod.ReviewQueueService(session, tg)


# ── /start ────────────────────────────────────────────────────────────────────


@command_router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Hi! I'm <b>Chiefly</b>, your AI Chief of Staff.\n\n"
        "I process tasks from your Google Tasks default tasklist and help you review them here.\n\n"
        "Use the menu below or type /help for commands.",
        reply_markup=main_menu_keyboard(),
    )


# ── /menu ─────────────────────────────────────────────────────────────────────


@command_router.message(Command("menu"))
async def cmd_menu(message: Message):
    await message.answer("📋 Main menu", reply_markup=main_menu_keyboard())


# ── /help ─────────────────────────────────────────────────────────────────────


@command_router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "<b>Chiefly Commands</b>\n\n"
        "/menu — main menu\n"
        "/next — next review item\n"
        "/backlog — review queue overview\n"
        "/today — today's tasks\n"
        "/projects — list projects\n"
        "/pause — pause/resume review queue\n"
        "/review — trigger daily review\n"
        "/draft — draft a follow-up message\n"
        "/settings — bot settings\n"
        "/stats — task statistics\n"
        "/help — this help text",
        reply_markup=main_menu_keyboard(),
    )


# ── /pause ────────────────────────────────────────────────────────────────────


@command_router.message(Command("pause"))
async def cmd_pause(message: Message):
    factory = get_session_factory()
    async with factory() as session:
        paused = await toggle_review_pause(session)
    if paused:
        await message.answer("⏸ Review queue paused. Send /pause again to resume.")
        return
    await message.answer("▶️ Review queue resumed.")


# ── /inbox ────────────────────────────────────────────────────────────────────


@command_router.message(Command("inbox"))
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
            lines.append(f"  • {html_mod.escape(title)}")
        await message.answer("\n".join(lines))


# ── /today ────────────────────────────────────────────────────────────────────


@command_router.message(Command("today"))
async def cmd_today(message: Message):
    factory = get_session_factory()
    async with factory() as session:
        repo = TaskRecordRepository(session)

        applied_rows = await repo.list_filtered(
            processing_status=WorkflowStatus.APPLIED,
            limit=10,
            offset=0,
        )
        awaiting_rows = await repo.list_filtered(
            processing_status=WorkflowStatus.AWAITING_REVIEW,
            limit=5,
            offset=0,
        )

    if not applied_rows and not awaiting_rows:
        await message.answer("📭 No active tasks today.", reply_markup=today_keyboard())
        return

    lines = ["📅 <b>Today</b>"]

    if applied_rows:
        lines.append("")
        lines.append("<b>Top focus:</b>")
        for i, (record, snapshot) in enumerate(applied_rows, 1):
            payload = snapshot.payload if snapshot and snapshot.payload else {}
            title = payload.get("title") or str(record.stable_id)
            lines.append(f"  {i}. {html_mod.escape(title)}")

    if awaiting_rows:
        lines.append("")
        lines.append("<b>Awaiting review:</b>")
        for record, snapshot in awaiting_rows:
            payload = snapshot.payload if snapshot and snapshot.payload else {}
            title = payload.get("title") or str(record.stable_id)
            lines.append(f"  • {html_mod.escape(title)}")

    await message.answer("\n".join(lines), reply_markup=today_keyboard())


# ── /projects ─────────────────────────────────────────────────────────────────


@command_router.message(Command("projects"))
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
            line = f"  • <b>{html_mod.escape(p.name)}</b> ({p.project_type})"
            if p.description:
                line += f"\n    <i>{html_mod.escape(p.description[:80])}</i>"
            lines.append(line)
        await message.answer("\n".join(lines))


# ── /review ───────────────────────────────────────────────────────────────────


@command_router.message(Command("review"))
async def cmd_review(message: Message):
    from apps.api.workers.daily_review_worker import run_daily_review

    await message.answer("🔄 Generating daily review...")
    await run_daily_review()


# ── /stats ────────────────────────────────────────────────────────────────────


@command_router.message(Command("stats"))
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


# ── /next ─────────────────────────────────────────────────────────────────────


@command_router.message(Command("next"))
async def cmd_next(message: Message):
    settings = get_settings()
    factory = get_session_factory()
    tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)

    try:
        async with factory() as session:
            queue_svc = _queue_service(session, tg)
            result = await queue_svc.send_next()

        if result == SendNextResult.SENT:
            pass
        elif result == SendNextResult.PAUSED:
            await message.answer("⏸ Review queue is paused. Use /pause to resume.")
        elif result == SendNextResult.ACTIVE_EXISTS:
            await message.answer("📋 There's already an active review. Please finish it first.")
        elif result == SendNextResult.QUEUE_EMPTY:
            await message.answer("✅ No more items in the review queue.")
    finally:
        await tg.aclose()


# ── /backlog ──────────────────────────────────────────────────────────────────


@command_router.message(Command("backlog"))
async def cmd_backlog(message: Message):
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
        await message.answer("✅ Queue is empty. Nothing to review.")
        return

    lines = [f"📋 <b>Pending review backlog: {total_queued} items</b>"]
    if has_active:
        lines.append("🔵 1 item currently under review")
    lines.append("")
    for i, title in enumerate(items, 1):
        lines.append(f"  {i}. {html_mod.escape(title)}")
    if total_queued > len(items):
        lines.append(f"  ... and {total_queued - len(items)} more")

    await message.answer("\n".join(lines), reply_markup=backlog_keyboard())


# ── /settings ─────────────────────────────────────────────────────────────────


@command_router.message(Command("settings"))
async def cmd_settings(message: Message):
    from apps.api.services.user_settings_service import get_user_settings

    factory = get_session_factory()
    async with factory() as session:
        user_settings = await get_user_settings(session)

    lines = [
        "⚙️ <b>Settings</b>",
        "",
        "<b>Review:</b>",
        f"  Auto-next: {'ON' if user_settings.get('auto_next') else 'OFF'}",
        f"  Batch size: {user_settings.get('batch_size', 1)}",
        f"  Paused: {'ON' if user_settings.get('paused') else 'OFF'}",
        "",
        "<b>Notifications:</b>",
        f"  Sync summary: {'ON' if user_settings.get('sync_summary') else 'OFF'}",
        f"  Daily brief: {'ON' if user_settings.get('daily_brief') else 'OFF'}",
        "",
        "<b>UX:</b>",
        f"  Show confidence: {'ON' if user_settings.get('show_confidence') else 'OFF'}",
        f"  Show raw input: {'ON' if user_settings.get('show_raw_input') else 'OFF'}",
        f"  Draft suggestions: {'ON' if user_settings.get('draft_suggestions') else 'OFF'}",
        f"  Ambiguity prompts: {'ON' if user_settings.get('ambiguity_prompts') else 'OFF'}",
    ]

    await message.answer(
        "\n".join(lines),
        reply_markup=settings_keyboard(user_settings),
    )


# ── /draft ────────────────────────────────────────────────────────────────────


@command_router.message(Command("draft"))
async def cmd_draft(message: Message):
    factory = get_session_factory()
    async with factory() as session:
        session_repo = ReviewSessionRepository(session)
        has_active = await session_repo.has_active_review()

    if not has_active:
        await message.answer("No active review item. Use /next to start reviewing.")
        return

    await message.answer(
        "💬 Draft message generation is available during review.\n"
        "Press <b>Draft Message</b> on the review card."
    )


# ── Reply keyboard text handlers ─────────────────────────────────────────────
# These catch button presses from the reply keyboard and route to commands


@command_router.message(F.text == "📋 Review Queue")
async def menu_review_queue(message: Message):
    await cmd_backlog(message)


@command_router.message(F.text == "▶️ Next Item")
async def menu_next_item(message: Message):
    await cmd_next(message)


@command_router.message(F.text == "📬 Backlog")
async def menu_backlog(message: Message):
    await cmd_backlog(message)


@command_router.message(F.text == "📅 Today")
async def menu_today(message: Message):
    await cmd_today(message)


@command_router.message(F.text == "📁 Projects")
async def menu_projects(message: Message):
    await cmd_projects(message)


@command_router.message(F.text == "✏️ Draft")
async def menu_draft(message: Message):
    await cmd_draft(message)


@command_router.message(F.text == "⚙️ Settings")
async def menu_settings(message: Message):
    await cmd_settings(message)


@command_router.message(F.text == "❓ Help")
async def menu_help(message: Message):
    await cmd_help(message)
