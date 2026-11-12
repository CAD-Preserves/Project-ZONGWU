---
name: 1.download-all-provinces
description: Compiles all county chronicles for Project-ZONGWU, running a subagent workflow for each province.
disable-model-invocation: true
---

Your role is as a historical researcher for the Warlord Era, Second Sino-Japanese War, and the Chinese Civil War, from 1912-1953. In doing so, you are to download, translate, OCR, and piece together county-by-county chronologies (alongside corresponding source material).

Each province is to be contained within the filepaths set forwards in `./common/defines/province_defines.json5`.

## Finding Source Material

- Academic gazetteers, blogposts, or lists can often be used to discover primary Chinese newspaper research, but such research is often paywalled.
  - Free websites containing newspapers or chronicles (especially at the county level) should obviously be scraped.
  - If a website is paywalled, you should try to find a way around the paywall, either via scripting or any mirrors that may exist.
- Use web-search to discover primary source material. Source material is mainly contained in county chronicles and newspapers.
- Hints from human researcher:
  - You are allowed to use shadow libraries. These include Sci-Hub, Libgen, z-lib, and Archive.
    - Of these shadow libraries, z-lib is by far the most important.
  - Let's say you want to find the chronicle for 'Youyang Tujia' and 'Miao Autonomous County in Chongqing City'. You would take the official name of the county: 酉阳土家族苗族自治县, and then add 志 to the end of it, i.e. 酉阳土家族苗族自治县志, looking that up on z-lib.
    - In this example, that wouldn't be the exact name of the book, as they often exclude any '... ethnicity autonomous' bit. So it would be 酉阳县志 on z-lib.
  - Chinese chronicles are often structured as follows:
    - First 30 pages: photos from the county, normally photos of party officials and nature.
    - 5 different introductions or so.
    - Table of Contents.
    - After this usually (90%) comes the **Chronicle of Major Events**.
    - Afterwards, is often the **History of the Administration**, which contains the historical borders of the county.
    - Then you have sections, not in order, but i.e. 'Nature', 'Population', 'Political Parties'.
    - Important for de-facto mapping is the **Military** section, which normally has reports on battles from the 1200s onwards, and is needed for mappers.
    - Most of the content trails off after this, but ideally you would scrape the entire book.
  - The most interesting parts for mappers are: 大事记 (Major events), 军事 (Military affairs), and 人口 (Population).
  - Make sure you choose a recent chronicle from 1980 to 2010 or so, don't accidentally choose one from the 1940s or something.
  - Newspapers are entirely separate affairs, since they are contemporaneous. Sometimes you can find them at the provincial level or in major cities, make sure `/2.index-province` covers this and receives this context.


## Step 1. Subagent Swarm

For each province, create a Province Subagent. This subagent is allowed access to all tools, and should find source material in accordance with the section (`## Finding Source Material`) for both 2. and 3. Call skills in the following order sequentially, waiting for a preceding step to finish before calling the next skill. When calling commands, make sure that the necessary context is embedded in the command for the subagent to work.

1. `/2.index-province`
2. `/3.scrape-province`

Verify and test its outputs. If you cannot verify that its outputs are complete, send the subagent back to work and wait for it to finish.

## Step 2. OCR and Translation

For each province, call the following skills. Make sure you wait for the preceding step to complete before going onto the next one. This follows the same rules as `## Step 1. Subagent Swarm`.

1. `/4.OCR-translate-province`
2. `/5.chronology-province`