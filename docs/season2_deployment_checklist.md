# Season 2 Deployment Checklist

This checklist ensures Season 2 data-processing changes are deployed safely across environments. Run through every item before promoting importer updates or refreshed data sets.

## Pre-deployment
- [ ] Confirm the repository is on the commit that passed CI and includes the latest Season 2 parsing/import changes (`app/season2/*`, `scripts/season2/*`).
- [ ] Regenerate or validate the Season 2 CSV snapshots and manifest if the upstream Google Sheet changed. Record the downloader output in release notes.【F:scripts/season2/download_sheet_csvs.py†L8-L118】
- [ ] Run the Season 2 importer against a staging database and capture the summary counters.
  ```bash
  python scripts/season2/import_results.py --data-root data/raw/season02/csv --manifest data/raw/season02/manifest.json
  ```
- [ ] Execute the verification script and ensure it exits successfully. Attach the JSON payload to the deployment ticket.
  ```bash
  python scripts/season2/verify_results.py --pretty
  ```
- [ ] Snapshot the staging database file (or take a managed backup) so it can be restored quickly if the production import deviates.

## Deployment
- [ ] Export the validated staging database to the production environment (for SQLite deployments, copy the file; for hosted databases, use `sqlite3 .dump` piped into the target).
- [ ] Apply environment-specific configuration (`PANENKA_RESULTS_DB`, cron entries, or data-volume mounts) required for the Season 2 importer jobs.
- [ ] Run the importer in production with the same manifest to ensure deterministic results. Keep stdout/stderr logs.

## Post-deployment
- [ ] Re-run the verification script against production data. Investigation is required if any check fails before closing the deployment.
- [ ] Update monitoring dashboards or alerts to include the Season 2 data tables (`fights`, `fight_participants`, `questions`, `question_results`).
- [ ] Close the deployment checklist by linking to the importer summary, verifier output, and stored database snapshot. This makes future reruns auditable.

For a detailed explanation of each step and Season 1 vs. Season 2 nuances, see `docs/season2_import_runbook.md`.
