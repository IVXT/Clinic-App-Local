"""Authentication helpers using Flask-Login and RBAC."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from flask import abort, g
from flask_login import LoginManager, current_user, login_required

from clinic_app.extensions import db
from clinic_app.models_rbac import User
from clinic_app.services.audit import audit_denied


login_manager = LoginManager()
login_manager.login_view = "auth.login"


@login_manager.user_loader
def _load_user(user_id: str) -> User | None:
    # Convert to string if it's an int (defensive coding)
    if isinstance(user_id, int):
        user_id = str(user_id)
    if not isinstance(user_id, str) or not user_id.strip():
        return None
    session = db.session()
    try:
        user = session.get(User, user_id.strip())
        if user and user.is_active:
            return user
        return None
    finally:
        session.close()


def requires(permission_code: str, *, no_store: bool = True) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator enforcing that the current user has the specified permission."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        @login_required
        def wrapped(*args: Any, **kwargs: Any):
            if no_store:
                g.nostore = True
            print(f"DEBUG: Checking permission '{permission_code}' for user {current_user.username if current_user.is_authenticated else 'None'}")
            print(f"DEBUG: User authenticated: {current_user.is_authenticated}")
            if current_user.is_authenticated:
                has_perm = current_user.has_permission(permission_code)
                print(f"DEBUG: User has permission '{permission_code}': {has_perm}")
                if not has_perm:
                    print(f"DEBUG: User roles: {[r.name for r in current_user.roles]}")
                    print(f"DEBUG: User permissions: {set().union(*[r.permissions for r in current_user.roles])}")
            if not current_user.is_authenticated or not current_user.has_permission(permission_code):
                audit_denied(permission_code, reason="forbidden")
                abort(403)
            return func(*args, **kwargs)

        return wrapped

    return decorator


def current_user_has(permission_code: str) -> bool:
    return current_user.is_authenticated and current_user.has_permission(permission_code)
