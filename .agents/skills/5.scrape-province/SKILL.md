---
name: 5.scrape-province
description: Stages raw DjVu, IIIF and HTML primary-source downloads inside input/scrape_cache/, enforces Stage B PDF/colophon verification against JiuZhi reprints and regional pub_year cutoffs, audits multi-volume/fascicle completeness, compiles lossless *_orig.pdf containers and *_meta.json5 sidecars strictly under output/chronicles/ or output/newspapers/.
---

# 5. Scrape, Audit and Compile Lossless Source Containers

Follow [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md). Never store compiled `_orig.pdf` files inside `input/`.

## Step 1. Read Manifest and Deduplication Registry

1. Load `<chronicle_path>/index_manifest.json5` (`schema_version: 2`, resolved via `"chronicle_path"` in `common/defines/province_defines.json5`) and `common/sources/source_registry.json5`.
2. Skip any unit marked `"redirected_to_1990s_parent"` if its canonical parent `source_id` in `source_registry.json5` already has a verified SHA-256 hash and existing `output_orig_pdf`.
3. Skip any individual `source_id` whose `output_orig_pdf` already exists under `./output/` with a matching verified SHA-256 hash.

## Step 2. Stage Ephemeral Raw Fragments in `./input/scrape_cache/`

1. Download IIIF image sequences, DjVu bundles, paged scans, PDFs or HTML articles strictly into `./input/scrape_cache/<division_slug>/<source_id>/` (or `./input/scrape_cache/newspapers/<pub_slug>/`).
2. Respect repository rate limits configured in `common/sources/series_a_sources_config.json5`, preserve original resolution and record exact retrieval timestamps in `GMT+0`.

## Step 3. Stage B Pre-Flight Content and Colophon Audit (`Problems #7 & #8`)

Before moving or compiling any chronicle container into `./output/chronicles/`, run a mandatory Stage B inspection in `./input/scrape_cache/` across the first `15` pages (cover, editorial board, `序言`/`凡例`, `总目录`) and last `10` pages (`后记`/`编后记`, `版权页`):

1. **Block Qing and Republican Reprints (`Zero-JiuZhi` Verification)**:
   - Immediately reject and delete the staged cache if the document exhibits any of:
     - Vertical right-to-left Traditional woodblock (`木刻`), lithograph (`石印`) or string-bound (`线装`) scans on Mainland county chronicles.
     - Title page, preface or colophon identifying a `点校` / `影印` / `整理` modern reprint (`1980–2000`) of a Qing (`乾隆`/`道光`/`同治`/`光绪`/`宣统`) or Republican (`民国`) gazetteer.
     - `凡例` or `大事记` whose historical span terminates at or before `1949` (`断限止于民国` / `清宣统三年`).
2. **Enforce Regional Publication-Year and Span Cutoffs on `版权页`**:
   - Verify exact print/publication year from `版权页` (catalogue metadata can lag or misdate multi-year printings):
     - **Mainland PRC (`mainland_prc`)**: Reject if `版权页` shows `pub_year > 2000` (accept `1979–2000`) or if `凡例`/`总目录` reveals a Round-2 `续志` whose coverage begins `>= 1954` / `>= 1978` without pre-`1949` history.
     - **Taiwan (`taiwan`)**: Reject if `版权页` shows `pub_year > 2005` on modern `重修`/`鄉鎮市區志` chronicles (whilst preserving genuine `1911–1945` Japanese colonial administrative surveys).
     - **Mongolia and Tuva (`mongolia`, `tuva_republic`)**: Admissible through `pub_year <= 2026`.
3. Log rejected files back to `index_manifest.json5` (`excluded_candidates[]`) with exact Stage B failure reason and purge `./input/scrape_cache/<division_slug>/<source_id>/` immediately. Never write rejected `旧志` or over-cutoff PDFs into `./output/`.

## Step 4. Audit Multi-Volume (`上/中/下`) and Fascicle (`分志`) Completeness (`Problems #3 & #4`)

1. Parse `总目录` against the downloaded pages: confirm whether `大事记`, `建置`/`地理`, `军事`, `政权`/`政府`, `民族`/`土司`, `人物` and the closing `后记`/`版权页` are present in the compiled page span.
2. When a multi-volume work (`上、中、下册`) has missing sibling volumes (for example only `上册` downloaded because `中`/`下册` were absent upstream), compile the available volume cleanly using canonical suffix `<source_id>_vol1_shang_orig.pdf`, set `volume_set_complete: false` and list missing parts in `missing_volumes: ["中册", "下册"]`.
3. For standalone `分志` booklets, compile each verified fascicle under `<source_id>_fenzhi_<fascicle_slug>_orig.pdf`, linking siblings under `chronicle_series_id` and propagating unfound booklets in `missing_fascicles[]`.

## Step 5. Unconditional Compilation of Valid Chronicles and Yield Tagging (`Problem #9`)

1. **Never Skip Low-Yield or Ideological *Xinzhi***: If a Mainland `1979–2000` (or Taiwan `<= 2005` / Mongolia-Tuva `<= 2026`) chronicle passes Stage B but focuses heavily on 1930s revolutionary narratives with thin county administrative/military data, **compile it unconditionally** into `./output/chronicles/` so the corpus remains complete.
2. Package scan sequences losslessly (without lossy recompression) into `<source_id>*_orig.pdf` inside `<chronicle_path>/counties/<unit_slug>/raw/` or `./output/newspapers/<publication_slug>/raw/`. Preserve any native digital text layer and tag `has_embedded_text` accurately.
3. Write the sibling `<source_id>*_meta.json5` sidecar following Section `7` of `.agents/references/taxonomy_and_schemas.md`, recording `pub_year`, `region_cutoff_applied`, `temporal_coverage`, `volume_set_complete`, `stage_b_preflight_passed: true`, initial `historical_yield_1911_1953` (`"high" | "moderate" | "low_ideological_or_sparse" | "minimal"`), `yield_notes` and `sections` (`总目录`, `大事记`, `建置沿革`, `军事`/`兵事`, `政权`, `土司`, `人物`).
4. Update `common/sources/source_registry.json5` with final `sha256`, `output_orig_pdf`, `pub_year` and `ocr_status: "downloaded"`, then remove transient staging files inside `./input/scrape_cache/`.
