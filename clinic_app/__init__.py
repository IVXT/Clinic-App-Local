"""Clinic app package exposing the Flask application factory."""

from __future__ import annotations

import os
from pathlib import Path
from datetime import timedelta

from flask import Flask, jsonify
from flask_wtf.csrf import CSRFError

from .blueprints import register_blueprints
from .extensions import init_extensions
from .services.i18n import SUPPORTED_LOCALES, register_jinja
from .services.ui import register_ui
from .services.security import init_security
from .services.auto_migrate import auto_upgrade
from .services.bootstrap import ensure_base_tables
from .services.admin_guard import ensure_admin_exists
from .cli import register_cli
from .auth import login_manager

APP_HOST = "127.0.0.1"
APP_PORT = 8080


def _data_root(base_dir: Path, override: Path | None = None) -> Path:
    root = override if override else base_dir / "data"
    root.mkdir(parents=True, exist_ok=True)
    for sub in (
        "patient_images",
        "backups",
        "exports",
        "audit",
        "audit/archive",
        "import_reports",
        "receipts",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def create_app() -> Flask:
    base_dir = Path(__file__).resolve().parent.parent
    template_folder = base_dir / "templates"
    static_folder = base_dir / "static"
    db_override = os.getenv("CLINIC_DB_PATH")
    override_root = Path(db_override).parent if db_override else None
    data_root = _data_root(base_dir, override_root)

    app = Flask(
        __name__,
        template_folder=str(template_folder),
        static_folder=str(static_folder),
    )

    secret_key = os.getenv("CLINIC_SECRET_KEY")
    if not secret_key:
        secret_key = os.urandom(32)

    if db_override:
        db_path = Path(db_override)
    else:
        db_path = data_root / "app.db"

    default_locale = os.getenv("CLINIC_DEFAULT_LOCALE", "en").lower()
    if default_locale not in SUPPORTED_LOCALES:
        default_locale = "en"

    doctor_list = [
        doc.strip()
        for doc in os.getenv("CLINIC_DOCTORS", "Dr. Lina,Dr. Omar").split(",")
        if doc.strip()
    ]
    if not doctor_list:
        doctor_list = ["On Call"]

    app.config.update(
        SECRET_KEY=secret_key,
        SESSION_COOKIE_NAME="clinic_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SQLALCHEMY_ENGINE_OPTIONS={"connect_args": {"check_same_thread": False}},
        RATELIMIT_STORAGE_URI=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        DATA_ROOT=str(data_root),
        PALMER_PLUS_DB=str(db_path),
        DEFAULT_LOCALE=default_locale,
        LOCALE_COOKIE_NAME="lang",
        LOCALE_COOKIE_MAX_AGE=60 * 60 * 24 * 365,
        APPOINTMENT_SLOT_MINUTES=int(os.getenv("APPOINTMENT_SLOT_MINUTES", "30")),
        APPOINTMENT_CONFLICT_GRACE_MINUTES=int(os.getenv("APPOINTMENT_CONFLICT_GRACE_MINUTES", "5")),
        APPOINTMENT_DOCTORS=doctor_list,
        RECEIPT_SERIAL_PREFIX=os.getenv("RECEIPT_SERIAL_PREFIX", "R"),
        PDF_FONT_PATH=os.getenv(
            "PDF_FONT_PATH", str(base_dir / "static" / "fonts" / "DejaVuSans.ttf")
        ),
        # Optional Arabic font defaults (Cairo). Safe to remove or override.
        PDF_FONT_PATH_AR=os.getenv(
            "PDF_FONT_PATH_AR", str(base_dir / "static" / "fonts" / "Cairo-Regular.ttf")
        ),
        PDF_FONT_PATH_AR_BOLD=os.getenv(
            "PDF_FONT_PATH_AR_BOLD", str(base_dir / "static" / "fonts" / "Cairo-Bold.ttf")
        ),
        PDF_DEFAULT_ARABIC=os.getenv("PDF_DEFAULT_ARABIC", "cairo"),  # cairo|dejavu
    )

    register_jinja(app)
    register_ui(app)
    init_extensions(app)
    login_manager.init_app(app)
    register_blueprints(app)
    auto_upgrade(app)
    ensure_base_tables(Path(app.config["PALMER_PLUS_DB"]))
    ensure_admin_exists()
    init_security(app)
    register_cli(app)

    # Add CSRF error handling to catch CSRF validation failures
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        print(f"CSRF ERROR: {e}")
        return jsonify({"success": False, "errors": [f"CSRF validation failed: {str(e)}"]}), 400

    # Add general error handler to log all 400s that don't reach routes
    @app.errorhandler(400)
    def handle_bad_request(e):
        print(f"BAD REQUEST ERROR: {e}")
        return jsonify({"success": False, "errors": ["Bad request - check request format and CSRF token"]}), 400

    return app


__all__ = ["create_app", "APP_HOST", "APP_PORT"]
