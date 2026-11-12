---
name: 2.index-province
description: Indexes and compiles a gazetteer, newspaper, and Tusi source manifest for a single province or first-level division, complete with URLs and scraper instructions for /3.scrape-province.
---

# Index Province Sources

Compile a complete, deduplicated, time-domain-verified source manifest (`./chronicles/<province_slug>/index_manifest.json5`) for one first-level division—resolving `1912–1953` counties via modern PRC county-level divisions and Taiwan/Mongolia/Tuva local-history baselines, discovering bulk dumps on Wikimedia Commons and open archives, and indexing contemporaneous `1912–1953` newspapers and Tusi records for `/3.scrape-province`.

Read [taxonomy_and_schemas.md](../1.download-all-provinces/references/taxonomy_and_schemas.md) for exact JSON5 schemas, time-domain rules and regional edge cases, and `./common/ocr/ocr_translation_config.json5` for valid `language_orig` and `script_direction` codes.

## Step 1. Resolve Spatial Scope and Modern Crosswalk

1. Look up `<province_slug>` in `./common/defines/province_defines.json5` to obtain `name`, `name_zh`, `category`, `active_years` and `gis_unit_ids`.
2. Inspect `./gis/adm_2_<year>.geojson` and `./gis/adm_3_<year>.geojson` across `active_years` to enumerate every constituent historical `adm_2` and `adm_3` (`<county_slug>`), plus overlapping Tusi entries in `./common/tusi/tusi_catalog.json5`.
3. Load `./common/defines/modern_gazetteer_crosswalk.json5` and `./common/defines/local_history_edge_cases.json5` (created by `/1.download-PRC`) to map every historical `adm_3` unit onto its covering **modern PRC county-level divisions (`GB/T 2260`)** or **Taiwanese, Mongolian and Tuvan local-history units** (`modern_unit_id`, `covered_historical_adm3`, search queries and edge-case flags).

## Step 2. Generalised Repository and Dump Discovery

Before running narrow unit-by-unit queries, execute a generalised discovery sweep to locate where relevant digital dumps, bulk scans and mirror collections actually reside:

1. **Wikimedia Commons and Wikisource**:
   - Query the MediaWiki API (`commons.wikimedia.org/w/api.php` using `list=search` and `generator=categorymembers`) and `zh` / `ja` / `ru.wikisource.org` across provincial gazetteer and Republican/colonial press categories (for example `Category:地方志`, `Category:中華民國地方志`, `Category:中國近代報紙`, `Category:臺灣日日新報`, `File:NLC...`, `File:CADAL...`, plus Japanese, Russian and Mongolian archival categories).
   - Extract direct file pages (`PDF`, `DjVu`), multi-volume category trees and original upload metadata (checking edition/era titles before adding to the manifest).
2. **Open Archives, Academic Dumps and Web Mirrors**:
   - Run generalised `search_web` discovery queries combining province/region/newspaper names with dump and file-host patterns (`filetype:pdf`, `filetype:djvu`, `site:archive.org`, Harvard Dataverse, Zenodo, HuggingFace, GitHub/GitLab dataset mirrors, NLC open portals, Taiwan Memory / Sinica `臺灣方志網`, NDL Digital Collections / JACAR, CyberLeninka / TIGPI and university digital repositories).
   - Record discovered dump indices, bulk archive identifiers and mirror URLs in `scraper_notes` so `/3.scrape-province` downloads directly from the cleanest open host.

## Step 3. Unit-by-Unit Query Construction and Edge Cases

Construct targeted queries for every mapped modern unit and historical entity:

- **Mainland PRC Counties (`县`, `自治县`, `县级市`, `市辖区`, `旗`, `自治旗`, `特区`, `林区`)**:
  - Search both the shortened `<BaseName>县志` / `旗志` (stripping ethnic autonomous suffixes) and the full official title, alongside post-1953 renamings and `市志` titles for upgraded cities.
  - For historic core counties absorbed into urban **`市辖区`**, index **both** the district `区志` and the overarching municipal `市志` (`大事记` + `军事志`).
  - Detect and group **multi-volume sets (`上、中、下册` / `第一卷..第N卷`)** using `volume_set_id` and `volume_index: [k, n]`, ensuring all volumes covering `大事记`, `建置沿革`, `地名`, `人口`, `政党`, `军事` and `公安` (`剿匪`) are listed.
  - Target First-Round (`第一轮修志`, ca. `1980–2005`) or full-revision `重修` volumes covering `1912–1953`.
- **Provincial Gazetteers, Standalone Thematic Books (`分志`) and `地名志` (`provincial_gazetteers`)**:
  - Explicitly search for and index provincial (`省志`) and major municipal (`市志`) standalone thematic volumes: `<Province/City>志·大事记`, `·军事志`, `·地名志` (e.g. `黑龙江省志·地名志`), `·建置沿革志` / `·民政志` / `·行政区划志`, `·公安志` (`剿匪`), `·政党志`, `·民族志` and `·报业志` / `·新闻出版志`.
  - Index standalone `<Province/Prefecture/County>地名志`, `地名录` and `中华人民共和国地名词典（<Province>卷）` because they record granular subdivision `沿革` changes and local bandit mountain strongholds (`山寨`).
  - Cross-check any discovered `报业志` / `新闻出版志` to ensure no contemporaneous `1912–1953` regional newspaper is omitted under `newspapers`.
- **Taiwan**:
  - Index `1990–2015` `重修縣市志` (`GADM TWN_2`) paired with `GADM TWN_3` township/district chronicles (`鄉鎮縣轄市區志`, including `山地鄉`) and `1912–1945` Japanese *Shū*/*Chō*/*Gun*/*Banchi* official surveys (`州管內概況及事務概要`, `郡要覽`, `理蕃誌稿`).
  - Disambiguate **ROC Fujian `金門縣志` (Kinmen) and `連江縣志` (Matsu)** from PRC mainland Fuzhou `连江县志`.
- **Mongolia**:
  - Follow the tiered Cyrillic (`mn_cyrl`) fallback: *soum* monograph (`Сумын түүх`) -> *aimag* encyclopaedia/history (`Аймгийн түүх` / `Нэвтэрхий толь`) -> Mongolian Academy of Sciences (`ШУА`) & pre-1921 Qing/ROC frontier treatises (`库伦志略`, `乌里雅苏台志略`, `科布多政务总册`).
  - Apply post-1994 enclave aimag remapping (`Darkhan-Uul`, `Orkhon`, `Govisümber`), `1912–1931` *khoshuun* links and Kazakh bilingual indexing for `Bayan-Ölgii`.
- **Tuvan Republic**:
  - Index modern *kozhuun* local histories (`ru` and `tyv`) paired with republic-wide **TIGPI (`ТИГПИ` / `ТНИИЯЛИ`)** compendia (*Istoriya Tuvy*, *Uchenye zapiski*), remapping post-1953 *kozhuun* splits and flagging `Davst / Uvs Basin` border adjustments.
- **Tusi Polities**: Search `<TusiName>土司志`, `<TusiName>土司谱牒`, successor PRC autonomous-county gazetteers, CPPCC `文史资料`, `民族问题五种丛书`, Tibetan *deb-ther* and frontier journals (`边政公论`, `康导月刊`).
- **Contemporaneous Newspapers (`1912–1953`)**: Discover provincial, prefectural (`道`) and municipal/treaty-port titles (`spatial_scope`, `covered_adm2`, `covered_counties`, `date_span`, `affiliation`, `language_orig`).
- **Access Classification**: Set `access_status` honestly (`"open"`, `"mirror_open"`, `"blocked_paywall"`, `"blocked_captcha"`, `"unavailable"`). Never recommend credential spoofing or CAPTCHA bypassing in `scraper_notes`.

## Step 4. Strict `1912–1953` Time-Domain Relevance Filter

Never confuse publication year (`pub_year`) with historical content coverage (`content_years_covered`):

1. **Reject pre-1912 imperial gazetteers**: Discard `明`, `清`, `康熙`, `乾隆`, `光绪` and `宣统` editions whose `content_years_covered` ends before `1912` (the most common false positive in Wikimedia Commons and NLC/CADAL dumps).
2. **Reject post-1953-only continuations**: Reject standalone post-1985 PRC `第二轮续志` volumes or Taiwan `續修` continuations starting after `1953` unless paired with a base chronicle covering `1912–1953`.
3. **Tag partial Republican/colonial imprints (`1912–1953`)**: When a Wikimedia, NLC or NDL gazetteer was printed between `1912` and `1952`, set `time_coverage_role: "partial_contemporaneous_1912_1953"` and `content_years_covered: [1912, <pub_year>]`, and pair it with a `1980–2010` full-span chronicle or newspaper run so `1937–1953` is never missing.
4. **Clip newspapers and periodicals**: Index only issues or volumes whose dates overlap `1912-01-01` through `1953-12-31` (`GMT+0`).

## Step 5. Cross-Division Deduplication Check

Inspect `./chronicles/source_registry.json5` before finalising entries. Because a single modern PRC `县志`/`市志`, Taiwanese county chronicle, Mongolian *aimag* volume or Tuvan TIGPI compendium frequently covers multiple `1912–1953` `<county_slug>` or `<province_slug>` divisions, set `shared_from_province` to the canonical province slug and reuse the identical `source_slug` wherever already indexed.

## Step 6. Write and Verify `index_manifest.json5`

1. Save `./chronicles/<province_slug>/index_manifest.json5` using 2-space indentation and the schema in [taxonomy_and_schemas.md](../1.download-all-provinces/references/taxonomy_and_schemas.md).
2. Verify that every historical `adm_3` unit resolves to at least one modern crosswalk unit (`modern_unit_id`, `covered_historical_adm3`), `provincial_gazetteers` covers `地名志`, `大事记` and `军事志` searches, multi-volume `上、中、下册` sets include every volume (`volume_set_id`, `volume_index`), every accepted source passes the `1912–1953` `content_years_covered` filter, every entry specifies `language_orig`, `script_direction`, `format`, `gazetteer_tier_or_round`, `time_coverage_role` and `access_status`, and the file parses cleanly with `gis_helpers.load_json5()`.
