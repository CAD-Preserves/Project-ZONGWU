---
name: 2.build-prc-crosswalk
description: Downloads modern PRC, Taiwan, Mongolia and Tuva boundary references into input/gis/modern_reference/, assembles WGS84 layers under input/gis/modern/, constructs modern_gazetteer_crosswalk.json5 and renders diagnostic PNGs to tests/outputs/.
---

# 2. Build Modern Reference Layers and Gazetteer Crosswalk

Follow [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md). Do not duplicate lookup tables already held in `common/defines/local_history_edge_cases.json5`.

## Inputs and Outputs

- **Inputs**:
  - `common/paths.json5`, `common/gis/data_sources.json5`, `common/defines/province_defines.json5`, `common/defines/local_history_edge_cases.json5` and `common/tusi/tusi_catalog.json5`.
  - Historical baseline layers in `output/gis/adm_annual/` (`adm_3_1912..1953.geojson`) and `output/gis/layers/tusi_1912_1953.geojson`.
  - Downloaded modern raw datasets cached under `input/gis/modern_reference/` and `input/gis/gadm/`.
- **Outputs**:
  - `input/gis/modern/`: 10 clean WGS84 reference GeoJSON layers (`mng_adm_{1,2}`, `prc_adm_{1,2,3}`, `tuva_adm_{1,2}`, `twn_adm_{1,2,3}`). Note that these are reference inputs for local-history lookups and remain under `input/gis/modern/`.
  - `common/defines/modern_gazetteer_crosswalk.json5`: Spatial crosswalk mapping historical 1912–1953 counties and Tusi polities to modern jurisdictions and candidate gazetteer search titles.
  - `tests/outputs/`: `PRC_modern_adm_{1,2,3}.png` scanline verification plots.

## Execution

Run the pipeline entrypoint after `1.build-chgis-admin` has populated `output/gis/`:

```bash
python core/server/pipelines/G_download_and_crosswalk_modern_gis.py
```

## Verification Checks

1. Verify `input/gis/modern/` contains all 10 GeoJSON files.
2. Verify `common/defines/modern_gazetteer_crosswalk.json5` parses cleanly and maps modern units across Mainland PRC, Taiwan, Mongolia and Tuva.
3. Confirm `tests/outputs/PRC_modern_adm_1.png`, `PRC_modern_adm_2.png` and `PRC_modern_adm_3.png` render without geometry errors.
