---
name: 1.build-chgis-admin
description: Acquires historical CHGIS, GADM, HydroSHEDS and Natural Earth priors, models Tibet/Yushu reference polygons and Feudatory polities, builds watertight 1911–1953 annual adm_1/adm_2/adm_3 layers, verifies scanlines and exports output/chronicles/, defines and localisation.
---

# 1. Build CHGIS Historical Administrative Series (`1911–1953`)

Follow [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md). Never write outside the canonical `7`-folder workspace (`common`, `core`, `input`, `localisation`, `output`, `tests`, `.agents`).

## Inputs and Outputs

- **Inputs (read-only and caches)**:
  - Configs in `common/paths.json5`, `common/gis/data_sources.json5`, `common/gis/admin_mappings.json5`, `common/gis/tibet_reference_config.json5`, `common/gis/admin_reforms_1912_1953.json5`, `common/gis/transport_corridors.json5`, `common/tusi/tusi_catalog.json5`, `common/tusi/tusi_modelling_config.json5` and `common/defines/localisation_maps.json5`.
  - Raw source archives pulled into `input/gis/{chgis,gadm,hydrosheds,natural_earth}/`.
  - Internal Terrarium DEM caches (`terrarium_dem_z7_z8.npz`, `terrarium_tiles/`), HydroRIVERS pickle (`hydrorivers_china_ord3.pkl`), extracted frontline priors (`tibet_yushu_reference_polygons.geojson`) and CHGIS `1911` base GeoJSONs (`chgis_1911_adm{1,2,3}_base.geojson`) under `input/gis/priors/`.
  - Calibration images and plates under `input/tusi/` (`tibet_reference.png`, `plates.json5`, `frames/`).
- **Outputs (public exports and verification renders)**:
  - `./output/gis/adm_annual/`: Strictly `129` annual `adm_<1|2|3>_<1911..1953>.geojson` polygon layers. Never place post-`1953` (`1954–2026`) layers in this directory.
  - `./output/gis/layers/`: `elevation_contours.geojson`, `railways_1912_1953.geojson`, `roads_1912_1953.geojson`, `tusi_1912_1953.geojson` and `waterways_1912_1953.geojson`.
  - `./output/chronicles/`: `6`-branch hierarchy of `750` division folders.
  - `common/defines/province_defines.json5` and `localisation/{en_gb,fr,de}.json5`.
  - `tests/outputs/`: Verification PNG renders (`CHGIS_adm_*.png`, `tusi_verify_*.png`, `tibet_scanline_*.png`).

## Pipeline Execution Order

Run all steps from the workspace root in sequence:

```bash
python core/server/pipelines/A_download_and_reproject_gis.py
python core/server/pipelines/B_build_tibet_reference.py
python core/server/pipelines/C_build_tusi_divisions.py
python core/server/pipelines/D_build_annual_admin_series.py
python core/server/pipelines/B_build_tibet_reference.py --scanline-only
python core/server/pipelines/E_scanline_rasterise_adm.py --years 1911,1912,1936,1948
python core/server/pipelines/F_export_chronicles_and_defines.py
```

## `01 January 1953 -> 01 January 1954` Hand-Off Contract

The terminal `01 January 1953` (`GMT+0`) snapshot emitted by `D_build_annual_admin_series.py` serves as the immutable spatial starting point for `2.build-prc-crosswalk` when generating `./output/gis/prc_annual_1954_2026/`:

- Preserve deterministic `unit_id`, `name_en`, `name_ch`, `parent_adm1`, `parent_adm2`, `category`, `seat_lon` and `seat_lat` attributes across every feature in `adm_1_1953.geojson`, `adm_2_1953.geojson` and `adm_3_1953.geojson`.
- Record active vs abolished Feudatory (`tusi`) state on `01 January 1953` so early PRC autonomous-prefecture (`自治州`/`自治区`) reforms (`1954–1958`) link seamlessly across the `1953`/`1954` boundary without losing county seat provenance.

## Verification Checks

1. Confirm `B_build_tibet_reference.py --scanline-only` exits with status `0` and all `5` plates (`ref_1916`, `vid_1916`, `vid_1917`, `vid_1922`, `vid_1929`) meet `>= 95,0%` pixel agreement.
2. Confirm `./output/gis/adm_annual/` contains exactly `129` GeoJSON files (`1911–1953`) and `./output/gis/layers/` contains `5` GeoJSON files.
3. Confirm `F_export_chronicles_and_defines.py` emits all `750` `"chronicle_path"` targets under `./output/chronicles/`.
