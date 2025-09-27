import json
import os
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

bp = Blueprint("main", __name__)

AUTH_FILE = Path("auth.json")
AUTH_ENV_VAR = "AUTH_JSON"
AUTH_S3_BUCKET_ENV = "AUTH_JSON_S3_BUCKET"
AUTH_S3_KEY_ENV = "AUTH_JSON_S3_KEY"
AUTH_S3_BUCKET_FALLBACK_ENV = "AUTH_JSON_S3_BUCKET_NAME"
AUTH_S3_URI_ENV = "AUTH_JSON_S3_URI"
AUTH_JSON_URL_ENV = "AUTH_JSON_URL"
DEFAULT_S3_KEY = "auth.json"


class AuthFileMissingError(FileNotFoundError):
    """Raised when the auth.json file is missing."""


def _load_from_env():
    auth_payload = os.getenv(AUTH_ENV_VAR)
    if not auth_payload:
        return None
    try:
        payload = json.loads(auth_payload)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "AUTH_JSON environment variable contains invalid JSON."
        ) from exc
    return payload


def _load_from_file():
    if not AUTH_FILE.exists():
        raise AuthFileMissingError(
            "The auth.json file is missing. Please create it using the format described in README.md "
            "or configure the AUTH_JSON environment variable."
        )
    with AUTH_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def _parse_s3_reference(reference):
    if not reference:
        return None, None

    parsed = urlparse(reference)
    if parsed.scheme == "s3":
        bucket = parsed.netloc
        key = parsed.path.lstrip("/") or DEFAULT_S3_KEY
        return bucket or None, key

    if parsed.scheme in {"https", "http"}:
        host = parsed.netloc
        path = parsed.path.lstrip("/")
        if host.endswith(".s3.amazonaws.com"):
            bucket = host.split(".s3.amazonaws.com", 1)[0]
            return bucket or None, path or DEFAULT_S3_KEY
        if host == "s3.amazonaws.com" and path:
            parts = path.split("/", 1)
            if len(parts) == 2:
                bucket, key = parts
                return bucket or None, key or DEFAULT_S3_KEY
    return None, None


def _load_from_url(url):
    if not url:
        return None
    try:
        from urllib.request import urlopen
        from urllib.error import HTTPError, URLError
    except ImportError as exc:  # pragma: no cover - standard library always available
        raise ValueError("Unable to import urllib to download auth.json from URL.") from exc

    try:
        with urlopen(url) as response:
            raw_contents = response.read()
    except (HTTPError, URLError) as exc:
        raise ValueError(
            "Unable to download auth.json from the provided URL. Verify AUTH_JSON_URL and its accessibility."
        ) from exc

    if isinstance(raw_contents, bytes):
        raw_contents = raw_contents.decode("utf-8")

    try:
        return json.loads(raw_contents)
    except json.JSONDecodeError as exc:
        raise ValueError("auth.json file downloaded from URL contains invalid JSON.") from exc


def _load_from_s3():
    bucket_name = os.getenv(AUTH_S3_BUCKET_ENV) or os.getenv(AUTH_S3_BUCKET_FALLBACK_ENV)
    object_key = os.getenv(AUTH_S3_KEY_ENV, DEFAULT_S3_KEY)

    bucket_from_uri, key_from_uri = _parse_s3_reference(os.getenv(AUTH_S3_URI_ENV))
    if bucket_from_uri:
        bucket_name = bucket_from_uri
    if key_from_uri:
        object_key = key_from_uri

    if not bucket_name:
        return _load_from_url(os.getenv(AUTH_JSON_URL_ENV))

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise ValueError(
            "Loading credentials from S3 requires the boto3 package. Make sure it is installed or "
            "remove the AUTH_JSON_S3_BUCKET environment variable."
        ) from exc

    try:
        s3_client = boto3.client("s3")
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
    except (BotoCoreError, ClientError) as exc:
        raise ValueError(
            "Unable to download auth.json from S3. Verify the AUTH_JSON_S3_BUCKET and AUTH_JSON_S3_KEY "
            "values as well as your AWS credentials."
        ) from exc

    body = response.get("Body")
    if body is None:
        raise ValueError("Received an empty response when downloading auth.json from S3.")

    raw_contents = body.read()
    if isinstance(raw_contents, bytes):
        raw_contents = raw_contents.decode("utf-8")

    try:
        return json.loads(raw_contents)
    except json.JSONDecodeError as exc:
        raise ValueError("auth.json file stored in S3 contains invalid JSON.") from exc


def load_credentials():
    payload = _load_from_env()
    if payload is None:
        try:
            payload = _load_from_s3()
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    if payload is None:
        payload = _load_from_file()
    users = payload.get("users", [])
    users_by_login = {}
    for user in users:
        login = user.get("login")
        password = user.get("password")
        if not login or not password:
            continue
        users_by_login[login] = {
            "password": password,
            "name": user.get("name"),
        }

    return users_by_login


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
            except (AuthFileMissingError, ValueError) as exc:
                error = str(exc)
            else:
                user_record = credentials.get(login_code)
                if user_record and user_record["password"] == password_code:
                    session["user_id"] = login_code
                    session["user_name"] = user_record.get("name")
                    return redirect(url_for("main.dashboard"))
                error = "Invalid login or password."

        flash(error, "error")

    return render_template("login.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        login_code=session.get("user_id"),
        user_name=session.get("user_name"),
    )


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))
