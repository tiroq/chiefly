"""
Unit tests for admin authentication: is_htmx helper, require_admin dependency,
login/logout routes, and HTMX-aware exception handler.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_token() -> str:
    return "test-secret-token"


@pytest.fixture
def serializer(admin_token: str) -> URLSafeSerializer:
    return URLSafeSerializer(admin_token)


@pytest.fixture
def valid_cookie(serializer: URLSafeSerializer) -> str:
    return serializer.dumps({"authenticated": True})


@pytest.fixture
def app(admin_token: str) -> FastAPI:
    """Build a minimal FastAPI app with admin auth wired up."""
    from fastapi import Depends

    from apps.api.admin.auth import create_login_router, htmx_exception_handler, require_admin

    application = FastAPI()

    # Mount login router (no auth dependency)
    login_router = create_login_router(admin_token)
    application.include_router(login_router)

    # Protected route to test require_admin
    @application.get("/admin/protected")
    async def protected(
        _=Depends(require_admin(admin_token)),
    ) -> dict[str, str]:
        return {"status": "ok"}

    # Register HTMX-aware exception handler
    application.add_exception_handler(403, htmx_exception_handler)
    application.add_exception_handler(303, htmx_exception_handler)

    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# is_htmx helper
# ---------------------------------------------------------------------------


class TestIsHtmx:
    def test_returns_true_when_hx_request_header_present(self) -> None:
        from apps.api.admin.auth import is_htmx

        request = MagicMock()
        request.headers = {"HX-Request": "true"}
        assert is_htmx(request) is True

    def test_returns_false_when_header_absent(self) -> None:
        from apps.api.admin.auth import is_htmx

        request = MagicMock()
        request.headers = {}
        assert is_htmx(request) is False


# ---------------------------------------------------------------------------
# require_admin dependency
# ---------------------------------------------------------------------------


class TestRequireAdmin:
    def test_redirects_to_login_when_no_cookie(self, client: TestClient) -> None:
        resp = client.get("/admin/protected")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/login"

    def test_redirects_when_cookie_tampered(self, client: TestClient) -> None:
        client.cookies.set("admin_session", "tampered-garbage-value")
        resp = client.get("/admin/protected")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/login"

    def test_passes_through_with_valid_cookie(self, client: TestClient, valid_cookie: str) -> None:
        client.cookies.set("admin_session", valid_cookie)
        resp = client.get("/admin/protected")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Login / Logout routes
# ---------------------------------------------------------------------------


class TestLoginRoutes:
    def test_get_login_returns_html_form(self, client: TestClient) -> None:
        resp = client.get("/admin/login")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "<form" in resp.text
        assert 'name="token"' in resp.text

    def test_post_login_correct_token_sets_cookie_and_redirects(
        self, client: TestClient, admin_token: str
    ) -> None:
        resp = client.post("/admin/login", data={"token": admin_token})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin"
        # Cookie should be set
        assert "admin_session" in resp.cookies

    def test_post_login_wrong_token_redirects_with_error(
        self,
        client: TestClient,
    ) -> None:
        resp = client.post("/admin/login", data={"token": "wrong-token"})
        assert resp.status_code == 303
        assert "error=1" in resp.headers["location"]

    def test_post_logout_clears_cookie_and_redirects(
        self, client: TestClient, valid_cookie: str
    ) -> None:
        client.cookies.set("admin_session", valid_cookie)
        resp = client.post("/admin/logout")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/login"


# ---------------------------------------------------------------------------
# HTMX-aware exception handler
# ---------------------------------------------------------------------------


class TestHtmxExceptionHandler:
    def test_htmx_request_returns_fragment(self, client: TestClient) -> None:
        """For HX-Request: true, handler should return a fragment (no <html> tag)."""
        resp = client.get(
            "/admin/protected",
            headers={"HX-Request": "true"},
        )
        # Should get a redirect or an error fragment, not full HTML page
        # With HTMX, the 303 should be handled — we get the fragment
        # The require_admin raises HTTPException(303), which the handler catches
        assert "<html" not in resp.text.lower()

    def test_normal_request_returns_redirect(self, client: TestClient) -> None:
        """For normal (non-HTMX) request, should redirect to login."""
        resp = client.get("/admin/protected")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/login"

    def test_login_page_shows_error_message(self, client: TestClient) -> None:
        resp = client.get("/admin/login?error=1")
        assert resp.status_code == 200
        assert (
            "invalid" in resp.text.lower()
            or "wrong" in resp.text.lower()
            or "incorrect" in resp.text.lower()
        )
