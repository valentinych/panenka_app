import json
import os
import secrets
import time
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

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

LOBBY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LOBBY_CODE_LENGTH = 4
LOBBY_EXPIRATION_SECONDS = 60 * 60
PLAYER_EXPIRATION_SECONDS = 45


LOBBIES = {}


class AuthFileMissingError(FileNotFoundError):
    """Raised when the auth.json file is missing."""


def _current_display_name():
    user_name = session.get("user_name")
    login_code = session.get("user_id")
    if user_name:
        return user_name
    if login_code:
        return f"Player {login_code}"
    return "Host"


def _clear_buzzer_session():
    session.pop("buzzer_role", None)
    session.pop("buzzer_code", None)
    session.pop("buzzer_id", None)
    session.pop("buzzer_name", None)


def _generate_lobby_code():
    while True:
        code = "".join(
            secrets.choice(LOBBY_CODE_ALPHABET) for _ in range(LOBBY_CODE_LENGTH)
        )
        if code not in LOBBIES:
            return code


def _expire_stale_players(lobby, now):
    removed_ids = []
    for player_id, player in list(lobby["players"].items()):
        last_seen = player.get("last_seen", lobby["created_at"])
        if now - last_seen > PLAYER_EXPIRATION_SECONDS:
            removed_ids.append(player_id)
            del lobby["players"][player_id]

    if removed_ids:
        lobby["buzz_order"] = [
            player_id for player_id in lobby["buzz_order"] if player_id not in removed_ids
        ]
        lobby["updated_at"] = now


def _expire_stale_lobbies():
    now = time.time()
    expired_codes = []
    for code, lobby in list(LOBBIES.items()):
        _expire_stale_players(lobby, now)
        host_seen = lobby.get("host_seen", lobby["created_at"])
        if now - lobby.get("updated_at", lobby["created_at"]) > LOBBY_EXPIRATION_SECONDS:
            expired_codes.append(code)
        elif now - host_seen > LOBBY_EXPIRATION_SECONDS:
            expired_codes.append(code)
        elif not lobby["players"] and now - host_seen > PLAYER_EXPIRATION_SECONDS * 2:
            expired_codes.append(code)

    for code in expired_codes:
        del LOBBIES[code]


def _remove_player_from_lobby(code, player_id):
    if not code or not player_id:
        return
    lobby = LOBBIES.get(code)
    if not lobby:
        return

    if player_id in lobby["players"]:
        del lobby["players"][player_id]
        lobby["buzz_order"] = [
            existing for existing in lobby["buzz_order"] if existing != player_id
        ]
        lobby["updated_at"] = time.time()


def _get_lobby_or_404(code):
    _expire_stale_lobbies()
    lobby = LOBBIES.get(code)
    if not lobby:
        abort(404)
    return lobby

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


@bp.route("/buzzer")
@login_required
def buzzer_home():
    _expire_stale_lobbies()
    code = session.get("buzzer_code")
    role = session.get("buzzer_role")
    player_id = session.get("buzzer_id")

    if role == "host" and code in LOBBIES:
        lobby = LOBBIES.get(code)
        if lobby and lobby.get("host_id") == player_id:
            return redirect(url_for("main.buzzer_host", code=code))

    if role == "player" and code in LOBBIES:
        lobby = LOBBIES.get(code)
        if lobby and player_id in lobby["players"]:
            return redirect(url_for("main.buzzer_player", code=code))

    _clear_buzzer_session()
    requested_code = request.args.get("code", "").strip().upper()
    return render_template(
        "buzzer_landing.html",
        default_name=_current_display_name(),
        requested_code=requested_code,
        lobby_code_length=LOBBY_CODE_LENGTH,
    )


@bp.route("/buzzer/create", methods=["POST"])
@login_required
def buzzer_create():
    _expire_stale_lobbies()
    _clear_buzzer_session()

    code = _generate_lobby_code()
    host_id = str(uuid4())
    host_name = _current_display_name()
    now = time.time()

    LOBBIES[code] = {
        "code": code,
        "host_id": host_id,
        "host_name": host_name,
        "created_at": now,
        "updated_at": now,
        "host_seen": now,
        "locked": False,
        "players": {},
        "buzz_order": [],
    }

    session["buzzer_role"] = "host"
    session["buzzer_code"] = code
    session["buzzer_id"] = host_id
    session["buzzer_name"] = host_name

    return redirect(url_for("main.buzzer_host", code=code))


@bp.route("/buzzer/join", methods=["POST"])
@login_required
def buzzer_join():
    _expire_stale_lobbies()
    code = request.form.get("code", "").strip().upper()
    display_name = request.form.get("display_name", "").strip()

    if session.get("buzzer_role") == "player":
        _remove_player_from_lobby(session.get("buzzer_code"), session.get("buzzer_id"))
        _clear_buzzer_session()

    if not code or len(code) != LOBBY_CODE_LENGTH:
        flash("Enter a valid lobby code to join.", "error")
        return redirect(url_for("main.buzzer_home", code=code))

    lobby = LOBBIES.get(code)
    if not lobby:
        flash("We couldn't find a lobby with that code.", "error")
        return redirect(url_for("main.buzzer_home"))

    if not display_name:
        display_name = _current_display_name()

    display_name = display_name[:32]

    player_id = str(uuid4())
    now = time.time()
    lobby["players"][player_id] = {
        "id": player_id,
        "name": display_name,
        "joined_at": now,
        "last_seen": now,
        "buzzed_at": None,
    }
    lobby["updated_at"] = now

    session["buzzer_role"] = "player"
    session["buzzer_code"] = code
    session["buzzer_id"] = player_id
    session["buzzer_name"] = display_name

    return redirect(url_for("main.buzzer_player", code=code))


@bp.route("/buzzer/host/<code>")
@login_required
def buzzer_host(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)

    if session.get("buzzer_role") != "host" or session.get("buzzer_id") != lobby["host_id"]:
        flash("You're not hosting this lobby.", "error")
        return redirect(url_for("main.buzzer_home"))

    share_url = url_for("main.buzzer_home", _external=True, code=code)
    return render_template(
        "buzzer_host.html",
        code=code,
        host_name=lobby["host_name"],
        share_url=share_url,
    )


@bp.route("/buzzer/player/<code>")
@login_required
def buzzer_player(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)

    if session.get("buzzer_role") != "player" or session.get("buzzer_code") != code:
        flash("Join the lobby first to buzz in.", "error")
        return redirect(url_for("main.buzzer_home", code=code))

    player_id = session.get("buzzer_id")
    if player_id not in lobby["players"]:
        _clear_buzzer_session()
        flash("Your session is no longer part of this lobby.", "error")
        return redirect(url_for("main.buzzer_home"))

    return render_template(
        "buzzer_player.html",
        code=code,
        display_name=session.get("buzzer_name"),
        host_name=lobby["host_name"],
    )


@bp.route("/buzzer/api/lobbies/<code>/state")
@login_required
def buzzer_state(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)
    role = session.get("buzzer_role")
    session_id = session.get("buzzer_id")
    now = time.time()

    if role == "host" and session_id == lobby["host_id"]:
        lobby["host_seen"] = now
    elif role == "player" and session_id in lobby["players"]:
        lobby["players"][session_id]["last_seen"] = now
    else:
        return jsonify({"error": "not-in-lobby"}), 403

    _expire_stale_players(lobby, now)

    players = []
    for player_id, player in sorted(
        lobby["players"].items(), key=lambda item: item[1]["joined_at"]
    ):
        position = (
            lobby["buzz_order"].index(player_id) + 1
            if player_id in lobby["buzz_order"]
            else None
        )
        players.append(
            {
                "id": player_id,
                "name": player["name"],
                "buzzed": position is not None,
                "position": position,
                "is_self": role == "player" and player_id == session_id,
            }
        )

    buzz_queue = []
    for index, player_id in enumerate(lobby["buzz_order"]):
        player = lobby["players"].get(player_id)
        if not player:
            continue
        buzz_queue.append(
            {
                "id": player_id,
                "name": player["name"],
                "position": index + 1,
            }
        )

    response = {
        "code": code,
        "locked": lobby["locked"],
        "host": {"name": lobby["host_name"]},
        "players": players,
        "buzz_queue": buzz_queue,
        "buzz_open": not lobby["locked"],
    }

    if role == "player":
        position = next(
            (entry["position"] for entry in buzz_queue if entry["id"] == session_id),
            None,
        )
        response["you"] = {
            "id": session_id,
            "name": session.get("buzzer_name"),
            "position": position,
            "can_buzz": not lobby["locked"] and position is None,
        }
    else:
        response["you"] = {"role": "host", "name": session.get("buzzer_name")}

    return jsonify(response)


@bp.route("/buzzer/api/lobbies/<code>/buzz", methods=["POST"])
@login_required
def buzzer_buzz(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)

    if session.get("buzzer_role") != "player" or session.get("buzzer_code") != code:
        return jsonify({"error": "not-in-lobby"}), 403

    player_id = session.get("buzzer_id")
    player = lobby["players"].get(player_id)
    if not player:
        _clear_buzzer_session()
        return jsonify({"error": "not-in-lobby"}), 403

    if lobby["locked"]:
        return jsonify({"error": "locked"}), 400

    if player_id in lobby["buzz_order"]:
        position = lobby["buzz_order"].index(player_id) + 1
        return jsonify({"status": "already", "position": position})

    now = time.time()
    lobby["buzz_order"].append(player_id)
    player["buzzed_at"] = now
    player["last_seen"] = now
    lobby["updated_at"] = now
    if len(lobby["buzz_order"]) == 1:
        lobby["locked"] = True

    return jsonify({"status": "ok", "position": len(lobby["buzz_order"])})


@bp.route("/buzzer/api/lobbies/<code>/reset", methods=["POST"])
@login_required
def buzzer_reset(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)

    if session.get("buzzer_role") != "host" or session.get("buzzer_id") != lobby["host_id"]:
        return jsonify({"error": "forbidden"}), 403

    lobby["buzz_order"].clear()
    lobby["locked"] = False
    now = time.time()
    for player in lobby["players"].values():
        player["buzzed_at"] = None
    lobby["updated_at"] = now

    return jsonify({"status": "ok"})


@bp.route("/buzzer/api/lobbies/<code>/lock", methods=["POST"])
@login_required
def buzzer_lock(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)

    if session.get("buzzer_role") != "host" or session.get("buzzer_id") != lobby["host_id"]:
        return jsonify({"error": "forbidden"}), 403

    lobby["locked"] = not lobby["locked"]
    lobby["updated_at"] = time.time()

    return jsonify({"status": "ok", "locked": lobby["locked"]})


@bp.route("/buzzer/api/lobbies/<code>/close", methods=["POST"])
@login_required
def buzzer_close(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)

    if session.get("buzzer_role") != "host" or session.get("buzzer_id") != lobby["host_id"]:
        return jsonify({"error": "forbidden"}), 403

    del LOBBIES[code]
    _clear_buzzer_session()

    return jsonify({"status": "ok"})


@bp.route("/buzzer/api/lobbies/<code>/leave", methods=["POST"])
@login_required
def buzzer_leave(code):
    code = code.upper()

    if session.get("buzzer_role") != "player" or session.get("buzzer_code") != code:
        _clear_buzzer_session()
        return jsonify({"status": "ok"})

    player_id = session.get("buzzer_id")
    _remove_player_from_lobby(code, player_id)
    _clear_buzzer_session()

    return jsonify({"status": "ok"})


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
