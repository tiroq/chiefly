"""
Admin authentication: token-based auth with signed cookie, login/logout routes,
and HTMX-aware exception handler.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

from apps.api.logging import get_logger

logger = get_logger(__name__)

COOKIE_NAME = "admin_session"


def is_htmx(request: Request) -> bool:
    """Return True when the request originates from HTMX (HX-Request header)."""
    return request.headers.get("HX-Request") == "true"


def is_htmx_boosted(request: Request) -> bool:
    """Return True when the request is from HTMX with hx-boost (HX-Boosted header).
    
    hx-boost requests expect the full page response, not just partials.
    """
    return request.headers.get("HX-Boosted") == "true"


def require_admin(admin_token: str) -> Callable[..., object]:
    """Return a FastAPI dependency that validates the admin session cookie.

    On invalid/missing cookie the dependency raises HTTP 303 → /admin/login.
    """
    serializer = URLSafeSerializer(admin_token)

    async def dependency(request: Request) -> None:
        cookie = request.cookies.get(COOKIE_NAME)
        if cookie is None:
            raise HTTPException(
                status_code=303,
                headers={"Location": "/admin/login"},
            )
        try:
            serializer.loads(cookie)
        except BadSignature:
            raise HTTPException(
                status_code=303,
                headers={"Location": "/admin/login"},
            )

    return dependency


def create_login_router(admin_token: str) -> APIRouter:
    """Create an APIRouter with login/logout routes (no auth dependency)."""
    router = APIRouter(tags=["admin-auth"])
    serializer = URLSafeSerializer(admin_token)

    @router.get("/admin/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        error = request.query_params.get("error")
        error_html = ""
        if error:
            error_html = (
                '<p style="color:#dc2626;margin-bottom:1rem;">'
                "Incorrect token. Please try again.</p>"
            )
        html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Admin Login — Chiefly</title>
  <style>
    body {{ font-family: system-ui, sans-serif; display: flex;
           justify-content: center; align-items: center; min-height: 100vh;
           margin: 0; background: #f3f4f6; }}
    .card {{ background: #fff; padding: 2rem; border-radius: 0.5rem;
             box-shadow: 0 1px 3px rgba(0,0,0,.1); max-width: 24rem; width: 100%; }}
    h1 {{ margin: 0 0 1.5rem; font-size: 1.25rem; }}
    input[type="password"] {{ width: 100%; padding: 0.5rem; margin-bottom: 1rem;
                              border: 1px solid #d1d5db; border-radius: 0.25rem;
                              box-sizing: border-box; }}
    button {{ width: 100%; padding: 0.5rem; background: #2563eb; color: #fff;
              border: none; border-radius: 0.25rem; cursor: pointer;
              font-size: 1rem; }}
    button:hover {{ background: #1d4ed8; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Chiefly Admin</h1>
    {error_html}
    <form method="post" action="/admin/login">
      <input type="password" name="token" placeholder="Admin token" required autofocus>
      <button type="submit">Sign in</button>
    </form>
  </div>
</body>
</html>"""
        return HTMLResponse(content=html)

    @router.post("/admin/login")
    async def login_submit(request: Request) -> Response:
        form = await request.form()
        token = form.get("token", "")
        if token != admin_token:
            logger.warning("admin_login_failed")
            return RedirectResponse(url="/admin/login?error=1", status_code=303)
        signed = serializer.dumps({"authenticated": True})
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie(
            key=COOKIE_NAME,
            value=signed,
            httponly=True,
            samesite="lax",
        )
        logger.info("admin_login_success")
        return response

    @router.post("/admin/logout")
    async def logout(request: Request) -> Response:
        response = RedirectResponse(url="/admin/login", status_code=303)
        response.delete_cookie(key=COOKIE_NAME)
        logger.info("admin_logout")
        return response

    return router


async def htmx_exception_handler(request: Request, exc: Exception) -> Response:
    """HTMX-aware exception handler.

    For HX-Request: true  → return an HTML fragment (no <html> wrapper).
    For normal requests   → return a redirect or full HTML error page.
    """
    if is_htmx(request):
        # Return a small fragment that HTMX can swap in
        fragment = (
            f'<div class="error-toast" role="alert">'
            f"Session expired. "
            f'<a href="/admin/login">Log in again</a>.'
            f"</div>"
        )
        return HTMLResponse(content=fragment, status_code=200)

    # Normal browser request — honour Location header if present
    http_exc = exc if isinstance(exc, HTTPException) else None
    headers = getattr(exc, "headers", None) or {}
    location = headers.get("Location") if isinstance(headers, dict) else None
    if location:
        return RedirectResponse(url=location, status_code=303)

    status_code = http_exc.status_code if http_exc else 500
    detail = http_exc.detail if http_exc else "An error occurred."
    return HTMLResponse(
        content=(
            "<!DOCTYPE html><html><body>"
            f"<h1>Error {status_code}</h1>"
            f"<p>{detail}</p>"
            f'<a href="/admin/login">Back to login</a>'
            "</body></html>"
        ),
        status_code=status_code,
    )
