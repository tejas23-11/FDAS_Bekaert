"""Flask application factory and entry point for the FDAS Operator UI.

Runs as an independent service alongside the pipeline and watchdog —
a crash here never affects detection or notification.

Usage:
    python -m ui.app                         # dev server on 0.0.0.0:5000
    python -m ui.app --port 8080             # custom port
"""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from flask import Flask

from backend.db import init_db

_CONFIG_PATH = Path(__file__).parent / "config.env"


def _load_config() -> dict[str, str]:
    """Load key=value pairs from config.env (if it exists)."""
    config: dict[str, str] = {}
    if _CONFIG_PATH.exists():
        for line in _CONFIG_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip()
    return config


def _ensure_config() -> dict[str, str]:
    """Create config.env with defaults if it doesn't exist yet."""
    if not _CONFIG_PATH.exists():
        secret_key = secrets.token_hex(32)
        # Default password: 'fdas' (operator should change via `python -m ui.auth set-password`)
        from werkzeug.security import generate_password_hash
        default_hash = generate_password_hash("fdas")
        _CONFIG_PATH.write_text(
            f"# FDAS Operator UI configuration (auto-generated)\n"
            f"# Change the password: python -m ui.auth set-password\n"
            f"FDAS_UI_SECRET_KEY={secret_key}\n"
            f"FDAS_UI_PASSWORD_HASH={default_hash}\n"
            f"FDAS_UI_PORT=5000\n"
        )
    return _load_config()


def create_app() -> Flask:
    """Application factory."""
    config = _ensure_config()

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.secret_key = config.get("FDAS_UI_SECRET_KEY", secrets.token_hex(32))

    # Store the password hash where auth.py can read it.
    app.config["FDAS_UI_PASSWORD_HASH"] = config.get("FDAS_UI_PASSWORD_HASH", "")

    # Initialize the database (safe to re-run — uses IF NOT EXISTS).
    init_db()

    # Register blueprints.
    from ui.auth import auth_bp
    from ui.views.dashboard import dashboard_bp
    from ui.views.events import events_bp
    from ui.views.upload import upload_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(upload_bp)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FDAS Operator UI")
    parser.add_argument("--port", type=int, default=None, help="Port to serve on (default: from config or 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    config = _load_config()
    port = args.port or int(config.get("FDAS_UI_PORT", "5000"))

    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=args.debug)
