from __future__ import annotations

from fastapi import FastAPI

from apps.admin.main import app as admin_app
from apps.admin.main import create_admin_app
from apps.api.main import app as public_app


def _paths(app: FastAPI) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


class TestAdminSplit:
    def test_create_admin_app_returns_fastapi(self):
        app = create_admin_app()
        assert isinstance(app, FastAPI)

    def test_admin_app_has_admin_routes_and_health(self):
        paths = _paths(admin_app)
        assert any(path.startswith("/admin") for path in paths)
        assert "/health/live" in paths

    def test_public_app_excludes_admin_ui_and_admin_api_routes(self):
        paths = _paths(public_app)
        assert "/admin/ui/dashboard" not in paths
        assert "/admin/api/tasks" not in paths
        assert "/admin/" not in paths

    def test_public_app_keeps_scheduler_admin_and_miniapp_routes(self):
        paths = _paths(public_app)
        assert "/admin/sync-now" in paths
        assert "/api/app/review/queue" in paths
