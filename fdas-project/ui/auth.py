"""Authentication blueprint — login, logout, and @login_required.

Uses Flask's built-in session handling with a single shared password
(hashed with werkzeug.security). Proportionate for a small local system
where facility fault data shouldn't be left wide open, but enterprise
SSO would be overkill.

Change the password:
    python -m ui.auth set-password
"""

from __future__ import annotations

import sys
import functools
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint("auth", __name__)

_CONFIG_PATH = Path(__file__).parent / "config.env"


def login_required(view):
    """Decorator that redirects unauthenticated users to /login."""
    @functools.wraps(view)
    def wrapped(**kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        password = request.form.get("password", "")
        stored_hash = current_app.config.get("FDAS_UI_PASSWORD_HASH", "")
        if stored_hash and check_password_hash(stored_hash, password):
            session["logged_in"] = True
            session.permanent = True
            next_url = request.args.get("next", url_for("dashboard.index"))
            return redirect(next_url)
        flash("Incorrect password.", "error")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


# ---- CLI helper: set-password ------------------------------------------------

def _set_password():
    """Interactive password setter — writes the hash to config.env."""
    import getpass

    password = getpass.getpass("New dashboard password: ")
    if not password:
        print("Password cannot be empty.")
        sys.exit(1)
    confirm = getpass.getpass("Confirm: ")
    if password != confirm:
        print("Passwords do not match.")
        sys.exit(1)

    new_hash = generate_password_hash(password)

    # Read existing config, replace or append the hash line.
    lines: list[str] = []
    found = False
    if _CONFIG_PATH.exists():
        for line in _CONFIG_PATH.read_text().splitlines():
            if line.startswith("FDAS_UI_PASSWORD_HASH="):
                lines.append(f"FDAS_UI_PASSWORD_HASH={new_hash}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"FDAS_UI_PASSWORD_HASH={new_hash}")

    _CONFIG_PATH.write_text("\n".join(lines) + "\n")
    print("Password updated. Restart the UI service to apply.")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "set-password":
        _set_password()
    else:
        print("Usage: python -m ui.auth set-password")
