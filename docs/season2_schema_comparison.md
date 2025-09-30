# Season 2 Sheet Schema Comparison

## Baseline: Season 1 Import Expectations
- Season 1 fight data is organised per tour with fight codes like `S01E02F07`, theme headers in the second row, total scores in the third row, and one row per nominal value (10–50) for the buzz outcomes. The importer relies on those headers and blank-column separators to detect fight blocks.【F:docs/tour_statistics_import.md†L106-L149】

## Season 2 Spreadsheet Inventory
- The Season 2 workbook now exposes 29 tabs, expanding beyond tour sheets to include player leaderboards (`Sheet12`), Elo-style history (`Sheet17`), clash matrices, cumulative stats, and even an "AnTour1" worksheet. The manifest captured during the snapshot lists all tabs with their gids and row counts.【F:data/raw/season02/manifest.json†L1-L205】

## Structural Differences Observed in Season 2

### 1. Additional summary and rating sheets
- `Sheet12` lists top performers with season totals, ranking deltas, and paired secondary metrics, which had no analogue in the Season 1 source ingest pipeline. (The hefty CSV export was dropped from the repo after the audit to keep the tree small.)
- `Sheet17` records multiple historical rating columns per player (e.g., per tour or per date ranges), again diverging from the single-tour focus that Season 1 ingestion assumed. Regenerate the sheet snapshot from Google Sheets when digging into those metrics.
- The workbook adds wide analytical tables such as `All Clashes`, a head-to-head matrix with derived aggregates (`sum`, `>0`, `tours`) at the far right. Those exports are also fetched on demand now that the repository only stores the manifests.

### 2. Tour sheets embed multi-section layouts
- Each `TourN` CSV now begins with a header row that repeats the fight ordinal (`1`) across column groups and appends side tables for tour hosts and inactive players ("Ведущие тура" / "не играли") immediately to the right.【F:data/raw/season02/csv/12_tour1.csv†L1-L2】
- Instead of Season 1 fight codes, the leading columns per fight hold summary metrics (`Нажатия`, `Сумма очков`, `Плюсы`, `Минусы`, plus percentage columns), mirroring the structure that also feeds the cumulative `AllSeason2` and `ALL ANSWERS` tabs. (Only the tour snapshots remain in-repo; regenerate the cumulative tables when cross-checking.)
- Fight grids still preserve five rows per nominal value (10–50), but they interleave `Host`/`Miss` flags with player scores inside the blocks, so the importer must ignore non-numeric markers that never appeared in Season 1 exports.【F:data/raw/season02/csv/12_tour1.csv†L5-L21】
- After the per-fight matrix, the sheet appends aggregate statistics tables that summarise press counts, score totals, and percentage splits by nominal value—additional content that Season 1 parsers never encountered and must skip explicitly.【F:data/raw/season02/csv/12_tour1.csv†L70-L80】

### 3. Cumulative per-question sheets replace simple fight listings
- `ALL ANSWERS` and `AllSeason2` flatten all fights into a tall table with the same summary metrics and embed `Host`/`Miss` annotations alongside per-player deltas, indicating the dataset distinguishes moderators from active participants in-line. (Snapshots for those wide tables can be recreated from the workbook when validation work begins.)
- These cumulative sheets finish with mini roll-ups (`плюсы`, `минусы`, `разница`, percentage columns) that were absent in Season 1, signalling the need for Season 2 ingestion to either leverage or explicitly discard these aggregates during transformation. Take a fresh extract when the importer needs to reason about them.

### 4. New analytics-oriented tabs
- Tabs like `plusstat`, `AVSQ`, `Градиентное`, `Треш`, and `AnTour1` provide season-wide analytics (score distributions, gradient analyses, alternate tour layouts). These did not exist in the Season 1 source and may require new downstream destinations or explicit exclusion from the importer scope.【F:data/raw/season02/manifest.json†L30-L203】

## Implications for Import Development
- The lack of fight codes and the presence of auxiliary markers (`Host`, `Miss`, host/absent rosters) mean the Season 1 column scanning logic must be extended to detect fight boundaries differently—likely via ordinal groups or by cross-referencing the cumulative sheets.
- Extra summary sections at the bottom/right of each sheet require robust guards so that only the five nominal rows per fight feed the question parser.
- Player rosters now span beyond active fighters in many tables, so normalisation utilities need to recognise and filter hosts or inactive participants before creating `fight_participants` records.
