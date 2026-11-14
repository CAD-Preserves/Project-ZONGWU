---
name: 6.ocr-translate-province
description: Runs multimodal OCR and bidirectional ZH / EN-GB translation over compiled *_orig.pdf containers in output/chronicles/ and output/newspapers/ according to common/ocr/ocr_translation_config.json5, handles multi-volume/fascicle series and scores 1911–1953 historical content yield.
---

# 6. Multimodal OCR and Bidirectional Translation

Read `common/ocr/ocr_translation_config.json5`, [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md). Never write OCR exports into `input/`.

## Engine and Script Routing

Route each source strictly according to its `language` code in `common/ocr/ocr_translation_config.json5`:

- **`zh_hans` (Mainland PRC *Xinzhi* `1979–2000`)**: Use `EasyOCR` (`ch_sim`, horizontal left-to-right `lr-tb`), pairing `ZihCiLin/trocr-traditional-chinese-baseline` only on quoted Republican documents, vertical tables or inset seals.
- **`zh_hant` (Taiwan `<= 2005`, HK/Macau and `1912–1953` Press/Gazettes)**: Use `EasyOCR` text/layout detection (`ch_tra`) paired with `ZihCiLin/trocr-traditional-chinese-baseline` (falling back to `ZihCiLin/trocr-traditional-chinese-historical-finetune` on damaged `1912–1953` newsprint and gazettes). Verify vertical right-to-left (`tb-rl`) columns on Republican press/official gazettes and horizontal left-to-right (`lr-tb`) on modern Taiwan `重修` editions.
- **`mn_hudum` / `mnc` / `sjo`**: Vertical left-to-right (`tb-lr`) Mongolian, Manchu and Sibe scripts **must** use the multimodal VLM extractor so column reading order is never reversed to `tb-rl`.
- **`bo` / `ug`**: Route Tibetan (`bo`) through `tesseract_bod` and Uyghur/Kazakh (`ug`) through `tesseract_uig` with multimodal VLM verification (`tusi_catalog.json5` placename cross-checks for Tibetan).
- **`ja` / `ru` / `mn_cyrl` / `tyv` / `en` / `fr` / `de`**: Use configured `EasyOCR` language packs with multimodal VLM verification and pre-`1918` Russian orthography normalisation where needed.
- **Non-Text Insets (`multimodal_regions`)**: Crop `battle_map`, `boundary_map`, `census_or_oob_table`, `photograph_caption` and `seal_or_masthead` regions at `300` DPI and extract structured tables/captions via multimodal VLM rather than pure text OCR.

## Multi-Volume (`上/中/下`) and Fascicle (`分志`) Handling (`Problems #3 & #4`)

1. Process every sibling volume (`_vol1_shang_orig.pdf`, `_vol2_zhong_orig.pdf`, `_vol3_xia_orig.pdf`) and standalone fascicle (`_fenzhi_<slug>_orig.pdf`) present under `<chronicle_path>/counties/<unit_slug>/raw/`, preserving explicit `[vol_label, page_no]` headers inside each `_zh_raw.md` and `_en_raw.md` so downstream citations stay traceable.
2. When `volume_set_complete: false` or `missing_fascicles` is non-empty in `_meta.json5`, emit an explicit machine-readable completeness notice at the top of `<source_id>*_en_raw.md` and `<source_id>*_zh_raw.md` listing which chapters/volumes are absent upstream.

## Post-OCR Content-Yield Scoring (`Problem #9`)

1. **Never Suppress Export on Low-Yield Chronicles**: Always generate full `_zh.pdf`, `_en.pdf`, `_zh_raw.md` and `_en_raw.md` outputs for every valid Stage-B-approved chronicle, regardless of sparse or ideologically formulaic content.
2. **Score and Annotate `_meta.json5`**: After extracting full `1911–1953` text sections (`大事记`, `建置`, `军事`, `政权`, `土司`), update `historical_yield_1911_1953` (`"high"`, `"moderate"`, `"low_ideological_or_sparse"` or `"minimal"`) and `yield_notes` inside the sibling `<source_id>*_meta.json5` sidecar based on dated `1911–1953` administrative, military and societal entries vs repetitive slogan passages.

## Output Artefacts and Translation Style

1. Read `<source_id>*_orig.pdf` and `<source_id>*_meta.json5` from `./output/chronicles/.../raw/` or `./output/newspapers/<pub_slug>/raw/`.
2. Write sibling artefacts under the matching `ocr/` directory inside `./output/`:
   - `<source_id>*_zh.pdf` and `<source_id>*_zh_raw.md` (normalised Chinese archival transcript).
   - `<source_id>*_en.pdf` and `<source_id>*_en_raw.md` (complete English translation in non-Oxford EN-GB).
3. Author English translations in crisp, unhurried non-Oxford British English (`GMT+0`, `dd Month YYYY`, European decimals where prose statistics appear, faithful preservation of original placenames, official ranks and troop designations).
4. Set `ocr_status: "done"` and record final `historical_yield_1911_1953` in `common/sources/source_registry.json5`.
