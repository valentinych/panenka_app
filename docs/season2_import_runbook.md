# Season 2 Import Runbook

## Purpose
This runbook documents the end-to-end workflow for refreshing the Season 2 buzzer results dataset from the Google Sheet snapshots committed to the repository. It highlights the key differences from the Season 1 pipeline so operators can confidently re-run the import without re-discovering the quirks that motivated the Season 2 code path.

## Prerequisites
- Local Python environment with the project dependencies installed (`pip install -r requirements.txt`).
- Access to the Season 2 Google Sheet snapshots stored under `data/raw/season02`. If an updated extract is required, use the downloader in `scripts/season2/download_sheet_csvs.py` to regenerate the CSVs and `manifest.json`.
- Write access to the Season 2 staging database (defaults to `app/season2/season2_results.sqlite3` unless `PANENKA_RESULTS_DB` is set). The schema is managed automatically by `Season2ResultsStore`.

## Key differences vs. Season 1
1. **Fight identifiers are synthetic.** The Season 1 HTML export embedded `SxxEyyFzz` headers in every fight block; Season 2 tour tabs only expose ordinal numbers. The importer reconstructs fight codes as `S02E{tour}F{ordinal}` while persisting the originating CSV path and Google Sheet `gid` for traceability.【F:app/season2/importer.py†L104-L151】【F:app/season2/results_store.py†L39-L123】
2. **Player names are unavailable in tour tabs.** Unlike Season 1, the Season 2 fight matrices omit player headers. The current pipeline stores placeholder seat labels (`Seat 1`…`Seat 4`) and deterministic normalized identifiers (`s02e{tour}f{fight}_seat{n}`) so downstream enrichment jobs can join rosters from the aggregate sheets when they become available.【F:app/season2/importer.py†L153-L194】【F:app/season2/tour_sheet_parser.py†L17-L88】
3. **Zero values are blank.** Season 2 exports leave zero deltas empty; the parser normalises these blanks (and other unicode quirks) to integer zeros before inserting question results, which keeps validation logic consistent with Season 1.【F:app/season2/tour_sheet_parser.py†L30-L69】【F:app/season2/importer.py†L177-L194】

## Import steps
1. **(Optional) Refresh the raw data.** If the upstream Google Sheet changed, download fresh CSVs and manifest metadata:
   ```bash
   python scripts/season2/download_sheet_csvs.py --destination data/raw/season02
   ```
   The downloader preserves a manifest mapping each tour tab to its `gid` and saved filename for deterministic imports.【F:scripts/season2/download_sheet_csvs.py†L8-L118】
2. **Ensure the staging schema exists.** The importer will call `Season2ResultsStore.ensure_schema()` automatically, but you can also bootstrap manually when provisioning a new environment:
   ```bash
   python scripts/season2/bootstrap_results_schema.py
   ```
   This creates (or upgrades) the SQLite schema under the configured database path and seeds seasons 1–2 entries if needed.【F:scripts/season2/bootstrap_results_schema.py†L1-L39】【F:app/season2/results_store.py†L39-L147】
3. **Run the Season 2 importer.** Execute the CLI to load either all tours or a filtered list:
   ```bash
   python scripts/season2/import_results.py \
       --data-root data/raw/season02/csv \
       --manifest data/raw/season02/manifest.json
   ```
   Use `--tours 3 4` to limit the run and `--db-path` to target a custom SQLite file. The summary counters confirm how many fights, participants, questions, and deltas were inserted.【F:scripts/season2/import_results.py†L1-L46】【F:app/season2/importer.py†L42-L198】
4. **Verify the import.** Run the Season 2 verification script to confirm every fight contains five questions, totals reconcile, and no placeholder participants leaked into inactive seats:
   ```bash
   python scripts/season2/verify_results.py --pretty
   ```
   The command exits non-zero if any consistency check fails, which should block deployments until investigated.【F:scripts/season2/verify_results.py†L1-L45】【F:app/season2/verifier.py†L1-L120】
5. **Archive the summary.** Preserve the importer and verifier outputs (stdout) alongside the commit or deployment notes to maintain traceability across re-runs.

## Troubleshooting tips
- **Missing tours in the manifest.** Confirm the Season 2 spreadsheet is still shared publicly and the downloader user agent has not been blocked. Regenerating the manifest ensures new tours are picked up automatically.
- **SQLite locking errors.** The importer wraps inserts in a transaction per run. If multiple imports execute concurrently against the same database file, serialize them or point `PANENKA_RESULTS_DB` at per-user working copies.
- **Roster reconciliation.** Placeholder participants are expected until the roster enrichment job is implemented. Use the deterministic normalized IDs when joining with the `AllSeason2` flat table for manual checks.
