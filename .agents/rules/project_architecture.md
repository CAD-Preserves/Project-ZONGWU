# Project Architecture Rules

All contributors and automation workflows inside `Project-Zongwu` must enforce the strict 7-folder workspace invariant and modular server separation.

## 1. Strict 7-Folder Root Layout

The repository root may contain **only** these 7 top-level directories:

1. `.agents/`: Agent rules, shared reference schemas and phase skills (`1.build-chgis-admin` to `7.chronology-province`).
2. `common/`: Declarative JSON and JSON5 configuration, path mappings (`common/paths.json5`), province defines (`common/defines/province_defines.json5`), GIS source configs, OCR routing configs and the global deduplication registry (`common/sources/source_registry.json5`).
3. `core/`: Runtime source code divided into `core/framework/`, `core/ui/` and `core/server/`.
4. `input/`: Read-only upstream priors, raw archives, reference images/frames, downloaded modern reference admin layers (`input/gis/modern/`) and ephemeral scrape/raster caches (`input/gis/priors/`, `input/scrape_cache/`).
5. `localisation/`: User-facing EN-GB, FR and DE localisation maps.
6. `output/`: Generated public exports (`output/gis/adm_annual/`, `output/gis/layers/`, `output/chronicles/`, `output/newspapers/`).
7. `tests/`: Automated structure/regression verification scripts (`tests/verify_file_structure.py`) and transient rendered inspection images (`tests/outputs/`).

Top-level `chronicles/`, `gis/` and `docs/` directories must **never** exist. `/input/chronicles/` must **never** exist because chronicles are generated public exports.

## 2. Boundary Between `input/` and `output/`

- **`input/`**: Strictly read-only priors or internal pulled caches consumed by pipelines (`A_`–`G_` and Skills `4.`–`7.`). Never write public chronicle dossiers, compiled `_orig.pdf` exports, OCR transcripts or final GIS shapefiles/GeoJSON outputs under `input/`.
- **`output/`**: Strictly generated public artefacts (`output/gis/`, `output/chronicles/`, `output/newspapers/`). Look up concrete division targets from `province_defines.json5` `"chronicle_path"` rather than hardcoding paths.

## 3. Configuration and Path Resolution

- Resolve all workspace paths in Python through `core/server/helpers/path_helpers.py` and `common/paths.json5`.
- Keep all lookup tables, category mappings, exonyms, Taiwan 1911 Cho mappings, Southern McMahon IDs and verification plate definitions in `common/` or `input/tusi/plates.json5`, never embedded as magic dictionaries in code.

## 4. `core/server/` Layout and Coding Standard

- `core/server/classes/<CamelCase>.py`: Strictly one class per file, under 1000 lines, no `__init__.py` (PEP 420) and no CLI `main()`.
- `core/server/helpers/<snake_case>.py`: Stateless helper modules containing zero classes, under 1000 lines.
- `core/server/pipelines/<Letter>_<snake_case>.py`: Thin CLI entrypoints (`A_` through `G_`), importing from `classes` and `helpers`.
- Follow 2-space Python indentation, `arg<#>_` parameter names, `# Convert from parameters` / `# Declare local instance variables.` / `# Return statement` section headers, space before function definition parameter lists (`def fn (arg1_x):`) and Doxygen docstrings (`@param`, `@return`).
- Author all prose in non-Oxford British English (`EN-GB`), use `GMT+0` and format dates as `dd Month YYYY`.
