"""Step 2 PRC 1954-2026 administrative lineage graph, 2026 carvings, and query-hygiene helpers."""

import os
import sys
from shapely.geometry import Point, box, shape
from shapely.ops import unary_union

if os.path.abspath(os.path.join(os.path.dirname(__file__), "..")) not in sys.path:
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from helpers import gis_helpers


def _infer_rank_from_zh (arg1_name_zh, arg2_fallback="xian"):
  """Infer canonical local-history administrative rank from a Simplified Chinese unit name.

  @param arg1_name_zh Official Chinese unit name.
  @param arg2_fallback Fallback rank string if no standard suffix matches.
  @return Canonical rank token (xian, autonomous_xian, banner_qi, etc.).
  """
  # Convert from parameters
  fallback = str(arg2_fallback or "xian")
  name_zh = str(arg1_name_zh or "").strip()

  if name_zh.endswith("林区"):
    return "linqu"
  if name_zh.endswith("特区"):
    return "tequ"
  if name_zh.endswith("自治旗"):
    return "autonomous_qi"
  if name_zh.endswith("旗"):
    return "banner_qi"
  if name_zh.endswith("自治县"):
    return "autonomous_xian"
  if name_zh.endswith("区"):
    return "urban_qu"
  if name_zh.endswith("市"):
    return "county_level_shi"
  if name_zh.endswith("县"):
    return "xian"

  # Return statement
  return fallback


def _patch_hotan_2024_units (arg1_units, arg2_reforms_cfg):
  """Disambiguate 653201/653221 in GADM and carve 27 December 2024 Hotan counties (653228, 653229).

  @param arg1_units Mutable list of PRC adm_3 unit dicts.
  @param arg2_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Updated list of PRC adm_3 unit dicts.
  """
  # Convert from parameters
  reforms_cfg = arg2_reforms_cfg or {}
  units = list(arg1_units or [])

  # Declare local instance variables.
  hotan_cfg = reforms_cfg.get("epoch_3_2001_2026", {}).get("hotan_2024_new_counties", [])
  hotan_geoms = []
  hotan_proto = None
  kept_units = []
  new_items = []

  for u in units:
    if u.get("parent_adm1") == "XinjiangUygur" and str(u.get("gb_code") or "").startswith("653201"):
      hotan_geoms.append(u["geom"])
      if hotan_proto is None or float(u["geom"].area) < float(hotan_proto["geom"].area):
        hotan_proto = dict(u)
    else:
      kept_units.append(u)

  if not hotan_geoms or hotan_proto is None:
    # Return statement
    return units

  combined = gis_helpers.clean_polygonal_geometry(unary_union(hotan_geoms))
  if combined is None or combined.is_empty:
    # Return statement
    return units

  min_x, min_y, max_x, max_y = combined.bounds
  split_lat = 36.15
  split_lon = 78.90
  south_box = box(min_x - 0.1, min_y - 0.1, max_x + 0.1, split_lat)
  hean_box = box(split_lon, min_y - 0.1, max_x + 0.1, split_lat)
  hekang_box = box(min_x - 0.1, min_y - 0.1, split_lon, split_lat)

  north_geom = gis_helpers.clean_polygonal_geometry(combined.difference(south_box))
  shi_disk = Point(79.92, 37.11).buffer(0.14, resolution=4)
  shi_geom = gis_helpers.clean_polygonal_geometry(north_geom.intersection(shi_disk)) if north_geom is not None else None
  xian_geom = gis_helpers.clean_polygonal_geometry(north_geom.difference(shi_geom)) if (north_geom is not None and shi_geom is not None) else north_geom

  if shi_geom is not None and not shi_geom.is_empty:
    shi_u = dict(hotan_proto)
    shi_u.update({
      "gb_code": "653201",
      "gb_1990": "653201",
      "geom": shi_geom,
      "name_en": "Hotan Shi",
      "name_py": "Hotan",
      "name_zh": "和田市",
      "name_zh_hant": "和田市",
      "parent_adm2": "Hotan",
      "parent_adm2_gb": "653200",
      "parent_adm2_zh": "和田地区",
      "unit_id": "prc_653201_hotan_shi",
      "unit_type": "county_level_shi",
    })
    new_items.append(shi_u)

  if xian_geom is not None and not xian_geom.is_empty:
    xian_u = dict(hotan_proto)
    xian_u.update({
      "gb_code": "653221",
      "gb_1990": "653221",
      "geom": xian_geom,
      "name_en": "Hotan Xian",
      "name_py": "Hotan",
      "name_zh": "和田县",
      "name_zh_hant": "和田縣",
      "parent_adm2": "Hotan",
      "parent_adm2_gb": "653200",
      "parent_adm2_zh": "和田地区",
      "unit_id": "prc_653221_hotan_xian",
      "unit_type": "xian",
    })
    new_items.append(xian_u)

  for cfg_item in hotan_cfg:
    gb = str(cfg_item["gb_code"])
    cbox = hean_box if gb == "653228" else hekang_box
    cgeom = gis_helpers.clean_polygonal_geometry(combined.intersection(cbox))
    if cgeom is None or cgeom.is_empty:
      continue
    new_u = dict(hotan_proto)
    new_u.update({
      "edge_cases": ["hotan_2024_carveout"],
      "gb_code": gb,
      "gb_1990": "653221",
      "geom": cgeom,
      "name_en": cfg_item["name_en"],
      "name_py": cfg_item["name_en"].replace(" Xian", ""),
      "name_zh": cfg_item["name_zh"],
      "name_zh_hant": cfg_item["name_zh"].replace("县", "縣"),
      "parent_adm2": "Hotan",
      "parent_adm2_gb": "653200",
      "parent_adm2_zh": "和田地区",
      "snapshot_year": int(cfg_item.get("snapshot_year", 2025)),
      "unit_id": f"prc_{gb}_{gis_helpers.slugify_snake(cfg_item['name_en'])}",
      "unit_type": "xian",
    })
    new_items.append(new_u)

  kept_units.extend(new_items)

  # Return statement
  return kept_units


def build_chronicle_search_plan (arg1_unit_meta, arg2_lineage_entry, arg3_edge_cases, arg4_reforms_cfg):
  """Construct clean 4-rung Mainland ZH chronicle search plan and blocklist per Skill 2/4 hygiene.

  @param arg1_unit_meta Dict containing gb_code, name_zh, parent_adm1, parent_adm2_zh, unit_type, edge_cases.
  @param arg2_lineage_entry Optional lineage record from prc_admin_lineage_1954_2026.json5.
  @param arg3_edge_cases Parsed local_history_edge_cases.json5 dict.
  @param arg4_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Tuple (edge_flags_list, chronicle_search_plan_dict, flat_clean_queries_list).
  """
  # Convert from parameters
  edge_cases = arg3_edge_cases or {}
  lineage = arg2_lineage_entry or {}
  reforms_cfg = arg4_reforms_cfg or {}
  unit_meta = arg1_unit_meta or {}

  # Declare local instance variables.
  banned_pre1949 = set(reforms_cfg.get("epoch_1_1954_1979", {}).get("pre_1949_imperial_republican_names_banned_in_mainland_xinzhi", []))
  blocked = []
  city_zh = str(unit_meta.get("parent_adm2_zh") or "").strip()
  edges = list(unit_meta.get("edge_cases") or [])
  eth_tokens = edge_cases.get("mainland_prc", {}).get("autonomous_ethnicity_tokens", [])
  gb = str(unit_meta.get("gb_code") or "").strip()
  n1 = str(unit_meta.get("parent_adm1") or "").strip()
  n3 = str(unit_meta.get("name_en") or "").strip()
  name_zh = str(unit_meta.get("name_zh") or "").strip()
  prov_zh = str(unit_meta.get("parent_adm1_zh") or "").strip()
  rung1 = []
  rung2 = []
  rung3 = []
  rung4 = []
  snap1990 = lineage.get("unit_1990s_snapshot", {})
  names_1990s = [str(n).strip() for n in snap1990.get("names_1980_2000", []) if str(n).strip()]
  ranks_1990s = [str(r).strip() for r in snap1990.get("ranks_1980_2000", []) if str(r).strip()]
  utype = str(unit_meta.get("unit_type") or "xian").strip()

  def _push (arg1_lst, arg2_q):
    q = str(arg2_q or "").strip()
    if not q:
      return
    base_q = q[:-1] if q.endswith("志") else q
    if q in banned_pre1949 or base_q in banned_pre1949:
      return
    if q not in arg1_lst:
      arg1_lst.append(q)

  if gb == "810000":
    if "hong_kong_sar" not in edges:
      edges.append("hong_kong_sar")
    hk_qs = edge_cases["mainland_prc"]["hong_kong_and_macau"]["810000"]["search_queries"]
    for q in hk_qs:
      _push(rung1, q)
    plan = {"blocked_post_2000_titles": [], "rung_1_1990s_exact": rung1, "rung_2_eth_stripped": [], "rung_3_shortened_bare": [], "rung_4_higher_admin": []}
    return edges, plan, list(rung1)

  if gb.startswith("82"):
    if "macau_sar" not in edges:
      edges.append("macau_sar")
    mo_qs = edge_cases["mainland_prc"]["hong_kong_and_macau"]["820000"]["search_queries"]
    for q in mo_qs:
      _push(rung1, q)
    plan = {"blocked_post_2000_titles": [], "rung_1_1990s_exact": rung1, "rung_2_eth_stripped": [], "rung_3_shortened_bare": [], "rung_4_higher_admin": []}
    return edges, plan, list(rung1)

  if gb == "350122" and "mainland_fuzhou_lianjiang_disambig" not in edges:
    edges.append("mainland_fuzhou_lianjiang_disambig")

  if not names_1990s:
    names_1990s = [name_zh]
  primary_90 = names_1990s[0]
  rank_90 = ranks_1990s[0] if ranks_1990s else _infer_rank_from_zh(primary_90, utype)
  events = snap1990.get("conversion_events", [])

  # Post-2000 conversion / carveout / rename checks
  if events:
    ev_types = {str(ev.get("event_type") or "") for ev in events}
    if "converted_to_qu" in ev_types or "merged_into_qu" in ev_types:
      if "che_xian_she_qu_post_2000" not in edges:
        edges.append("che_xian_she_qu_post_2000")
      _push(blocked, f"{name_zh}志")
    if "upgraded_to_shi" in ev_types:
      if "che_xian_she_shi_post_2000" not in edges:
        edges.append("che_xian_she_shi_post_2000")
      _push(blocked, f"{name_zh}志")
    if "renamed" in ev_types:
      if "post_2000_renaming" not in edges:
        edges.append("post_2000_renaming")
      _push(blocked, f"{name_zh}志")
      for ev in events:
        if ev.get("event_type") == "renamed" and ev.get("to_name"):
          _push(blocked, f"{ev['to_name']}志")
    if "carved_new_xian" in ev_types or "carved_xpcc_shi" in ev_types:
      _push(blocked, f"{name_zh}志")

  # Rung 1: exact 1980-2000 compilation-era titles
  for nm90 in names_1990s:
    if f"{nm90}志" not in blocked:
      _push(rung1, f"{nm90}志")

  # Include pre-1990 PRC simplifications (never pre-1949 names) if relevant
  for simp in reforms_cfg.get("epoch_1_1954_1979", {}).get("rare_character_simplifications_1950s_1960s", []):
    if str(simp.get("gb_code") or "") == gb or str(simp.get("new_name_zh") or "") == primary_90:
      old_s = str(simp.get("old_name_zh") or "")
      new_s = str(simp.get("new_name_zh") or "")
      if int(simp.get("effective_year", 1960)) <= 1986:
        if new_s:
          _push(rung1, f"{new_s}志")
      if "rare_char_simplified_1950s_1960s" not in edges:
        edges.append("rare_char_simplified_1950s_1960s")

  # Rung 2: recursive 55-ethnicity stripping for autonomous counties/banners
  if rank_90 in ("autonomous_xian", "autonomous_qi") or utype in ("autonomous_xian", "autonomous_qi") or "自治" in primary_90:
    if "autonomous_suffix_strip" not in edges:
      edges.append("autonomous_suffix_strip")
    stem = strip_ethnicity_tokens_recursive(primary_90, eth_tokens)
    tail = "旗志" if (rank_90 == "autonomous_qi" or utype == "autonomous_qi") else "县志"
    if stem and stem != primary_90:
      _push(rung2, f"{stem}{tail}")
    _push(rung3, f"{stem}志")
  else:
    stem = strip_ethnicity_tokens_recursive(primary_90, eth_tokens)
    if rank_90 == "county_level_shi" or utype == "county_level_shi":
      if "che_xian_she_shi" not in edges:
        edges.append("che_xian_she_shi")
      _push(rung1, f"{stem}县志")
    elif utype == "urban_qu" and f"{name_zh}志" not in blocked:
      _push(rung1, f"{name_zh}志")
      if rank_90 == "xian":
        _push(rung1, f"{stem}县志")
    if stem:
      _push(rung3, f"{stem}志")

  _push(rung3, f"{primary_90}地名志")
  if "dimingzhi_check" not in edges:
    edges.append("dimingzhi_check")

  # Rung 4: Higher prefecture, provincial summary, and metropolitan fenzhi fallbacks
  for _, m_info in edge_cases.get("mainland_prc", {}).get("metropolitan_core_districts", {}).items():
    if gb.startswith(m_info["gb_prefix"]) or n1 == m_info.get("city_zh"):
      if utype == "urban_qu" or name_zh.endswith("区"):
        if "metropolitan_core_district" not in edges:
          edges.append("metropolitan_core_district")
        for fz in m_info.get("fenzhi_suffixes", []):
          _push(rung4, f"{m_info['city_zh']}{fz}")
        for h_cnty in m_info.get("historic_counties", []):
          _push(rung1, f"{h_cnty}志" if not h_cnty.endswith("志") else h_cnty)

  if city_zh and city_zh != name_zh and city_zh != prov_zh:
    _push(rung4, f"{city_zh}志")
    if city_zh.endswith("地区"):
      _push(rung4, f"{city_zh[:-2]}市志")
  if prov_zh:
    p_stem = prov_zh.replace("壮族自治区", "").replace("回族自治区", "").replace("维吾尔自治区", "").replace("自治区", "").rstrip("省市")
    _push(rung4, f"{p_stem}省志·市县概况" if prov_zh.endswith("省") else f"{p_stem}通志")

  flat = []
  for lst in (rung1, rung2, rung3, rung4):
    for q in lst:
      if q not in flat and q not in blocked:
        flat.append(q)

  plan = {
    "blocked_post_2000_titles": blocked,
    "rung_1_1990s_exact": rung1,
    "rung_2_eth_stripped": rung2,
    "rung_3_shortened_bare": rung3,
    "rung_4_higher_admin": rung4,
  }

  # Return statement
  return edges, plan, flat


def build_prc_lineage_graph (arg1_units_2026, arg2_citas_1990, arg3_reforms_cfg, arg4_fz_cfg, arg5_edge_cases):
  """Construct the 1954-2026 directed acyclic administrative lineage graph.

  @param arg1_units_2026 List of 2026 PRC adm_3 unit dicts from ModernLayerAssembler.
  @param arg2_citas_1990 List of 1990 CITAS county dicts with gb, name_zh.
  @param arg3_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @param arg4_fz_cfg Parsed prc_functional_zones_and_sez.json5 dict.
  @param arg5_edge_cases Parsed local_history_edge_cases.json5 dict.
  @return Dict formatted for common/defines/prc_admin_lineage_1954_2026.json5.
  """
  # Convert from parameters
  citas_list = list(arg2_citas_1990 or [])
  fz_cfg = arg4_fz_cfg or {}
  reforms_cfg = arg3_reforms_cfg or {}
  units_2026 = list(arg1_units_2026 or [])

  # Declare local instance variables.
  citas_by_gb = {}
  conv_by_gb2026 = {}
  hotan_orig = fz_cfg.get("hotan_2024_origins", {})
  tibet_by_gb = {}
  units_by_id = {}
  units_by_gb = {str(u.get("gb_code") or ""): u for u in units_2026}
  xpcc_events = {}
  xpcc_orig = fz_cfg.get("xpcc_origins", {})

  for c in citas_list:
    gb = str(c.get("gb") or "").strip()
    nm = "".join(str(c.get("name_zh") or "").split())
    if gb and nm:
      citas_by_gb[gb] = nm

  e3 = reforms_cfg.get("epoch_3_2001_2026", {})
  for ev in e3.get("conversion_events", []):
    conv_by_gb2026.setdefault(str(ev.get("gb_2026") or ""), []).append(dict(ev))
  for ev in e3.get("tibetan_prefecture_upgrades", []):
    tibet_by_gb[str(ev.get("county_2026_gb") or "")] = dict(ev)
  for ev in e3.get("xpcc_shi_cities", []):
    xpcc_events[str(ev.get("gb_code") or "")] = dict(ev)

  for u in units_2026:
    uid = str(u["unit_id"])
    gb26 = str(u.get("gb_code") or "")
    gb90 = str(u.get("gb_1990") or gb26)
    n26_zh = str(u.get("name_zh") or "")
    utype26 = str(u.get("unit_type") or "xian")
    events = []
    names90 = []
    parent90_ids = []
    ranks90 = []

    if gb26 in hotan_orig:
      ho = hotan_orig[gb26]
      names90 = list(ho["parent_1990s_names_zh"])
      parent90_ids = list(ho["parent_1990s_unit_ids"])
      ranks90 = ["xian"]
      events.append({"effective_date": "27 December 2024", "event_type": "carved_new_xian", "from_name": "和田县", "snapshot_year": 2025, "to_name": n26_zh})
    elif gb26 in xpcc_orig and gb26 != "659001":
      xo = xpcc_orig[gb26]
      names90 = list(xo["parent_1990s_names_zh"])
      parent90_ids = list(xo["parent_1990s_unit_ids"])
      ranks90 = [_infer_rank_from_zh(names90[0], "xian")]
      xev = xpcc_events.get(gb26, {})
      events.append({"effective_date": xev.get("effective_date", "01 January 2003"), "event_type": "carved_xpcc_shi", "from_name": names90[0], "snapshot_year": int(xev.get("snapshot_year", 2003)), "to_name": n26_zh})
    elif gb26 in conv_by_gb2026:
      evs = sorted(conv_by_gb2026[gb26], key=lambda x: int(x.get("snapshot_year", 2001)))
      gb90 = str(evs[0].get("gb_1990") or gb90)
      names90 = [str(evs[0]["from_name"])]
      ranks90 = [_infer_rank_from_zh(names90[0], "xian")]
      for ev in evs:
        events.append({
          "effective_date": ev.get("effective_date", ""),
          "event_type": ev.get("event_type", "converted_to_qu"),
          "from_name": ev.get("from_name", ""),
          "gb_1990": ev.get("gb_1990", gb90),
          "snapshot_year": int(ev.get("snapshot_year", 2001)),
          "to_name": ev.get("to_name", n26_zh),
        })
      stem_s = gis_helpers.slugify_snake(u.get("name_en") or n26_zh)
      parent90_ids = [f"prc_{gb90}_{stem_s}"]
    elif gb26 in tibet_by_gb:
      tev = tibet_by_gb[gb26]
      names90 = [str(tev["county_1990_name"])]
      ranks90 = [_infer_rank_from_zh(names90[0], "xian")]
      events.append({
        "effective_date": tev["effective_date"],
        "event_type": "converted_to_qu",
        "from_name": tev["county_1990_name"],
        "pref_name_old": tev["pref_name_old"],
        "pref_name_zh": tev["pref_name_zh"],
        "snapshot_year": int(tev["snapshot_year"]),
        "to_name": n26_zh,
      })
      parent90_ids = [f"prc_{gb90}_{gis_helpers.slugify_snake(u.get('name_en') or n26_zh)}"]
    else:
      c_zh = citas_by_gb.get(gb90, "")
      if c_zh and "辖区" not in c_zh and c_zh != n26_zh:
        names90 = [c_zh]
        ranks90 = [_infer_rank_from_zh(c_zh, utype26)]
        if utype26 == "urban_qu" and c_zh.endswith("县"):
          events.append({"effective_date": "01 January 2001", "event_type": "converted_to_qu", "from_name": c_zh, "snapshot_year": 2001, "to_name": n26_zh})
        elif utype26 == "county_level_shi" and c_zh.endswith("县"):
          events.append({"effective_date": "01 January 1995", "event_type": "upgraded_to_shi", "from_name": c_zh, "snapshot_year": 1995, "to_name": n26_zh})
      else:
        names90 = [n26_zh]
        ranks90 = [utype26]
      parent90_ids = [uid]

    units_by_id[uid] = {
      "is_post_1990_sez_or_new_area": False,
      "parent_1990s_unit_ids": parent90_ids,
      "unit_1990s_snapshot": {
        "conversion_events": events,
        "gb_1990": gb90,
        "names_1980_2000": names90,
        "ranks_1980_2000": ranks90,
      },
      "unit_2026_snapshot": {
        "gb_code": gb26,
        "name_zh": n26_zh,
        "parent_adm1_zh": str(u.get("parent_adm1_zh") or ""),
        "parent_adm2_zh": str(u.get("parent_adm2_zh") or ""),
        "unit_type": utype26,
      },
    }

  # Register non-GB2260 functional zones, SEZs, and State-level New Areas
  for fz_id, fz_meta in sorted(fz_cfg.get("functional_zones", {}).items()):
    gb26 = str(fz_meta.get("gb_2026") or "")
    u_match = units_by_gb.get(gb26) if gb26 else None
    units_by_id[fz_id] = {
      "is_post_1990_sez_or_new_area": True,
      "parent_1990s_unit_ids": list(fz_meta.get("parent_1990s_unit_ids") or []),
      "unit_1990s_snapshot": {
        "conversion_events": [{
          "effective_date": f"01 January {fz_meta.get('established_year', 1994)}",
          "event_type": "established_functional_zone",
          "from_name": "/".join(fz_meta.get("parent_1990s_names_zh") or []),
          "snapshot_year": int(fz_meta.get("established_year", 1994)),
          "to_name": str(fz_meta.get("name_zh") or ""),
        }],
        "gb_1990": "",
        "names_1980_2000": list(fz_meta.get("parent_1990s_names_zh") or []),
        "ranks_1980_2000": ["xian"],
      },
      "unit_2026_snapshot": {
        "gb_code": gb26 or (u_match["gb_code"] if u_match else ""),
        "name_zh": str(fz_meta.get("name_zh") or ""),
        "parent_adm1_zh": str(fz_meta.get("parent_adm1_zh") or ""),
        "parent_adm2_zh": str(fz_meta.get("parent_adm1_zh") or ""),
        "unit_type": str(fz_meta.get("kind") or "state_new_area"),
      },
    }

  # Return statement
  return {"coverage_years": [1954, 2026], "schema_version": 1, "units_by_id": units_by_id}


def carve_2026_prc_additions (arg1_units, arg2_reforms_cfg, arg3_fz_cfg, arg4_gb_lookup, arg5_precision):
  """Apply 2024 Hotan new counties (653228/653229) and XPCC shi-city carvings (659002-659012).

  @param arg1_units List of PRC adm_3 unit dicts from GADM CHN_3.
  @param arg2_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @param arg3_fz_cfg Parsed prc_functional_zones_and_sez.json5 dict.
  @param arg4_gb_lookup GB/T 2260 lookup dictionary.
  @param arg5_precision Coordinate rounding decimal places.
  @return Updated watertight list of 2026 PRC adm_3 unit dicts.
  """
  # Convert from parameters
  precision = int(arg5_precision)
  reforms_cfg = arg2_reforms_cfg or {}
  units = _patch_hotan_2024_units(arg1_units, reforms_cfg)

  # Declare local instance variables.
  by_gb = {}
  carved_units = []
  existing_gbs = {str(u.get("gb_code") or "") for u in units}
  xpcc_list = reforms_cfg.get("epoch_3_2001_2026", {}).get("xpcc_shi_cities", [])

  for u in units:
    by_gb[str(u.get("gb_code") or "")] = u

  for xitem in xpcc_list:
    xgb = str(xitem["gb_code"])
    if xgb in existing_gbs:
      continue
    pt = Point(float(xitem["seat_lon"]), float(xitem["seat_lat"]))
    disk = pt.buffer(float(xitem.get("radius_deg", 0.06)), resolution=4)
    xj_units = [u for u in units if u.get("parent_adm1") == "XinjiangUygur" and u["geom"].intersects(disk)]
    if not xj_units:
      host_u = by_gb.get(str(xitem["host_county_gb"]))
      if host_u is not None:
        xj_units = [host_u]
    if not xj_units:
      continue
    inter_parts = []
    primary_host = None
    best_ov = -1.0
    for hu in xj_units:
      part = gis_helpers.clean_polygonal_geometry(hu["geom"].intersection(disk))
      if part is None or part.is_empty:
        continue
      rem = gis_helpers.clean_polygonal_geometry(hu["geom"].difference(part))
      if rem is None or rem.is_empty:
        continue
      hu["geom"] = rem
      inter_parts.append(part)
      if float(part.area) > best_ov:
        best_ov = float(part.area)
        primary_host = hu
    if not inter_parts:
      continue
    inter_u = gis_helpers.clean_polygonal_geometry(unary_union(inter_parts))
    inter_r = gis_helpers.round_geometry(inter_u, precision) if inter_u is not None else None
    if inter_r is None or inter_r.is_empty:
      continue
    actual_host_gb = str(primary_host["gb_code"]) if primary_host else str(xitem["host_county_gb"])
    carved_units.append({
      "edge_cases": ["xpcc_shi_city_carveout"],
      "gb_code": xgb,
      "gb_1990": actual_host_gb,
      "geom": inter_r,
      "host_gb_2026": actual_host_gb,
      "name_en": str(xitem["name_en"]),
      "name_py": str(xitem["name_en"]),
      "name_zh": str(xitem["name_zh"]),
      "name_zh_hant": str(xitem["name_zh"]).replace("师", "師").replace("图", "圖").replace("铁", "鐵").replace("门", "門").replace("关", "關").replace("双", "雙").replace("杨", "楊").replace("阳", "陽"),
      "parent_adm1": "XinjiangUygur",
      "parent_adm1_gb": "650000",
      "parent_adm1_zh": "新疆维吾尔自治区",
      "parent_adm2": "XPCC County-level Cities",
      "parent_adm2_gb": "659000",
      "parent_adm2_zh": "自治区直辖县级行政区划",
      "region": "mainland_prc",
      "search_queries": [],
      "snapshot_year": int(xitem.get("snapshot_year", 2003)),
      "unit_id": f"prc_{xgb}_{gis_helpers.slugify_snake(xitem['name_en'])}",
      "unit_type": "county_level_shi",
    })

  units.extend(carved_units)

  # Return statement
  return units


def strip_ethnicity_tokens_recursive (arg1_name_zh, arg2_tokens):
  """Strip autonomous suffixes and recursively remove all 55 ethnicity tokens from a county name.

  @param arg1_name_zh Full Chinese autonomous county/banner name.
  @param arg2_tokens Ordered list of ethnicity tokens (longest-first preferred).
  @return Bare place-name stem without ethnicity or autonomous-unit suffixes.
  """
  # Convert from parameters
  stem = str(arg1_name_zh or "").strip()
  tokens = sorted([str(t).strip() for t in (arg2_tokens or []) if str(t).strip()], key=len, reverse=True)

  # Declare local instance variables.
  changed = True

  for sfx in ("自治县", "自治旗", "自治州", "林区", "特区", "市", "区", "县", "旗"):
    if stem.endswith(sfx) and len(stem) > len(sfx):
      stem = stem[:-len(sfx)]
      break

  for _ in range(10):
    if not changed:
      break
    changed = False
    for tok in tokens:
      if stem.endswith(tok) and len(stem) > len(tok):
        stem = stem[:-len(tok)]
        changed = True
        break

  # Return statement
  return stem
