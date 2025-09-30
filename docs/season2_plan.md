# Season 2 Processing Plan

## Objective
Prepare and import Season 2 match data from the provided Google Sheet into the application with parity to the Season 1 workflow.

## Stage 1 – Data Intake & Assessment
1. ✅ Download the Season 2 spreadsheet as CSV/Excel for reproducible local processing. *(scripts/season2/download_sheet_csvs.py + raw snapshot committed)*
2. ✅ Compare its schema to the Season 1 source (columns, tabs, naming) and document any structural differences. *(see `docs/season2_schema_comparison.md`)*
3. ✅ Draft normalization rules to align Season 2 raw data with Season 1 importer expectations. *(see `docs/season2_normalization_rules.md`)*

## Stage 2 – Transformation Logic Updates
1. ✅ Update or extend import scripts to handle Season 2-specific columns and edge cases. *(see `app/season2/tour_sheet_parser.py`)*
2. ✅ Add unit tests/fixtures that cover new transformations, ensuring legacy Season 1 behavior stays intact. *(see `tests/season2/test_tour_sheet_parser.py`)*
3. ✅ Validate transformed outputs against a small sample of Season 2 matches. *(see `tests/season2/test_tour_sheet_parser.py::test_sample_fights_snapshot`)*

## Stage 3 – Database Integration & Verification
1. ✅ Run migrations or seeders if new entities/fields are required for Season 2. *(see `app/season2/results_store.py` and `scripts/season2/bootstrap_results_schema.py`)*
2. ✅ Execute the importer on the full Season 2 dataset in a staging database. *(see `app/season2/importer.py` and `scripts/season2/import_results.py`)*
3. ✅ Verify the results in the app (statistics, leaderboards) and adjust if inconsistencies appear. *(see `app/season2/verifier.py`, `scripts/season2/verify_results.py`, and `tests/season2/test_verifier.py`)*

## Stage 4 – Documentation & Deployment
1. ✅ Document Season 2 import steps and notable differences from Season 1. *(see `docs/season2_import_runbook.md`)*
2. ✅ Update README/operations notes with instructions for rerunning the Season 2 import. *(see `README.md` → “Season 2 results data pipeline”)*
3. ✅ Prepare deployment checklist ensuring the new logic is promoted safely. *(see `docs/season2_deployment_checklist.md`)*
