---
name: series-a-workflow
description: Constructs 1911–1953 historical and 1954–2026 PRC administrative GIS divisions in separate annual folders, then orchestrates Series A chronicle and newspaper indexing, scraping, OCR and 1911–1953 chronologies.
disable-model-invocation: true
---

# Series A End-to-End Archival Workflow (`1911–2026` GIS + `1911–1953` Chronicles)

Follow [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md). When executing steps sequentially, confirm the previous skill exited cleanly and passed every structural check before advancing to the next phase.

## Step 1A. Construct Historical `1911–1953` GIS Divisions

Run only if `./output/gis/adm_annual/` (`129` GeoJSON files) and the `750` target folders under `./output/chronicles/` have not yet been generated cleanly:

1. Invoke `/1.build-chgis-admin` to construct strictly `1911–1953` annual `adm_1`/`adm_2`/`adm_3` layers inside `./output/gis/adm_annual/`, `5` historical vector layers inside `./output/gis/layers/`, `common/defines/province_defines.json5` (`750` entries) and the `01 January 1953` baseline hand-off.

## Step 1B. Model PRC `1954–2026` Divisions, Lineage Graph and Crosswalk

Run `/2.build-prc-crosswalk` whenever post-`1953` annual PRC layers, functional-zone mappings or `schema_version: 2` gazetteer search indices have not yet been built:

1. Invoke `/2.build-prc-crosswalk` to model continuous `01 January 1954` to `01 January 2026` (`GMT+0`) PRC `adm_1`/`adm_2`/`adm_3` evolution in the separate `./output/gis/prc_annual_1954_2026/` folder (`219` GeoJSON files), compile `common/defines/prc_admin_lineage_1954_2026.json5`, build the `10` WGS84 reference layers under `./input/gis/modern/` and export `common/defines/modern_gazetteer_crosswalk.json5` (`schema_version: 2`, including every county's `unit_1990s_snapshot` and parent redirections for post-`1990` SEZs and split districts).
2. Run `python tests/verify_file_structure.py` and confirm `[VERIFY OK]` before starting Step 2.

## Step 2. Scrape Chronicles, Newspapers and Compile Chronologies

Orchestrate primary-source discovery, archival compilation, OCR/translation and `dd Month YYYY` (`GMT+0`) chronology generation across all `750` divisions:

1. Invoke `/3.orchestrate-chronicles` (which schedules `/4.index-province` -> `/5.scrape-province` -> `/6.ocr-translate-province` -> `/7.chronology-province` per prioritised wave).
2. Enforce across every division:
   - **Zero-JiuZhi Rule**: Hard ban on Ming, Qing and Republican county gazetteers (`旧志`) or modern `点校`/`影印` reprints inside `./output/chronicles/`, whilst retaining contemporaneous `1912–1953` press and official `公報` inside `./output/newspapers/`.
   - **Regional Publication-Year Cutoffs**: Mainland PRC `1979 <= pub_year <= 2000` (pick latest full-span edition `<= 2000`, reject `> 2000` and Round-2 `续志`), Taiwan `pub_year <= 2005`, Mongolia and Tuva `pub_year <= 2026` (to present).
   - **Resilience to Real-World Holdings**: Parent-county redirection for post-`1990` SEZs/New Areas/splits via `prc_admin_lineage_1954_2026.json5`, 4-rung shortened-title expansion for autonomous counties, multi-volume (`上/中/下`) sibling verification, `分志` Priority A–C fascicle tracking, upward fallback for chronicle-less Tibetan/frontier counties and unconditional compilation + yield tagging of sparse/ideological chronicles.
3. Run `python tests/verify_file_structure.py` after each wave completes.
