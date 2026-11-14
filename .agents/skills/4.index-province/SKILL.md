---
name: 4.index-province
description: Compiles a comprehensive gazetteer, contemporaneous newspaper and Feudatory primary-source manifest for a single division in common/defines/province_defines.json5, resolving 1990s administrative statuses via prc_admin_lineage_1954_2026.json5 and enforcing regional publication cutoffs and the Zero-JiuZhi ban.
---

# 4. Index Primary Sources for a Division

Consult [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md) (`schema_version: 2` manifests) before authoring manifests.

## Step 1. Resolve `1911–2026` Temporal and Spatial Context

1. Look up `<slug>` in `common/defines/province_defines.json5` to read its `"chronicle_path"`, `category`, `active_years` and `gis_unit_ids`.
2. Inspect annual `1911–1953` geometry in `./output/gis/adm_annual/adm_<1|2|3>_<1911..1953>.geojson` and `./output/gis/layers/tusi_1912_1953.geojson`, plus `1954–2026` PRC evolution in `./output/gis/prc_annual_1954_2026/prc_adm_<1|2|3>_<1954..2026>.geojson`.
3. Cross-reference every unit against `common/defines/prc_admin_lineage_1954_2026.json5`, `common/defines/modern_gazetteer_crosswalk.json5` (`schema_version: 2`) and `common/tusi/tusi_catalog.json5`:
   - Extract `unit_1990s_snapshot` (`names_1980_2000`, `ranks_1980_2000`, `gb_1990`) rather than targeting the modern `2026` administrative name blindly.
   - **Post-`1990` SEZs, New Areas, Splits and XPCC `师市` (`Problem #2`)**: Whenever a `2026` zone (`雄安新区`, `浦东新区`, `滨海新区`, `两江新区`, `天府新区`, `苏州工业园区`, `洋浦经济开发区`, `经开区`/`高新区`, XPCC `师市` or post-`2000` carved district) did not exist during the `1985–2000` compilation window, resolve `parent_1990s_unit_ids` and set `chronicle_availability: "redirected_to_1990s_parent"`, indexing the parent county chronicle(s) rather than hunting for non-existent post-`2000` zone books.
   - **`1990s` Administrative Status Targeting (`Problem #5`)**: Use `ranks_1980_2000` for title generation. If `converted_to_qu_year > 2000` (for example `户县 -> 鄠邑区`, `郫县 -> 郫都区`) or `upgraded_to_shi_year > 2000`, automatically target `《XX县志》` / `《XX自治县志》` and reject `《XX区志》` / `《XX市志》` as post-`2000` by construction.
   - **Renamings Hygiene**: Prioritise exact `1980–2000` PRC names for units renamed post-`2000` (`中甸县` -> `香格里拉`, `思茅` -> `普洱`, `襄樊` -> `襄阳`, `潞西` -> `芒市`) or in `1954–1985` (`大庸县` -> `张家界`, `灌县` -> `都江堰`, `眉县` <- `郿县`). Never search bare pre-`1949` imperial/Republican names (`碾伯县`, `打箭炉厅`, `迪化县`) as primary Mainland county-chronicle queries.

## Step 2. Generate Search Queries via Four-Rung Expansion Ladder (`Problem #6`)

For Mainland PRC units, construct `zh_hans` queries in descending precision using `unit_1990s_snapshot` and the `55`-ethnicity list in `common/defines/local_history_edge_cases.json5`:

1. **Rung 1 — Full `1980–2000` Official Name**: `<1990s_full_name>志` (for example `张家川回族自治县志`, `积石山保安族东乡族撒拉族自治县志`).
2. **Rung 2 — Ethnic-Token and Modifier-Stripped Title**: Recursively remove every trailing minority ethnicity token (both `<Ethnicity>族` and bare `<Ethnicity>`), `各族` and `自治` until no ethnic qualifier remains, then append the `1990s` base rank (`县志` or `旗志`): for example `张家川县志`, `积石山县志`, `双江县志`, `鄂温克旗志`.
3. **Rung 3 — Shortened Bare Title**: Strip the administrative rank (`县`, `市`, `旗`, `区`) and query `<bare_stem>志` (for example `张家川志`, `积石山志`). Guard Rung 3 matches strictly by requiring matching provincial metadata (`parent_adm1`) and a post-`1979` editorial committee (`地方志编纂委员会`) so short stems never match mountain/temple gazetteers (`山志`/`寺志`) or Qing `州志`.
4. **Rung 4 — Prefectural and Toponymic Companions**: Emit `<1990s_adm2>志`, `<1990s_county>地名志` and `<1990s_adm2>地名志`. Never inject Mainland Traditional `<name_hant>志` strings into bare PRC county searches.

## Step 3. Search Authoritative Archives and Enforce Zero-JiuZhi & Regional Cutoffs (`Problems #7 & #8`)

Search repositories configured in `common/sources/series_a_sources_config.json5` and regional archives (`nlc.cn`,方志 catalogues, Academia Sinica, `JACAR`, National Diet Library, `runivers`, `prlib.ru`, National Library of Mongolia, `BDRC`/`TBRC`, Internet Archive, Wikimedia Commons for newspapers/official gazettes and HathiTrust), applying two non-negotiable gates:

### A. Stage A Zero-JiuZhi Filter (Mainland PRC County Chronicles)
- **Hard-Reject Imperial and Republican County Gazetteers**: Reject and exclude any Mainland county/prefectural gazetteer candidate whose title, series or metadata contains:
  - Imperial dynasties or reign eras (`明`, `清`, `顺治`, `康熙`, `雍正`, `乾隆`, `嘉庆`, `道光`, `咸丰`, `同治`, `光绪`, `宣统`).
  - Republican era markers (`民国`, `民國`, `中华民国`, `民國某年`, `民国xx年`) or pre-`1949` historical ranks (`府志`, `直隶州志`, `厅志`, `乡土志`, except when an autonomous/modern PRC name itself ends in `州` as a prefectural *xinzhi* such as `通州区志` or `德宏州志`).
  - Classical reprint series or antique-edition keywords (`中国方志丛书`, `中国地方志集成`, `稀见中国地方志汇刊`, `旧志`, `古籍`, `点校`, `影印`, `善本`, `线装`, `刻本`, `木刻`, `石印`, `抄本`).
- Remove `ctext.org` from Mainland county-chronicle search providers; never target pre-`1949` `舊志` volumes for `output/chronicles/`.
- **Keep Press Separate**: Contemporaneous `1912–1953` newspapers (`申報`, `大公報`, `中央日報`, `North China Herald`) and official government gazettes (`政府公報`, `國民政府公報`, `省政府公報`, `臺灣總督府報`, `滿洲國政府公報`) remain valid **only** when linked under `newspaper_links` targeting `./output/newspapers/`.

### B. Regional Publication-Year Cutoffs and Multiple-Edition Selection
1. **Mainland PRC (`mainland_prc`) — Hard Cutoff `1979 <= pub_year <= 2000`**:
   - Hard-reject every compilation with `pub_year > 2000` (even if titled `XX县志`), logging it in `excluded_candidates[]` with `reason: "post_2000_cutoff"`, because post-`2000` works drop 1980s/1990s eyewitness testimonies.
   - Hard-reject Round-2 `续志` (`第二轮`) or continuation volumes whose `temporal_coverage` starts `>= 1978` (`1986–2005`, `1979–2000`) with `reason: "post_1978_continuation_only"`.
   - **Multiple Eligible Editions (`1986` vs `1994`)**: When two or more full-span (`通贯古今`, starting pre-`1949`) PRC editions exist with `pub_year <= 2000`, **select `max(pub_year <= 2000)`** (`1994` over `1986`), breaking same-year ties by formal `地方志编纂委员会` publisher over internal mimeographs and by page completeness. Log losing `<= 2000` editions in `superseded_editions[]`.
2. **Taiwan and ROC Fujian Offshore (`taiwan`: Taiwan, Penghu, Kinmen, Lienchiang/Matsu) — Hard Cutoff `pub_year <= 2005`**:
   - Prefer `1985–2005` `重修` county/city and township `鄉鎮市區志`, paired with `1911–1945` Japanese `州/廳管內概況`, `郡要覽`, `理蕃誌稿` and `高砂族調查書`.
   - Hard-reject `pub_year > 2005` chronicles and Qing Taiwan `府志`/`縣志` reprints. Disambiguate `Kinmen` / `Lienchiang (Matsu)` cleanly from PRC `Fujian` mainland holdings (`同安`/`连江`).
3. **Mongolia (`mongolia`) and Tuvan Republic (`tuva_republic`) — Extends Through `pub_year <= 2026` (To Present)**:
   - Admit `Сумын түүх`, `Аймгийн нэвтэрхий толь`, `ШУА` / `БНМАУ-ын түүх`, `ТНИИЯЛИ` / `ТИГПИ` (`История Тувы`, `Учёные записки`) and kozhuun monographs published up to `2026`, selecting the fullest scholarly work paired with `1911–1953` archival/press records (`Тувинская правда`, `Шын`, Pre-1921 treatises).

## Step 4. Handle Multi-Volume Sets, Chapter Fascicles and Missing Chronicles (`Problems #1, #3 & #4`)

1. **Multi-Volume Expansion (`上、中、下册` / `第1..N册`)**: Whenever any candidate title or catalogue card shows a volume indicator (`上册`/`中册`/`下册`, `（上）`/`（中）`/`（下）`, `上卷`/`下卷`, `第一..四册`), tag `publication_structure: "multi_volume_set"`, assign a shared `volume_set_id` and execute targeted searches to capture **every** sibling volume. Record unrecovered siblings in `missing_volumes[]` and set `chronicle_availability: "partial_volumes_or_fascicles"` until all volumes are indexed.
2. **Chapter-Split Fascicles (`分志` / `专志`)**: For cities or large counties published as separate fascicles (`publication_structure: "chapter_fascicles"`), track retrieval against the **Priority A–C Fascicle Checklist**:
   - **Priority A (Core)**: `总述`/`大事记`, `建置沿革`/`地理`/`政区`, `军事`/`兵防`/`人武`.
   - **Priority B (Institutional)**: `政权`/`政府`/`政务`, `公安`/`司法`, `党派`/`社团`, `民族`/`宗教`/`土司`, `外事`/`租界`/`侨务`.
   - **Priority C (Toponymic and Biographical)**: `人物`, `地名志`, `文史资料` (`<= 2000` with `1911–1953` coverage).
   Log unfound fascicles explicitly in `missing_fascicles[]`.
3. **No-Chronicle Fallback Ladder (`Problem #1`)**: If exhaustive `4`-Rung searches return zero compliant local chronicles (for example Tibetan and frontier counties), set `chronicle_availability: "no_chronicle_published"` (or `"not_digitised"` if only offline print holdings exist) and log `attempted_queries`. **Never** relax the Zero-JiuZhi ban or the regional `pub_year` cap. Instead, execute this upward fallback ladder:
   - Tier 1: Parent prefectural/autonomous-prefecture/league chronicle (`地区志`, `州志`, `盟志`, within regional `pub_year` limit).
   - Tier 2: Provincial gazetteer volumes (`省志·市县概况`, `省志·建置志`, `省志·军事志`), provincial `地名志` and `中华人民共和国地名词典`.
   - Tier 3: `BDRC`/`TBRC` monastic and frontier histories, `文史资料` (`<= 2000`) and linked `1912–1953` press / `政府公報` under `newspaper_links`.

## Step 5. Deduplicate, Route Targets and Write Manifest

1. Check `common/sources/source_registry.json5` first; reuse existing canonical `source_id` records for shared newspapers, prefectural chronicles and parent-county books referenced by post-`1990` SEZs/split districts.
2. Route staging caches strictly under `./input/scrape_cache/<division_or_pub>/` and archival outputs strictly under `<chronicle_path>/counties/<unit_slug>/raw/<source_id>*_orig.pdf` or `./output/newspapers/<publication_slug>/raw/`.
3. Write `<chronicle_path>/index_manifest.json5` (`schema_version: 2`) and upsert newly discovered sources into `common/sources/source_registry.json5` with `ocr_status: "indexed"`.
