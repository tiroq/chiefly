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
from apps.api.workers.processing_worker import run_processing
from apps.api.workers.project_sync_worker import run_project_sync
from apps.api.workers.sync_worker import run_sync

logger = get_logger(__name__)


def _build_telegram_dispatcher():
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    from apps.api.telegram import register_all_routers

    dp = Dispatcher(storage=MemoryStorage())
    register_all_routers(dp)
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

        from apps.api.telegram.commands import BOT_COMMANDS

        await bot.set_my_commands(BOT_COMMANDS)

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

    # Run project sync in the background on startup so the server is available immediately
    async def _startup_project_sync() -> None:
        try:
            await run_project_sync()
            logger.info("project_sync_startup_completed")
        except Exception as e:
            logger.warning("project_sync_startup_failed", error=str(e))

    asyncio.create_task(_startup_project_sync())

    try:
        from apps.api.services.review_pause import load_pause_state

        factory_for_pause = get_session_factory()
        async with factory_for_pause() as pause_session:
            await load_pause_state(pause_session)
        logger.info("pause_state_loaded")
    except Exception as e:
        logger.warning("pause_state_load_failed", error=str(e))

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
