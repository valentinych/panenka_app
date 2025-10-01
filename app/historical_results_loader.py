"""Helpers for assembling historical fight results datasets."""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .season2 import Season2Importer, Season2ResultsStore

DEFAULT_SEASON1_FIXTURE = Path("app/static/data/season01_tour_results.json")
DEFAULT_SEASON3_FIXTURE = Path("app/static/data/season03_tour_results.json")
DEFAULT_SEASON4_FIXTURE = Path("app/static/data/season04_tour_results.json")
DEFAULT_SEASON2_DATA_ROOT = Path("data/raw/season02/csv")
DEFAULT_SEASON2_MANIFEST = Path("data/raw/season02/manifest.json")
DEFAULT_EXTRA_FIXTURES = (DEFAULT_SEASON3_FIXTURE, DEFAULT_SEASON4_FIXTURE)

_FIGHT_CODE_PATTERN = re.compile(
    r"S(?P<season>\d{2})E(?P<tour>\d{2})F(?P<fight>\d{2})",
    flags=re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")


@lru_cache(maxsize=1)
def load_historical_dataset(
    season1_json: str | Path = DEFAULT_SEASON1_FIXTURE,
    season2_data_root: str | Path = DEFAULT_SEASON2_DATA_ROOT,
    season2_manifest: str | Path = DEFAULT_SEASON2_MANIFEST,
    extra_fixtures: Iterable[str | Path] = DEFAULT_EXTRA_FIXTURES,
) -> dict[str, Iterable]:
    """Load historical fight payload assembled from seasons 1 and 2.

    The heavy lifting is delegated to :func:`build_historical_database`, which
    reuses the Season 2 importer to normalise CSV snapshots. To avoid committing
    binary assets the SQLite database is created inside a temporary directory
    and converted to a lightweight in-memory representation before returning to
    the caller. Results are cached across calls for the lifetime of the
    process so repeated requests do not rebuild the dataset.
    """

    season1_path = Path(season1_json)
    season2_root_path = Path(season2_data_root)
    season2_manifest_path = Path(season2_manifest)
    extra_fixture_paths = [Path(path) for path in extra_fixtures]

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "historical.sqlite3"
        build_historical_database(
            season1_json=season1_path,
            season2_data_root=season2_root_path,
            season2_manifest=season2_manifest_path,
            output=output,
            extra_fixtures=extra_fixture_paths,
        )
        fights, seasons = _extract_historical_records(output)

    # Ensure upcoming seasons are visible in the UI filters even before fights
    # are imported, so the options appear as soon as the season starts.
    seasons = sorted({*seasons, 3, 4})

    raw_names = [
        participant["display"]
        for fight in fights
        for participant in fight.get("participants", [])
    ]

    return {
        "fights": fights,
        "raw_names": raw_names,
        "seasons": seasons,
    }


def build_historical_database(
    *,
    season1_json: Path,
    season2_data_root: Path,
    season2_manifest: Path,
    output: Path,
    extra_fixtures: Iterable[Path] = (),
) -> dict[str, dict[str, int]]:
    """Compile season 1 and 2 fight snapshots into a SQLite bundle."""

    if output.exists():
        output.unlink()

    store = Season2ResultsStore(db_path=str(output))

    season2_summary = _import_season2(
        store,
        data_root=season2_data_root,
        manifest=season2_manifest,
    )

    fixture_summaries: dict[str, dict[str, int]] = {"season2": season2_summary}
    with store.connection() as conn:
        for fixture_path in [season1_json, *extra_fixtures]:
            if not fixture_path.exists():
                continue
            season_number, summary = _insert_fixture_results(
                conn,
                fixture_path=fixture_path,
            )
            fixture_summaries[f"season{season_number}"] = summary
        conn.commit()

    return fixture_summaries


def _sanitize_name(value: str | None) -> str:
    value = (value or "").strip()
    return _WHITESPACE_RE.sub(" ", value)


def _normalize_name(value: str | None) -> str:
    sanitized = _sanitize_name(value)
    return sanitized.lower()


def _ensure_season(conn: sqlite3.Connection, season_number: int) -> int:
    row = conn.execute(
        "SELECT id FROM seasons WHERE season_number = ?",
        (season_number,),
    ).fetchone()
    if row is not None:
        return int(row["id"])
    cursor = conn.execute(
        "INSERT INTO seasons (season_number, slug) VALUES (?, ?)",
        (season_number, f"{season_number:02d}"),
    )
    return int(cursor.lastrowid)


def _ensure_tour(
    conn: sqlite3.Connection,
    *,
    season_id: int,
    tour_number: int,
    gid: int | None,
) -> int:
    row = conn.execute(
        "SELECT id FROM tours WHERE season_id = ? AND tour_number = ?",
        (season_id, tour_number),
    ).fetchone()
    if row is not None:
        tour_id = int(row["id"])
        if gid is not None:
            conn.execute(
                "UPDATE tours SET gid = ? WHERE id = ?",
                (gid, tour_id),
            )
        return tour_id
    cursor = conn.execute(
        "INSERT INTO tours (season_id, tour_number, gid) VALUES (?, ?, ?)",
        (season_id, tour_number, gid),
    )
    return int(cursor.lastrowid)


def _record_import(
    conn: sqlite3.Connection,
    *,
    source: str,
    identifier: str,
    season_number: int,
) -> int:
    started_at = time.time()
    cursor = conn.execute(
        (
            "INSERT INTO imports (source, source_identifier, season_number, started_at, status) "
            "VALUES (?, ?, ?, ?, ?)"
        ),
        (source, identifier, season_number, started_at, "running"),
    )
    import_id = int(cursor.lastrowid)
    conn.execute(
        "UPDATE imports SET finished_at = ?, status = ? WHERE id = ?",
        (time.time(), "success", import_id),
    )
    return import_id


def _parse_fight_code(code: str) -> tuple[int, int, int]:
    match = _FIGHT_CODE_PATTERN.fullmatch(code.strip())
    if not match:
        raise ValueError(f"Unrecognised fight code: {code!r}")
    return (
        int(match.group("season")),
        int(match.group("tour")),
        int(match.group("fight")),
    )


def _insert_fixture_results(
    conn: sqlite3.Connection,
    *,
    fixture_path: Path,
) -> tuple[int, dict[str, int]]:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    season_number = int(data.get("season_number") or 1)
    season_id = _ensure_season(conn, season_number)
    source_label = f"fixture_season_{season_number:02d}"
    import_id = _record_import(
        conn,
        source=source_label,
        identifier=str(fixture_path),
        season_number=season_number,
    )

    fights_inserted = 0
    participants_inserted = 0
    questions_inserted = 0
    results_inserted = 0

    for tour in data.get("tours", []):
        tour_number = int(tour.get("tour_number") or 0)
        gid = tour.get("gid")
        tour_id = _ensure_tour(
            conn,
            season_id=season_id,
            tour_number=tour_number,
            gid=int(gid) if isinstance(gid, int) else None,
        )
        for fight in tour.get("fights", []):
            fight_code = fight.get("code")
            if not fight_code:
                continue
            _, _, fight_number = _parse_fight_code(str(fight_code))
            letter = fight.get("letter")
            conn.execute("DELETE FROM fights WHERE fight_code = ?", (fight_code,))
            cursor = conn.execute(
                (
                    "INSERT INTO fights (tour_id, fight_number, ordinal, fight_code, letter, imported_at, source_path, import_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    tour_id,
                    fight_number,
                    fight_number,
                    fight_code,
                    letter,
                    time.time(),
                    str(fixture_path),
                    import_id,
                ),
            )
            fight_id = int(cursor.lastrowid)
            fights_inserted += 1

            participant_ids: list[int] = []
            seen_normalized: set[str] = set()
            players = fight.get("players", [])
            for seat_index, player in enumerate(players, start=1):
                display_name = _sanitize_name(player.get("name"))
                if not display_name or display_name in {"-", "—", "--"}:
                    display_name = f"Неизвестный игрок {seat_index}"
                normalized = _normalize_name(display_name)
                if normalized in seen_normalized:
                    normalized = f"{normalized}#{seat_index}"
                seen_normalized.add(normalized)
                total = int(player.get("total") or 0)
                cursor = conn.execute(
                    (
                        "INSERT INTO fight_participants (fight_id, display_name, normalized_name, seat_index, total_score) "
                        "VALUES (?, ?, ?, ?, ?)"
                    ),
                    (fight_id, display_name, normalized, seat_index, total),
                )
                participant_ids.append(int(cursor.lastrowid))
            participants_inserted += len(participant_ids)

            questions = fight.get("questions", [])
            for question in questions:
                order = int(question.get("order") or 0)
                nominal = int(question.get("nominal") or 0)
                theme = question.get("theme")
                cursor = conn.execute(
                    (
                        "INSERT INTO questions (fight_id, question_order, nominal, theme, source_row) "
                        "VALUES (?, ?, ?, ?, ?)"
                    ),
                    (fight_id, order, nominal, theme, None),
                )
                question_id = int(cursor.lastrowid)
                questions_inserted += 1

                results = list(question.get("results", []))
                for participant_id, result in zip(participant_ids, results):
                    delta = int(result.get("delta") or 0)
                    is_correct = 1 if result.get("is_correct") else 0
                    conn.execute(
                        (
                            "INSERT INTO question_results (question_id, participant_id, delta, is_correct) "
                            "VALUES (?, ?, ?, ?)"
                        ),
                        (question_id, participant_id, delta, is_correct),
                    )
                    results_inserted += 1

    return season_number, {
        "fights": fights_inserted,
        "participants": participants_inserted,
        "questions": questions_inserted,
        "question_results": results_inserted,
    }


def _import_season2(
    store: Season2ResultsStore,
    *,
    data_root: Path,
    manifest: Path,
) -> dict[str, int]:
    importer = Season2Importer(store=store, data_root=data_root, manifest_path=manifest)
    summary = importer.import_season()
    return summary.as_dict()


def _extract_historical_records(db_path: Path) -> tuple[list[dict], list[int]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        season_rows = conn.execute(
            "SELECT season_number FROM seasons ORDER BY season_number"
        ).fetchall()
        available_seasons = [int(row["season_number"]) for row in season_rows]

        fight_rows = conn.execute(
            (
                "SELECT f.id, f.fight_code, f.fight_number, f.ordinal, f.letter, "
                "t.tour_number, s.season_number "
                "FROM fights f "
                "JOIN tours t ON f.tour_id = t.id "
                "JOIN seasons s ON t.season_id = s.id "
                "ORDER BY s.season_number, t.tour_number, f.ordinal"
            )
        ).fetchall()

        fights: list[dict] = []
        for fight_row in fight_rows:
            fight_id = int(fight_row["id"])
            participant_rows = conn.execute(
                (
                    "SELECT display_name, normalized_name, seat_index, total_score "
                    "FROM fight_participants WHERE fight_id = ? ORDER BY seat_index"
                ),
                (fight_id,),
            ).fetchall()
            participants = [
                {
                    "display": str(row["display_name"]),
                    "normalized": str(row["normalized_name"]),
                    "total": int(row["total_score"]),
                }
                for row in participant_rows
            ]
            fights.append(
                {
                    "season_number": int(fight_row["season_number"]),
                    "tour_number": int(fight_row["tour_number"]),
                    "fight_code": str(fight_row["fight_code"]),
                    "ordinal": int(fight_row["ordinal"]),
                    "letter": fight_row["letter"],
                    "participants": participants,
                }
            )

        return fights, available_seasons
    finally:
        conn.close()
