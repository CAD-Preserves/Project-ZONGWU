# Shared Taxonomy and Output Schemas

This shared reference defines canonical workspace paths, the 6-branch `output/chronicles/` taxonomy, the standalone `output/newspapers/` tree and metadata schemas shared across Skills `1.` through `7.`.

## 1. Canonical Paths (`common/paths.json5`)

- `common/paths.json5`: Master workspace path registry read by `core/server/helpers/path_helpers.py`.
- `common/defines/province_defines.json5`: 750 first-level divisions and Tusi polities with their exact resolved `"chronicle_path"`.
- `common/defines/localisation_maps.json5`: Category labels (`category_loc`), EN/FR/DE exonyms (`exonyms_fr_de`) and chronicle output branches (`chronicle_category_branches`).
- `common/defines/modern_gazetteer_crosswalk.json5`: Bidirectional crosswalk between 1912–1953 `adm_3` / `tusi` units and modern PRC, Taiwan, Mongolia and Tuva jurisdictions.
- `common/sources/source_registry.json5`: Global deduplication index of primary sources across chronicles and newspapers (`schema_version: 1`, `sources` dictionary keyed by `source_id`).
- `common/ocr/ocr_translation_config.json5`: Multimodal script routing (`bo`, `de`, `en`, `fr`, `ja`, `mn_cyrl`, `mn_hudum`, `mnc`, `ru`, `sjo`, `tyv`, `ug`, `zh_hans`, `zh_hant`) and file suffixes.
- `input/gis/{chgis,gadm,hydrosheds,modern,modern_reference,natural_earth,priors}/`: Read-only upstream GIS archives, modern GADM/geoboundaries layers and internal priors/caches.
- `input/scrape_cache/`: Ephemeral DjVu, IIIF tile and HTML downloads staged prior to PDF compilation (cleaned after PDF export).
- `output/gis/adm_annual/`: 129 annual `adm_<1|2|3>_<1911..1953>.geojson` polygon layers.
- `output/gis/layers/`: 5 thematic vector layers (`elevation_contours.geojson`, `railways_1912_1953.geojson`, `roads_1912_1953.geojson`, `tusi_1912_1953.geojson`, `waterways_1912_1953.geojson`).
- `tests/outputs/`: Verification renders (`CHGIS_adm_*.png`, `tusi_verify_*.png`, `tibet_scanline_*.png`, `PRC_modern_adm_*.png`).

## 2. Six-Branch `./output/chronicles/` Hierarchy (`750` Entries)

Every entry in `common/defines/province_defines.json5` resolves deterministically via `path_helpers.resolve_chronicle_relpath` into one of 6 root branches under `./output/chronicles/`:

| Branch | Categories Included | Expected Entries |
| --- | --- | --- |
| `./output/chronicles/provinces/<slug>/` | `province` | 51 |
| `./output/chronicles/municipalities/<slug>/` | `municipality` | 10 |
| `./output/chronicles/autonomous_and_special/<slug>/` | `special_region`, `autonomous_region`, `autonomous_oblast` | 4 |
| `./output/chronicles/occupied_and_leased/<slug>/` | `puppet_province`, `occupied_province`, `occupied_city`, `leased_territory`, `colony` | 29 |
| `./output/chronicles/frontier_and_outer/<slug>/` | `aimag`, `frontier_polity`, `republic` | 33 |
| `./output/chronicles/tusi/<region>/<slug>/` | `tusi` across 5 catalog regions | 623 |

Tusi regional sub-buckets mirror `common/tusi/tusi_catalog.json5`:
- `gansu_qinghai_banners` (171)
- `guizhou_guangxi_hunan` (71)
- `sichuan_xikang` (141)
- `tibet_himalaya_xinjiang` (148)
- `yunnan` (92)

### Per-Division Directory Layout

Inside each `<chronicle_path>` directory:

```text
<chronicle_path>/
├── index_manifest.json5
├── actors_local.json5
├── chronology_<slug>_en.md
├── chronology_<slug>_zh.md
└── counties/
    └── <county_or_unit_slug>/
        ├── raw/                      # Compiled lossless *_orig.pdf containers + *_meta.json5
        ├── ocr/                      # Searchable *_zh.pdf, *_en.pdf, *_zh_raw.md, *_en_raw.md
        ├── actors_local.json5
        ├── chronology_en.md
        └── chronology_zh.md
```

## 3. Standalone `./output/newspapers/` Tree

Contemporaneous `1912–1953` press spanning multiple provinces (for example Shenbao, Takungpao, North China Herald and Manchurian gazettes) is stored once per publication under `./output/newspapers/` to prevent duplicate downloads:

```text
./output/newspapers/<publication_slug>/
├── issue_index.json5
├── raw/                              # YYYY-MM-DD_<pub_slug>_orig.pdf + _meta.json5
└── ocr/                              # YYYY-MM-DD_<pub_slug>_{zh,en}.pdf + _raw.md
```

Register each publication issue in `common/sources/source_registry.json5` with `covered_divisions` listing all relevant `<slug>` keys from `province_defines.json5`.

## 4. `index_manifest.json5` Schema (Skill `4.index-province`)

```json5
{
  "division_slug": "sichuan",
  "chronicle_path": "./output/chronicles/provinces/sichuan/",
  "active_years": [1911, 1953],
  "units_indexed": [
    {
      "unit_slug": "chengdu_xian",
      "modern_crosswalk_id": "510104",
      "sources": [
        {
          "source_id": "sc_chengdu_1929_gaz",
          "kind": "gazetteer",
          "language": "zh_hant",
          "title_zh": "...",
          "year": 1929,
          "url": "https://...",
          "tier": 1,
          "format": "iiif_or_pdf",
          "cache_dir": "./input/scrape_cache/sichuan/chengdu_xian/",
          "output_orig_pdf": "./output/chronicles/provinces/sichuan/counties/chengdu_xian/raw/sc_chengdu_1929_gaz_orig.pdf"
        }
      ]
    }
  ],
  "newspaper_links": ["shenbao", "dagongbao_chongqing"]
}
```

## 5. `source_registry.json5` Entry Schema

```json5
{
  "schema_version": 1,
  "sources": {
    "sc_chengdu_1929_gaz": {
      "kind": "gazetteer",
      "url": "https://...",
      "sha256": "...",
      "output_orig_pdf": "./output/chronicles/provinces/sichuan/counties/chengdu_xian/raw/sc_chengdu_1929_gaz_orig.pdf",
      "covered_divisions": ["sichuan"],
      "ocr_status": "done"
    }
  }
}
```

## 6. Sidecar `_meta.json5` Schema (Skill `5.scrape-province`)

Every lossless PDF written under `./output/chronicles/.../raw/` or `./output/newspapers/.../raw/` requires a matching `<source_id>_meta.json5`:

```json5
{
  "source_id": "sc_chengdu_1929_gaz",
  "language": "zh_hant",
  "page_count": 412,
  "has_embedded_text": false,
  "source_url": "https://...",
  "downloaded_utc": "2026-01-15T12:00:00Z",
  "sections": [
    {"title_zh": "大事记", "page_start": 12, "page_end": 88}
  ]
}
```

## 7. Chronology & Actor Rules (Skill `7.chronology-province`)

- Always resolve geometry and sovereignty state from `./output/gis/adm_annual/` and `./output/gis/layers/` (`tusi_1912_1953.geojson`).
- Format dates strictly as `dd Month YYYY` (for example `01 January 1912`) in non-Oxford EN-GB with `GMT+0` timestamps.
- Harmonise faction, warlord clique, party, army unit, Tusi ruling lineage and external power identifiers inside `actors_local.json5` alongside the EN-GB and ZH chronologies.
