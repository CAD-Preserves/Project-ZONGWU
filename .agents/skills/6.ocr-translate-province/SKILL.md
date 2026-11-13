---
name: 6.ocr-translate-province
description: Runs multimodal OCR and bidirectional ZH / EN-GB translation over compiled *_orig.pdf containers in output/chronicles/ and output/newspapers/ according to common/ocr/ocr_translation_config.json5.
---

# 6. Multimodal OCR and Bidirectional Translation

Read `common/ocr/ocr_translation_config.json5`, [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md). Never write OCR exports into `input/`.

## Engine and Script Routing

Route each source strictly according to its `language` code in `common/ocr/ocr_translation_config.json5`:

- **`zh_hant` / `zh_hans`**: Use `EasyOCR` text/layout detection (`ch_tra` / `ch_sim`) paired with `ZihCiLin/trocr-traditional-chinese-baseline` (falling back to `ZihCiLin/trocr-traditional-chinese-historical-finetune` on damaged Republican prints). Verify vertical right-to-left (`tb-rl`) columns on Republican gazetteers and horizontal left-to-right (`lr-tb`) on *xinzhi*.
- **`mn_hudum` / `mnc` / `sjo`**: Vertical left-to-right (`tb-lr`) Mongolian, Manchu and Sibe scripts **must** use the multimodal VLM extractor so column reading order is never reversed to `tb-rl`.
- **`bo` / `ug`**: Route Tibetan (`bo`) through `tesseract_bod` and Uyghur/Kazakh (`ug`) through `tesseract_uig` with multimodal VLM verification (`tusi_catalog.json5` placename cross-checks for Tibetan).
- **`ja` / `ru` / `mn_cyrl` / `tyv` / `en` / `fr` / `de`**: Use configured `EasyOCR` language packs with multimodal VLM verification and pre-1918 Russian orthography normalisation where needed.
- **Non-Text Insets (`multimodal_regions`)**: Crop `battle_map`, `boundary_map`, `census_or_oob_table`, `photograph_caption` and `seal_or_masthead` regions at `300` DPI and extract structured tables/captions via multimodal VLM rather than pure text OCR.

## Output Artefacts and Translation Style

1. Read source `<source_id>_orig.pdf` + `<source_id>_meta.json5` from `output/chronicles/.../raw/` or `output/newspapers/<pub_slug>/raw/`.
2. Write sibling artefacts under the matching `ocr/` directory inside `output/`:
   - `<source_id>_zh.pdf` and `<source_id>_zh_raw.md` (normalised Chinese archival transcript).
   - `<source_id>_en.pdf` and `<source_id>_en_raw.md` (complete English translation in non-Oxford EN-GB).
3. Author English translations in crisp, unhurried non-Oxford British English (`GMT+0`, `dd Month YYYY`, European decimals where prose statistics appear, faithful preservation of original placenames, official ranks and troop designations).
4. Set `ocr_status: "done"` in `common/sources/source_registry.json5`.
