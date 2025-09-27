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

DEFAULT_FALLBACK_USERS = [
    {
        "login": "888",
        "password": "6969",
        "name": "Integration Test Player",
    }
]


class AuthFileMissingError(FileNotFoundError):
    """Raised when the auth.json file is missing."""


def _get_sanitized_env(name):
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


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
    """Return (bucket, key) parsed from different S3 URI/URL formats."""

    if not reference:
        return None, None

    parsed = urlparse(reference)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.netloc or "").split("@")[-1]  # strip credentials if provided
    host = host.split(":")[0]  # strip port information
    path = parsed.path.lstrip("/")

    if scheme == "s3":
        bucket = host.strip()
        key = path or DEFAULT_S3_KEY
        return bucket or None, key

    if scheme in {"https", "http"} and host:
        host_lower = host.lower()

        # Virtual-hosted style URLs (bucket.s3.amazonaws.com, bucket.s3.us-east-1.amazonaws.com, bucket.s3-us-west-2.amazonaws.com)
        if host_lower.endswith(".amazonaws.com") and ".s3" in host_lower:
            for marker in (".s3.", ".s3-", ".s3.amazonaws.com"):
                if marker in host_lower:
                    bucket = host_lower.split(marker, 1)[0]
                    if bucket:
                        return bucket or None, path or DEFAULT_S3_KEY

        # Path-style URLs (s3.amazonaws.com/bucket/key, s3.us-east-1.amazonaws.com/bucket/key, s3-accelerate.amazonaws.com/bucket/key)
        path_style_hosts = {
            "s3.amazonaws.com",
            "s3-accelerate.amazonaws.com",
        }
        if host_lower in path_style_hosts or (
            host_lower.startswith("s3.") and host_lower.endswith(".amazonaws.com")
        ) or (
            host_lower.startswith("s3-") and host_lower.endswith(".amazonaws.com")
        ):
            if path:
                parts = path.split("/", 1)
                if parts[0]:
                    bucket = parts[0]
                    key = parts[1] if len(parts) == 2 else DEFAULT_S3_KEY
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
    import logging
    logger = logging.getLogger(__name__)
    
    bucket_name = _get_sanitized_env(AUTH_S3_BUCKET_ENV) or _get_sanitized_env(
        AUTH_S3_BUCKET_FALLBACK_ENV
    )
    object_key = _get_sanitized_env(AUTH_S3_KEY_ENV) or DEFAULT_S3_KEY
    
    logger.info(f"S3 Config - Bucket: {bucket_name}, Key: {object_key}")
    logger.info(f"Environment variables: AUTH_S3_BUCKET={_get_sanitized_env(AUTH_S3_BUCKET_ENV)}, AUTH_S3_KEY={_get_sanitized_env(AUTH_S3_KEY_ENV)}")

    bucket_from_uri, key_from_uri = _parse_s3_reference(_get_sanitized_env(AUTH_S3_URI_ENV))
    if bucket_from_uri:
        bucket_name = bucket_from_uri
        logger.info(f"Updated bucket from URI: {bucket_name}")
    if key_from_uri:
        object_key = key_from_uri
        logger.info(f"Updated key from URI: {object_key}")

    if not bucket_name:
        logger.info("No bucket name found, trying URL fallback")
        return _load_from_url(_get_sanitized_env(AUTH_JSON_URL_ENV))

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
        logger.info("boto3 imported successfully")
    except ImportError as exc:
        logger.error("boto3 not available")
        raise ValueError(
            "Loading credentials from S3 requires the boto3 package. Make sure it is installed or "
            "remove the AUTH_JSON_S3_BUCKET environment variable."
        ) from exc

    try:
        logger.info("Creating S3 client...")
        s3_client = boto3.client("s3")
        logger.info(f"Attempting to download s3://{bucket_name}/{object_key}")
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        logger.info("Successfully downloaded file from S3")
    except (BotoCoreError, ClientError) as exc:
        logger.error(f"S3 error: {exc}")
        raise ValueError(
            f"Unable to download auth.json from S3 (s3://{bucket_name}/{object_key}). "
            f"Error: {exc}. Verify the AUTH_JSON_S3_BUCKET and AUTH_JSON_S3_KEY "
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
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    logger.info("Starting credential loading process...")
    
    payload = _load_from_env()
    if payload is not None:
        logger.info("Loaded credentials from environment variable")
    else:
        logger.info("No credentials in environment variable, trying S3...")
        try:
            payload = _load_from_s3()
            if payload is not None:
                logger.info(f"Successfully loaded credentials from S3, found {len(payload.get('users', []))} users")
            else:
                logger.warning("S3 returned None payload")
        except ValueError as exc:
            logger.error(f"Failed to load from S3: {exc}")
            raise ValueError(str(exc)) from exc
        except Exception as exc:
            logger.error(f"Unexpected error loading from S3: {exc}")
            raise ValueError(f"Unexpected S3 error: {exc}") from exc

    if payload is None:
        logger.info("No S3 payload, trying local file...")
        try:
            payload = _load_from_file()
            logger.info("Loaded credentials from local file")
        except AuthFileMissingError:
            logger.warning("No local file found, using fallback users")
            payload = {"users": DEFAULT_FALLBACK_USERS}
    users = payload.get("users", [])
    users_by_login = {}
    for user in users:
        # Skip inactive users
        if user.get("inactive", False):
            continue
            
        login = user.get("login")
        password = user.get("password")
        if login is None or password is None:
            continue
        login = str(login).strip()
        password = str(password).strip()
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
