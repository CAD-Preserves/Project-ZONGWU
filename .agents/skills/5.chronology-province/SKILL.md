---
name: 5.chronology-province
description: Harmonises all combatant, party, clique, polity, and individual actor names across provinces and builds structured bullet timelines (dd Month YYYY) for counties and provinces.
---

# Harmonise Actors and Compile Province Chronology (1912–1953, GMT+0)

Execute a strict **two-step** pipeline over `./chronicles/<province_slug>/`: first harmonising every actor name globally across Project-ZONGWU for future text mining, and second building intra-provincially and inter-provincially coherent bullet-point chronologies.

Read `./common/chronology/actor_glossary.json5`, `./common/defines/modern_gazetteer_crosswalk.json5`, `./common/gis/transport_corridors.json5` and [taxonomy_and_schemas.md](../1.download-all-provinces/references/taxonomy_and_schemas.md) before editing timelines.

## Step 1. Cross-Province Harmonisation of Actors, Combatants, Parties, Cliques and Polities

1. **Ingest Raw Markdown**: Scan every `*_zh_raw.md` and `*_en_raw.md` file across `counties/`, `newspapers/` and `tusi_sources/` (resolving shared sources via `canonical_source_path`).
2. **Extract All Actors**: Identify every historical entity appearing in `1912–1953` events—**not only states and major warlords**, but all:
   - Polities (`polity`), foreign powers (`foreign_power`) and Tusi polities (`tusi_polity`)
   - Warlord cliques and regional factions (`clique`)
   - Political parties, youth leagues, fronts and secret/religious societies (`party_or_society`, e.g. Red Spears, Elder Brother Society)
   - Military units and irregular formations (`military_unit`, `bandit_or_irregular`)
   - Named commanders, county magistrates, party cadres, Tusi chieftains, monastic leaders and foreign envoys (`commander`, `tusi_chieftain`, `civil_or_religious_figure`)
3. **Standardise Military Echelons and Romanisation**:
   - Translate Chinese military formations strictly using `echelon_standard_en_gb` in `./common/chronology/actor_glossary.json5` (for example `18th Group Army`, `29th Corps`, `38th Division`, `Peace Preservation Regiment`, `Mintuan Militia`).
   - Apply `romanisation_rules` consistently (tone-free Hanyu Pinyin for Mandarin names unless an established English historical spelling is already fixed in `actor_glossary.json5`).
4. **Reconcile and Persist Globally**:
   - Match every extracted alias (Simplified/Traditional Chinese, Wade-Giles, Postal, Japanese, Russian, Mongolian, Tibetan, Manchu, Uyghur) to an `actor_id` in `./common/chronology/actor_glossary.json5`.
   - Whenever a newly encountered actor may appear in other provinces or campaigns, append its canonical entry (`actor_type`, `canonical_name_en`, `canonical_name_zh`, `aliases`) atomically to `./common/chronology/actor_glossary.json5` (alphabetised by `actor_id`) so downstream and sibling province agents reuse identical spellings.
   - Write `./chronicles/<province_slug>/actors_local.json5` recording every `actor_id`, local `surface_forms`, `active_years` and `citations` observed in this division.

## Step 2. Intra-Provincial and Inter-Provincial Chronology Structuring

1. **Normalise and Filter Dates to Gregorian GMT+0 (`01 January 1912 – 31 December 1953`)**:
   - Convert Minguo (`+1911`), Taishō (`+1911`), Shōwa (`+1925`), *Olnoo Örgögdsön* (`+1910`), pre-February 1918 Russian Julian (`+13 days`), and Chinese/Tibetan lunar dates using `calendar_conversions` in `actor_glossary.json5`.
   - **Strict time-domain filter**: Full-span `1980–2010` chronicles contain events from antiquity to the 1980s; extract and retain **only** events occurring between `01 January 1912` and `31 December 1953 (GMT+0)`, discarding pre-1912 imperial and post-1953 modern entries (unless a post-1953 note records an explicit `1912–1953` administrative border clarification).
   - Use exact partial-date placeholders when precision is missing (`00 Month YYYY` when day is unattested; `00 Unknown YYYY` when only year is recorded). **Never invent days or months.**
2. **Enforce Bullet Contract**:
   Every timeline entry must conform strictly to:
   `- dd Month YYYY: [Event Name] — Concise non-Oxford EN-GB summary using exact canonical actor and division names. (Location: <county_slug>; Cross-province: <province_slugs | none>; Source: <source_slug> p. <N>)`
3. **Crosswalk Modern Local Histories to Historical `1912–1953` Counties**:
   - Use `./common/defines/modern_gazetteer_crosswalk.json5` (`covered_historical_adm3`) alongside internal town, village, river and *khoshuun* toponyms inside the text to route events from modern PRC county/district chronicles (`市辖区`/`县级市`), Taiwanese township chronicles, Mongolian post-1994 aimag/soum books and Tuvan republic-wide TIGPI compendia onto the exact contemporaneous `1912–1953` `<county_slug>` and `<province_slug>`.
   - Where a single historical frontier `厅` or `府` split into multiple modern PRC counties, merge events from all daughter `县志` into that historical `<county_slug>`; where a modern county straddles multiple historical `adm_3` units, split each event by its attested settlement toponym.
4. **Compile County Timelines First, Then Synthesise Province Timeline**:
   - Write `./chronicles/<province_slug>/counties/<county_slug>/chronology_<county_slug>.md` for every county, merging county chronicle events (`大事记`, `军事`, `建置沿革`) with county-level dispatches from `newspapers/` and `tusi_sources/`. Deduplicate identical events reported across multiple sources while retaining all citations in `(Source: ...)`.
   - Synthesise `./chronicles/<province_slug>/chronology_<province_slug>.md` by merging all `chronology_<county_slug>.md` entries with provincial/prefectural newspaper events and `tusi_sources/` entries, ordered chronologically from `1912` to `1953`.
5. **Enforce Inter-Provincial Coherence**:
   - **Date-Contemporaneous Jurisdiction**: Attribute every event on date `D` to the first-level division administering or occupying `<county_slug>` on date `D` per `./common/defines/province_defines.json5` and `./gis/adm_3_<year>.geojson`. Whenever a county or Tusi transfers between divisions (e.g. Zhili -> Rehe, Sichuan -> Xikang, East Hebei, Manchukuo or `改土归流` Tusi abolition), record paired `[Administrative Transfer of <County>]` entries with reciprocal `Cross-province:` tags.
   - **Cross-Border Campaigns and Corridors**: When military operations, retreats or political decrees span provincial, Tusi or international borders along `./common/gis/transport_corridors.json5`, tag `Cross-province:` with every affected `<province_slug>` and adopt a unified `[<Campaign Name> — <Sub-event>]` event title across all involved divisions.

## Step 3. Verification

1. Verify every bullet in `chronology_<county_slug>.md` and `chronology_<province_slug>.md` matches `- \d{2} [A-Z][a-z]+ \d{4}: \[[^\]]+\]` and sits in ascending chronological order within `1912–1953`.
2. Verify every actor name in the prose resolves to `canonical_name_en` in `./common/chronology/actor_glossary.json5` and `./chronicles/<province_slug>/actors_local.json5`.
3. Verify prose adheres to non-Oxford British English (`EN-GB`), `GMT+0` dating and exact source page citations.
