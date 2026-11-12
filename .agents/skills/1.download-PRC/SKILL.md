---
name: 1.download-PRC
description: Downloads modern PRC county-level divisions and Taiwan, Mongolia, and Tuvan Republic local-history reference layers, building the spatial crosswalk to 1912-1953 CHGIS and Tusi polygons for /1.download-all-provinces.
disable-model-invocation: true
---

# Step 0B: Modern PRC County Divisions and Peripheral Local-History Crosswalk

Whilst `/1.download-CHGIS` constructs `1912–1953` historical boundaries, modern local chronicles (`1980–2010` `新编地方志`) are compiled at the level of **modern PRC county-level jurisdictions (`县级行政区`, GB/T 2260)**, and local histories in **Taiwan, Mongolia and the Tuvan Republic** follow their own modern subnational hierarchies. Run `/1.download-PRC` after `/1.download-CHGIS` and before `/1.download-all-provinces` so downstream indexing and chronology agents can resolve modern local histories cleanly onto `1912–1953` counties and Tusi polities.

Consult [taxonomy_and_schemas.md](../1.download-all-provinces/references/taxonomy_and_schemas.md) for crosswalk schemas and local-history edge-case rules.

## Step 1. Modern PRC Administrative Divisions (`./gis/modern/prc_adm_<1|2|3>.geojson`)

1. Download and clean WGS84 (`EPSG:4326`) modern PRC administrative polygons up to **level 3 (`adm_3`)**—stopping at county-level units (`adm_1` provinces, autonomous regions, municipalities and SARs; `adm_2` prefectures and leagues; `adm_3` county-level units)—anchored to the `1990–2005` first-round gazetteer baseline (`v5_1990_citas_cnty`, modern GADM `CHN` levels 1–3 and 6-digit `GB/T 2260` codes, with Simplified/Traditional Chinese names and Pinyin).
2. Classify every PRC `adm_3` unit's subtype (`xian`, `autonomous_xian`, `county_level_shi`, `urban_qu`, `banner_qi`, `autonomous_qi`, `tequ`, `linqu`) and capture critical structural edge cases:
   - **Post-1953 renamings and upgrades**: Track renamed units (for example `迪化` -> `乌鲁木齐`, `绥远` -> `呼和浩特`, `安东` -> `丹东`) and `撤县设市` / `撤县设区` upgrades so searches match both `县志` and `市志`/`区志`.
   - **Metropolitan core districts (`市辖区`)**: Flag urban districts carved out of historic core counties (such as Beijing `宛平`/`大兴`, Shanghai `上海`/`宝山`, Nanjing `江宁`/`上元`, Chongqing `巴县`, Guangzhou `番禺`/`南海`, Wuhan `武昌`/`汉阳`) as requiring both district `区志` and overarching municipal `市志` (`大事记` + `军事志`).
   - **Frontier subdivisions**: Record where one large `1912` CHGIS `厅` or `府` split into multiple modern PRC counties or banners, ensuring every daughter county is linked to its parent historical polygon.
   - **Autonomous ethnic county titles**: Generate both the shortened title stripping ethnic autonomous suffixes (`酉阳土家族苗族自治县` -> `酉阳县志`) and the full official title (`酉阳土家族苗族自治县志`).
   - **Use of `地名志` (*Dimingzhi* / `地名录` / `地名词典`)**: Cross-check provincial and county `地名志` (for example `黑龙江省志·地名志`) when building the PRC-to-CHGIS crosswalk, as `地名志` systematically record sub-county and county `沿革` changes (abolished `设治局`, Manchukuo `街村`/`保甲`, township transfers and renamed bandit or frontier settlements).
   - **Big-city multi-volume (`上中下`) and standalone `分志` flagging**: For provincial capitals, direct-controlled municipalities and prefecture-level cities (`市辖区` + `市志`), populate crosswalk query templates not only for multi-volume `<City>市志` (`上、中、下册`) sets but also for standalone thematic books (`<City/Province>志·大事记`, `·军事志`, `·地名志`, `·建置沿革志` / `民政志`, `·公安志`).

## Step 2. Peripheral Local-History Baselines and Edge Cases (Taiwan, Mongolia, Tuvan Republic)

Export modern reference layers into `./gis/modern/` and encode each territory's structural edge cases inside `./common/defines/local_history_edge_cases.json5`:

1. **Taiwan (`./gis/modern/twn_adm_<1|2|3>.geojson`)**:
   - Include both `adm_2` counties/provincial cities (`縣市志`) and `adm_3` townships/county-administered cities/districts (`鄉鎮縣轄市區志`, including indigenous mountain townships `山地鄉`), linked to `1912–1945` Japanese *Shū*/*Chō*/*Gun*/*Banchi* divisions.
   - Flag preference for **`1990–2015` `重修` (full-revision) county and township chronicles** paired with `1912–1945` Japanese colonial surveys (`州管內概況及事務概要`, `郡要覽`, `理蕃誌稿`), avoiding sole reliance on censored 1950s–1960s first editions or post-1951-only `續修` continuations.
   - Explicitly disambiguate **ROC Fujian offshore `金門縣` (Kinmen) and `連江縣` (Matsu)** from PRC mainland Fuzhou `连江县` (`350122`) and `同安县`.
2. **Mongolia (`./gis/modern/mng_adm_<1|2>.geojson`)**:
   - Export modern 21 *aimags* plus Ulaanbaatar (`adm_1`) and ~330 *soums* (`adm_2`) in Cyrillic Mongolian (`mn_cyrl`), flagging `Bayan-Ölgii` for Kazakh + Mongolian bilingual local histories.
   - Remap **post-1994 enclave aimags** (`Darkhan-Uul` -> `Selenge`, `Orkhon` -> `Bulgan`, `Govisümber` -> `Dornogovi`) back to their `1932–1953` parent aimags, and intersect post-1931 *soums* against `1912–1931` Bogd Khanate / early MPR *khoshuuns* and *shabi* estates.
   - Encode the tiered local-history fallback hierarchy: *soum* jubilee monographs (`Сумын түүх`) -> *aimag* encyclopaedias (`Аймгийн түүх` / `Нэвтэрхий толь`) -> Mongolian Academy of Sciences (`ШУА`) regional compendia and pre-1921 Qing/ROC frontier treatises (`库伦志略`, `乌里雅苏台志略`, `科布多政务总册`).
3. **Tuvan Republic (`./gis/modern/tuva_adm_<1|2>.geojson`)**:
   - Export the Republic of Tyva (`adm_1`) and its 17 *kozhuuns* plus 2 cities (`adm_2` from GADM `RUS`), remapping post-1953 *kozhuun* splits (`Chedi-Khol` -> `Tandi / Ulug-Khem`) and flagging Tuva-Mongolia cross-border adjustments (`Davst / Uvs Basin`).
   - Pair *kozhuun* local histories (`ru` and `tyv`) with republic-wide **TIGPI (`ТИГПИ` / `ТНИИЯЛИ`)** scholarly compendia (*Istoriya Tuvy*, *Uchenye zapiski TIGPI*), since Tuvan local history relies heavily on republic-level archival series alongside district monographs.

## Step 3. Spatial Crosswalk Export (`./common/defines/modern_gazetteer_crosswalk.json5`)

1. Perform a geometric intersection between all modern local-history polygons (`prc_adm_3`, `twn_adm_2`/`twn_adm_3`, `mng_adm_1`/`mng_adm_2`, `tuva_adm_2`) and the historical `1912–1953` layers (`./gis/adm_<1|2|3>_<1912..1953>.geojson` and `./gis/tusi_1912_1953.geojson`), retaining overlaps with area ratio >= `0,05` or historical county-seat containment.
2. Write `./common/defines/modern_gazetteer_crosswalk.json5` with bidirectional lookups (`by_historical_province` and `by_modern_unit`) mapping every `1912–1953` `<province_slug>`, `<county_slug>` and `tusi_id` <-> covering `modern_unit_id` entries, candidate gazetteer query titles and edge-case flags so any modern monograph spanning multiple historical counties is downloaded once and linked cleanly.

## Step 4. Scanline Raster Audit and Handoff to `/1.download-all-provinces`

1. Rasterise `./gis/modern/` layers into `./tests/PRC_modern_adm_<1|2|3>.png` (retaining these test PNGs for user inspection) and visually confirm complete coverage with zero unmapped holes across Mainland China, Taiwan, Mongolia, Tuva and Tusi territories.
2. Verify `./common/defines/modern_gazetteer_crosswalk.json5` and `./common/defines/local_history_edge_cases.json5` exist and resolve cleanly so `/1.download-all-provinces` ([SKILL.md](../1.download-all-provinces/SKILL.md)) can run immediately next.
