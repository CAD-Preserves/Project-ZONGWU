# Project-ZONGWU Taxonomy, File Architecture and Schemas

This shared reference defines the workspace directory taxonomy, JSON5 manifest schemas, raw Markdown conventions, chronology bullet formats and peripheral-language rules used across `/1.download-CHGIS`, `/1.download-all-provinces`, `/2.index-province`, `/3.scrape-province`, `/4.OCR-translate-province` and `/5.chronology-province`.

## 1. Workspace and Pipeline Architecture

Project-ZONGWU reconstructs historical *de jure* and *de facto* territorial control from **01 January 1912 to 31 December 1953 (GMT+0)** across **Mainland China, Taiwan, Mongolia and the Tuvan Republic**, treating autonomous **Tusi polities (`土司`)** as first-level divisions.

### Shared Configuration and Registry Files

- `./common/defines/province_defines.json5` — Authoritative registry of all first-level divisions (`province_slug`, canonical names, categories, `active_years`, `gis_unit_ids` and `./chronicles/<province_slug>/` directory paths), exported by `/1.download-CHGIS`.
- `./common/tusi/tusi_catalog.json5` — Catalogue of all 1912–1953 Tusi polities, parent provinces, active dates, lineage titles and CHGIS/kriged geometry modes.
- `./common/ocr/ocr_translation_config.json5` — Model endpoints (`ZihCiLin/trocr-traditional-chinese-baseline`, `ZihCiLin/trocr-traditional-chinese-historical-finetune`, `EasyOCR`), script-direction routing (`tb-rl`, `tb-lr`, `lr-tb`, `rl-tb`), DPI and validation thresholds.
- `./common/chronology/actor_glossary.json5` — Global cross-province registry of canonical names and aliases for all polities, cliques, parties, military units, Tusi chieftains, commanders and civil or religious figures, plus military echelon translations and calendar conversion rules.
- `./chronicles/source_registry.json5` — Global deduplication index keyed by `source_slug` and `sha256`. When a county or Tusi spans historical splits, renames or wartime partitions (for example `zhili`/`hebei`/`east_hebei`, `sichuan`/`chuanbei`/`xikang` or a Tusi polity and its successor autonomous county), the PDF is downloaded and processed once under its primary division and linked via `canonical_source_path` across overlapping divisions.

### Server Pipeline Sequence (`./core/server/`)

1. `A_download_and_reproject_gis.py` — Downloads CHGIS, GADM and Natural Earth sources and builds the 1911 baseline plus transport corridors.
2. `B_build_tusi_divisions.py` — Builds Tusi subadministrative polygons (`tusi_1912_1953.geojson`) from scraped/kriged settlements.
3. `C_build_annual_admin_series.py` — Generates annual 1 January (`00:00 GMT+0`) `adm_1_<year>.geojson`, `adm_2_<year>.geojson` and `adm_3_<year>.geojson` snapshots for 1912–1953.
4. `D_scanline_rasterise_adm.py` — Exports visual verification rasters to `./tests/CHGIS_adm_<level>_<year>.png`.
5. `E_export_chronicles_and_defines.py` — Initialises `./chronicles/<province_slug>/` folders, `./common/defines/province_defines.json5` and `./localisation/{en_gb,fr,de}.json5`.
6. Optional provincial automation scripts follow the same alphabetical contract: `F_index_province_sources.py`, `G_scrape_province_sources.py`, `H_ocr_and_translate_province.py` and `I_compile_province_chronology.py`.

---

## 2. Per-Division Directory Taxonomy

Every first-level division defined in `./common/defines/province_defines.json5` owns one directory under `./chronicles/<province_slug>/`:

```text
./chronicles/<province_slug>/
├── index_manifest.json5
├── actors_local.json5
├── chronology_<province_slug>.md
├── counties/
│   └── <county_slug>/
│       ├── raw/
│       │   ├── <source_slug>_orig.pdf
│       │   └── <source_slug>_meta.json5
│       ├── ocr/
│       │   ├── <source_slug>_zh.pdf
│       │   ├── <source_slug>_en.pdf
│       │   ├── <source_slug>_zh_raw.md
│       │   └── <source_slug>_en_raw.md
│       └── chronology_<county_slug>.md
├── newspapers/
│   └── <publication_slug>/
│       ├── raw/
│       │   ├── <issue_or_vol_slug>_orig.pdf
│       │   └── <issue_or_vol_slug>_meta.json5
│       └── ocr/
│           ├── <issue_or_vol_slug>_zh.pdf
│           ├── <issue_or_vol_slug>_en.pdf
│           ├── <issue_or_vol_slug>_zh_raw.md
│           └── <issue_or_vol_slug>_en_raw.md
└── tusi_sources/
    └── <source_slug>/
        ├── raw/
        │   ├── <source_slug>_orig.pdf
        │   └── <source_slug>_meta.json5
        └── ocr/
            ├── <source_slug>_zh.pdf
            ├── <source_slug>_en.pdf
            ├── <source_slug>_zh_raw.md
            └── <source_slug>_en_raw.md
```

### Spatial Granularity Rules

- `counties/` operates at **`adm_3`** granularity (xian, zhou, ting, banner, soum, kozhuun, Japanese-era Taiwan county/city). Use the canonical `snake_case` county slug derived from `adm_3_<year>.geojson`.
- `newspapers/` sits directly under `<province_slug>/newspapers/` because contemporaneous 1912–1953 newspapers normally operate between province and county (`provincial`, `prefectural`/`道`, or `municipal`/treaty-port catchment). Each publication records its exact `spatial_scope`, `covered_adm2` and `covered_counties` inside `index_manifest.json5`.
- `tusi_sources/` captures Tusi-specific genealogies (`土司谱牒`), *Wenshi Ziliao* (`文史资料`), *Five Series* (`民族问题五种丛书`) ethnographic surveys, monastic *deb-ther* and frontier journals (`边政公论`, `康导月刊`). For `category == "tusi"` divisions, county-level successor gazetteers (such as autonomous county chronicles overlapping the Tusi seat) may also sit in `counties/` or link via `shared_from_province`.

---

## 3. JSON5 Schemas

All JSON5 files use 2-space indentation, a leading `//` comment header and UTF-8 encoding.

### 3.1 `./chronicles/source_registry.json5`

```json5
// Global deduplication registry for downloaded and OCR-processed primary sources.
{
  "schema_version": 1,
  "sources": {
    "youyang_xianzhi_1992": {
      "canonical_province": "sichuan",
      "canonical_source_path": "./chronicles/sichuan/counties/youyang_zhou/raw/youyang_xianzhi_1992_orig.pdf",
      "ocr_status": "complete",
      "page_count": 842,
      "sha256": "<64-hex-digest>",
      "shared_with": ["chuandong"]
    }
  }
}
```

### 3.2 `./chronicles/<province_slug>/index_manifest.json5`

```json5
// Source gazetteer, newspaper, and Tusi index for <province_slug>.
{
  "active_years": [1912, 1953],
  "category": "province",
  "constituent_adm2": ["Chongqing Fu", "Chengdu Fu"],
  "constituent_adm3": ["youyang_zhou", "ba_xian"],
  "counties": {
    "youyang_zhou": [
      {
        "access_status": "open",
        "format": "pdf",
        "language_orig": "zh_hans",
        "ocr_status": "pending",
        "pub_year": 1992,
        "scrape_status": "pending",
        "script_direction": "lr-tb",
        "search_queries_used": ["酉阳县志", "酉阳土家族苗族自治县志"],
        "shared_from_province": "",
        "scraper_notes": "Single PDF on Internet Archive; verify ToC for 大事记 and 军事.",
        "source_slug": "youyang_xianzhi_1992",
        "title_orig": "酉阳县志",
        "urls": ["https://archive.org/details/..."]
      }
    ]
  },
  "name": "Sichuan",
  "name_zh": "四川",
  "newspapers": [
    {
      "access_status": "open",
      "affiliation": "KMT provincial organ / commercial",
      "covered_adm2": ["Chongqing Fu", "Chengdu Fu"],
      "covered_counties": ["ba_xian", "chengdu_xian"],
      "date_span": ["1937-01-01", "1949-11-30"],
      "issues_or_volumes": [
        {
          "format": "iiif_images",
          "issue_or_vol_slug": "xinminbao_1938_01",
          "language_orig": "zh_hant",
          "ocr_status": "pending",
          "scrape_status": "pending",
          "script_direction": "tb-rl",
          "scraper_notes": "Vertical Traditional layout; compile daily issues per month.",
          "urls": ["https://..."]
        }
      ],
      "publication_slug": "xinminbao_chongqing",
      "spatial_scope": "provincial",
      "title_orig": "新民报"
    }
  ],
  "province_slug": "sichuan",
  "schema_version": 1,
  "tusi_sources": []
}
```

Allowed `access_status` values: `"open"`, `"mirror_open"`, `"blocked_paywall"`, `"blocked_captcha"`, `"unavailable"`. Allowed `scrape_status` and `ocr_status` values: `"pending"`, `"complete"`, `"shared"`, `"blocked"`, `"failed"`.

### 3.3 `<source_slug>_meta.json5`

```json5
// Provenance and section index for <source_slug>_orig.pdf.
{
  "canonical_source_path": "",
  "language_orig": "zh_hans",
  "page_count": 842,
  "priority_sections": {
    "admin_history_pages": [45, 72],
    "major_events_pages": [34, 68],
    "military_pages": [512, 560],
    "parties_pages": [480, 511],
    "population_pages": [180, 210]
  },
  "retrieved_at_utc": "2026-11-12T22:00:00Z",
  "script_direction": "lr-tb",
  "sha256": "<64-hex-digest>",
  "source_slug": "youyang_xianzhi_1992",
  "source_type": "county_chronicle",
  "source_url": "https://archive.org/details/..."
}
```

### 3.4 `./chronicles/<province_slug>/actors_local.json5`

```json5
// Local surface forms and citations resolved against ./common/chronology/actor_glossary.json5.
{
  "province_slug": "sichuan",
  "schema_version": 1,
  "actors": {
    "sichuan_clique": {
      "active_years": [1916, 1938],
      "citations": ["youyang_xianzhi_1992:p.518", "xinminbao_1938_01:p.2"],
      "surface_forms": ["川军", "Sichuan Army", "防区制军阀"]
    }
  }
}
```

---

## 4. Raw Markdown and Chronology Contracts

### 4.1 Raw Markdown (`<source_slug>_zh_raw.md` and `<source_slug>_en_raw.md`)

1. Start with a concise metadata block naming `source_slug`, `province_slug`, `county_slug` or `publication_slug`, `language_orig`, `target_language` (`ZH-UTF8` or `EN-GB`) and `page_count`.
2. Insert an explicit `<!-- page: N -->` marker before every page (`1` through `page_count`) so ZH and EN dumps align 1-to-1 with `_orig.pdf`, `_zh.pdf` and `_en.pdf`.
3. Preserve original chapter and section headings (`大事记`, `建置沿革`, `军事`, `人口`, `政党`) as Markdown headings, and render statistical tables or orders of battle as GitHub-flavoured Markdown tables.
4. Capture non-prose visual evidence (maps, boundary diagrams, photographs, seals and mastheads) with structured multimodal callout blocks:

```markdown
> [!NOTE] Multimodal Figure (Page 47 — boundary_map)
> **ZH**: 酉阳县1935年行政区划图；标示县城钟多镇、龚滩及川黔边防线。
> **EN-GB**: 1935 Youyang County administrative map; marks county seat Zhongduozhen, Gongtan and the Sichuan-Guizhou border defence line.
```

### 4.2 Chronology Timelines (`chronology_<county_slug>.md` and `chronology_<province_slug>.md`)

Every event must use **GMT+0 Gregorian dates** and follow this exact bullet contract:

```markdown
- dd Month YYYY: [Event Name] — Concise EN-GB factual summary using exact canonical actor and division names from actor_glossary.json5. (Location: <county_slug>; Cross-province: <province_slugs | none>; Source: <source_slug> p. <N>)
```

#### Partial-Date Rules (Never Fabricate Precision)

- Exact day known: `- 18 September 1931: [Mukden Incident] — ...`
- Month and year known, day unrecorded: `- 00 October 1934: [Capture of Youyang Seat] — ...`
- Year known only (for example `1924年冬` or `民国十三年`): `- 00 Unknown 1924: [Local Garrison Reorganisation] — ...` (mention seasonal nuance inside the summary text rather than inventing a month or day).

---

## 5. Peripheral and Wartime Language Reference Matrix

| Code | Language / Script | Target Regions (1912–1953) | Primary Archival Material | Reading Order | Calendar Era Handling |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `zh_hant` | Traditional Chinese | Republican Mainland, Taiwan (post-1945), HK/treaty press | Contemporaneous newspapers (*Shen Bao*, *Dagongbao*, *Zhongyang Ribao*), pre-1953 gazetteers, Taiwan *xinzhi* | `tb-rl` (vertical) or `lr-tb` | Minguo (`+1911`), Chinese lunar |
| `zh_hans` | Simplified Chinese | Mainland China `1980–2010` county chronicles | *Xinzhi* (`县志`, `旗志`, `自治县志`), *Wenshi Ziliao* | `lr-tb` (with `tb-rl` insets) | Gregorian (`GMT+0`) |
| `ja` | Japanese (*kyūjitai* / modern) | Taiwan (`1912–1945`), Kwantung, Manchukuo, occupied corridors | *Taiwan Sōtokufu* / *Shū*/*Chō* gazettes, *Manshū Nichinichi Shinbun*, *Senshi Sōsho* | `tb-rl` or `lr-tb` | Taishō (`+1911`), Shōwa (`+1925`) |
| `mn_hudum` | Classical Vertical Mongolian | Bogd Khanate (`1912–1924`), early MPR (`1924–1941`), Inner Mongolia banners | Banner registers, *Bogd Khan* decrees, early *Ünen* issues | **`tb-lr` (vertical left-to-right)** | *Olnoo Örgögdsön* (`+1910`) |
| `mn_cyrl` | Cyrillic Mongolian | Mongolian People's Republic (`1941–1953`) | Aimag/soum histories, *Ünen*, *Ardyn Erkh*, state archives | `lr-tb` | Gregorian (`GMT+0`) |
| `ru` | Russian (pre-1918 & Soviet) | Uryankhay Krai (`1914–1921`), CER Harbin, Mongolia/Xinjiang/Manchuria borders | Harbin émigré press (*Zarya*), *Tuvinskaya Pravda*, Soviet military reports | `lr-tb` | Julian pre-Feb 1918 (`+13 days`) |
| `tyv` | Tuvan (Latin & Cyrillic) | Tuvan People's Republic (`1921–1944`), Tuva AO (`1944–1953`) | *Shyn*, *Tuvan Pravda*, khoshuun/rayon administrative chronicles | `lr-tb` | Gregorian (`GMT+0`) |
| `bo` | Tibetan (*Uchen*) | Tibet (Kashag), Chamdo, Xikang, Qinghai, Sichuan/Yunnan Tusis | *Deb-ther* monastic annals, Kashag edicts, local histories | `lr-tb` | *Rab-byung* sexagenary cycle |
| `mnc` / `sjo` | Manchu / Sibe | Heilongjiang, Jilin, Hulunbuir, Ili (Xinjiang) banner garrisons | Banner genealogies, *booi* / *niru* rolls, late-Qing/early-ROC memorials | **`tb-lr` (vertical left-to-right)** | Gregorian / Minguo |
| `ug` | Uyghur / Kazakh (Arabic) | Xinjiang, Altai, First & Second East Turkestan Republics | *Shinjang Geziti*, Ili/Kashgar press, oasis chronicles | **`rl-tb` (horizontal right-to-left)** | Gregorian / Islamic Hijri |
| `en` / `fr` / `de` | Western Concession Press | Shanghai, Tianjin, Hankou, Guangzhou, Qingdao, Kunming | *North-China Herald*, *Peking & Tientsin Times*, *L'Écho de Chine*, *Tsingtauer Neueste Nachrichten* | `lr-tb` | Gregorian (`GMT+0`) |
