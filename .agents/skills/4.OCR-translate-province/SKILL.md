---
name: 4.OCR-translate-province
description: Runs multimodal OCR and bidirectional ZH/EN-GB translation across scraped county chronicles, newspapers, and peripheral-language sources using EasyOCR and ZihCiLin/trocr-traditional-chinese-baseline.
---

# OCR and Translate Province Sources (ZH and EN-GB)

Harmonise every scraped PDF under `./chronicles/<province_slug>/` into **four artefacts per source**—two searchable PDFs (`_zh.pdf` and `_en.pdf`) plus two raw Markdown dumps (`_zh_raw.md` and `_en_raw.md`)—handling Traditional Chinese, Simplified Chinese, peripheral/wartime scripts and multimodal maps, tables and seals.

Read `./common/ocr/ocr_translation_config.json5` for model IDs, thresholds and script routing, and [taxonomy_and_schemas.md](../1.download-all-provinces/references/taxonomy_and_schemas.md) for output schemas and Markdown formatting.

## Step 1. Text-Layer Audit and Image Preparation

1. Read `./chronicles/<province_slug>/index_manifest.json5`. For each source with `scrape_status: "complete"`, locate `<source_slug>_orig.pdf` and `<source_slug>_meta.json5` (skip `scrape_status: "shared"` items and link their canonical `ocr/` outputs instead).
2. Inspect each page of `<source_slug>_orig.pdf` with PyMuPDF (`fitz`):
   - **Digital Chinese text layer**: If `language_orig` is `zh_hans` or `zh_hant` and extracted UTF-8 text passes `embedded_text_validation` (`min_chars_per_text_page` >= 40, `min_cjk_ratio_zh` >= 0,60, `max_garbled_ratio` <= 0,05 without Mojibake or PUA corruption), reuse the embedded Chinese prose directly. Even on valid text-layer PDFs, **always** inspect pages containing images, maps, seals or tables using multimodal visual extraction.
   - **Scanned / image-only / non-Chinese pages**: Render pages at `300 DPI` (`page_render_dpi` in `ocr_translation_config.json5`), apply light deskew and contrast normalisation, and preserve page images for line detection and multimodal analysis.

## Step 2. Meshed OCR Pipeline (`EasyOCR` + `ZihCiLin/trocr-traditional-chinese-baseline`)

> [!IMPORTANT]
> `ZihCiLin/trocr-traditional-chinese-baseline` (`TrOCRProcessor` + `VisionEncoderDecoderModel`) is a **line/strip recognition** model (`microsoft/trocr-base-stage1`), not a full-page layout detector. Always crop individual text lines with `EasyOCR` detection first—never pass an uncropped multi-column newspaper page directly into TrOCR.

1. **Line Detection and Reading-Order Sorting**:
   - Run `EasyOCR` (`reader.detect()`) using `craft_text_threshold`, `link_threshold` and `low_text` from `ocr_translation_config.json5` to extract oriented line bounding boxes.
   - Sort detected boxes strictly according to `script_direction` in `<source_slug>_meta.json5`:
     - `tb-rl` (Vertical right-to-left): Republican newspapers, Traditional vertical gazetteers and vertical Japanese. Sort columns right-to-left, and lines top-to-bottom within each column.
     - `tb-lr` (**Vertical left-to-right**): Classical Mongolian (`mn_hudum`) and Manchu/Sibe (`mnc`/`sjo`). **Never sort these `tb-rl`**, as reversing columns scrambles every sentence.
     - `lr-tb` (Horizontal left-to-right): `1980–2010` PRC county chronicles (`zh_hans`), Russian, Tuvan, Cyrillic Mongolian, Tibetan and Latin press.
     - `rl-tb` (Horizontal right-to-left): Uyghur/Kazakh Arabic script (`ug`).
2. **Chinese Recognition Routing**:
   - **Traditional / Vertical / Republican / Taiwan (`zh_hant`)**: Crop each sorted strip (rotating vertical strips upright when horizontal-strip alignment is required) and recognise with `ZihCiLin/trocr-traditional-chinese-baseline`. Cross-check any strip with low confidence, token repetition or archival ink bleed against `EasyOCR` (`['ch_tra', 'en']`) and fall back to `ZihCiLin/trocr-traditional-chinese-historical-finetune` for severely degraded manuscripts or woodblock/mimeograph prints.
   - **Modern Simplified Chronicles (`zh_hans`)**: Recognise with `EasyOCR` (`['ch_sim', 'en']`), and dispatch quoted Republican documents, seals or vertical Traditional insets to `ZihCiLin/trocr-traditional-chinese-baseline`.
3. **Peripheral and Wartime Languages**:
   - Route `ja`, `ru`, `tyv`, `mn_cyrl`, `en`, `fr` and `de` through `EasyOCR` using `script_routing` in `ocr_translation_config.json5`, normalising Japanese *kyūjitai* and pre-1918 Russian orthography during post-processing.
   - Route `bo` (Tibetan) and `ug` (Uyghur/Kazakh) through Tesseract (`bod`/`uig`) plus multimodal vision verification, and transcribe vertical `mn_hudum`, `mnc` and `sjo` via multimodal vision inspection. Cross-check proper nouns against `./common/tusi/tusi_catalog.json5` and `./common/chronology/actor_glossary.json5`.

## Step 3. Multimodal Region Extraction (Maps, Tables, Seals and Photos)

Inspect every page flagged with non-text visual regions (`battle_map`, `boundary_map`, `census_or_oob_table`, `photograph_caption`, `seal_or_masthead`):

- Transcribe tabular figures (population censuses, casualty returns, garrison strengths, county revenue) into exact GitHub-flavoured Markdown tables in both Chinese and EN-GB.
- Extract battle arrows, troop unit symbols, river/railway labels, legend keys, map dates, photo captions and official seals into `> [!NOTE] Multimodal Figure (Page N — <type>)` blocks in both ZH and EN-GB.

## Step 4. Generate Dual PDFs and Raw Markdown Dumps

Write all four artefacts into the source's `ocr/` directory (`counties/<county_slug>/ocr/`, `newspapers/<publication_slug>/ocr/` or `tusi_sources/<source_slug>/ocr/`):

1. **`<source_slug>_zh.pdf`**: Searchable Chinese PDF. For Chinese sources, embed an invisible UTF-8 text layer over the original page scans (using a CJK-capable font); for non-Chinese peripheral sources (`ja`, `ru`, `tyv`, `mn_*`, `bo`, `mnc`, `ug`, `en`, `fr`, `de`), render a cleanly typeset Chinese translation PDF matching original page numbers 1-to-1.
2. **`<source_slug>_en.pdf`**: Searchable **non-Oxford British English (`EN-GB`)** translated PDF preserving 1-to-1 page correspondence with `_orig.pdf` and `_zh.pdf` (carrying forward canonical actor and military echelon names from `./common/chronology/actor_glossary.json5` wherever recognised).
3. **`<source_slug>_zh_raw.md`**: Raw UTF-8 Chinese Markdown dump containing `<!-- page: N -->` markers for every page, preserved chapter headings, tables and multimodal blocks.
4. **`<source_slug>_en_raw.md`**: Raw EN-GB Markdown dump matching `<!-- page: N -->` markers, tables and multimodal blocks 1-to-1 with `_zh_raw.md`.

## Step 5. Verification

Before marking `ocr_status: "complete"` in `./chronicles/<province_slug>/index_manifest.json5` and `./chronicles/source_registry.json5`:

1. Confirm all four files (`_zh.pdf`, `_en.pdf`, `_zh_raw.md`, `_en_raw.md`) exist and are non-empty.
2. Confirm `fitz.open()` page counts match identically across `_orig.pdf`, `_zh.pdf` and `_en.pdf`.
3. Confirm `<!-- page: N -->` marker counts match `page_count` in both `_zh_raw.md` and `_en_raw.md`, and verify extracted CJK/EN-GB text is free of unparsed Mojibake.
