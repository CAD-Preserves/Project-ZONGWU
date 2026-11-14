# Shared Taxonomy and Output Schemas

This shared reference defines canonical workspace paths, the `1911–1953` and `1954–2026` GIS folders, the `6`-branch `output/chronicles/` taxonomy, the standalone `output/newspapers/` tree and metadata schemas shared across `/series-a-workflow` and Skills `1.` through `7.`.

## 1. Canonical Paths (`common/paths.json5`)

- `common/paths.json5`: Master workspace path registry read by `core/server/helpers/path_helpers.py`.
- `common/defines/province_defines.json5`: `750` first-level divisions and Feudatory (`tusi`) polities with their exact resolved `"chronicle_path"`.
- `common/defines/localisation_maps.json5`: Category labels (`category_loc`), EN/FR/DE exonyms (`exonyms_fr_de`) and chronicle output branches (`chronicle_category_branches`).
- `common/gis/prc_admin_reforms_1954_2026.json5`: Declarative `1954–2026` PRC territorial reorganisation table (`大行政区` abolition, dissolved provinces, autonomous region formations, `1969–1979` Inner Mongolia transfers, `1950s–1960s` rare-character simplifications and MCA `1980–2026` `GB/T 2260` change logs).
- `common/gis/prc_functional_zones_and_sez.json5`: Spatial and parent-code registry mapping post-`1990` Special Economic Zones (`经济特区`), development zones (`经开区`/`高新区`), State-level New Areas (`新区`) and Xinjiang XPCC `师市` cities back to `1985–2000` `GB/T 2260` parent counties.
- `common/defines/prc_admin_lineage_1954_2026.json5`: Directed acyclic temporal lineage graph linking `01 January 1954` through `01 January 2026` (`GMT+0`) units (`unit_1990s_snapshot` and `unit_2026_snapshot`).
- `common/defines/modern_gazetteer_crosswalk.json5`: Bidirectional crosswalk (`schema_version: 2`) between `1912–1953` `adm_3` / Feudatory units, `1980–2000` compilation-era PRC jurisdictions (`unit_1990s_snapshot`) and `2026` modern Mainland PRC, Taiwan, Mongolia and Tuva jurisdictions.
- `common/sources/source_registry.json5`: Global deduplication index of primary sources across chronicles and newspapers (`schema_version: 1`, `sources` dictionary keyed by `source_id`).
- `common/ocr/ocr_translation_config.json5`: Multimodal script routing (`bo`, `de`, `en`, `fr`, `ja`, `mn_cyrl`, `mn_hudum`, `mnc`, `ru`, `sjo`, `tyv`, `ug`, `zh_hans`, `zh_hant`) and file suffixes.
- `input/gis/{chgis,gadm,hydrosheds,modern,modern_reference,natural_earth,priors}/`: Read-only upstream GIS archives, modern GADM/geoboundaries layers and internal priors/caches.
- `input/scrape_cache/`: Ephemeral DjVu, IIIF tile and HTML downloads staged prior to PDF compilation and Stage B pre-flight audit (cleaned after export or rejection).
- `output/gis/adm_annual/`: Strictly `1911–1953` historical annual layers (`129` `adm_<1|2|3>_<1911..1953>.geojson` polygon files). Never place post-`1953` files here.
- `output/gis/prc_annual_1954_2026/`: Separate PRC `1954–2026` annual layers resolved via `output.gis.prc_annual_dir` (`219` `prc_adm_<1|2|3>_<1954..2026>.geojson` polygon files at `01 January` `GMT+0`).
- `output/gis/layers/`: `5` historical thematic vector layers (`elevation_contours.geojson`, `railways_1912_1953.geojson`, `roads_1912_1953.geojson`, `tusi_1912_1953.geojson` and `waterways_1912_1953.geojson`).
- `tests/outputs/`: Verification renders (`CHGIS_adm_*.png`, `tusi_verify_*.png`, `tibet_scanline_*.png`, `PRC_modern_adm_*.png` and `PRC_adm_*.png`).

## 2. Six-Branch `./output/chronicles/` Hierarchy (`750` Entries)

Every entry in `common/defines/province_defines.json5` resolves deterministically via `path_helpers.resolve_chronicle_relpath` into one of `6` root branches under `./output/chronicles/`:

| Branch | Categories Included | Expected Entries |
| --- | --- | --- |
| `./output/chronicles/provinces/<slug>/` | `province` | 51 |
| `./output/chronicles/municipalities/<slug>/` | `municipality` | 10 |
| `./output/chronicles/autonomous_and_special/<slug>/` | `special_region`, `autonomous_region`, `autonomous_oblast` | 4 |
| `./output/chronicles/occupied_and_leased/<slug>/` | `puppet_province`, `occupied_province`, `occupied_city`, `leased_territory`, `colony` | 29 |
| `./output/chronicles/frontier_and_outer/<slug>/` | `aimag`, `frontier_polity`, `republic` | 33 |
| `./output/chronicles/tusi/<region>/<slug>/` | `tusi` across 5 catalog regions | 623 |

Feudatory (`tusi`) regional sub-buckets mirror `common/tusi/tusi_catalog.json5`:
- `gansu_qinghai_banners` (`171`)
- `guizhou_guangxi_hunan` (`71`)
- `sichuan_xikang` (`141`)
- `tibet_himalaya_xinjiang` (`148`)
- `yunnan` (`92`)

### Per-Division Directory Layout and Multi-Volume / Fascicle File Naming

Inside each `<chronicle_path>` directory:

```text
<chronicle_path>/
├── index_manifest.json5
├── actors_local.json5
├── chronology_en.md
├── chronology_zh.md
└── counties/
    └── <county_or_unit_slug>/
        ├── raw/                      # Compiled lossless *_orig.pdf containers + *_meta.json5
        ├── ocr/                      # Searchable *_zh.pdf, *_en.pdf, *_zh_raw.md, *_en_raw.md
        ├── actors_local.json5
        ├── chronology_en.md
        └── chronology_zh.md
```

Use deterministic container suffixes inside `raw/` and `ocr/`:
- Single-volume monograph: `<source_id>_orig.pdf` and `<source_id>_meta.json5`
- Multi-volume set (`上、中、下册` or `第1..N册`): `<source_id>_vol1_shang_orig.pdf`, `<source_id>_vol2_zhong_orig.pdf`, `<source_id>_vol3_xia_orig.pdf` (matching `volume_index` `1..N`)
- Standalone chapter fascicle (`分志` / `专志`): `<source_id>_fenzhi_<fascicle_slug>_orig.pdf` (for example `_fenzhi_dashiji`, `_fenzhi_junshi`, `_fenzhi_zhengquan`)

## 3. Standalone `./output/newspapers/` Tree

Contemporaneous `1912–1953` press and official government gazettes (`公報`) spanning multiple provinces (for example Shenbao, Takungpao, Central Daily News, North China Herald, Beiyang/National Government Gazettes and Manchurian/Taiwan official gazettes) are stored once per publication under `./output/newspapers/` to prevent duplicate downloads and keep pre-`1954` serials isolated from county chronicles:

```text
./output/newspapers/<publication_slug>/
├── issue_index.json5
├── raw/                              # YYYY-MM-DD_<pub_slug>_orig.pdf + _meta.json5
└── ocr/                              # YYYY-MM-DD_<pub_slug>_{zh,en}.pdf + _raw.md
```

Register each publication issue in `common/sources/source_registry.json5` with `covered_divisions` listing all relevant `<slug>` keys from `province_defines.json5`.

## 4. `prc_admin_lineage_1954_2026.json5` and `modern_gazetteer_crosswalk.json5` (v2 Schemas)

### `common/defines/prc_admin_lineage_1954_2026.json5`

```json5
// Temporal administrative lineage graph across 1954-2026 PRC transformations.
{
  "schema_version": 1,
  "coverage_years": [1954, 2026],
  "units_by_id": {
    "prc_610118_huyi": {
      "unit_2026_snapshot": {
        "gb_code": "610118",
        "name_zh": "鄠邑区",
        "parent_adm2_zh": "西安市",
        "parent_adm1_zh": "陕西省",
        "unit_type": "urban_qu"
      },
      "unit_1990s_snapshot": {
        "gb_1990": "610125",
        "names_1980_2000": ["户县"],
        "ranks_1980_2000": ["xian"],
        "conversion_events": [
          {
            "event_type": "converted_to_qu",
            "from_name": "户县",
            "to_name": "鄠邑区",
            "effective_date": "24 November 2016"
          }
        ]
      },
      "parent_1990s_unit_ids": ["prc_610125_huxian"],
      "is_post_1990_sez_or_new_area": false
    }
  }
}
```

### `common/defines/modern_gazetteer_crosswalk.json5` (`schema_version: 2`)

```json5
{
  "schema_version": 2,
  "by_historical_province": {
    "shaanxi": {
      "hu_xian": [
        {
          "area_overlap_ratio": 0.9964,
          "contains_historical_seat": true,
          "edge_cases": ["che_xian_she_qu_post_2000"],
          "modern_unit_id": "prc_610118_huyi",
          "unit_2026_snapshot": {
            "gb_code": "610118",
            "name_zh": "鄠邑区",
            "unit_type": "urban_qu"
          },
          "unit_1990s_snapshot": {
            "gb_1990": "610125",
            "names_zh": ["户县"],
            "ranks": ["xian"],
            "converted_post_2000": true
          },
          "parent_1990s_unit_ids": ["prc_610125_huxian"],
          "chronicle_search_plan": {
            "rung_1_1990s_exact": ["户县志"],
            "rung_2_eth_stripped": [],
            "rung_3_shortened_bare": ["户县地名志"],
            "rung_4_higher_admin": ["西安市志", "陕西省志·市县概况"],
            "blocked_post_2000_titles": ["鄠邑区志"]
          },
          "unit_type": "urban_qu"
        }
      ]
    }
  }
}
```

## 5. `index_manifest.json5` Schema (Skill `4.index-province`)

Every indexed division tracks candidate availability, regional publication-year limits (`<= 2000` Mainland PRC, `<= 2005` Taiwan, `<= 2026` Mongolia/Tuva), excluded `旧志`/over-cutoff editions, multi-volume completeness and parent redirections for post-`1990` SEZs/splits:

```json5
{
  "schema_version": 2,
  "division_slug": "gansu",
  "chronicle_path": "./output/chronicles/provinces/gansu/",
  "active_years": [1911, 1953],
  "units_indexed": [
    {
      "unit_slug": "zhangjiachuan_xian",
      "region": "mainland_prc",
      "modern_crosswalk_id": "620525",
      "target_1990s_unit_id": "prc_620525_zhangjiachuan",
      "chronicle_availability": "complete",
      "publication_structure": "multi_volume_set",
      "parent_1990s_redirect": null,
      "attempted_queries": [
        "张家川回族自治县志",
        "张家川县志",
        "张家川志",
        "天水市志"
      ],
      "superseded_editions": [
        {
          "title_zh": "张家川回族自治县志（1986内部本）",
          "pub_year": 1986,
          "reason": "superseded_by_later_edition_up_to_2000"
        }
      ],
      "excluded_candidates": [
        {
          "title_zh": "张家川回族自治县志（1979-2008）",
          "pub_year": 2010,
          "reason": "post_2000_cutoff"
        },
        {
          "title_zh": "清水县民国志（张家川析置前旧志影印）",
          "pub_year": 1991,
          "reason": "jiuzhi_reprint_banned"
        }
      ],
      "missing_volumes": [],
      "missing_fascicles": [],
      "sources": [
        {
          "source_id": "gs_zhangjiachuan_1994_xinzhi",
          "volume_set_id": "gs_zhangjiachuan_1994_xinzhi",
          "volume_label": "上册",
          "volume_index": 1,
          "expected_volume_count": 2,
          "kind": "xinzhi_county_chronicle",
          "language": "zh_hans",
          "title_zh": "张家川回族自治县志（上册）",
          "pub_year": 1994,
          "temporal_coverage": [1840, 1990],
          "url": "https://...",
          "tier": 1,
          "format": "pdf",
          "cache_dir": "./input/scrape_cache/gansu/zhangjiachuan_xian/",
          "output_orig_pdf": "./output/chronicles/provinces/gansu/counties/zhangjiachuan_xian/raw/gs_zhangjiachuan_1994_xinzhi_vol1_shang_orig.pdf"
        }
      ]
    }
  ],
  "newspaper_links": ["shenbao", "dagongbao", "zhengfu_gongbao_beiyang"]
}
```

Valid values for `chronicle_availability` are `"complete"`, `"partial_volumes_or_fascicles"`, `"redirected_to_1990s_parent"`, `"fallback_higher_admin_only"`, `"no_chronicle_published"` and `"not_digitised"`.

## 6. `source_registry.json5` Entry Schema

Retain `schema_version: 1` for backward verification compatibility whilst supporting multi-volume and yield metadata:

```json5
{
  "schema_version": 1,
  "sources": {
    "gs_zhangjiachuan_1994_xinzhi_vol1": {
      "kind": "xinzhi_county_chronicle",
      "pub_year": 1994,
      "volume_set_id": "gs_zhangjiachuan_1994_xinzhi",
      "url": "https://...",
      "sha256": "...",
      "output_orig_pdf": "./output/chronicles/provinces/gansu/counties/zhangjiachuan_xian/raw/gs_zhangjiachuan_1994_xinzhi_vol1_shang_orig.pdf",
      "covered_divisions": ["gansu"],
      "ocr_status": "done",
      "historical_yield_1911_1953": "moderate"
    }
  }
}
```

## 7. Sidecar `_meta.json5` Schema (Skill `5.scrape-province` & Skill `6.ocr-translate-province`)

Every lossless PDF written under `./output/chronicles/.../raw/` or `./output/newspapers/.../raw/` requires a matching `*_meta.json5` recording Stage B verification and yield:

```json5
{
  "source_id": "gs_zhangjiachuan_1994_xinzhi_vol1",
  "region": "mainland_prc",
  "region_cutoff_applied": 2000,
  "pub_year": 1994,
  "temporal_coverage": [1840, 1990],
  "language": "zh_hans",
  "publication_structure": "multi_volume_set",
  "volume_set_id": "gs_zhangjiachuan_1994_xinzhi",
  "volume_label": "上册",
  "volume_index": 1,
  "expected_volume_count": 2,
  "volume_set_complete": true,
  "missing_volumes": [],
  "fascicle_category": null,
  "stage_b_preflight_passed": true,
  "page_count": 486,
  "has_embedded_text": false,
  "historical_yield_1911_1953": "moderate",
  "yield_notes": "Covers late-Qing/ROC county reorganisation and Hui militia chronology alongside post-1935 Red Army transit.",
  "source_url": "https://...",
  "downloaded_utc": "2026-11-13T23:30:00Z",
  "sections": [
    {"title_zh": "总目录", "page_start": 5, "page_end": 11},
    {"title_zh": "大事记", "page_start": 18, "page_end": 74},
    {"title_zh": "建置志", "page_start": 75, "page_end": 142}
  ]
}
```

## 8. Regional Cutoffs and Chronology Rules (Skill `7.chronology-province`)

| Region Key | Max Publication Year (`pub_year`) | Admissible Local History Corpora | Strictly Excluded |
| --- | :--- | :--- | :--- |
| `mainland_prc` | `<= 2000` (`1979–2000`) | Round-1 *xinzhi* (`县志`, `市志`, `区志` if pre-`2001`, `自治县志`, `旗志`, `分志`, `地区志`/`省志`, `地名志`, `文史资料 <= 2000`) | Ming/Qing/Republican `旧志`, modern `点校`/`影印` reprints, `pub_year > 2000` *xinzhi*, Round-2 `续志` (`>= 1978` span) |
| `taiwan` (incl. Penghu, Kinmen, Lienchiang) | `<= 2005` | `1985–2005` `重修` county/city/township `鄉鎮市區志`, `1911–1945` Japanese `州/廳管內概況`, `郡要覽`, `理蕃誌稿`, `高砂族調查書` | Qing Taiwan `府志`/`縣志` reprints, `pub_year > 2005` local chronicles |
| `mongolia` | `<= 2026` (to present) | `Сумын түүх`, `Аймгийн нэвтэрхий толь`, `ШУА` / `БНМАУ-ын түүх` academic works, contemporaneous newspapers | Unverified amateur blogs lacking archival citations |
| `tuva_republic` | `<= 2026` (to present) | `ТНИИЯЛИ` / `ТИГПИ` (`История Тувы`, `Учёные записки`), kozhuun local histories up to `2026`, `Тувинская правда`, `Шын` | Unverified amateur blogs lacking archival citations |

- Always resolve `1911–1953` geometry and sovereignty state from `./output/gis/adm_annual/` and `./output/gis/layers/tusi_1912_1953.geojson`; reconcile retrospective PRC place names (`1954–2026`) through `./output/gis/prc_annual_1954_2026/` and `common/defines/prc_admin_lineage_1954_2026.json5`.
- Format dates strictly as `dd Month YYYY` (for example `01 January 1912`) in non-Oxford EN-GB with `GMT+0` timestamps.
- Harmonise faction, warlord clique, party, army unit, Feudatory ruling lineage and external power identifiers inside `actors_local.json5` alongside the EN-GB and ZH chronologies.
