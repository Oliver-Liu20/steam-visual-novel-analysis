# Steam Visual Novel Analysis (2020–2025)

This repository builds an auditable dataset and report for Steam visual novels released from 2020 through 2025.

The current analysis universe combines:

1. Steam AppIDs present in both VNDB and the Steam `Visual Novel` tag (tag ID `3799`); and
2. VNDB-only Steam AppIDs whose VNDB relation type contains `complete`.

The expanded universe is enriched with Steam review summaries, VNDB release-level adult-content fields, and Gamalytic `copiesSold` estimates. The final workbook includes Chinese explanations intended for non-technical readers.

## Current dataset

- Original VNDB × Steam-tag intersection: 2,840 games
- Additional VNDB-only complete games: 1,820
- Expanded total: 4,660 games
- Games with `copiesSold`: 4,259
- Steam review summaries available: 4,660

These figures reflect the collection snapshot dated 2026-08-08.

## Pipeline

```text
VNDB + Steam tag + Gamalytic
             |
             v
        src/collect.py
             |
             v
  intersection and difference CSVs
             |
             v
    src/enrich_expanded.py
       /                 \
      v                   v
final master CSV    grouped summaries
      |                   |
      v                   v
src/plot_dense_scatter.py
             |
             v
src/build_expanded_workbook.mjs
             |
             v
Chinese Excel report and PNG charts
```

## Main files

- `src/collect.py`: collects VNDB releases, Steam tag-search results, and initial Gamalytic estimates; produces source intersections and differences.
- `src/enrich_expanded.py`: builds the expanded universe, fetches release-level VNDB details and Steam review summaries, refreshes Gamalytic estimates, and writes the final tables.
- `src/plot_dense_scatter.py`: creates Python density plots and median-trend comparisons.
- `src/build_expanded_workbook.mjs`: builds the final formatted Excel report.
- `data/processed/expanded/visual_novels_master_2020_2025.csv`: current master dataset.
- `outputs/expanded_vndb_complete_2020_2025/steam_visual_novels_expanded_2020_2025_cn_guide.xlsx`: current reader-facing workbook.

## Run the data pipeline

```powershell
python .\src\collect.py
python .\src\enrich_expanded.py
python .\src\plot_dense_scatter.py
```

Successful network responses are cached under `data/raw/`, which is intentionally excluded from Git. Re-running a stage reuses existing cache files unless a `--refresh-*` option is supplied.

To see supported refresh options:

```powershell
python .\src\collect.py --help
python .\src\enrich_expanded.py --help
```

## Build the Excel report

The workbook builder uses `@oai/artifact-tool`, supplied by the Codex workspace runtime used for this project:

```powershell
node .\src\build_expanded_workbook.mjs
```

The committed Excel file can be read without that runtime. Rebuilding it on another machine requires a compatible `@oai/artifact-tool` environment.

## Classification rules

For every Steam AppID, all linked VNDB releases are considered:

- any `has_ero=true` → non-all-ages;
- otherwise, at least one known `has_ero=false` → all-ages;
- all values missing → unknown.

`minage` and `uncensored` are preserved as descriptive fields but never replace `has_ero` for this classification.

## Interpretation notes

- `copiesSold` is a Gamalytic cumulative estimate at collection time, not official Steam sales and not sales during the release month.
- Missing sales estimates remain blank; they are not imputed.
- Review-based popularity groups are descriptive and do not imply causation.
- Free-game values are not directly comparable with paid unit sales.

## Data sources

- VNDB Kana API: https://api.vndb.org/kana
- Steam Visual Novel tag: https://store.steampowered.com/tags/en/Visual%20Novel/
- Steam review API documentation: https://partner.steamgames.com/doc/store/getreviews
- Gamalytic API documentation: https://api.gamalytic.com/reference/
