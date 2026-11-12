---
name: 2.index-province
description: Indexes and compiles a gazetteer, newspaper, and Tusi source manifest for a single province or first-level division, complete with URLs and scraper instructions for /3.scrape-province.
---

# Index Province Sources

Compile a complete, deduplicated source manifest (`./chronicles/<province_slug>/index_manifest.json5`) for one first-level division—covering county chronicles (`adm_3`), contemporaneous regional/provincial newspapers (`1912–1953`), Tusi records (where applicable) and peripheral-language archives—so `/3.scrape-province` can acquire every source cleanly.

Read [taxonomy_and_schemas.md](../1.download-all-provinces/references/taxonomy_and_schemas.md) for exact JSON5 schemas and `./common/ocr/ocr_translation_config.json5` for valid `language_orig` and `script_direction` codes.

## Step 1. Resolve Spatial Scope (1912–1953)

1. Look up `<province_slug>` in `./common/defines/province_defines.json5` to obtain `name`, `name_zh`, `category`, `active_years` and `gis_unit_ids`.
2. Inspect `./gis/adm_2_<year>.geojson` and `./gis/adm_3_<year>.geojson` across the division's `active_years` to extract every constituent level-2 (`adm_2`) and level-3 (`adm_3`) unit, normalising each county/banner/soum/kozhuun to its canonical `snake_case` `<county_slug>`.
3. If `category == "tusi"` or if Tusis overlapped the province's territory, inspect `./common/tusi/tusi_catalog.json5` to list all overlapping `tusi_id` entries, successor autonomous counties and parent provinces.

## Step 2. Build Search Queries per Territory Type

Construct multilingual search queries for each constituent unit:

- **Mainland China counties**: Search both the shortened `<CountyName>县志` / `旗志` (stripping `土家族苗族自治县` or similar ethnic suffixes) and the full modern name (`<FullName>志`), targeting `1980–2010` *xinzhi* editions (`新编地方志`). Record historical 1912–1953 name variants (`州`, `厅`, `府`) for cross-referencing.
- **Taiwan**: Map Japanese-era *Shū*/*Chō* (`州`/`廳`) and post-1945 counties/cities to modern `鄉鎮縣轄市志`, `縣志` and *Taiwan Sōtokufu* archival compilations (`ja` and `zh_hant`).
- **Mongolia**: Map Bogd Khanate banners and MPR aimags/soums (`1912–1953`) to Mongolian aimag/soum histories (`mn_hudum` and `mn_cyrl`), *Ünen* runs and Russian/Chinese borderland studies.
- **Tuvan Republic**: Map Tannu Uriankhai, Uryankhay Krai, Tuvan People's Republic khoshuuns and Tuva AO rayons (`1912–1953`) to Tuvan/Russian regional histories (`ru` and `tyv`), *Tuvinskaya Pravda* and *Shyn*.
- **Tusi Polities**: Search `<TusiName>土司志`, `<TusiName>土司谱牒`, successor autonomous-county gazetteers, CPPCC `文史资料` series, `民族问题五种丛书` surveys, Tibetan *deb-ther* and frontier journals (`边政公论`, `康导月刊`).

## Step 3. Discover County Chronicles and Newspapers

1. **County Chronicles**: Search Internet Archive (`archive.org`), NLC open gazetteer catalogues, Taiwan Memory, university digital collections and public mirrors. For each county, record candidate editions (preferring complete `1980–2010` editions over 1940s drafts unless a 1940s chronicle is uniquely detailed), `language_orig`, `script_direction`, `urls`, `format` (`pdf`, `iiif_images`, `html_chapters`) and concrete `scraper_notes` (for example pagination patterns, image manifest URLs or multi-volume structure).
2. **Contemporaneous Newspapers (`1912–1953`)**: Because newspapers operate between province and county (`provincial`, `prefectural`/`道`, or `municipal`/treaty-port scales), discover relevant titles via academic gazetteers, Republican press directories, NDL/JACAR (Japanese), Harbin/Russian archives and treaty-port collections. Record `spatial_scope`, `covered_adm2`, `covered_counties`, `date_span`, `affiliation`, `language_orig` and issue/volume download targets.
3. **Access Classification**: Set `access_status` honestly (`"open"`, `"mirror_open"`, `"blocked_paywall"`, `"blocked_captcha"` or `"unavailable"`). Never recommend credential spoofing or CAPTCHA bypassing in `scraper_notes`.

## Step 4. Cross-Division Deduplication Check

Inspect `./chronicles/source_registry.json5` before finalising entries. If a county or Tusi chronicle is already indexed under an overlapping province (for example `zhili` and `hebei`, `sichuan` and `xikang`, or a Tusi and its parent province), set `shared_from_province` to the canonical province slug and reuse the identical `source_slug`.

## Step 5. Write and Verify `index_manifest.json5`

1. Save `./chronicles/<province_slug>/index_manifest.json5` using 2-space indentation and the exact schema in [taxonomy_and_schemas.md](../1.download-all-provinces/references/taxonomy_and_schemas.md).
2. Verify that every `adm_3` unit from Step 1 appears under `counties`, at least one provincial/regional newspaper search pass is logged under `newspapers`, every entry includes `language_orig`, `script_direction` and `access_status`, and the file parses cleanly with `gis_helpers.load_json5()`.
