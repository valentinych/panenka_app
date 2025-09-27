import argparse
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple
from urllib.parse import quote
from urllib.request import Request, urlopen

from .question_store import QuestionRecord, question_store

SPREADSHEET_ID = "1JnSeNlpCq1XMz3mmROCOGCG5j0WpGNVlUsMeqNPqh-8"
GVIZ_ENDPOINT = (
    "https://docs.google.com/spreadsheets/d/" "{spreadsheet_id}/gviz/tq?tqx=out:json&sheet={sheet}"
)
USER_AGENT = "Mozilla/5.0 (compatible; PanenkaImporter/1.0)"

DATE_CLEAN_RE = re.compile(r"^(?P<date>[^()]+?)(?:\s*\((?P<editor>[^()]+)\))?$")
DATE_FORMATS = (
    "%d.%m.%Y",
    "%Y.%m.%d",
    "%d.%m.%y",
)


@dataclass
class ParsedQuestion:
    season_number: int
    row_number: int
    played_at_raw: Optional[str]
    played_at: Optional[str]
    editor: Optional[str]
    topic: Optional[str]
    question_value: Optional[int]
    author: Optional[str]
    question_text: Optional[str]
    answer_text: Optional[str]
    taken_count: Optional[int]
    not_taken_count: Optional[int]
    comment: Optional[str]

    def as_record(self) -> QuestionRecord:
        return (
            self.season_number,
            self.row_number,
            self.played_at_raw,
            self.played_at,
            self.editor,
            self.topic,
            self.question_value,
            self.author,
            self.question_text,
            self.answer_text,
            self.taken_count,
            self.not_taken_count,
            self.comment,
        )

    def as_dict(self) -> dict:
        return {
            "season_number": self.season_number,
            "row_number": self.row_number,
            "played_at_raw": self.played_at_raw,
            "played_at": self.played_at,
            "editor": self.editor,
            "topic": self.topic,
            "question_value": self.question_value,
            "author": self.author,
            "question_text": self.question_text,
            "answer_text": self.answer_text,
            "taken_count": self.taken_count,
            "not_taken_count": self.not_taken_count,
            "comment": self.comment,
        }


def _fetch_season_data(season_number: int) -> Tuple[dict, List[dict]]:
    sheet_name = quote(f"Сезон {season_number}")
    url = GVIZ_ENDPOINT.format(spreadsheet_id=SPREADSHEET_ID, sheet=sheet_name)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        payload = response.read().decode("utf-8")
    prefix = "/*O_o*/\ngoogle.visualization.Query.setResponse("
    suffix = ");"
    if not payload.startswith(prefix) or not payload.endswith(suffix):
        raise ValueError(f"Unexpected response format for season {season_number}")
    data = json.loads(payload[len(prefix) : -len(suffix)])
    table = data.get("table") or {}
    rows = table.get("rows") or []
    return data, rows


def _parse_played_at(value: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not value:
        return None, None, None
    value = value.strip()
    if not value:
        return None, None, None

    editor: Optional[str] = None
    match = DATE_CLEAN_RE.match(value)
    date_part = value
    if match:
        date_part = match.group("date").strip()
        editor_value = match.group("editor")
        if editor_value:
            editor = editor_value.strip() or None
    date_part = date_part.replace("\\u00a0", " ").strip()
    parsed_date: Optional[str] = None
    normalized = date_part.replace("/", ".").replace("-", ".")
    for fmt in DATE_FORMATS:
        try:
            parsed_date = datetime.strptime(normalized, fmt).date().isoformat()
            break
        except ValueError:
            continue
    return value, parsed_date, editor


def _coerce_int(value: Optional[object]) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int,)):
        return int(value)
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(" ", "")
        if not cleaned:
            return None
        try:
            return int(float(cleaned))
        except ValueError:
            return None
    return None


def _coerce_text(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if cleaned else None
    return str(value)


def _row_to_question(
    season_number: int,
    row_index: int,
    header_rows: int,
    row: dict,
) -> Optional[ParsedQuestion]:
    cells = row.get("c") or []

    def cell_value(index: int) -> Optional[object]:
        if index >= len(cells):
            return None
        cell = cells[index]
        if not cell:
            return None
        return cell.get("v")

    raw_date = _coerce_text(cell_value(0))
    topic = _coerce_text(cell_value(1))
    question_value = _coerce_int(cell_value(2))
    author = _coerce_text(cell_value(3))
    question_text = _coerce_text(cell_value(4))
    answer_text = _coerce_text(cell_value(5))
    taken_count = _coerce_int(cell_value(6))
    not_taken_count = _coerce_int(cell_value(7))
    comment = _coerce_text(cell_value(8))

    if not any(
        (
            raw_date,
            topic,
            question_value,
            author,
            question_text,
            answer_text,
            taken_count,
            not_taken_count,
            comment,
        )
    ):
        return None

    played_at_raw_cleaned, parsed_date, editor = _parse_played_at(raw_date)
    row_number = row_index + 1 + header_rows

    return ParsedQuestion(
        season_number=season_number,
        row_number=row_number,
        played_at_raw=played_at_raw_cleaned,
        played_at=parsed_date,
        editor=editor,
        topic=topic,
        question_value=question_value,
        author=author,
        question_text=question_text,
        answer_text=answer_text,
        taken_count=taken_count,
        not_taken_count=not_taken_count,
        comment=comment,
    )


def _iter_season_questions() -> Iterator[ParsedQuestion]:
    seen_signatures = set()
    season_number = 1
    while True:
        data, rows = _fetch_season_data(season_number)
        signature = data.get("sig")
        if signature in seen_signatures:
            break
        seen_signatures.add(signature)

        table = data.get("table") or {}
        header_rows = table.get("parsedNumHeaders") or 0
        for row_index, row in enumerate(rows):
            parsed = _row_to_question(season_number, row_index, header_rows, row)
            if parsed:
                yield parsed
        season_number += 1


def _dump_fixture(path: Path, questions: Sequence[ParsedQuestion]) -> None:
    payload = [question.as_dict() for question in questions]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def import_questions(*, dump_fixture_path: Optional[Path] = None) -> int:
    start = time.time()
    questions = list(_iter_season_questions())
    if dump_fixture_path:
        _dump_fixture(dump_fixture_path, questions)
    count = question_store.replace_all(q.as_record() for q in questions)
    elapsed = time.time() - start
    print(f"Imported {count} questions in {elapsed:.2f}s across {len({q.season_number for q in questions})} seasons.")
    return count


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Import trivia questions from Google Sheets.")
    parser.add_argument(
        "--dump-fixture",
        type=Path,
        help="Optional path to write imported questions as a JSON fixture.",
    )
    args = parser.parse_args(argv)

    try:
        import_questions(dump_fixture_path=args.dump_fixture)
    except Exception as exc:  # pragma: no cover - manual execution helper
        print(f"Failed to import questions: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
