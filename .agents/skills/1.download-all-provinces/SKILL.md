---
name: 1.download-all-provinces
description: Orchestrates county chronicle and contemporaneous newspaper indexing, scraping, multimodal ZH/EN OCR-translation, and harmonised chronology generation across all divisions defined in province_defines.json5.
disable-model-invocation: true
---

# Project-ZONGWU: Provincial Source Acquisition, OCR and Chronology Orchestrator

Your role is that of a historical researcher covering the Warlord Era, Northern Expedition, Nanjing Decade, Second Sino-Japanese War, Chinese Civil War and frontier state-building from **01 January 1912 to 31 December 1953 (GMT+0)**. Working across **Mainland China, Taiwan, Mongolia, the Tuvan Republic and autonomous Tusi polities**, you orchestrate subagents to index, download, OCR/translate into both Chinese and British English (`EN-GB`), and compile harmonised county-level and province-level chronologies.

Full directory schemas, JSON5 formats, Markdown templates and peripheral-language rules live in [taxonomy_and_schemas.md](./references/taxonomy_and_schemas.md). Shared pipeline configurations live in `./common/ocr/ocr_translation_config.json5` and `./common/chronology/actor_glossary.json5`.

## Prerequisite Handoff from `/1.download-CHGIS`

Before launching subagents, confirm that `/1.download-CHGIS` has completed:

1. Verify `./common/defines/province_defines.json5`, `./common/tusi/tusi_catalog.json5` and `./gis/adm_<1|2|3>_<1912..1953>.geojson` exist. If missing, stop and instruct the user to run `/1.download-CHGIS` first.
2. Verify `./common/ocr/ocr_translation_config.json5` and `./common/chronology/actor_glossary.json5` are present.
3. Ensure `./chronicles/source_registry.json5` exists (initialise an empty `{"schema_version": 1, "sources": {}}` file if absent) so divisions sharing overlapping counties or Tusis deduplicate downloads and OCR runs cleanly.

## Workspace Taxonomy Summary

Each division `<province_slug>` listed in `./common/defines/province_defines.json5` owns:

- `./chronicles/<province_slug>/index_manifest.json5` — Master index of county chronicles, regional/provincial newspapers and Tusi sources.
- `./chronicles/<province_slug>/counties/<county_slug>/` — `adm_3` county chronicles (`raw/` and `ocr/`) plus `chronology_<county_slug>.md`.
- `./chronicles/<province_slug>/newspapers/<publication_slug>/` — Contemporaneous 1912–1953 newspapers (`raw/` and `ocr/`), stored at division level because press coverage typically spans provincial, prefectural (`道`) or major municipal catchments between province and county.
- `./chronicles/<province_slug>/tusi_sources/<source_slug>/` — Tusi genealogies, *Wenshi Ziliao*, *Five Series* ethnographic surveys, monastic *deb-ther* and frontier journals (`raw/` and `ocr/`).
- `./chronicles/<province_slug>/actors_local.json5` and `chronology_<province_slug>.md` — Local actor provenance and harmonised province-level bullet timeline.

## Finding Source Material

### County Chronicles (`地方志`)

- Focus on **`1980–2010` new-edition county chronicles (`新编地方志`)** rather than incomplete 1940s Republican drafts whenever a modern edition exists.
- Search open digital libraries, Internet Archive (`archive.org`), National Library of China (NLC) open gazetteer portals, Taiwan Memory, university digital repositories and public open mirrors.
- **Naming tip (ethnic autonomous counties)**: Take the official name—for example Youyang Tujia and Miao Autonomous County (`酉阳土家族苗族自治县`)—and append `志`, whilst **also** searching the shortened form without the autonomous ethnicity suffix (`酉阳县志`), which is frequently the actual book title in catalogues.
- **Typical chronicle anatomy**:
  - First ~30 pages: photographs of officials, infrastructure and scenery.
  - ~5 prefaces/introductions followed by the Table of Contents (`目录`).
  - **Chronicle of Major Events (`大事记`)**: immediately follows the ToC in ~90% of volumes.
  - **History of Administration (`建置沿革` / `行政区划`)**: records historical border shifts, seats and transfers.
  - Thematic chapters (`自然`, `人口`, `政党`, etc.).
  - **Military Affairs (`军事`)**: often covers conflicts from the 1200s onwards; critical for *de facto* battle and garrison mapping.
  - Ideally scrape the entire volume; prioritise `大事记`, `军事`, `建置沿革`, `人口` and `政党` when indexing page spans.

### Contemporaneous Newspapers (`1912–1953`)

- Newspapers sit between county and province (`provincial`, `prefectural` or `municipal`/treaty-port) and provide day-by-day contemporaneous dispatches absent from retrospective 1980s gazetteers.
- Use academic gazetteers, bibliography lists and library catalogues to identify relevant titles (such as *Shen Bao*, *Dagongbao*, *Zhongyang Ribao*, *Xinhua Ribao*, *Yishibao*, provincial *Minguo Ribao*, Manchukuo *Datong Bao*/*Manshū Nichinichi*, Taiwan *Taiwan Nichinichi Shimpō*, Harbin *Zarya* or Ulaanbaatar *Ünen*).

### Tusi Scraping (`土司`)

- Divisions with `category == "tusi"` in `province_defines.json5` rarely have standalone modern `县志`. Index and scrape: (a) successor autonomous-county/prefecture gazetteers (`自治县志`/`州志`) linked via `shared_from_province`, (b) dedicated `土司志` and family genealogies (`土司谱牒`), (c) CPPCC `文史资料` local series, (d) the 1950s *Five Series* (`民族问题五种丛书`) social-history surveys and (e) Tibetan *deb-ther* or Republican frontier journals (`边政公论`, `康导月刊`).

### Peripheral and Wartime Languages

- Handle non-Chinese primary material across peripheral regions and wartime zones: **Japanese** (Taiwan, Kwantung, Manchukuo, IJA *Senshi Sōsho*), **Russian & Tuvan** (Uryankhay Krai, Tuvan PR, Tuva AO, CER Harbin), **Classical Vertical & Cyrillic Mongolian** (Bogd Khanate, MPR, Inner Mongolia banners), **Tibetan** (Kashag, Chamdo, Xikang, Amdo), **Manchu/Sibe** (Northeast & Ili banners), **Uyghur/Kazakh** (Xinjiang, First & Second ETR) and **English/French/German** treaty-port press.

### Access Boundaries

- Use open digital portals, institutional open access and public mirrors listed in `index_manifest.json5`. Never defeat paywalls, spoof credentials or bypass CAPTCHAs; record any paywalled or CAPTCHA-gated item with `access_status: "blocked_paywall"` or `"blocked_captcha"` so the user can retrieve it manually.

---

## Step 1. Subagent Swarm — Indexing and Scraping

For each first-level division `<province_slug>` in `./common/defines/province_defines.json5`, spawn one Province Subagent with full workspace tools and pass its division entry (`name`, `name_zh`, `category`, `active_years`, `gis_unit_ids` and constituent `adm_2`/`adm_3` lists). Each Province Subagent must run the following skills sequentially, waiting for the first to finish before starting the next:

1. `/2.index-province` ([SKILL.md](../2.index-province/SKILL.md)) — Produces `./chronicles/<province_slug>/index_manifest.json5`.
2. `/3.scrape-province` ([SKILL.md](../3.scrape-province/SKILL.md)) — Downloads/assembles `<source_slug>_orig.pdf` and `<source_slug>_meta.json5` across `counties/`, `newspapers/` and `tusi_sources/`, updating `./chronicles/source_registry.json5`.

### Step 1 Verification Gate

Verify that every division has a valid `index_manifest.json5`, all `open` sources have valid `%PDF-` files with non-zero pages, and all `blocked_*` or `unavailable` gaps are explicitly logged. If outputs are incomplete, message the Province Subagent to remediate before proceeding to Step 2.

---

## Step 2. Subagent Swarm — Multimodal OCR/Translation and Chronology

Once a division passes Step 1 verification, instruct its Province Subagent (or a fresh continuation subagent with the same division context) to run the remaining skills sequentially:

1. `/4.OCR-translate-province` ([SKILL.md](../4.OCR-translate-province/SKILL.md)) — Produces four artefacts per source (`_zh.pdf`, `_en.pdf`, `_zh_raw.md` and `_en_raw.md`) using `EasyOCR` + `ZihCiLin/trocr-traditional-chinese-baseline` plus multimodal table/map extraction.
2. `/5.chronology-province` ([SKILL.md](../5.chronology-province/SKILL.md)) — Harmonises all actors into `./common/chronology/actor_glossary.json5` and `./chronicles/<province_slug>/actors_local.json5`, then compiles `chronology_<county_slug>.md` and `chronology_<province_slug>.md` using `- dd Month YYYY: [Event Name]` bullets.

### Step 2 Verification Gate

Confirm that:
1. Every processed PDF has matching page counts across `_orig.pdf`, `_zh.pdf` and `_en.pdf`, and matching `<!-- page: N -->` markers across `_zh_raw.md` and `_en_raw.md`.
2. Every actor across all divisions resolves to a canonical entry in `./common/chronology/actor_glossary.json5`.
3. Cross-provincial transfers (`Cross-province:`) and date-contemporaneous jurisdictions align cleanly across neighbouring divisions and Tusi polities.
