---
name: series-a-workflow
description: Runs Series A scrapers to construct gazetteers, newspapers, and chronologies from 1911-1953.
disable-model-invocation: true
---

When running skills, ensure the previous skill has exited cleanly and verify that it has completed before proceeding to the next one.

## Step 1. Construct GIS divisions.

Only run this step if CHGIS and PRC subdivisions have not yet been constructed. Proceed to Step 2 otherwise.

Run skills in the following order if they have not yet been constructed:
1. `/1.build-chgis-admin`
2. `/2.build-prc-crosswalk`

## Step 2. Scrape chronicles & newspapers.

Run skills in the following order:

1. `/3.orchestrate-chronicles`