"""Security helpers: headers, rate limiting, and audit hooks."""

from __future__ import annotations

from typing import Callable

from flask import g, make_response, request
from flask_login import current_user
from flask_limiter.errors import RateLimitExceeded

from clinic_app.auth import requires
from clinic_app.extensions import limiter
from clinic_app.services.audit import audit_rate_limit, write_event


def require_permission(scope: str, *, no_store: bool = True) -> Callable:
    """Backward-compatible wrapper for legacy decorators."""

    return requires(scope, no_store=no_store)


def user_has_permission(user, scope: str) -> bool:
    if user is None:
        return False
    return getattr(user, "has_permission", lambda code: False)(scope)


def init_security(app) -> None:
    protected_blueprints = (
        "patients",
        "payments",
        "reports",
        "palmer_plus",
        "core",
        "appointments",
        "appointment_move",
        "receipts",
        "expenses",
        "admin_settings",
        "images",
    )
    for bp_name in protected_blueprints:
        bp = app.blueprints.get(bp_name)
        if bp is not None:
            limiter.limit("60 per minute", methods=["POST", "PUT", "DELETE"])(bp)

    @limiter.request_filter
    def skip_rate_limits() -> bool:  # type: ignore[unused-local]
        return request.endpoint in {"static"}

    @app.before_request
    def sync_current_user() -> None:
        g.nostore = False
        g.current_user = current_user if current_user.is_authenticated else None

    @app.after_request
    def apply_headers(response):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob: https://cdn.tailwindcss.com https://unpkg.com; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "connect-src 'self' https://unpkg.com https://fonts.googleapis.com https://fonts.gstatic.com;",
        )
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        if getattr(g, "nostore", False):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit(exc: RateLimitExceeded):  # type: ignore[override]
        audit_rate_limit(request.endpoint or "global")
        return make_response("Too Many Requests", 429)


def record_login(user, *, success: bool) -> None:
    if success and user:
        write_event(user.id, "login", meta={"username": user.username})
    else:
        actor = getattr(user, "id", None)
        write_event(actor, "login_failed", result="denied", meta={"username": request.form.get("username", "")})


def record_logout(user) -> None:
    if user:
        write_event(user.id, "logout", meta={"username": user.username})
