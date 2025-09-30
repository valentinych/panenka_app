# Season 2 Normalization Rules

## Purpose
Translate the raw Season 2 Google Sheet exports into the same fight/question structures that the Season 1 importer expects so that downstream database schemas (`fights`, `questions`, `question_results`, etc.) remain unchanged.【F:docs/tour_statistics_import.md†L33-L118】

## Source Surfaces
- **Tour tabs (`Tour1`…`Tour14`)** remain the canonical source for question-by-question results. Each tab contains repeating column groups per fight with the fight ordinal in the first row and the five nominal rows (10–50) preserved underneath.【F:data/raw/season02/csv/12_tour1.csv†L1-L22】
- **Cumulative sheets (`ALL ANSWERS`, `AllSeason2`)** provide flat records per question with the same summary metrics as the tour tabs and will be used for cross-checks and for deriving fight codes that are no longer embedded in the tour headers. (The full workbook still exposes these tabs even though the oversized CSV snapshots were trimmed from the repo.)
- **Manifest metadata** identifies every worksheet’s `gid` and row count, allowing the downloader to map tab names to stored CSV snapshots for deterministic re-imports.【F:data/raw/season02/manifest.json†L1-L205】

## Fight Identification & Metadata
1. **Fight numbering**. Season 2 tour tabs no longer provide `SxxEyyFzz` codes. Use the ordinal header (`1`, `2`, …) combined with the containing tour number to derive synthetic fight numbers (`S02E{tour}F{ordinal}`).【F:data/raw/season02/csv/12_tour1.csv†L1-L15】
2. **Code reconstruction**. Join the ordinal/tour pair with the `AllSeason2` sheet, which records explicit `Тур`, `Бой`, and player rosters, to verify the mapping and capture any official fight identifiers if added later. (Refer back to the live workbook or regenerate a trimmed export when needed.)
3. **Sheet linkage**. Persist the Google Sheet `gid` from the manifest for each tour tab so imports remain traceable to the correct worksheet snapshot.【F:data/raw/season02/manifest.json†L1-L205】

## Column Segmentation
1. **Block detection**. Treat a change in ordinal at row 1 or an empty column as the start of a new fight block. Skip the trailing “Ведущие тура” and “не играли” rosters, which appear to the right of the fight grids.【F:data/raw/season02/csv/12_tour1.csv†L1-L9】
2. **Metric columns**. Within each block, the first six columns store per-fight aggregates (`Нажатия`, `Сумма очков`, `Плюсы`, `Минусы`, `Решающие`, `% попаданий`). Record these at the fight level for auditing but do not let them interfere with per-question parsing.【F:data/raw/season02/csv/12_tour1.csv†L5-L15】
3. **Player columns**. Active player names occupy the remaining columns until the host/inactive roster begins. Detect the roster boundary by the literal headers `Ведущие тура` and the consistent `Host`/`Miss` markers in the nominal rows.【F:data/raw/season02/csv/12_tour1.csv†L1-L22】

## Participant Normalization
1. **Active fighters**. Retain only columns whose nominal rows contain numeric deltas (positive or negative multiples of 10). Columns filled with `Host` or `Miss` across all nominal rows represent non-playing participants and must be excluded from `fight_participants`.【F:data/raw/season02/csv/12_tour1.csv†L9-L22】
2. **Score totals**. Use the `Сумма очков` row inside each fight block to populate `fight_participants.total_score`, matching the Season 1 expectation that totals come from the third row of each block.【F:data/raw/season02/csv/12_tour1.csv†L5-L15】【F:docs/tour_statistics_import.md†L71-L108】
3. **Name standardisation**. Apply the same lower-casing, trimming, and `ё→е` substitutions defined for Season 1 when creating/looking up `players`. (No Season 2-specific adjustments observed yet.)【F:docs/tour_statistics_import.md†L109-L134】

## Question & Theme Extraction
1. **Nominal rows**. The five nominal values still appear in column `F` of the fight block. Use them to iterate question order and nominal amount, ignoring the interspersed summary tables appended beneath the fight grids.【F:data/raw/season02/csv/12_tour1.csv†L5-L21】
2. **Delta parsing**. For each active player column, read the numeric delta in each nominal row. Non-numeric tokens (empty, `Host`, `Miss`) should be treated as zeros and skipped when persisting `question_results` records.【F:data/raw/season02/csv/12_tour1.csv†L9-L22】
3. **Themes**. Tour tabs continue to supply theme names above the nominal rows. Capture them per column group and normalise via the existing Season 1 theme loader. If theme cells are blank, fall back to the `ALL ANSWERS` table where the `Тема` column is populated for every question.【F:data/raw/season02/csv/04_all_answers.csv†L1-L24】

## Aggregate Tables & Non-imported Sheets
- Rows after the nominal grid (press counts by nominal, percentage breakdowns) should be ignored during question parsing but can be stored in auxiliary audit tables if needed.【F:data/raw/season02/csv/12_tour1.csv†L70-L80】
- Analytical tabs such as `plusstat`, `AVSQ`, `Градиентное`, and `Треш` remain outside the importer scope; they are inputs for future analytics but should not create fight/question rows directly. These oversized CSV exports were removed after the initial audit, so pull them on demand when exploring advanced metrics.
- Leaderboard sheets (`Sheet12`, `Sheet17`) provide season-level aggregates only; treat them as validation data to compare against aggregated Season 2 results post-import. Regenerate those snapshots from the Google Sheet if validation requires them.

## Validation Checklist
1. Recalculate per-player totals from the parsed question deltas and confirm they equal the `Сумма очков` row captured from the fight block.【F:data/raw/season02/csv/12_tour1.csv†L5-L15】
2. Sum `Плюсы`/`Минусы` per fight and verify they match the counts derived from positive/negative deltas.
3. Cross-check the imported fight roster against the `AllSeason2` sheet to ensure hosts/inactive players are not erroneously added to fights. (Use a freshly generated extract from the live workbook.)
4. Compare aggregated Season 2 leaderboard outputs with `Sheet12` totals to validate the Season 2 pipeline end-to-end before deployment. Generate those numbers from the workbook as part of the release checklist.
