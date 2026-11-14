---
name: 3.orchestrate-chronicles
description: Orchestrates phases 4.index-province through 7.chronology-province across the 750 divisions in province_defines.json5 using output/chronicles/ and output/newspapers/.
---

# 3. Orchestrate Primary-Source Chronicles Across All Divisions

Follow [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and read [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md) for directory trees, file formats and JSON5 schemas.

## Hard Constraints

- Never create or write under top-level `chronicles/` or `/input/chronicles/`.
- Always look up each target division's concrete output path from `"chronicle_path"` in `common/defines/province_defines.json5` (resolved inside `./output/chronicles/` across its `6` branches: `provinces/`, `municipalities/`, `autonomous_and_special/`, `occupied_and_leased/`, `frontier_and_outer/` and `tusi/<region>/`).
- Keep `./output/gis/adm_annual/` (`1911–1953`) and `./output/gis/prc_annual_1954_2026/` (`1954–2026`) strictly separate when passing spatial priors into Phases `4.` through `7.`.
- Always place multi-province contemporaneous `1912–1953` newspapers and official central/provincial `公報` under `./output/newspapers/<publication_slug>/` and link them via `common/sources/source_registry.json5`.
- Stage temporary scrape fragments strictly inside `./input/scrape_cache/` and prune them immediately after Stage B rejection or lossless `_orig.pdf` compilation into `./output/`.

## Wave Priority and Parent-County Deduplication

Process the `750` divisions in priority waves configured in `common/sources/series_a_sources_config.json5` (`wave_1` municipalities and provinces -> `wave_2` autonomous, occupied, leased and frontier divisions -> `wave_3` Feudatories):

1. **Pre-Resolve `1985–2000` Parent Jurisdictions**: Before scheduling constituent units inside a wave, load `common/defines/prc_admin_lineage_1954_2026.json5` and `common/defines/modern_gazetteer_crosswalk.json5` (`schema_version: 2`). Schedule canonical `1985–2000` parent counties before post-`1990` split districts, Special Economic Zones, New Areas and Xinjiang XPCC `师市` cities so child units resolve via `chronicle_availability: "redirected_to_1990s_parent"` and link the parent's `source_id` in `common/sources/source_registry.json5` without duplicate downloads.
2. **Enforce Corpus Cutoffs Across Waves**: Audit that no Mainland county chronicle violates the Zero-JiuZhi ban (no Ming, Qing or Republican county gazetteers or modern `点校`/`影印` reprints) and that every candidate respects its regional publication-year cutoff (`<= 2000` Mainland PRC, `<= 2005` Taiwan, `<= 2026` Mongolia and Tuva).

## Per-Division Execution Workflow

For each prioritised division slug in `common/defines/province_defines.json5`:

1. Invoke `4.index-province` to construct `<chronicle_path>/index_manifest.json5` (`schema_version: 2`) and update `common/sources/source_registry.json5`.
2. Invoke `5.scrape-province` to stage fragments into `./input/scrape_cache/`, run the Stage B pre-flight audit, compile lossless `<source_id>*_orig.pdf` + `<source_id>_meta.json5` containers into `./output/chronicles/` or `./output/newspapers/` and record multi-volume (`上/中/下`) or fascicle (`分志`) completeness.
3. Invoke `6.ocr-translate-province` to produce `_zh.pdf`, `_en.pdf`, `_zh_raw.md` and `_en_raw.md` inside sibling `ocr/` directories under `./output/` and score `historical_yield_1911_1953` in `_meta.json5`.
4. Invoke `7.chronology-province` to harmonise actors into `actors_local.json5` (with `1911–2026` toponym disambiguation and press/higher-admin triangulation for absent or low-yield county sources) and author structured `dd Month YYYY` (`GMT+0`) timelines (`chronology_en.md` in non-Oxford EN-GB and `chronology_zh.md`).

## Valid Terminal States and Quality Gates

- A county unit passes orchestration in any of these explicit states, provided regional cutoffs and the Zero-JiuZhi ban were strictly upheld:
  - `"complete"`: Full compliant local chronicle (`上/中/下` or unified monograph) scraped, OCR'd and chronologically integrated.
  - `"partial_volumes_or_fascicles"`: Partial multi-volume (`missing_volumes` logged) or chapter-split (`missing_fascicles` logged) *xinzhi* compiled with explicit gap notes and supplemented by higher-admin/press sources.
  - `"redirected_to_1990s_parent"`: Post-`1990` SEZ, New Area, XPCC `师市` or split district linked cleanly via `source_registry.json5` to its `1985–2000` parent county chronicle(s).
  - `"no_chronicle_published"` / `"not_digitised"` / `"fallback_higher_admin_only"`: Counties (including Tibetan and frontier units) with zero published or digitised compliant county chronicle resolved via prefectural `地区志`/`州志`/`盟志`, provincial `省志`, `BDRC`/frontier compendia and `1912–1953` press.
  - Any of the above whose retrieved chronicle is tagged `historical_yield_1911_1953: "low_ideological_or_sparse"` or `"minimal"`, which **must** remain compiled and OCR'd whilst `7.chronology-province` triggers mandatory multi-source triangulation.
- Run `python tests/verify_file_structure.py` after each wave completes to guarantee zero outputs leaked into `input/` or disallowed root folders and every `index_manifest.json5` source exists in `common/sources/source_registry.json5`.
