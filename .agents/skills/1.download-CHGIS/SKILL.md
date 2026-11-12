---
name: 1.download-CHGIS
description: Downloads CHGIS and historical GIS divisions (1912-1953) for Mainland China, Taiwan, Mongolia, Tuva, and Tusi polities, exporting annual GeoJSONs, raster audits, and province defines.
disable-model-invocation: true
---

# Step 0: GIS Foundation, Tusi Polities and Division Registry (1912–1953, GMT+0)

Project-ZONGWU models *de jure* and contemporaneous wartime *de facto* administrative geography from **01 January 1912 to 31 December 1953 (GMT+0)** across **Mainland China, Taiwan, Mongolia and the Tuvan Republic**, treating autonomous **Tusi polities (`土司`)** as first-level divisions. All GIS deliverables sit in `./gis/`, declarative rules in `./common/gis/`, Tusi records in `./common/tusi/` and province stubs in `./chronicles/`.

Consult [taxonomy_and_schemas.md](../1.download-all-provinces/references/taxonomy_and_schemas.md) for the downstream directory and manifest contracts required by `/1.download-all-provinces`.

## Step 1. CHGIS, Subadministrative Divisions, Banners and Transport Corridors

1. Download CHGIS (`1911`/`1912` baseline) and frontier/peripheral GADM and Natural Earth layers via `./core/server/A_download_and_reproject_gis.py` (configured in `./common/gis/data_sources.json5`). Export GeoJSON files named `adm_<level>_<year>.geojson` in WGS84 (`EPSG:4326`), stopping at **level 3 (`adm_3`)**—never generate level-4 polygons.
2. Fetch and compile continuous annual **1 January (`00:00 GMT+0`)** *de jure* subadministrative divisions from `1912` to `1953` via `./core/server/C_build_annual_admin_series.py` and `./common/gis/admin_reforms_1912_1953.json5`:
   - **Mainland China**: Beiyang, Nationalist (ROC) and early PRC provincial, municipal, special-region and Inner Mongolian banner changes (including Rehe, Chahar, Suiyuan, Xikang, Qinghai, Ningxia, Pingyuan and 1950–1952 split provinces). Include Japanese occupation and puppet administrations (Manchukuo, East Hebei, Mengjiang, Wang Jingwei RNG corridors) **strictly within territory contemporaneously controlled on 1 January of that year**.
   - **Taiwan**: 1912–1920 *12 Chō*, 1921–1945 *5 Shū / 3 Chō* under the Empire of Japan, 1946–1950 *8 Counties / 9 Provincial Cities*, and 1951–1953 ROC county-city reform (keeping Kinmen and Lienkiang under Fujian).
   - **Mongolia**: Bogd Khanate banners and aimags (`1912–1923`), early MPR mountain aimags (`1924–1931`), and MPR aimag/soum reforms (`1932–1953`).
   - **Tuvan Republic**: Tannu Uriankhai (`1912–1914`), Uryankhay Krai (`1915–1921`), Tuvan People's Republic khoshuuns (`1922–1944`) and Tuva Autonomous Oblast (`1945–1953`).
3. Compile contemporaneous transport networks (`./gis/roads_1912_1953.geojson`, `./gis/railways_1912_1953.geojson`, `./gis/waterways_1912_1953.geojson`) using `./common/gis/transport_corridors.json5` so downstream chronology and mapping steps can interpolate army movements along historical corridors.

## Step 2. Tusi Polities (`土司`)

1. Conduct a comprehensive literature review of Tusi polities and frontier chieftaincies across Sichuan, Xikang, Yunnan, Guizhou, Guangxi, Qinghai, Gansu and Tibet active between `1912` and `1953`.
2. Launch three coordinated subagents:
   - `1. Scraper`: compiles every documented Tusi polity, its rank (`宣慰司`, `宣抚司`, `安抚司`, `长官司`, `土千户`, `土百户`), succession dates, `改土归流` abolition dates and parent province, forwarding structured records to `2. Mapper`.
   - `2. Mapper`: combines Step 1 subadministrative divisions, natural watershed/ridge boundaries, scraped historical maps and kriged settlements (`gns_*` and `v6_1911_twn_pts`) via `./core/server/B_build_tusi_divisions.py` to build `./common/tusi/tusi_catalog.json5` and `./gis/tusi_1912_1953.geojson`.
   - `3. Verifier`: visually inspects and fact-checks **every single deliverable** from `2. Mapper` using web research and historical gazetteers; if any boundary, lifespan or parent attribution is inaccurate, `3. Verifier` rejects it back to `2. Mapper` and `1. Scraper`.
3. Loop until `3. Verifier` signs off all Tusi units, and independently verify `3. Verifier`'s sign-off as parent coordinator before moving on.

## Step 3. Scanline Rasterisation and Visual Audit

1. Run `./core/server/D_scanline_rasterise_adm.py` to rasterise each year (`1912–1953`) at levels 1–3 into `./tests/CHGIS_adm_<level>_<year>.png`. **Do not delete** these test PNGs when finished so the user can inspect them.
2. Visually inspect each 1 January (`00:00 GMT+0`) image for historical and contemporaneous territorial accuracy across Mainland China, Taiwan, Mongolia, Tuva and Tusi enclaves.
3. If any visual inspection reveals a historical or geometric error, you must state `'I HAVE FAILED MYSELF'` and return to Step 1 to fix the underlying rules or polygons before continuing.

## Step 4. Chronicles Scaffolding and Handoff to `/1.download-PRC`

1. Run `./core/server/E_export_chronicles_and_defines.py` to create `./chronicles/<province_slug>/` for every first-level division and Tusi polity (`category: "tusi"`), alongside `./common/defines/province_defines.json5` and `./localisation/{en_gb,fr,de}.json5`.
2. Verify that `./common/defines/province_defines.json5`, `./common/tusi/tusi_catalog.json5` and annual `./gis/adm_<1|2|3>_<1912..1953>.geojson` files are complete and consistent, then hand off to `/1.download-PRC` ([SKILL.md](../1.download-PRC/SKILL.md)) to construct the modern PRC county and Taiwan/Mongolia/Tuva local-history crosswalk before running `/1.download-all-provinces` ([SKILL.md](../1.download-all-provinces/SKILL.md)).
