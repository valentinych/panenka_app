"""Download Season 2 spreadsheet tabs as CSV files."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0 (compatible; PanenkaSeason2Downloader/1.0)"
SPREADSHEET_ID = "1XtnUV3toMG4PjbJv9a-uU-IP9ICzJh7I_7zi_COysVY"

HTMLVIEW_ENDPOINT = (
    "https://docs.google.com/spreadsheets/d/"
    "{spreadsheet_id}/htmlview"
)
GVIZ_CSV_ENDPOINT = (
    "https://docs.google.com/spreadsheets/d/"
    "{spreadsheet_id}/gviz/tq?tqx=out:csv&gid={gid}"
)

# Basic transliteration map for Cyrillic characters to ASCII approximations.
CYRILLIC_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "i",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "c",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}
CYRILLIC_TRANSLIT.update({k.upper(): v.capitalize() for k, v in CYRILLIC_TRANSLIT.items()})

SHEET_PATTERN = re.compile(r"items.push\(\{name: \"([^\"]+)\",.*?gid: \"(\d+)\"", re.DOTALL)


@dataclass
class SheetInfo:
    name: str
    gid: str

    def slug(self) -> str:
        transliterated = "".join(CYRILLIC_TRANSLIT.get(ch, ch) for ch in self.name)
        normalized = unicodedata.normalize("NFKD", transliterated)
        ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^0-9a-zA-Z]+", "_", ascii_only).strip("_").lower()
        return slug or f"sheet_{self.gid}"


def _http_get(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        return response.read()


def fetch_sheet_catalog(spreadsheet_id: str) -> List[SheetInfo]:
    html = _http_get(HTMLVIEW_ENDPOINT.format(spreadsheet_id=spreadsheet_id)).decode("utf-8")
    entries = [SheetInfo(name=name, gid=gid) for name, gid in SHEET_PATTERN.findall(html)]
    if not entries:
        raise RuntimeError("No sheet metadata found; check spreadsheet accessibility.")
    return entries


def fetch_sheet_csv(spreadsheet_id: str, gid: str) -> str:
    data = _http_get(GVIZ_CSV_ENDPOINT.format(spreadsheet_id=spreadsheet_id, gid=gid))
    return data.decode("utf-8-sig")


def write_csv(path: Path, csv_text: str) -> int:
    rows = list(csv.reader(csv_text.splitlines()))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerows(rows)
    return len(rows)


def download_all(destination: Path, spreadsheet_id: str = SPREADSHEET_ID) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    csv_dir = destination / "csv"
    csv_dir.mkdir(exist_ok=True)

    manifest: List[dict] = []
    for index, sheet in enumerate(fetch_sheet_catalog(spreadsheet_id), start=1):
        csv_text = fetch_sheet_csv(spreadsheet_id, sheet.gid)
        filename = f"{index:02d}_{sheet.slug()}.csv"
        file_path = csv_dir / filename
        row_count = write_csv(file_path, csv_text)
        manifest.append(
            {
                "index": index,
                "name": sheet.name,
                "gid": sheet.gid,
                "filename": filename,
                "rows": row_count,
            }
        )
        print(f"Saved {sheet.name!r} (gid={sheet.gid}) to {file_path} [{row_count} rows]")

    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"manifest": manifest_path, "sheets": manifest}


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("data/raw/season02"),
        help="Directory where CSV files and manifest.json will be stored.",
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=SPREADSHEET_ID,
        help="Google Sheets document identifier.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        download_all(args.destination, args.spreadsheet_id)
    except Exception as exc:  # pragma: no cover - CLI convenience
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
