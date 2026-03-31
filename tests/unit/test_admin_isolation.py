from __future__ import annotations

from fastapi import FastAPI

from apps.admin.main import app as admin_app
from apps.api.main import app as public_app


def _paths(app: FastAPI) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


class TestAdminIsolation:
    def test_public_app_has_no_admin_panel_paths(self):
        paths = _paths(public_app)
        assert not any(path.startswith("/admin/api/") for path in paths)
        assert not any(path.startswith("/admin/model-settings") for path in paths)
        assert not any(path.startswith("/admin/projects") for path in paths)

    def test_public_app_has_expected_public_paths(self):
        paths = _paths(public_app)
        assert "/health/live" in paths
        assert "/api/app/review/queue" in paths
        assert "/api/app/review/{stable_id}" in paths

    def test_admin_app_includes_admin_prefixed_paths(self):
        paths = _paths(admin_app)
        assert any(path.startswith("/admin") for path in paths)
        assert any(path.startswith("/admin/api") for path in paths)
        assert "/health/live" in paths
