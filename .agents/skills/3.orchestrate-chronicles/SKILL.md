---
name: 3.orchestrate-chronicles
description: Orchestrates phases 4.index-province through 7.chronology-province across the 750 divisions in province_defines.json5 using output/chronicles/ and output/newspapers/.
---

# 3. Orchestrate Primary-Source Chronicles Across All Divisions

Follow [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and read [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md) for directory trees, file formats and JSON5 schemas.

## Hard Constraints

- Never create or write under top-level `chronicles/` or `/input/chronicles/`.
- Always look up each target division's concrete output path from `"chronicle_path"` in `common/defines/province_defines.json5` (resolved inside `./output/chronicles/` across its 6 branches: `provinces/`, `municipalities/`, `autonomous_and_special/`, `occupied_and_leased/`, `frontier_and_outer/` and `tusi/<region>/`).
- Always place multi-province contemporaneous `1912–1953` newspapers under `./output/newspapers/<publication_slug>/` and link them via `common/sources/source_registry.json5`.
- Stage temporary scrape fragments strictly inside `./input/scrape_cache/` and prune them after lossless `_orig.pdf` compilation into `output/`.

## Per-Division Execution Workflow

For each prioritised division slug in `common/defines/province_defines.json5` (starting with core Republican provinces and strategic borderlands before smaller Tusi polities):

1. Invoke `4.index-province` to construct `<chronicle_path>/index_manifest.json5` and update `common/sources/source_registry.json5`.
2. Invoke `5.scrape-province` to fetch manifests into `input/scrape_cache/` and export lossless `<source_id>_orig.pdf` + `<source_id>_meta.json5` containers into `output/chronicles/` or `output/newspapers/`.
3. Invoke `6.ocr-translate-province` to produce `_zh.pdf`, `_en.pdf`, `_zh_raw.md` and `_en_raw.md` inside sibling `ocr/` directories under `output/`.
4. Invoke `7.chronology-province` to harmonise actors into `actors_local.json5` and author structured `dd Month YYYY` (`GMT+0`) timelines (`chronology_en.md` in non-Oxford EN-GB and `chronology_zh.md`).

## Quality Gates

- Run `python tests/verify_file_structure.py` after batch updates to guarantee no outputs leak into `input/` or disallowed root folders.
- Verify every source registered in an `index_manifest.json5` exists in `common/sources/source_registry.json5` so duplicate primary-source pulls are avoided across provinces.
