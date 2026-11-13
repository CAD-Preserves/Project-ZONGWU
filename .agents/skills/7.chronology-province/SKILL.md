---
name: 7.chronology-province
description: Harmonises political, military and Tusi actor identifiers across provinces against output/gis/ boundaries and authors structured dd Month YYYY (GMT+0) chronologies inside output/chronicles/.
---

# 7. Harmonise Actors and Compile Province/County Chronologies

Follow [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md). Never write outputs to `input/` or top-level `chronicles/`.

## Authoritative Context Resolution

1. Resolve the division's `<chronicle_path>` from `common/defines/province_defines.json5`.
2. Load spatial boundary history (`1911–1953`) from `./output/gis/adm_annual/adm_<1|2|3>_<year>.geojson` and `./output/gis/layers/tusi_1912_1953.geojson`, plus modern crosswalk links in `common/defines/modern_gazetteer_crosswalk.json5` and `common/tusi/tusi_catalog.json5`.
3. Ingest all sibling `_zh_raw.md` and `_en_raw.md` transcripts from `<chronicle_path>/counties/*/ocr/` and linked press clips in `./output/newspapers/*/ocr/`.

## Actor Harmonisation (`actors_local.json5`)

Emit structured entity registries (`<chronicle_path>/actors_local.json5` and per-county `actors_local.json5`) resolving aliases consistently across languages and years:
- **Sovereign polities & regimes**: Beiyang Government, Nanjing Nationalist Government, PRC, Manchukuo, Mengjiang, East Hebei, Reorganised National Government, Japanese Governorates, Soviet/MPR/Tuvan organs and British/French/Portuguese concessions.
- **Military cliques & forces**: Zhili, Anhui, Fengtian, Kuomintang NRA armies/corps, Eighth Route/New Fourth/PLA field armies, provincial warlord armies (`Sichuan`, `Yunnan`, `Guangxi`, `Shanxi`, `Ma` cliques, `Sheng Shicai`), IJA units and irregular militias (`紅槍會`, `哥老會`).
- **Tusi & Indigenous Houses**: Link every ruling Tusi lineage to its canonical `tusi_id` in `common/tusi/tusi_catalog.json5`, recording `gaituguiliu` (`改土歸流`) de jure vs de facto transition dates.

## Chronology Style Contract (`chronology_en.md` / `chronology_zh.md`)

- Write bulleted chronological entries strictly dated as `dd Month YYYY` (for example `10 October 1911`, `01 January 1932`) using `GMT+0` time references.
- Cross-check border shifts directly against annual `adm_1`/`adm_2`/`adm_3` polygons and flag disputed sovereignty intervals explicitly.
- Author `chronology_en.md` in non-Oxford British English (`EN-GB`) alongside `chronology_zh.md` inside `<chronicle_path>/` and `<chronicle_path>/counties/<unit_slug>/`.
