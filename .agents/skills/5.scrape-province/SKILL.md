---
name: 5.scrape-province
description: Stages raw DjVu, IIIF and HTML primary-source downloads inside input/scrape_cache/ and compiles lossless *_orig.pdf containers plus *_meta.json5 sidecars strictly under output/chronicles/ or output/newspapers/.
---

# 5. Scrape and Compile Lossless Source Containers

Follow [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md). Never store compiled `_orig.pdf` files inside `input/`.

## Step-by-Step Workflow

1. **Read Manifest and Registry**:
   - Load `<chronicle_path>/index_manifest.json5` (using `"chronicle_path"` from `common/defines/province_defines.json5`) and `common/sources/source_registry.json5`.
   - Skip any `source_id` whose `output_orig_pdf` already exists under `./output/` with a matching verified SHA-256 hash.
2. **Stage Ephemeral Raw Fragments in `input/scrape_cache/`**:
   - Download IIIF image sequences, DjVu bundles, paged scans or HTML articles strictly into `./input/scrape_cache/<division_slug>/<source_id>/` (or `./input/scrape_cache/newspapers/<pub_slug>/`).
   - Respect site rate limits, preserve original resolution and record exact retrieval timestamps in `GMT+0`.
3. **Compile Lossless Archival PDFs into `output/`**:
   - Package scan sequences losslessly (without lossy recompression) into `<source_id>_orig.pdf` inside `<chronicle_path>/counties/<unit_slug>/raw/` or `./output/newspapers/<publication_slug>/raw/`.
   - Preserve any native digital text layer; detect and tag `has_embedded_text` accurately.
   - Write the sibling `<source_id>_meta.json5` sidecar following Section 6 of `.agents/references/taxonomy_and_schemas.md`, recording page counts and section boundaries (`大事记`, `建置沿革`, `兵事`, `土司`, `人物`).
4. **Register and Clean Cache**:
   - Update `common/sources/source_registry.json5` with final `sha256`, `output_orig_pdf` and `ocr_status: "downloaded"`.
   - Remove transient tile/page staging directories inside `./input/scrape_cache/` once the compiled `_orig.pdf` passes integrity validation.
