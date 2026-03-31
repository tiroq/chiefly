from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from apps.api.admin.auth import create_login_router, htmx_exception_handler
from apps.api.config import get_settings
from apps.api.logging import configure_logging, get_logger
from apps.api.routes import health
from apps.api.routes.admin_api import router as admin_api_router
from apps.api.routes.admin_ui import router as admin_ui_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    logger.info("starting_admin_app")
    yield
    logger.info("admin_app_shutdown")


def create_admin_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title="Chiefly Admin",
        description="Chiefly internal admin panel",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.mount("/static/admin", StaticFiles(directory="apps/api/static/admin"), name="admin_static")
    app.add_exception_handler(Exception, htmx_exception_handler)
    app.include_router(admin_ui_router, prefix="/admin")
    app.include_router(admin_api_router, prefix="/admin/api")
    app.include_router(create_login_router(settings.admin_token))

    return app


app = create_admin_app()
