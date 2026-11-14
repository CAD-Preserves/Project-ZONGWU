# Project Architecture Rules

All contributors and automation workflows inside `Project-Zongwu` must enforce the strict 7-folder workspace invariant and modular server separation.

## 1. Strict 7-Folder Root Layout

The repository root may contain **only** these 7 top-level directories:

1. `.agents/`: Agent rules, shared reference schemas and phase skills (`series-a-workflow` plus `1.build-chgis-admin` to `7.chronology-province`).
2. `common/`: Declarative JSON and JSON5 configuration, path mappings (`common/paths.json5`), province defines (`common/defines/province_defines.json5`), `1954–2026` PRC administrative reform and functional-zone tables (`common/gis/`), lineage and crosswalk defines (`common/defines/`), OCR routing configs and the global deduplication registry (`common/sources/source_registry.json5`).
3. `core/`: Runtime source code divided into `core/framework/`, `core/ui/` and `core/server/`.
4. `input/`: Read-only upstream priors, raw archives, reference images/frames, downloaded modern reference admin layers (`input/gis/modern/`) and ephemeral scrape/raster caches (`input/gis/priors/`, `input/scrape_cache/`).
5. `localisation/`: User-facing EN-GB, FR and DE localisation maps.
6. `output/`: Generated public exports organised across separate annual and archival trees:
   - `output/gis/adm_annual/`: strictly `1911–1953` historical annual layers (`129` GeoJSON files).
   - `output/gis/prc_annual_1954_2026/`: separate `1954–2026` PRC annual administrative layers (`219` GeoJSON files from `01 January 1954` to `01 January 2026`, `GMT+0`).
   - `output/gis/layers/`: `5` historical thematic vector layers (`1911–1953`).
   - `output/chronicles/`: `6`-branch hierarchy of `750` division folders.
   - `output/newspapers/`: contemporaneous `1912–1953` multi-province press and official government gazettes (`公報`).
7. `tests/`: Automated structure/regression verification scripts (`tests/verify_file_structure.py`) and transient rendered inspection images (`tests/outputs/`).

Top-level `chronicles/`, `gis/` and `docs/` directories must **never** exist. `/input/chronicles/` must **never** exist because chronicles are generated public exports. Keep `output/gis/adm_annual/` (`1911–1953`) and `output/gis/prc_annual_1954_2026/` (`1954–2026`) strictly separate.

## 2. Boundary Between `input/` and `output/`

- **`input/`**: Strictly read-only priors or internal pulled caches consumed by pipelines (`A_`–`G_` and Skills `4.`–`7.`). Never write public chronicle dossiers, compiled `_orig.pdf` exports, OCR transcripts or final GIS shapefiles/GeoJSON outputs under `input/`.
- **`output/`**: Strictly generated public artefacts (`output/gis/`, `output/chronicles/`, `output/newspapers/`). Look up concrete division targets from `province_defines.json5` `"chronicle_path"` rather than hardcoding paths.

## 3. Configuration and Path Resolution

- Resolve all workspace paths in Python through `core/server/helpers/path_helpers.py` and `common/paths.json5` (including `output.gis.adm_annual_dir` for `1911–1953` and `output.gis.prc_annual_dir` for `1954–2026`).
- Keep all lookup tables, category mappings, exonyms, Taiwan `1911` Cho mappings, Southern McMahon IDs, `1954–2026` PRC administrative reform/SEZ tables and verification plate definitions in `common/` or `input/tusi/plates.json5`, never embedded as magic dictionaries in code.

## 4. `core/server/` Layout and Coding Standard

- `core/server/classes/<CamelCase>.py`: Strictly one class per file, under `1000` lines, no `__init__.py` (PEP 420) and no CLI `main()`.
- `core/server/helpers/<snake_case>.py`: Stateless helper modules containing zero classes, under `1000` lines.
- `core/server/pipelines/<Letter>_<snake_case>.py`: Thin CLI entrypoints (`A_` through `G_`), importing from `classes` and `helpers`.
- Follow `2`-space Python indentation, `arg<#>_` parameter names, `# Convert from parameters` / `# Declare local instance variables.` / `# Return statement` section headers, space before function definition parameter lists (`def fn (arg1_x):`) and Doxygen docstrings (`@param`, `@return`).
- Author all prose in non-Oxford British English (`EN-GB`), use `GMT+0` and format dates as `dd Month YYYY`.

## 5. Archival Source Admissibility and Regional Cutoffs

All automated indexing (`4.index-province`), scraping (`5.scrape-province`), OCR (`6.ocr-translate-province`) and chronology assembly (`7.chronology-province`) must enforce these corpus guardrails:

1. **Zero-JiuZhi Rule (Hard Ban on Ming, Qing and Republican Gazetteers)**: Never index, scrape or store pre-`1949` imperial or Republican county/prefectural gazetteers (`旧志`) — or modern `点校` / `影印` reprints of `旧志` — inside `output/chronicles/`. Contemporaneous `1912–1953` newspapers and official central/provincial government gazettes (`公報`) remain admissible strictly inside `output/newspapers/`.
2. **Regional Publication-Year Cutoffs**:
   - **Mainland PRC (`mainland_prc`)**: `1979 <= pub_year <= 2000`. Prefer the latest full-span edition (`通贯古今`) with `pub_year <= 2000` (for example `1994` over `1986`); hard-reject `pub_year > 2000` compilations and Round-2 `续志` starting from `1978` onwards because they drop 1980s/1990s eyewitness testimonies.
   - **Taiwan and ROC Fujian Offshore (`taiwan`: Taiwan, Penghu, Kinmen and Lienchiang/Matsu)**: `pub_year <= 2005`. Prefer `1985–2005` `重修` county/city and township `鄉鎮市區志` paired with `1911–1945` Japanese `州/廳管內概況`, `郡要覽` and `理蕃誌稿` surveys; hard-reject `pub_year > 2005` editions and Qing Taiwan `府志`/`縣志` reprints.
   - **Mongolia (`mongolia`) and Tuvan Republic (`tuva_republic`)**: `pub_year <= 2026` (may extend to the present day). `Сумын түүх`, `Аймгийн нэвтэрхий толь`, `ШУА` monographs and Tuvan `ТНИИЯЛИ` / `ТИГПИ` (`История Тувы`, `Учёные записки`, kozhuun histories) remain admissible up to `2026`.
3. **Unconditional Retention of Valid Low-Yield Chronicles**: Never discard a compliant chronicle for ideological padding or sparse `1911–1953` administrative detail; always compile `_orig.pdf`, run OCR and annotate `historical_yield_1911_1953` in `<source_id>_meta.json5`.
