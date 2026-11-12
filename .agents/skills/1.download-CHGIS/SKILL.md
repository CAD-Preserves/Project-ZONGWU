---
name: 1.download-CHGIS
description: Downloads CHGIS and other historical GIS provinces and prefectures for 1912-1953.
disable-model-invocation: true
---

Files generated at this stage are to be placed in the base directory, in the `./gis/` folder.

## Step 1. CHGIS, Subadministrative Divisions and Mongol Banners.

- Download CHGIS for all admin levels at 1912AD (or the closest year). Ensure your files are named adm_<level>_<year>.geojson, and are in GeoJSON format. If you cannot find a GeoJSON format, convert it. Do not go further than the 3rd-admin level.
- Using web_search and other tools, fetch and download subadministrative divisions for China, Mongolia, and the Tuvan Republic from 1912-1953AD, ensuring continuous timespans and updates. These divisions should be de jure, however any administrative changes made by the Japanese occupation should be included only in the territory they contemporaneously controlled.
- Transport networks: roads, railways (contemporaneous to the era), and waterways are important for interpolating natural transport corridors along which armies moved, relevant for Steps 2-3.

## Step 2. Tusi Tribes.

- Conduct a comprehensive literature review of Tusi tribes and all associated polities that existed from 1912-1953. Create three subagents for this task:
  - 1. Scraper: compiles lists of Tusi tribes and their chronologies. Scraper forwards to Mapper.
  - 2. Mapper: uses subadministrative divisions from Step 1, natural boundaries, scraped images/maps, and kriged settlements (presence modelling) to create potential Tusi subadministrative divisions.
  - 3. Verifier: visually inspects and checks EACH AND EVERY deliverable from `2. Mapper`. If a historical inaccuracy can be found using the web_search tool, or the model's knowledge base, it sends the task back to `2. Mapper` and `1. Scraper`.
- Continue until this goal is achieved. The parent model should check if the verifier has correctly completed the task.

## Step 3. 

- Using scanline rasterisation, place each year's raster into `./tests/CHGIS_adm_<level>_<year>.png/`. Do not clear these test files after you have finished, so that the user is able to inspect it.
- For 1 January each year, visually inspect each image to ensure that it is historically accurate and contemporaneous. If it is not, you must state 'I HAVE FAILED MYSELF', and proceed to Step 1.

## Step 4. 

- For all provinces or first-level subadministrative divisions, create a folder named `./chronicles/<province_name>/`. Tusis are to be treated as first-level subadministrative divisions.
- In `./common/defines/province_defines.json5`, define all province filepaths and their human-readable names.