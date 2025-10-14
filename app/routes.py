import json
import os
import re
import secrets
import time
from collections import Counter
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import requests

from .historical_results_loader import load_historical_dataset
from .lobby_store import lobby_store
from .question_store import question_store

bp = Blueprint("main", __name__)

QUESTION_SOURCE_SHEET_ID = "1kjXOU8cE09vJk8xWzY4vWd1HLCpZQqySi9wULBPg-Iw"
AUTH_FILE = Path("auth.json")
AUTH_ENV_VAR = "AUTH_JSON"
AUTH_S3_BUCKET_ENV = "AUTH_JSON_S3_BUCKET"
AUTH_S3_KEY_ENV = "AUTH_JSON_S3_KEY"
AUTH_S3_BUCKET_FALLBACK_ENV = "AUTH_JSON_S3_BUCKET_NAME"
AUTH_S3_URI_ENV = "AUTH_JSON_S3_URI"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

GAME_TEN_ACTIVE_URL_ENV = "GAME_TEN_ACTIVE_URL"
GAME_TEN_ACTIVE_S3_BUCKET_ENV = "GAME_TEN_ACTIVE_S3_BUCKET"
GAME_TEN_ACTIVE_S3_KEY_ENV = "GAME_TEN_ACTIVE_S3_KEY"
GAME_TEN_ACTIVE_DEFAULT_KEY = "game_active.json"
GAME_TEN_ACTIVE_TEMPLATE_PATH = PROJECT_ROOT / "data" / "game_active.template.json"
AUTH_JSON_URL_ENV = "AUTH_JSON_URL"
DEFAULT_S3_KEY = "auth.json"

DEFAULT_FALLBACK_USERS = [
    {
        "login": "888",
        "password": "6969",
        "name": "Тестовый игрок",
    }
]

_LETTER_TRANSLATION = str.maketrans(
    {
        "ё": "е",
        "Ё": "Е",
        "і": "и",
        "І": "И",
        "ї": "и",
        "Ї": "И",
        "є": "е",
        "Є": "Е",
        "ґ": "г",
        "Ґ": "Г",
    }
)
_PLACEHOLDER_PATTERN = re.compile(r"^игрок\s*\d*$", flags=re.IGNORECASE)
_TOKEN_SPLIT_RE = re.compile(r"[\s\u00A0]+", flags=re.UNICODE)

_PLACEHOLDER_NORMALIZED_VALUES = {
    "",
    "пусто",
    ".",
    "-",
    "--",
    "---",
}

_MANUAL_NAME_OVERRIDES = {
    "александр к.": "Александр Комса",
    "мария т.": "Мария Тимохова",
    "мария т": "Мария Тимохова",
    "максим к.": "Максим Корнеевец",
    "станислав с-б.": "Станислав Силицкий-Бутрим",
    "хорхе": "Хорхе Чаос",
    "михась": "Михась Коберник",
    "шабанов": "Сергей Шабанов",
}
_MANUAL_OVERRIDE_TARGETS = set(_MANUAL_NAME_OVERRIDES.values())


def _normalize_letters(value: str) -> str:
    return value.translate(_LETTER_TRANSLATION)


def _sanitize_player_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    return re.sub(r"\s+", " ", name)


def _tokenize_player_name(name: str) -> list[str]:
    return [token for token in _TOKEN_SPLIT_RE.split(name) if token]


def _extract_surname(normalized_name: str) -> str:
    tokens = _tokenize_player_name(normalized_name)
    return tokens[-1] if tokens else ""


def _is_placeholder_name(name: str) -> bool:
    if not name:
        return False
    normalized = re.sub(r"\s+", " ", _normalize_letters(name.lower())).strip()
    simple = normalized.replace("—", "-").replace("–", "-")
    collapsed = re.sub(r"[.\-]+", "", simple)
    if not collapsed:
        return True
    if normalized in _PLACEHOLDER_NORMALIZED_VALUES or collapsed in _PLACEHOLDER_NORMALIZED_VALUES:
        return True
    return bool(_PLACEHOLDER_PATTERN.fullmatch(normalized))


def _is_single_char_variation(left: str, right: str) -> bool:
    if left == right:
        return True
    len_left = len(left)
    len_right = len(right)
    if abs(len_left - len_right) > 1:
        return False
    if len_left == len_right:
        diff = sum(1 for lch, rch in zip(left, right) if lch != rch)
        return diff == 1
    if len_left < len_right:
        shorter, longer = left, right
    else:
        shorter, longer = right, left
    index_short = 0
    index_long = 0
    mismatch_found = False
    while index_short < len(shorter) and index_long < len(longer):
        if shorter[index_short] == longer[index_long]:
            index_short += 1
            index_long += 1
            continue
        if mismatch_found:
            return False
        mismatch_found = True
        index_long += 1
    return True


@dataclass
class _PlayerEntry:
    display: str
    surname: str
    first_name: str
    token_count: int
    variants: set[str] = field(default_factory=set)
    normalized_variants: set[str] = field(default_factory=set)
    variant_counts: Counter[str] = field(default_factory=Counter)
    surname_initials: str = ""


class PlayerNameNormalizer:
    def __init__(self) -> None:
        self._entries: list[_PlayerEntry] = []
        self._variant_map: dict[str, str] = {}
        self._normalized_map: dict[str, str] = {}
        self._signature_map: dict[tuple[str, ...], _PlayerEntry] = {}
        self._raw_first_token_counts: Counter[str] = Counter()
        self._raw_last_token_counts: Counter[str] = Counter()
        self._first_name_index: dict[str, list[_PlayerEntry]] = {}
        self._surname_index: dict[str, list[_PlayerEntry]] = {}
        self._unique_first_names: dict[str, _PlayerEntry] = {}
        self._unique_surnames: dict[str, _PlayerEntry] = {}

    def build(self, names: list[str]) -> None:
        self._entries.clear()
        self._variant_map = {}
        self._normalized_map = {}
        self._signature_map = {}
        self._raw_first_token_counts.clear()
        self._raw_last_token_counts.clear()
        self._first_name_index = {}
        self._surname_index = {}
        self._unique_first_names = {}
        self._unique_surnames = {}

        for name in names:
            sanitized = _sanitize_player_name(name)
            if not sanitized or _is_placeholder_name(sanitized):
                continue
            tokens = _tokenize_player_name(sanitized)
            normalized_tokens = [_normalize_letters(token.lower()) for token in tokens]
            if len(normalized_tokens) >= 2:
                self._raw_first_token_counts[normalized_tokens[0]] += 1
                self._raw_last_token_counts[normalized_tokens[-1]] += 1
            self._register_name(sanitized, tokens, normalized_tokens)
        self._rebuild_mappings()

    def canonicalize(self, name: str) -> str | None:
        sanitized = _sanitize_player_name(name)
        if not sanitized or _is_placeholder_name(sanitized):
            return None
        normalized_value = _normalize_letters(sanitized.lower())
        override = _MANUAL_NAME_OVERRIDES.get(normalized_value)
        if override:
            return override
        mapped = self._variant_map.get(sanitized)
        if mapped:
            return mapped
        mapped = self._normalized_map.get(normalized_value)
        if mapped:
            return mapped
        tokens = _tokenize_player_name(sanitized)
        normalized_tokens = [_normalize_letters(token.lower()) for token in tokens]
        token_count = len(tokens)
        if token_count == 0:
            return None
        signature = tuple(sorted(normalized_tokens))
        entry = self._signature_map.get(signature)
        if entry:
            return entry.display

        if token_count == 1:
            token = normalized_tokens[0]
            entry = self._unique_first_names.get(token)
            if entry:
                return entry.display
            entry = self._unique_surnames.get(token)
            if entry:
                return entry.display
            for candidate in self._entries:
                if candidate.first_name == token or candidate.surname == token:
                    return candidate.display
            return sanitized

        initials = _extract_initials(tokens[-1])
        if initials:
            first_norm = normalized_tokens[0]
            matches = [
                entry
                for entry in self._entries
                if entry.first_name == first_norm and entry.surname_initials == initials
            ]
            if len(matches) == 1:
                return matches[0].display
            if matches:
                return max(
                    matches,
                    key=lambda candidate: sum(candidate.variant_counts.values()),
                ).display

        last_norm = normalized_tokens[-1]
        candidates = [entry for entry in self._entries if entry.surname == last_norm]
        if len(candidates) == 1:
            return candidates[0].display
        if candidates:
            for candidate in candidates:
                for variant_normalized in candidate.normalized_variants:
                    if _is_single_char_variation(normalized_value, variant_normalized):
                        return candidate.display
        return sanitized

    @staticmethod
    def is_placeholder(name: str) -> bool:
        return _is_placeholder_name(name)

    def _register_name(
        self,
        name: str,
        tokens: list[str],
        normalized_tokens: list[str],
    ) -> _PlayerEntry:
        token_count = len(tokens)
        normalized_value = _normalize_letters(name.lower())
        normalized_variants = _collect_normalized_variants(name, tokens)
        signature = tuple(sorted(normalized_tokens))

        for entry in self._entries:
            if entry.normalized_variants.intersection(normalized_variants):
                return self._merge_entry(
                    entry, name, tokens, normalized_tokens, normalized_variants, signature
                )

        if signature:
            entry = self._signature_map.get(signature)
            if entry:
                return self._merge_entry(
                    entry, name, tokens, normalized_tokens, normalized_variants, signature
                )

        if token_count >= 2:
            initials = _extract_initials(tokens[-1])
            if initials:
                first_norm = normalized_tokens[0]
                for entry in self._entries:
                    if entry.first_name == first_norm and entry.surname_initials == initials:
                        return self._merge_entry(
                            entry,
                            name,
                            tokens,
                            normalized_tokens,
                            normalized_variants,
                            signature,
                        )

        if token_count == 1 and normalized_tokens:
            candidate_token = normalized_tokens[0]
            for entry in self._entries:
                if entry.surname == candidate_token or entry.first_name == candidate_token:
                    return self._merge_entry(
                        entry,
                        name,
                        tokens,
                        normalized_tokens,
                        normalized_variants,
                        signature,
                    )

        surname = normalized_tokens[-1] if normalized_tokens else ""
        if surname:
            for entry in self._entries:
                if entry.surname != surname:
                    continue
                for variant_normalized in entry.normalized_variants:
                    if _is_single_char_variation(normalized_value, variant_normalized):
                        return self._merge_entry(
                            entry,
                            name,
                            tokens,
                            normalized_tokens,
                            normalized_variants,
                            signature,
                        )

        entry = _PlayerEntry(
            display=name,
            surname=surname,
            first_name=normalized_tokens[0] if normalized_tokens else "",
            token_count=token_count,
        )
        entry.variants.add(name)
        entry.normalized_variants.update(normalized_variants)
        entry.variant_counts[name] += 1
        entry.surname_initials = _extract_initials(tokens[-1]) if tokens else ""
        self._entries.append(entry)
        if signature:
            self._signature_map[signature] = entry
        self._update_entry_display(entry)
        return entry

    def _merge_entry(
        self,
        entry: _PlayerEntry,
        name: str,
        tokens: list[str],
        normalized_tokens: list[str],
        normalized_variants: set[str],
        signature: tuple[str, ...],
    ) -> _PlayerEntry:
        entry.variants.add(name)
        entry.normalized_variants.update(normalized_variants)
        entry.variant_counts[name] += 1
        if signature:
            self._signature_map[signature] = entry
        entry.surname_initials = _extract_initials(tokens[-1]) if tokens else entry.surname_initials
        self._update_entry_display(entry)
        return entry

    def _rebuild_mappings(self) -> None:
        self._variant_map = {}
        self._normalized_map = {}
        self._signature_map = {}
        self._first_name_index = {}
        self._surname_index = {}
        for entry in self._entries:
            canonical = entry.display
            tokens = _tokenize_player_name(canonical)
            normalized_tokens = [_normalize_letters(token.lower()) for token in tokens]
            if normalized_tokens:
                self._signature_map[tuple(sorted(normalized_tokens))] = entry
            if normalized_tokens:
                entry.first_name = normalized_tokens[0]
                entry.surname = normalized_tokens[-1]
                entry.surname_initials = _extract_initials(tokens[-1]) if tokens else ""
                self._first_name_index.setdefault(entry.first_name, []).append(entry)
                self._surname_index.setdefault(entry.surname, []).append(entry)
            for variant in entry.variants:
                self._variant_map[variant] = canonical
                normalized_variant = _normalize_letters(variant.lower())
                self._normalized_map[normalized_variant] = canonical
                variant_tokens = _tokenize_player_name(variant)
                normalized_variant_tokens = [
                    _normalize_letters(token.lower()) for token in variant_tokens
                ]
                if normalized_variant_tokens:
                    self._signature_map[
                        tuple(sorted(normalized_variant_tokens))
                    ] = entry

        self._unique_first_names = {
            key: entries[0]
            for key, entries in self._first_name_index.items()
            if len(entries) == 1
        }
        self._unique_surnames = {
            key: entries[0]
            for key, entries in self._surname_index.items()
            if len(entries) == 1
        }

    def _update_entry_display(self, entry: _PlayerEntry) -> None:
        if not entry.variant_counts:
            return

        def _variant_score(variant: str) -> tuple[int, int, int, int, int]:
            tokens = _tokenize_player_name(variant)
            normalized_tokens = [_normalize_letters(token.lower()) for token in tokens]
            token_count = len(tokens)
            first_norm = normalized_tokens[0] if normalized_tokens else ""
            last_norm = normalized_tokens[-1] if normalized_tokens else ""
            first_first = self._raw_first_token_counts.get(first_norm, 0)
            first_last = self._raw_last_token_counts.get(first_norm, 0)
            last_last = self._raw_last_token_counts.get(last_norm, 0)
            last_first = self._raw_first_token_counts.get(last_norm, 0)
            order_score = 0
            if token_count >= 2:
                first_likely_first = first_first >= first_last
                last_likely_last = last_last >= last_first
                order_score = int(first_likely_first and last_likely_last)
            manual_score = 1 if variant in _MANUAL_OVERRIDE_TARGETS else 0
            return (
                entry.variant_counts[variant],
                manual_score,
                order_score,
                token_count,
                len(variant),
            )

        best_variant = max(entry.variant_counts, key=_variant_score)
        entry.display = best_variant
        tokens = _tokenize_player_name(best_variant)
        normalized_tokens = [_normalize_letters(token.lower()) for token in tokens]
        entry.token_count = len(tokens)
        entry.first_name = normalized_tokens[0] if normalized_tokens else ""
        entry.surname = normalized_tokens[-1] if normalized_tokens else ""
        entry.surname_initials = _extract_initials(tokens[-1]) if tokens else ""


def _collect_normalized_variants(name: str, tokens: list[str]) -> set[str]:
    normalized = _normalize_letters(name.lower())
    variants = {normalized}
    if len(tokens) >= 2:
        reversed_name = " ".join(reversed(tokens))
        variants.add(_normalize_letters(reversed_name.lower()))
    return variants


def _extract_initials(token: str) -> str:
    if not token:
        return ""
    cleaned = re.sub(r"[^A-Za-zА-Яа-яЁё\-]+", "", token)
    if not cleaned:
        return ""
    parts = re.split(r"[\-]+", cleaned)
    initials = "".join(
        _normalize_letters(part.lower())[0] if part else "" for part in parts if part
    )
    return initials


LOBBY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LOBBY_CODE_LENGTH = 4
LOBBY_EXPIRATION_SECONDS = 60 * 60
# Players might briefly pause polling when their browser tab is hidden.
# Give them a generous window before considering the session stale so they
# are not unexpectedly kicked out of a lobby.
PLAYER_EXPIRATION_SECONDS = 180


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
    session.pop("buzzer_host_token", None)


def _generate_lobby_code():
    while True:
        code = "".join(
            secrets.choice(LOBBY_CODE_ALPHABET) for _ in range(LOBBY_CODE_LENGTH)
        )
        if not lobby_store.exists(code):
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
        if lobby.get("active_player_id") in removed_ids:
            lobby["active_player_id"] = None
        lobby["updated_at"] = now
        return True

    return False


def _expire_stale_lobbies():
    now = time.time()
    for lobby in lobby_store.get_all_lobbies():
        modified = _expire_stale_players(lobby, now)
        host_seen = lobby.get("host_seen", lobby["created_at"])
        should_expire = False
        if now - lobby.get("updated_at", lobby["created_at"]) > LOBBY_EXPIRATION_SECONDS:
            should_expire = True
        elif now - host_seen > LOBBY_EXPIRATION_SECONDS:
            should_expire = True
        elif not lobby["players"] and now - host_seen > PLAYER_EXPIRATION_SECONDS * 2:
            should_expire = True

        if should_expire:
            lobby_store.delete_lobby(lobby["code"])
        elif modified:
            lobby_store.save_lobby(lobby)


def _remove_player_from_lobby(code, player_id):
    if not code or not player_id:
        return
    lobby = lobby_store.get_lobby(code)
    if not lobby:
        return

    if player_id in lobby["players"]:
        del lobby["players"][player_id]
        lobby["buzz_order"] = [
            existing for existing in lobby["buzz_order"] if existing != player_id
        ]
        if lobby.get("active_player_id") == player_id:
            lobby["active_player_id"] = None
        lobby["updated_at"] = time.time()
        lobby_store.save_lobby(lobby)


def _get_lobby_or_404(code):
    _expire_stale_lobbies()
    lobby = lobby_store.get_lobby(code)
    if not lobby:
        abort(404)
    return lobby

def _get_sanitized_env(name):
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _extract_keywords(text):
    text = (text or "").strip()
    if not text:
        return []

    normalized_query = re.sub(r"\s+", " ", text).strip().lower()
    candidates = []
    if normalized_query:
        candidates.append(normalized_query)

    candidates.extend(
        match.lower()
        for match in re.findall(r"[\w-]+", text, flags=re.UNICODE)
    )

    deduped = []
    seen = set()
    for keyword in candidates:
        if keyword and keyword not in seen:
            deduped.append(keyword)
            seen.add(keyword)

    # Avoid overly large queries.
    return deduped[:10]


def _ai_expand_keywords(query):
    api_key = _get_sanitized_env("OPENAI_API_KEY")
    if not api_key:
        return [], "Чтобы включить ИИ-поиск, задайте переменную окружения OPENAI_API_KEY."

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You expand trivia search queries. Respond with up to six concise "
                    "keywords separated by commas, prioritizing important names, "
                    "dates, and topics from the request."
                ),
            },
            {
                "role": "user",
                "content": f"Search query: {query}",
            },
        ],
        "temperature": 0,
        "max_tokens": 120,
    }

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # pragma: no cover - depends on external API
        current_app.logger.warning("AI keyword expansion failed: %s", exc)
        return [], "Не удалось получить подсказки ИИ. Используем обычный поиск."

    choices = data.get("choices") or []
    if not choices:
        current_app.logger.warning("AI keyword expansion returned no choices: %s", data)
        return [], "ИИ не вернул дополнительные подсказки."

    message = choices[0].get("message", {}).get("content", "")
    if not message:
        return [], "ИИ не вернул дополнительные подсказки."

    suggested = [
        item.strip().lower()
        for item in re.split(r"[,\n]+", message)
        if item.strip()
    ]

    deduped = []
    seen = set()
    for keyword in suggested:
        if keyword and keyword not in seen:
            deduped.append(keyword)
            seen.add(keyword)

    return deduped[:10], None


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

    parsed = urlparse(url)
    bucket_from_url, key_from_url = _parse_s3_reference(url)
    if bucket_from_url and key_from_url:
        host_lower = (parsed.netloc or "").lower()
        path_no_slash = parsed.path.strip("/")
        path_segments = [segment for segment in parsed.path.split("/") if segment]

        path_style_hosts = {
            "s3.amazonaws.com",
            "s3-accelerate.amazonaws.com",
        }
        is_path_style_host = (
            host_lower in path_style_hosts
            or host_lower.startswith("s3.")
            or host_lower.startswith("s3-")
        )

        missing_key = False
        if not path_no_slash:
            missing_key = True
        elif is_path_style_host and len(path_segments) == 1:
            missing_key = True

        if missing_key:
            if is_path_style_host and path_segments:
                bucket_segment = path_segments[0]
                new_path = f"/{bucket_segment}/{key_from_url}"
            else:
                new_path = f"/{key_from_url}"
            parsed = parsed._replace(path=new_path)
            url = urlunparse(parsed)

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


def _download_json_from_s3(bucket_name, object_key, *, context_label):
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:  # pragma: no cover - requires optional dependency
        raise ValueError(
            f"Загрузка {context_label} из S3 требует установленного пакета boto3."
        ) from exc

    try:
        s3_client = boto3.client("s3")
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
    except (BotoCoreError, ClientError) as exc:
        raise ValueError(
            f"Не удалось загрузить {context_label} из S3 (s3://{bucket_name}/{object_key}). Ошибка: {exc}"
        ) from exc

    body = response.get("Body")
    if body is None:
        raise ValueError(
            f"Получен пустой ответ при загрузке {context_label} из S3 (s3://{bucket_name}/{object_key})."
        )

    raw_contents = body.read()
    if isinstance(raw_contents, bytes):
        raw_contents = raw_contents.decode("utf-8")

    try:
        return json.loads(raw_contents)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Файл {context_label} из S3 (s3://{bucket_name}/{object_key}) содержит некорректный JSON."
        ) from exc


def _load_json_from_http(url, *, context_label):
    try:
        response = requests.get(url, timeout=10)
    except requests.RequestException as exc:
        raise ValueError(
            f"Не удалось загрузить {context_label} по адресу {url}: {exc}"
        ) from exc

    if not response.ok:
        raise ValueError(
            f"Сервер вернул статус {response.status_code} при загрузке {context_label} по адресу {url}."
        )

    try:
        return response.json()
    except ValueError as exc:
        raise ValueError(
            f"Ответ по адресу {url} не является корректным JSON для {context_label}."
        ) from exc


def _load_json_from_path(path, *, context_label):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(
            f"Файл {context_label} не найден по пути {path}."
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"Не удалось прочитать файл {context_label} по пути {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Файл {context_label} по пути {path} содержит некорректный JSON."
        ) from exc


def _load_game_ten_active_payload():
    context_label = "game_active.json"
    raw_reference = _get_sanitized_env(GAME_TEN_ACTIVE_URL_ENV)

    if raw_reference:
        bucket, key = _parse_s3_reference(raw_reference)
        if bucket:
            current_app.logger.info(
                "Загружаем %s из S3 по конфигурации GAME_TEN_ACTIVE_URL", context_label
            )
            return _download_json_from_s3(
                bucket, key or GAME_TEN_ACTIVE_DEFAULT_KEY, context_label=context_label
            )

        lowered = raw_reference.lower()
        if lowered.startswith("http://") or lowered.startswith("https://"):
            current_app.logger.info(
                "Загружаем %s по HTTP из %s", context_label, raw_reference
            )
            return _load_json_from_http(raw_reference, context_label=context_label)

        candidate_path = Path(raw_reference)
        if not candidate_path.is_absolute():
            candidate_path = (PROJECT_ROOT / raw_reference).resolve()
        if candidate_path.exists():
            current_app.logger.info(
                "Загружаем %s из локального файла %s, указанного в GAME_TEN_ACTIVE_URL",
                context_label,
                candidate_path,
            )
            return _load_json_from_path(candidate_path, context_label=context_label)

        current_app.logger.warning(
            "Значение GAME_TEN_ACTIVE_URL (%s) не соответствует доступному ресурсу."
            " Будет произведена попытка использовать запасные варианты.",
            raw_reference,
        )

    bucket_name = _get_sanitized_env(GAME_TEN_ACTIVE_S3_BUCKET_ENV)
    object_key = (
        _get_sanitized_env(GAME_TEN_ACTIVE_S3_KEY_ENV) or GAME_TEN_ACTIVE_DEFAULT_KEY
    )
    if bucket_name:
        current_app.logger.info(
            "Загружаем %s из S3 по конфигурации GAME_TEN_ACTIVE_S3_BUCKET/GAME_TEN_ACTIVE_S3_KEY",
            context_label,
        )
        return _download_json_from_s3(
            bucket_name, object_key, context_label=context_label
        )

    if GAME_TEN_ACTIVE_TEMPLATE_PATH.exists():
        current_app.logger.info(
            "Используется шаблонный файл %s по пути %s", context_label, GAME_TEN_ACTIVE_TEMPLATE_PATH
        )
        return _load_json_from_path(
            GAME_TEN_ACTIVE_TEMPLATE_PATH, context_label=context_label
        )

    raise ValueError(
        "Не удалось определить источник данных для game_active.json. Проверьте переменные окружения."
    )


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

    if role == "host" and code:
        lobby = lobby_store.get_lobby(code)
        if lobby and lobby.get("host_id") == player_id:
            return redirect(url_for("main.buzzer_host", code=code))

    if role == "player" and code:
        lobby = lobby_store.get_lobby(code)
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


@bp.route("/game-lobby")
@login_required
def game_lobby():
    _expire_stale_lobbies()

    requested_code = request.args.get("code", "").strip().upper()
    code = session.get("buzzer_code")
    role = session.get("buzzer_role")
    session_id = session.get("buzzer_id")

    host_lobby = None
    player_lobby = None

    if role == "host" and code:
        lobby = lobby_store.get_lobby(code)
        if lobby and lobby.get("host_id") == session_id:
            host_lobby = {
                "code": code,
                "host_name": lobby["host_name"],
                "share_url": url_for("main.buzzer_home", _external=True, code=code),
                "manage_url": url_for(
                    "main.buzzer_host", _external=True, code=code, token=lobby["host_token"]
                ),
                "resume_url": url_for("main.buzzer_host", code=code),
                "player_count": len(lobby.get("players", {})),
            }
    elif role == "player" and code:
        lobby = lobby_store.get_lobby(code)
        if lobby and session_id in lobby["players"]:
            player = lobby["players"].get(session_id, {})
            player_lobby = {
                "code": code,
                "host_name": lobby["host_name"],
                "display_name": player.get("name") or session.get("buzzer_name"),
                "resume_url": url_for("main.buzzer_player", code=code),
            }

    return render_template(
        "game_lobby.html",
        default_name=_current_display_name(),
        requested_code=requested_code,
        lobby_code_length=LOBBY_CODE_LENGTH,
        host_lobby=host_lobby,
        player_lobby=player_lobby,
    )


@bp.route("/buzzer/create", methods=["POST"])
@login_required
def buzzer_create():
    _expire_stale_lobbies()
    _clear_buzzer_session()

    code = _generate_lobby_code()
    host_id = str(uuid4())
    host_name = _current_display_name()
    host_token = secrets.token_urlsafe(16)
    now = time.time()

    lobby = {
        "code": code,
        "host_id": host_id,
        "host_name": host_name,
        "host_token": host_token,
        "created_at": now,
        "updated_at": now,
        "host_seen": now,
        "locked": False,
        "players": {},
        "buzz_order": [],
        "question_value": 0,
        "active_player_id": None,
    }

    lobby_store.save_lobby(lobby)

    session["buzzer_role"] = "host"
    session["buzzer_code"] = code
    session["buzzer_id"] = host_id
    session["buzzer_name"] = host_name
    session["buzzer_host_token"] = host_token

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

    lobby = lobby_store.get_lobby(code)
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
        "score": 0,
    }
    lobby["updated_at"] = now

    lobby_store.save_lobby(lobby)

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

    token = request.args.get("token")
    session_token = session.get("buzzer_host_token")
    if token and token == lobby.get("host_token"):
        session["buzzer_role"] = "host"
        session["buzzer_code"] = code
        session["buzzer_id"] = lobby["host_id"]
        session["buzzer_name"] = lobby["host_name"]
        session["buzzer_host_token"] = lobby["host_token"]
    elif session_token and session_token == lobby.get("host_token"):
        session.setdefault("buzzer_role", "host")
        session.setdefault("buzzer_code", code)
        session.setdefault("buzzer_id", lobby["host_id"])
        session.setdefault("buzzer_name", lobby["host_name"])

    if session.get("buzzer_role") != "host" or session.get("buzzer_id") != lobby["host_id"]:
        flash("You're not hosting this lobby.", "error")
        return redirect(url_for("main.buzzer_home"))

    share_url = url_for("main.buzzer_home", _external=True, code=code)
    host_manage_url = url_for(
        "main.buzzer_host", _external=True, code=code, token=lobby["host_token"]
    )
    return render_template(
        "buzzer_host.html",
        code=code,
        host_name=lobby["host_name"],
        share_url=share_url,
        host_manage_url=host_manage_url,
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
    save_needed = False

    if role == "host" and session_id == lobby["host_id"]:
        lobby["host_seen"] = now
        save_needed = True
    elif role == "player" and session_id in lobby["players"]:
        lobby["players"][session_id]["last_seen"] = now
        save_needed = True
    else:
        return jsonify({"error": "not-in-lobby"}), 403

    if _expire_stale_players(lobby, now):
        save_needed = True

    if save_needed:
        lobby_store.save_lobby(lobby)

    question_value = int(lobby.get("question_value", 0) or 0)
    active_player_id = lobby.get("active_player_id")

    players = []
    for player_id, player in sorted(
        lobby["players"].items(), key=lambda item: item[1]["joined_at"]
    ):
        position = (
            lobby["buzz_order"].index(player_id) + 1
            if player_id in lobby["buzz_order"]
            else None
        )
        score = int(player.get("score", 0) or 0)
        is_active = player_id == active_player_id
        players.append(
            {
                "id": player_id,
                "name": player["name"],
                "buzzed": position is not None,
                "position": position,
                "score": score,
                "is_self": role == "player" and player_id == session_id,
                "is_active": is_active,
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
                "is_active": player_id == active_player_id,
            }
        )

    scoreboard_entries = []
    for player_id, player in sorted(
        lobby["players"].items(),
        key=lambda item: (-int(item[1].get("score", 0) or 0), item[1]["joined_at"]),
    ):
        scoreboard_entries.append(
            {
                "id": player_id,
                "name": player["name"],
                "score": int(player.get("score", 0) or 0),
                "is_active": player_id == active_player_id,
            }
        )

    active_player = None
    if active_player_id:
        active_player = lobby["players"].get(active_player_id)
        if active_player:
            active_player = {
                "id": active_player_id,
                "name": active_player["name"],
                "score": int(active_player.get("score", 0) or 0),
            }

    response = {
        "code": code,
        "locked": lobby["locked"],
        "host": {"name": lobby["host_name"]},
        "players": players,
        "buzz_queue": buzz_queue,
        "buzz_open": not lobby["locked"],
        "question_value": question_value,
        "scoreboard": scoreboard_entries,
        "active_player": active_player,
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
            "score": int(lobby["players"].get(session_id, {}).get("score", 0) or 0),
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
    lobby_store.save_lobby(lobby)

    return jsonify({"status": "ok", "position": len(lobby["buzz_order"])})


@bp.route("/buzzer/api/lobbies/<code>/value", methods=["POST"])
@login_required
def buzzer_set_value(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)

    if session.get("buzzer_role") != "host" or session.get("buzzer_id") != lobby["host_id"]:
        return jsonify({"error": "forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    raw_value = payload.get("value")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid-value"}), 400

    allowed_values = {10, 20, 30, 40, 50}
    if value not in allowed_values:
        return jsonify({"error": "invalid-value"}), 400

    lobby["question_value"] = value
    lobby["updated_at"] = time.time()
    lobby_store.save_lobby(lobby)

    return jsonify({"status": "ok", "question_value": value})


@bp.route("/buzzer/api/lobbies/<code>/confirm", methods=["POST"])
@login_required
def buzzer_confirm(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)

    if session.get("buzzer_role") != "host" or session.get("buzzer_id") != lobby["host_id"]:
        return jsonify({"error": "forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    player_id = payload.get("player_id")

    if not player_id or player_id not in lobby["players"]:
        return jsonify({"error": "invalid-player"}), 400

    if player_id not in lobby["buzz_order"]:
        return jsonify({"error": "player-not-in-queue"}), 400

    now = time.time()
    lobby["active_player_id"] = player_id
    lobby["locked"] = True
    player = lobby["players"][player_id]
    player["last_seen"] = now
    lobby["updated_at"] = now
    lobby_store.save_lobby(lobby)

    return jsonify(
        {
            "status": "ok",
            "active_player": {
                "id": player_id,
                "name": player["name"],
                "score": int(player.get("score", 0) or 0),
            },
        }
    )


@bp.route("/buzzer/api/lobbies/<code>/resolve", methods=["POST"])
@login_required
def buzzer_resolve(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)

    if session.get("buzzer_role") != "host" or session.get("buzzer_id") != lobby["host_id"]:
        return jsonify({"error": "forbidden"}), 403

    active_player_id = lobby.get("active_player_id")
    if not active_player_id or active_player_id not in lobby["players"]:
        return jsonify({"error": "no-active-player"}), 400

    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").lower()
    if action not in {"plus", "minus", "skip"}:
        return jsonify({"error": "invalid-action"}), 400

    player = lobby["players"][active_player_id]
    current_score = int(player.get("score", 0) or 0)
    question_value = int(lobby.get("question_value", 0) or 0)

    if action == "plus":
        current_score += question_value
    elif action == "minus":
        current_score -= question_value

    player["score"] = current_score
    now = time.time()
    player["last_seen"] = now
    lobby["active_player_id"] = None
    lobby["buzz_order"].clear()
    lobby["locked"] = False
    for participant in lobby["players"].values():
        participant["buzzed_at"] = None
    lobby["updated_at"] = now
    lobby_store.save_lobby(lobby)

    return jsonify(
        {
            "status": "ok",
            "action": action,
            "score": current_score,
        }
    )


@bp.route("/buzzer/api/lobbies/<code>/reset", methods=["POST"])
@login_required
def buzzer_reset(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)

    if session.get("buzzer_role") != "host" or session.get("buzzer_id") != lobby["host_id"]:
        return jsonify({"error": "forbidden"}), 403

    lobby["buzz_order"].clear()
    lobby["locked"] = False
    lobby["active_player_id"] = None
    now = time.time()
    for player in lobby["players"].values():
        player["buzzed_at"] = None
    lobby["updated_at"] = now

    lobby_store.save_lobby(lobby)

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

    lobby_store.save_lobby(lobby)

    return jsonify({"status": "ok", "locked": lobby["locked"]})


@bp.route("/buzzer/api/lobbies/<code>/close", methods=["POST"])
@login_required
def buzzer_close(code):
    code = code.upper()
    lobby = _get_lobby_or_404(code)

    if session.get("buzzer_role") != "host" or session.get("buzzer_id") != lobby["host_id"]:
        return jsonify({"error": "forbidden"}), 403

    lobby_store.delete_lobby(code)
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


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id") and request.method == "GET":
        return redirect(url_for("main.dashboard"))

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


@bp.route("/", methods=["GET", "POST"])
def root():
    if request.method == "POST":
        return login()

    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))

    return redirect(url_for("main.login"))


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        login_code=session.get("user_id"),
        user_name=session.get("user_name"),
    )


@bp.route("/game-ten")
@login_required
def game_ten():
    raw_active_url = _get_sanitized_env(GAME_TEN_ACTIVE_URL_ENV)
    if raw_active_url and raw_active_url.lower().startswith(("http://", "https://")):
        active_url = raw_active_url
    else:
        active_url = url_for("main.game_ten_active_data")

    live_url = _get_sanitized_env("GAME_TEN_LIVE_URL") or ""
    return render_template(
        "game_ten.html",
        game_ten_active_url=active_url,
        game_ten_live_url=live_url,
    )


@bp.route("/api/game-ten/active")
@login_required
def game_ten_active_data():
    try:
        payload = _load_game_ten_active_payload()
    except ValueError as exc:
        current_app.logger.error("Не удалось загрузить game_active.json: %s", exc)
        return jsonify({"error": str(exc)}), 502

    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


def _fetch_historical_records(selected_season: int | None):
    dataset = load_historical_dataset()
    fights_all: list[dict] = list(dataset["fights"])
    available_seasons: list[int] = list(dataset["seasons"])

    if selected_season and selected_season in available_seasons:
        fights_filtered = [
            fight for fight in fights_all if fight.get("season_number") == selected_season
        ]
    else:
        fights_filtered = fights_all

    player_names = [
        participant.get("display", "")
        for fight in fights_filtered
        for participant in fight.get("participants", [])
    ]

    return fights_filtered, player_names, available_seasons


@bp.route("/historical-results")
@login_required
def historical_results():
    selected_player_raw = request.args.get("player", "").strip()
    selected_season = request.args.get("season", type=int)

    fights_raw, raw_names, available_seasons = _fetch_historical_records(selected_season)

    normalizer = PlayerNameNormalizer()
    normalizer.build(raw_names)

    selected_player_canonical = (
        normalizer.canonicalize(selected_player_raw) if selected_player_raw else None
    )
    selected_player_display = selected_player_canonical or selected_player_raw

    fights: list[dict] = []
    player_names: set[str] = set()

    for fight in fights_raw:
        normalized_players = []
        includes_selected = False
        for participant in fight["participants"]:
            canonical_name = normalizer.canonicalize(participant["display"])
            if not canonical_name:
                continue
            total = participant.get("total", 0) or 0
            normalized_players.append(
                {
                    "name": participant["display"],
                    "canonical_name": canonical_name,
                    "total": total,
                }
            )
            player_names.add(canonical_name)
            if selected_player_canonical and canonical_name == selected_player_canonical:
                includes_selected = True

        if not normalized_players:
            continue

        normalized_players.sort(key=lambda entry: entry["total"], reverse=True)

        if selected_player_canonical and not includes_selected:
            continue

        fights.append(
            {
                "season_number": fight.get("season_number"),
                "tour_number": fight.get("tour_number"),
                "fight_code": fight.get("fight_code"),
                "letter": fight.get("letter"),
                "ordinal": fight.get("ordinal"),
                "players": normalized_players,
            }
        )

    all_players = sorted(player_names, key=lambda value: value.lower())
    selected_player_found = (
        bool(selected_player_canonical) and selected_player_canonical in player_names
    )

    return render_template(
        "historical_results.html",
        fights=fights,
        all_players=all_players,
        selected_player=selected_player_display,
        selected_player_found=selected_player_found,
        player_count=len(all_players),
        available_seasons=available_seasons,
        selected_season=selected_season if selected_season in available_seasons else None,
        selected_player_canonical=selected_player_canonical,
    )


@bp.route("/questions")
@login_required
def question_browser():
    query = request.args.get("q", "").strip()
    limit_value = request.args.get("limit", type=int)
    if not limit_value or limit_value <= 0:
        limit_value = 50
    limit_value = min(limit_value, 100)

    season_filter = request.args.get("season", type=int)
    if season_filter is not None and season_filter <= 0:
        season_filter = None

    value_filter = request.args.get("value", type=int)
    if value_filter is not None and value_filter <= 0:
        value_filter = None

    author_filter_raw = request.args.get("author", "")
    author_filter = author_filter_raw.strip() or None

    editor_filter_raw = request.args.get("editor", "")
    editor_filter = editor_filter_raw.strip() or None

    ai_enabled = _get_sanitized_env("OPENAI_API_KEY") is not None
    use_ai = request.args.get("ai") == "1"

    manual_keywords = _extract_keywords(query)
    ai_keywords = []
    ai_feedback = None

    if use_ai and not ai_enabled:
        ai_feedback = "Чтобы включить ИИ-поиск, задайте переменную окружения OPENAI_API_KEY."
    elif use_ai and not query:
        ai_feedback = "Введите поисковый запрос, чтобы использовать ИИ-подсказки."
    elif use_ai and query:
        ai_keywords, ai_message = _ai_expand_keywords(query)
        if ai_message:
            ai_feedback = ai_message
        elif ai_keywords:
            ai_feedback = "ИИ добавил ключевые слова: " + ", ".join(ai_keywords)

    combined_keywords = list(dict.fromkeys(manual_keywords + ai_keywords))

    taken_bounds = question_store.get_taken_not_taken_bounds()
    taken_max_bound, not_taken_max_bound = taken_bounds

    taken_min = request.args.get("taken_min", type=int)
    if taken_min is None or taken_min < 0:
        taken_min = 0

    taken_max = request.args.get("taken_max", type=int)
    if taken_max is None:
        taken_max = taken_max_bound
    else:
        taken_max = max(taken_min, min(taken_max, taken_max_bound))

    not_taken_min = request.args.get("not_taken_min", type=int)
    if not_taken_min is None or not_taken_min < 0:
        not_taken_min = 0

    not_taken_max = request.args.get("not_taken_max", type=int)
    if not_taken_max is None:
        not_taken_max = not_taken_max_bound
    else:
        not_taken_max = max(not_taken_min, min(not_taken_max, not_taken_max_bound))

    results = question_store.search_questions(
        combined_keywords,
        limit=limit_value,
        season_number=season_filter,
        question_value=value_filter,
        author=author_filter,
        editor=editor_filter,
        taken_min=taken_min,
        taken_max=taken_max,
        not_taken_min=not_taken_min,
        not_taken_max=not_taken_max,
    )
    result_count = len(results)

    seasons = question_store.list_seasons()
    values = question_store.list_question_values()
    authors = question_store.list_authors()
    editors = question_store.list_editors()

    return render_template(
        "question_browser.html",
        query=query,
        results=results,
        manual_keywords=manual_keywords,
        ai_keywords=ai_keywords,
        combined_keywords=combined_keywords,
        ai_feedback=ai_feedback,
        ai_enabled=ai_enabled,
        use_ai=use_ai,
        limit_value=limit_value,
        result_count=result_count,
        season_filter=season_filter,
        value_filter=value_filter,
        author_filter=author_filter,
        editor_filter=editor_filter,
        seasons=seasons,
        values=values,
        authors=authors,
        editors=editors,
        taken_min=taken_min,
        taken_max=taken_max,
        not_taken_min=not_taken_min,
        not_taken_max=not_taken_max,
        taken_max_bound=taken_max_bound,
        not_taken_max_bound=not_taken_max_bound,
    )


@bp.route("/questions/source")
@login_required
def question_source_table():
    sheet_direct_url = (
        f"https://docs.google.com/spreadsheets/d/{QUESTION_SOURCE_SHEET_ID}/edit?usp=sharing"
    )
    sheet_api_url = (
        f"https://docs.google.com/spreadsheets/d/{QUESTION_SOURCE_SHEET_ID}/gviz/tq?tqx=out:json"
    )

    sheet_data: dict[str, object] = {"columns": [], "rows": [], "total_rows": 0}
    load_error: str | None = None

    try:
        response = requests.get(sheet_api_url, timeout=10)
        response.raise_for_status()
        payload_raw = response.text
        start_index = payload_raw.find("(")
        end_index = payload_raw.rfind(")")
        if start_index == -1 or end_index == -1:
            raise ValueError("Unexpected response format from Google Sheets")
        payload = json.loads(payload_raw[start_index + 1 : end_index])
        table = payload.get("table", {})
        raw_columns = table.get("cols") or []
        raw_rows = table.get("rows") or []

        used_column_indexes: list[int] = []
        for index, _column in enumerate(raw_columns):
            column_has_data = False
            for raw_row in raw_rows:
                cells = raw_row.get("c") or []
                if index < len(cells):
                    cell = cells[index]
                    if cell and cell.get("v") not in (None, ""):
                        column_has_data = True
                        break
            if column_has_data:
                used_column_indexes.append(index)

        column_overrides = {0: "№", 1: "Игрок"}
        columns: list[str] = []
        for index in used_column_indexes:
            column = raw_columns[index] if index < len(raw_columns) else {}
            label = (column.get("label") or "").strip()
            if not label:
                label = column_overrides.get(index, "")
            if not label:
                label = (column.get("id") or f"Колонка {index + 1}").strip()
            columns.append(label)

        rows: list[list[str]] = []
        for raw_row in raw_rows:
            cells = raw_row.get("c") or []
            formatted_row: list[str] = []
            has_content = False
            for index in used_column_indexes:
                value: object = ""
                if index < len(cells):
                    cell = cells[index]
                    if cell:
                        value = cell.get("f")
                        if value is None:
                            value = cell.get("v")
                if value is None:
                    value = ""
                if isinstance(value, float):
                    if value.is_integer():
                        display_value = str(int(value))
                    else:
                        display_value = f"{value:.2f}".rstrip("0").rstrip(".")
                else:
                    display_value = str(value)
                if display_value:
                    has_content = True
                formatted_row.append(display_value)
            if has_content:
                rows.append(formatted_row)

        sheet_data = {
            "columns": columns,
            "rows": rows,
            "total_rows": len(rows),
        }
    except Exception as exc:  # pragma: no cover - network failure should be rare
        current_app.logger.warning(
            "Failed to load question source sheet: %s", exc, exc_info=True
        )
        load_error = (
            "Не удалось загрузить таблицу Google Sheets. Попробуйте открыть документ по прямой ссылке."
        )

    return render_template(
        "question_source_table.html",
        sheet_direct_url=sheet_direct_url,
        sheet_data=sheet_data,
        load_error=load_error,
    )


@bp.route("/questions/table")
@login_required
def question_table():
    limit_value = request.args.get("limit", type=int)
    if not limit_value or limit_value <= 0:
        limit_value = 100
    limit_value = max(10, min(limit_value, 500))

    page_value = request.args.get("page", type=int)
    if not page_value or page_value <= 0:
        page_value = 1

    season_value = request.args.get("season", type=int)
    if season_value is not None and season_value <= 0:
        season_value = None

    offset = (page_value - 1) * limit_value
    rows = question_store.list_questions(
        limit=limit_value, offset=offset, season_number=season_value
    )
    stats = question_store.get_question_stats(season_number=season_value)
    total_count = stats.get("total", 0) or 0

    has_previous = page_value > 1
    has_next = offset + len(rows) < total_count

    base_params = {"limit": limit_value}
    if season_value:
        base_params["season"] = season_value

    previous_url = None
    next_url = None
    if has_previous:
        prev_params = dict(base_params)
        prev_params["page"] = page_value - 1
        previous_url = url_for("main.question_table", **prev_params)
    if has_next:
        next_params = dict(base_params)
        next_params["page"] = page_value + 1
        next_url = url_for("main.question_table", **next_params)

    seasons = question_store.list_seasons()
    display_from = offset + 1 if rows else 0
    display_to = offset + len(rows)

    return render_template(
        "question_table.html",
        rows=rows,
        stats=stats,
        seasons=seasons,
        limit_value=limit_value,
        page_value=page_value,
        season_value=season_value,
        total_count=total_count,
        has_previous=has_previous,
        has_next=has_next,
        previous_url=previous_url,
        next_url=next_url,
        display_from=display_from,
        display_to=display_to,
    )


@bp.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("main.login"))
