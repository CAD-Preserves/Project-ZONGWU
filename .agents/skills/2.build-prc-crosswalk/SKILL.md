---
name: 2.build-prc-crosswalk
description: Models continuous 1954–2026 PRC annual adm_1/adm_2/adm_3 divisions into output/gis/prc_annual_1954_2026/, downloads Taiwan/Mongolia/Tuva/PRC references into input/gis/modern/, constructs prc_admin_lineage_1954_2026.json5 and modern_gazetteer_crosswalk.json5 v2 and renders diagnostic PNGs to tests/outputs/.
---

# 2. Model `1954–2026` PRC Divisions, Lineage Graph and Gazetteer Crosswalk

Follow [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md). Do not duplicate lookup tables already held in `common/defines/local_history_edge_cases.json5`, `common/gis/prc_admin_reforms_1954_2026.json5` or `common/gis/prc_functional_zones_and_sez.json5`.

## Inputs and Outputs

- **Inputs**:
  - `common/paths.json5`, `common/gis/data_sources.json5`, `common/gis/prc_admin_reforms_1954_2026.json5`, `common/gis/prc_functional_zones_and_sez.json5`, `common/defines/province_defines.json5`, `common/defines/local_history_edge_cases.json5` and `common/tusi/tusi_catalog.json5`.
  - Historical `1911–1953` hand-off baseline in `./output/gis/adm_annual/` (`adm_<1|2|3>_1912..1953.geojson`, anchored on `01 January 1953` `GMT+0`) and `./output/gis/layers/tusi_1912_1953.geojson`.
  - Downloaded modern raw datasets cached under `input/gis/modern_reference/` and `input/gis/gadm/`, `1990` CITAS county boundaries and MCA (`民政部`) `1980–2026` `GB/T 2260` annual change tables.
- **Outputs**:
  - `./output/gis/prc_annual_1954_2026/` *(separate folder resolved via `output.gis.prc_annual_dir`, never mixed into `./output/gis/adm_annual/`)*: `219` watertight WGS84 polygon layers (`prc_adm_<1|2|3>_<1954..2026>.geojson`) representing annual `01 January` (`GMT+0`) snapshots across all `73` years from `1954` up to `01 January 2026`.
  - `input/gis/modern/`: `10` clean WGS84 reference GeoJSON layers (`mng_adm_{1,2}`, `prc_adm_{1,2,3}`, `tuva_adm_{1,2}`, `twn_adm_{1,2,3}`) retained as local-history lookup inputs.
  - `common/defines/prc_admin_lineage_1954_2026.json5`: Directed acyclic lineage graph tracking splits, mergers, renamings, `撤县设市`, `撤县设区`, XPCC `师市` carvings and SEZ/New Area origins from `1954` through `2026`.
  - `common/defines/modern_gazetteer_crosswalk.json5` (`schema_version: 2`): Bidirectional spatial and temporal crosswalk pairing `1912–1953` historical units with `unit_2026_snapshot`, `unit_1990s_snapshot` (`1980–2000` compilation status/names/ranks), `parent_1990s_unit_ids` and clean 4-rung Mainland `zh_hans` `chronicle_search_plan` arrays.
  - `tests/outputs/`: `PRC_modern_adm_{1,2,3}.png` and landmark `PRC_adm_<1|2|3>_<year>.png` verification plots.

## Modelling Requirements Across `1954–2026` Epochs

1. **`1954–1979` Early and Mid-PRC Reorganisations**:
   - Model abolition of Greater Administrative Regions (`大行政区`) and dissolved provinces (`Rehe`, `Xikang`, `Suiyuan`, `Chahar`, `Pingyuan`, `Songjiang`, `Liaodong`, `Liaoxi`), formation of `Xinjiang Uygur AR` (`1955`), `Guangxi Zhuang AR` and `Ningxia Hui AR` (`1958`), `Tibet AR` (`1965`) and the `1969–1979` Inner Mongolia league partitioning and restoration.
   - Distinguish `1950s–1960s` rare-character county simplifications (`郿县 -> 眉县`, `盩厔 -> 周至`, `鄜县 -> 富县`, `葭县 -> 佳县`, `洵阳 -> 旬阳`, `沔阳 -> 仙桃`, `新淦 -> 新干`, `虔南 -> 全南`) from pre-`1949` imperial/Republican county names (`碾伯县`, `迪化县`).
2. **`1980–2000` Round-1 *Xinzhi* Compilation Window (`unit_1990s_snapshot`)**:
   - Model `Hainan Province` (`1988`), `Chongqing Municipality` (`1997`), `Hong Kong SAR` (`1997`), `Macau SAR` (`1999`), prefecture-to-city mergers (`地改市`) and the `1983–1997` county-to-city wave (`撤县设市`).
   - Record every county's exact name(s), administrative rank (`xian`, `autonomous_xian`, `banner_qi`, `autonomous_qi`, `county_level_shi`, `urban_qu`, `linqu`, `tequ`) and `gb_1990` code active between `1980` and `2000` inside `unit_1990s_snapshot`.
3. **`2001–2026` Contemporary Reorganisations**:
   - Apply MCA annual `GB/T 2260` change logs up to `01 January 2026`: post-`2000` `撤县设区`/`撤市设区`, metropolitan core district mergers (`卢湾+黄浦`, `闸北+静安`, `崇文+东城`, `宣武+西城`), post-`2000` renamings (`中甸 -> 香格里拉`, `思茅 -> 普洱`, `襄樊 -> 襄阳`, `潞西 -> 芒市`, `户县 -> 鄠邑区`), Tibetan prefecture upgrades (`日喀则`, `昌都`, `林芝`, `山南`, `那曲`), Xinjiang XPCC `师市` creations and `2024` Hotan counties (`和安县`, `和康县`).
   - Tag every county converted to `区` or upgraded to `市` after `2000` so `4.index-province` automatically blocks post-`2000` `区志`/`市志` titles and targets the `1990s` `县志`.
4. **Non-GB2260 Functional Zones, SEZs and New Areas**:
   - Map State-level New Areas (`雄安新区`, `浦东新区`, `滨海新区`, `两江新区`, `天府新区`), industrial parks (`苏州工业园区`), `经开区`/`高新区` and SEZs (`洋浦经济开发区`) to their exact `1985–2000` `parent_1990s_unit_ids` (`雄县`/`容城`/`安新`, `川沙`/`南汇`, `塘沽`/`汉沽`/`大港`, `江北`/`渝北`/`北碚`, `吴县`, `儋县`).
5. **Query-Hygiene Contract in Crosswalk Export**:
   - Strip all minority ethnicity tokens (complete `55`-ethnicity table in `local_history_edge_cases.json5`, plus `各族` and `自治`) recursively when generating shortened *xinzhi* queries (`张家川回族自治县志` -> `张家川县志` -> `张家川志`).
   - Never inject Traditional Chinese `<name_hant>志` strings or pre-`1949` imperial/Republican county names into Mainland PRC bare chronicle search queries.

## Execution

Run the pipeline entrypoint after `1.build-chgis-admin` has populated `./output/gis/`:

```bash
python core/server/pipelines/G_download_and_crosswalk_modern_gis.py
```

## Verification Checks

1. Confirm `./output/gis/prc_annual_1954_2026/` contains `219` watertight GeoJSON files (`1954–2026` × `3` levels) whilst `./output/gis/adm_annual/` remains strictly `129` GeoJSON files (`1911–1953`).
2. Confirm `input/gis/modern/` contains all `10` GeoJSON files.
3. Confirm `common/defines/prc_admin_lineage_1954_2026.json5` and `common/defines/modern_gazetteer_crosswalk.json5` (`schema_version: 2`) parse cleanly, cover Mainland PRC, Taiwan, Mongolia and Tuva and map post-`1990` SEZs/New Areas to `parent_1990s_unit_ids`.
4. Confirm `tests/outputs/PRC_modern_adm_{1,2,3}.png` and landmark `1954–2026` diagnostic renders show zero geometry or projection errors.
