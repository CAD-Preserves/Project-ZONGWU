---
name: 3.scrape-province
description: Downloads and compiles county chronicles, contemporaneous newspapers, and Tusi records listed in a province's index_manifest.json5 into lossless PDF containers with section metadata.
---

# Scrape Province Sources

Acquire every open source catalogued in `./chronicles/<province_slug>/index_manifest.json5`, assemble lossless `<source_slug>_orig.pdf` artefacts alongside `<source_slug>_meta.json5`, deduplicate shared sources across provinces and log gated items cleanly.

Consult [taxonomy_and_schemas.md](../1.download-all-provinces/references/taxonomy_and_schemas.md) for directory locations and metadata schemas.

## Step 1. Load Manifest and Deduplication Registry

1. Read `./chronicles/<province_slug>/index_manifest.json5` and `./chronicles/source_registry.json5`.
2. For each item in `counties`, `provincial_gazetteers`, `newspapers` and `tusi_sources`:
   - If `shared_from_province` is set and the canonical `<source_slug>` already shows `scrape_status: "complete"` in `source_registry.json5`, skip downloading. Write `<source_slug>_meta.json5` in the local `raw/` folder with `canonical_source_path` pointing to the canonical `_orig.pdf`, and set `scrape_status: "shared"` in `index_manifest.json5`.
   - If `access_status` is `"blocked_paywall"` or `"blocked_captcha"`, do not attempt to bypass authentication, paywalls or CAPTCHA gates; keep `scrape_status: "blocked"` and proceed to the next source.

## Step 2. Download and Assemble `_orig.pdf` Containers

Save raw files under the appropriate taxonomy branch:

- County chronicles: `./chronicles/<province_slug>/counties/<county_slug>/raw/`
- Provincial and major municipal `分志` / `地名志`: `./chronicles/<province_slug>/provincial_gazetteers/<source_slug>/raw/`
- Newspapers: `./chronicles/<province_slug>/newspapers/<publication_slug>/raw/`
- Tusi records: `./chronicles/<province_slug>/tusi_sources/<source_slug>/raw/`

Handle each source format as follows:

1. **Native PDF (`format: "pdf"`)**: Download cleanly with polite request throttling and retry backoff to `<source_slug>_orig.pdf`. If the primary URL fails or returns a rate-limit/access gate, fall back to listed open mirrors; if all open URLs are gated, update `access_status` (`"blocked_paywall"`, `"blocked_captcha"` or `"unavailable"`) and `scrape_status: "blocked"`.
2. **DjVu Archives (`format: "djvu"`)**: Common on Wikimedia Commons and Internet Archive. Download the original DjVu binary (via Wikimedia `Special:FilePath` or MediaWiki `imageinfo` URL) and losslessly render/convert pages into `<source_slug>_orig.pdf` preserving full resolution and embedded text where present.
3. **IIIF / Image Page Sequences (`format: "iiif_images"`)**: Download full-resolution page images in strict page order and losslessly compile them into `<source_slug>_orig.pdf` (preserving native pixel dimensions without downsampling). For multi-year newspaper runs, split output into monthly or volume containers (`<pub_slug>_YYYY_MM_orig.pdf`, maximum 500 pages per PDF) so OCR stages remain bounded.
4. **HTML Chapters (`format: "html_chapters"`)**: Fetch the full Table of Contents and all chapters cleanly, rendering UTF-8 text and embedded plates into `<source_slug>_orig.pdf` with clear chapter headers.

## Step 3. Inspect Table of Contents (`目录`) and Verify Time-Domain Coverage

1. Do not discard non-military chapters: retain the full book whenever available so administrative history, population tables and party records stay intact.
2. Inspect the Table of Contents (`目录`, typically following ~30 photo pages and ~5 prefaces in `1980–2010` county chronicles) and publication masthead via PyMuPDF (`fitz`) or page-image preview:
   - **Time-domain check**: Verify that `content_years_covered` inside the downloaded file genuinely overlaps `1912–1953`. If a downloaded file proves to be a pre-1912 dynastic reprint (`光绪`/`宣统` without post-1911 content) or a post-1985-only `续志` continuation missing `1912–1953` chapters, flag `scrape_status: "failed"` with note `"out_of_time_domain_1912_1953"` and trigger re-indexing for a valid Round-1 / `重修` edition.
   - **Multi-volume (`上、中、下`) and standalone `分志` completeness check**: If the ToC shows that the PDF is only `上册` or Volume 1 of a multi-volume set (for example ending before `军事`, `公安` or `政党`), verify all sibling volumes (`volume_set_id`, `volume_index`) are also queued and downloaded before marking the county or municipal set complete.
   - Populate `priority_sections` inside `<source_slug>_meta.json5`:
     - `major_events_pages` (`大事记`)
     - `admin_history_pages` (`建置沿革` / `行政区划`)
     - `toponymy_and_yange_pages` (`地名` / `历史沿革`)
     - `military_pages` (`军事`)
     - `bandit_suppression_pages` (`剿匪` / `公安` / `治安`)
     - `population_pages` (`人口`)
     - `parties_pages` (`政党`)
3. Compute the `sha256` digest, `page_count` and `retrieved_at_utc` (`YYYY-MM-DDTHH:MM:SSZ` in GMT+0), and write `<source_slug>_meta.json5` (including `modern_unit_id`, `covered_historical_adm3`, `gazetteer_tier_or_round`, `volume_set_id`, `volume_index` and verified `content_years_covered`). If `sha256` matches an existing entry in `./chronicles/source_registry.json5`, deduplicate by storing `canonical_source_path` and removing the redundant binary copy.

## Step 4. Verify Integrity and Update Registries

1. Validate every downloaded `_orig.pdf`: confirm `%PDF-` header magic bytes, verify `fitz.open()` reports `page_count > 0`, and check for corrupted or truncated streams.
2. Update `scrape_status` (`"complete"`, `"shared"` or `"blocked"`) in `./chronicles/<province_slug>/index_manifest.json5` and register every new canonical `source_slug` and `sha256` in `./chronicles/source_registry.json5`.
