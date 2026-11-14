---
name: 7.chronology-province
description: Harmonises political, military and Feudatory actor identifiers across provinces against 1911–1953 and 1954–2026 GIS boundaries, handles missing/partial/low-yield chronicles via multi-source triangulation and authors structured dd Month YYYY (GMT+0) chronologies inside output/chronicles/.
---

# 7. Harmonise Actors and Compile Province/County Chronologies

Follow [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md). Never write outputs to `input/` or top-level `chronicles/`.

## Authoritative Dual-Series Spatial Context Resolution

1. Resolve the division's `<chronicle_path>` and manifest from `common/defines/province_defines.json5` and `<chronicle_path>/index_manifest.json5`.
2. Load `1911–1953` spatial boundary history from `./output/gis/adm_annual/adm_<1|2|3>_<1911..1953>.geojson` and `./output/gis/layers/tusi_1912_1953.geojson`, alongside `common/tusi/tusi_catalog.json5`.
3. Load `1954–2026` PRC administrative evolution from `./output/gis/prc_annual_1954_2026/prc_adm_<1|2|3>_<1954..2026>.geojson`, `common/defines/prc_admin_lineage_1954_2026.json5` and `common/defines/modern_gazetteer_crosswalk.json5` (`schema_version: 2`):
   - Disambiguate retrospective `1980–2000` *xinzhi* place names (`张家界`, `黄山市`, `襄樊`, `香格里拉`, post-`1953` `撤县设市` or merged districts) cleanly back to their exact `1911–1953` county polygons (`大庸县`, `徽州`/`歙县`, `襄阳`, `中甸县`) without conflating boundary transfers across decades.
4. Ingest all sibling `_zh_raw.md` and `_en_raw.md` transcripts (across unified volumes, `_vol*` sets and `_fenzhi_*` booklets) from `<chronicle_path>/counties/*/ocr/` plus linked contemporaneous clips in `./output/newspapers/*/ocr/`.

## Actor Harmonisation (`actors_local.json5`)

Emit structured entity registries (`<chronicle_path>/actors_local.json5` and per-county `actors_local.json5`) resolving aliases consistently across languages and years:

- **Sovereign polities and regimes**: Beiyang Government, Nanjing Nationalist Government, PRC, Manchukuo, Mengjiang, East Hebei, Reorganised National Government, Japanese Governorates, Soviet/MPR/Tuvan organs and British/French/Portuguese concessions.
- **Military cliques and forces**: Zhili, Anhui, Fengtian, Kuomintang NRA armies/corps, Eighth Route/New Fourth/PLA field armies, provincial warlord armies (`Sichuan`, `Yunnan`, `Guangxi`, `Shanxi`, `Ma` cliques, `Sheng Shicai`), IJA units and irregular militias (`紅槍會`, `哥老會`).
- **Feudatory and Indigenous Houses**: Link every ruling Feudatory (`tusi`), Banner or monastic polity to its canonical `tusi_id` in `common/tusi/tusi_catalog.json5`, recording `gaituguiliu` (`改土歸流`) de jure vs de facto transition dates.
- **Source-Quality and Coverage Metadata**: Record `chronicle_availability`, `missing_volumes`, `missing_fascicles` and `source_insufficiency_flag` (`true` when the primary county chronicle is absent, partial or tagged `"low_ideological_or_sparse"`/`"minimal"`).

## Handling Missing, Partial or Low-Yield County Sources (`Problems #1, #2, #3, #4 & #9`)

1. **`redirected_to_1990s_parent` (Post-`1990` SEZs, New Areas and Splits)**: Resolve county history from the linked `parent_1990s_unit_ids` transcripts in `./output/` whilst keeping spatial scope bounded to the `1911–1953` historical polygon intersecting the `2026` unit.
2. **`no_chronicle_published` / `not_digitised` / `partial_volumes_or_fascicles`**: Explicitly note absent volumes (for example missing `下册` or missing `军事分志`) in a brief editorial header, then synthesise dated county events from prefectural chronicles (`地区志`/`州志`/`盟志`), provincial gazetteers (`省志·市县概况`/`省志·军事志`), `BDRC` frontier sources and `./output/newspapers/`.
3. **`historical_yield_1911_1953: "low_ideological_or_sparse"` or `"minimal"`**: Extract only verifiable dated administrative, fiscal, garrison, skirmish and boundary facts from the local chronicle; strip ungrounded ideological adjectives or undated hagiography; and elevate contemporaneous `政府公報`/`省政府公報`, `申報`/`大公報`/`中央日報` reports and adjacent-county *xinzhi* to primary triangulation sources. Never fabricate or extrapolate unattested dates.

## Chronology Style Contract (`chronology_en.md` / `chronology_zh.md`)

- Write bulleted chronological entries strictly dated as `dd Month YYYY` (for example `10 October 1911`, `01 January 1932`, `07 February 1938`) using `GMT+0` time references.
- Cross-check occupation corridors, enclaves and border shifts directly against annual `1911–1953` `adm_1`/`adm_2`/`adm_3` polygons and flag disputed sovereignty intervals explicitly.
- Author `chronology_en.md` in non-Oxford British English (`EN-GB`) alongside `chronology_zh.md` inside `<chronicle_path>/` and `<chronicle_path>/counties/<unit_slug>/`.
