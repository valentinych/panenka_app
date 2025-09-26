import json
from functools import wraps
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

bp = Blueprint("main", __name__)

AUTH_FILE = Path("auth.json")


class AuthFileMissingError(FileNotFoundError):
    """Raised when the auth.json file is missing."""


def load_credentials():
    if not AUTH_FILE.exists():
        raise AuthFileMissingError(
            "The auth.json file is missing. Please create it using the format described in README.md."
        )
    with AUTH_FILE.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    users = payload.get("users", [])
    return {user["login"]: user["password"] for user in users if "login" in user and "password" in user}


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("main.login"))
        return func(*args, **kwargs)

    return wrapper


@bp.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        login_code = request.form.get("login", "").strip()
        password_code = request.form.get("password", "").strip()

        if not login_code.isdigit() or len(login_code) != 3:
            error = "Login must be exactly three digits."
        elif not password_code.isdigit() or len(password_code) != 4:
            error = "Password must be exactly four digits."
        else:
            try:
                credentials = load_credentials()
            except AuthFileMissingError as exc:
                error = str(exc)
            else:
                stored_password = credentials.get(login_code)
                if stored_password and stored_password == password_code:
                    session["user_id"] = login_code
                    return redirect(url_for("main.dashboard"))
                error = "Invalid login or password."

        flash(error, "error")

    return render_template("login.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", login_code=session.get("user_id"))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))
