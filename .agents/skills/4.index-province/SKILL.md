---
name: 4.index-province
description: Compiles a comprehensive county gazetteer, contemporaneous newspaper and Tusi primary-source manifest for a single division in common/defines/province_defines.json5, resolving paths strictly inside output/chronicles/ and common/sources/source_registry.json5.
---

# 4. Index Primary Sources for a Division

Consult [.agents/rules/project_architecture.md](../../rules/project_architecture.md) and [.agents/references/taxonomy_and_schemas.md](../../references/taxonomy_and_schemas.md) before authoring manifests.

## Step-by-Step Workflow

1. **Resolve Division Metadata**:
   - Look up `<slug>` in `common/defines/province_defines.json5` to read its `"chronicle_path"`, `category`, `active_years` and `gis_unit_ids`.
   - Inspect annual geometry evolution for that division across `./output/gis/adm_annual/adm_<1|2|3>_<1911..1953>.geojson` and `./output/gis/layers/tusi_1912_1953.geojson`.
   - Cross-reference historical units with modern jurisdictions and search keywords in `common/defines/modern_gazetteer_crosswalk.json5` and `common/tusi/tusi_catalog.json5`.
2. **Search Authoritative Repositories**:
   - Republican Minguo gazetteers (`民國地方志`) and 1980–2010 *xinzhi* county chronicles (`新編地方志`): National Library of China (`nlc.cn`), CTExt (`ctext.org`), Academia Sinica, Wikimedia Commons, HathiTrust and Internet Archive.
   - Regional and external archives where applicable: Japan (`JACAR`, National Diet Library for Taiwan/Manchuria/occupied zones), Russia/Tuva (`runivers`, `prlib.ru`), Mongolia (`National Library of Mongolia`) and Tibet/Xinjiang (`TBRC`/`BDRC` and Chagatai/Tibetan borderland collections).
   - Contemporaneous `1912–1953` press: Shenbao, Takungpao, Central Daily News, North China Herald and provincial official gazettes (`省政府公報`).
3. **Deduplicate and Route Targets**:
   - Check `common/sources/source_registry.json5` first; if an external source or newspaper already exists, link its canonical `source_id` rather than scheduling a duplicate download.
   - Specify staging paths under `./input/scrape_cache/<division_or_pub>/`.
   - Specify compiled archival output targets strictly under `<chronicle_path>/counties/<unit_slug>/raw/<source_id>_orig.pdf` or `./output/newspapers/<publication_slug>/raw/`.
4. **Write Outputs**:
   - Write `<chronicle_path>/index_manifest.json5` following Section 4 of `.agents/references/taxonomy_and_schemas.md`.
   - Register newly discovered sources with `ocr_status: "indexed"` in `common/sources/source_registry.json5`.
