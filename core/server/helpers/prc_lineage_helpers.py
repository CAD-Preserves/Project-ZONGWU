"""PRC 1954-2026 statutory lineage graph builder and 4-rung Mainland gazetteer query planner."""

from collections import deque
import os
import sys
from shapely import STRtree

if os.path.abspath(os.path.join(os.path.dirname(__file__), "..")) not in sys.path:
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from helpers import gis_helpers


def _clean_zh_stem (arg1_name_zh):
  """Strip modern administrative suffix characters to obtain a clean Chinese toponym stem.

  @param arg1_name_zh Simplified Chinese administrative name.
  @return Stem string preserving short 2-char names intact.
  """
  # Convert from parameters
  name_zh = str(arg1_name_zh or "").strip()

  # Declare local instance variables.
  sfx = ""

  for sfx in (
    "特别行政区",
    "壮族自治区",
    "回族自治区",
    "维吾尔自治区",
    "自治区",
    "自治州",
    "自治县",
    "自治旗",
    "矿区",
    "林区",
    "新区",
    "特区",
    "地区",
    "盟",
    "市",
    "县",
    "区",
    "旗",
  ):
    if name_zh.endswith(sfx) and len(name_zh) - len(sfx) >= 2:
      return name_zh[:-len(sfx)]

  # Return statement
  return name_zh


def _collect_ethnicity_tokens (arg1_edge_cases):
  """Collect descending-length list of ethnicity names and autonomy tokens from config.

  @param arg1_edge_cases Parsed local_history_edge_cases.json5 dictionary.
  @return List of ethnic tokens sorted longest-first.
  """
  # Convert from parameters
  edge_cases = arg1_edge_cases or {}

  # Declare local instance variables.
  ml = edge_cases.get("mainland_prc", {})
  raw_tokens = []
  tok = ""

  raw_tokens.extend(ml.get("ethnic_minority_groups", []))
  raw_tokens.extend(ml.get("ethnicity_tokens", []))
  raw_tokens.extend(ml.get("recognized_ethnicities_55", []))

  # Expand bare ethnic nouns when entries end in 族
  expanded = set()
  for tok in raw_tokens:
    tok = str(tok or "").strip()
    if not tok:
      continue
    expanded.add(tok)
    if tok.endswith("族") and len(tok) > 1:
      expanded.add(tok[:-1])

  # Return statement
  return sorted(expanded, key=lambda x: (-len(x), x))


def _dedupe_queries (arg1_queries, arg2_banned_set):
  """Deduplicate Simplified Chinese search strings while purging banned pre-1949 or classical URLs.

  @param arg1_queries Candidate query strings list.
  @param arg2_banned_set Set of forbidden imperial/republican toponyms.
  @return Cleaned list of unique query strings.
  """
  # Convert from parameters
  banned_set = set(arg2_banned_set or ())
  queries = arg1_queries or []

  # Declare local instance variables.
  out = []
  q = ""
  seen = set()
  stem = ""

  for q in queries:
    q = str(q or "").strip()
    if not q or q in seen:
      continue
    if "ctext.org" in q.lower():
      continue
    stem = q.rstrip("志")
    if q in banned_set or stem in banned_set:
      continue
    seen.add(q)
    out.append(q)

  # Return statement
  return out


def _index_areacodes_backward (arg1_areacodes):
  """Build reverse code-transition lookup and 1990s-active ancestor index from scraped MCA areacodes.

  @param arg1_areacodes Output dict from ctamap_io_helpers.load_areacodes_lineage().
  @return Dictionary containing 'by_code' and 'prev_by_code' mappings.
  """
  # Convert from parameters
  ac_doc = arg1_areacodes or {}

  # Declare local instance variables.
  by_code = ac_doc.get("by_code", {})
  prev_by_code = {}
  row = {}
  tgt = {}

  for row in ac_doc.get("rows", []):
    for tgt in row.get("new_targets", []):
      prev_by_code.setdefault(tgt["code"], []).append({
        "change_year": tgt.get("year") or row.get("change_year"),
        "old_code": row["code"],
        "old_name_zh": row["name_zh"],
        "status": row["status"],
      })

  # Return statement
  return {"by_code": by_code, "prev_by_code": prev_by_code}


def _match_unit_ctamap_events (arg1_names_set, arg2_adm1_zh, arg3_events):
  """Collect scraped CTAmap change_events_v2 records mentioning a county or its 1990s predecessor.

  @param arg1_names_set Set of Chinese unit names (2026 + 1990s).
  @param arg2_adm1_zh Province Chinese name for regional disambiguation.
  @param arg3_events List of CTAmap change_events_v2 CSV row dicts.
  @return List of compact event summary dicts.
  """
  # Convert from parameters
  adm1_prefix = str(arg2_adm1_zh or "")[:2]
  events = arg3_events or []
  names_set = {str(n).strip() for n in arg1_names_set if str(n or "").strip()}

  # Declare local instance variables.
  ev = {}
  matched = []
  new_parts = []
  old_parts = []
  reg = ""

  if not names_set or not events:
    return matched

  for ev in events:
    reg = str(ev.get("region") or "")
    if adm1_prefix and reg and adm1_prefix not in reg:
      continue
    old_parts = [p.strip() for p in str(ev.get("old_unit") or "").split("；") if p.strip()]
    new_parts = [p.strip() for p in str(ev.get("new_unit") or "").split("；") if p.strip()]
    if any(p in names_set for p in old_parts) or any(p in names_set for p in new_parts):
      matched.append({
        "approval_no": str(ev.get("approval_no_norm") or ev.get("approval_no_raw") or ""),
        "event_id": str(ev.get("event_id") or ""),
        "event_type": str(ev.get("event_type") or ""),
        "new_unit": str(ev.get("new_unit") or ""),
        "old_unit": str(ev.get("old_unit") or ""),
        "snapshot_year": str(ev.get("snapshot_year") or ""),
      })

  # Return statement
  return matched


def _trace_1990s_areacodes (arg1_gb_code, arg2_rev_idx):
  """Traverse MCA areacodes reverse edges from a 2026 code back to 1981-1999 predecessors.

  @param arg1_gb_code 6-digit GB/T 2260 administrative code.
  @param arg2_rev_idx Index dict built by _index_areacodes_backward().
  @return Tuple of (ancestor_codes_ordered, ancestor_rows_ordered).
  """
  # Convert from parameters
  gb_code = str(arg1_gb_code or "").strip()
  rev_idx = arg2_rev_idx or {}

  # Declare local instance variables.
  by_code = rev_idx.get("by_code", {})
  code = ""
  depth = 0
  edge = {}
  out_codes = []
  out_rows = []
  prev_map = rev_idx.get("prev_by_code", {})
  q = deque()
  row = {}
  seen = set()

  if not gb_code:
    return out_codes, out_rows

  q.append((gb_code, 0))
  seen.add(gb_code)

  while q:
    code, depth = q.popleft()
    for row in by_code.get(code, []):
      out_rows.append(row)
      en_y = row.get("enable_year") or 1981
      ch_y = row.get("change_year") or 2026
      if en_y <= 1999 and ch_y >= 1989:
        out_codes.append((code, row["name_zh"], en_y, ch_y))
    if depth >= 6:
      continue
    for edge in prev_map.get(code, []):
      oc = edge["old_code"]
      if oc not in seen:
        seen.add(oc)
        q.append((oc, depth + 1))

  # Return statement
  return out_codes, out_rows


def build_chronicle_search_plan (arg1_unit_meta, arg2_lineage_entry, arg3_edge_cases, arg4_reforms_cfg):
  """Build edge-case tags and a 4-rung Simplified Chinese chronicle search plan for a Mainland unit.

  @param arg1_unit_meta Unit metadata dictionary (gb_code, name_zh, parent_adm1_zh, parent_adm2_zh, unit_type).
  @param arg2_lineage_entry Corresponding entry from build_prc_lineage_graph() units_by_id.
  @param arg3_edge_cases Parsed local_history_edge_cases.json5 dictionary.
  @param arg4_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dictionary.
  @return Tuple of (edge_cases_list, search_plan_dict, flat_queries_list).
  """
  # Convert from parameters
  edge_cases = arg3_edge_cases or {}
  lin_entry = arg2_lineage_entry or {}
  reforms_cfg = arg4_reforms_cfg or {}
  unit_meta = arg1_unit_meta or {}

  # Declare local instance variables.
  adm1_zh = str(unit_meta.get("parent_adm1_zh") or "")
  adm2_zh = str(unit_meta.get("parent_adm2_zh") or "")
  banned_pre1949 = set(reforms_cfg.get("epoch_1_1954_1979", {}).get("pre_1949_imperial_republican_names_banned_in_mainland_xinzhi", []))
  edges = ["prefer_1985_2005_xinzhi", "zh_hans_strict_mainland"]
  eth_tokens = _collect_ethnicity_tokens(edge_cases)
  flat_qs = []
  gb = str(unit_meta.get("gb_code") or "")
  name_2026 = str(unit_meta.get("name_zh") or "")
  names_1990s = []
  p1_stem = _clean_zh_stem(adm1_zh)
  p2_stem = _clean_zh_stem(adm2_zh)
  primary_90 = ""
  r1 = []
  r2 = []
  r3 = []
  r4 = []
  snap_90 = lin_entry.get("unit_1990s_snapshot", {})
  stem_90 = ""
  utype = str(unit_meta.get("unit_type") or "")

  if gb.startswith("81"):
    edges.append("hong_kong_chronicle_series")
  elif gb.startswith("82"):
    edges.append("macau_chronicle_series")
  if utype in ("autonomous_county", "autonomous_banner") or "自治" in name_2026:
    edges.append("strip_ethnicity_tokens_xinzhi")

  names_1990s = [str(n).strip() for n in snap_90.get("names_zh", []) if str(n or "").strip()]
  if not names_1990s and name_2026:
    names_1990s = [name_2026]
  primary_90 = str(snap_90.get("primary_name_zh") or (names_1990s[0] if names_1990s else name_2026))

  if gb.startswith("81"):
    r1 = ["香港志", "香港地方志", "新界年鉴", "新界志", "九龙城寨志"]
    r2 = ["香港通史", "港九地方志", "香港年鉴"]
    r3 = [f"{name_2026}志", f"{name_2026}区志"]
    r4 = ["广东省志·港澳台卷", "广东省志"]
  elif gb.startswith("82"):
    r1 = ["澳门志", "澳门地方志", "澳门编年史", "澳门年鉴"]
    r2 = ["澳门掌故", "澳门市政志"]
    r3 = [f"{name_2026}志"]
    r4 = ["广东省志·港澳台卷", "广东省志"]
  else:
    for n90 in names_1990s[:4]:
      s90 = _clean_zh_stem(n90)
      r1.extend([f"{n90}志", f"{n90}地名志", f"{s90}县志", f"{n90}·建置沿革"])

    for n90 in names_1990s[:3]:
      stem_90 = strip_ethnicity_tokens_recursive(n90, eth_tokens)
      if stem_90 and stem_90 != n90:
        r2.extend([f"{stem_90}志", f"{_clean_zh_stem(stem_90)}县志", f"{_clean_zh_stem(stem_90)}旗志"])
    if not r2 and primary_90:
      s_bare = _clean_zh_stem(strip_ethnicity_tokens_recursive(primary_90, eth_tokens))
      if s_bare:
        r2.extend([f"{s_bare}县志", f"{s_bare}地方志"])

    if name_2026:
      r3 = [f"{name_2026}志", f"{adm2_zh}{name_2026}志" if adm2_zh and adm2_zh != adm1_zh else f"{adm1_zh}{name_2026}志", f"{name_2026}年鉴"]

    if adm2_zh and adm2_zh != adm1_zh:
      r4.extend([f"{adm2_zh}志", f"{p2_stem}地区志", f"{p2_stem}市志·建置志"])
    if adm1_zh:
      r4.extend([f"{p1_stem}通志", f"{adm1_zh}志·建置沿革志", f"{p1_stem}省志·地名志"])

  r1 = _dedupe_queries(r1, banned_pre1949)
  r2 = _dedupe_queries(r2, banned_pre1949)
  r3 = _dedupe_queries(r3, banned_pre1949)
  r4 = _dedupe_queries(r4, banned_pre1949)

  plan = {
    "rung_1_1990s_exact": r1,
    "rung_2_ethnicity_stripped": r2,
    "rung_3_2026_modern": r3,
    "rung_4_prefecture_provincial_fallback": r4,
  }
  flat_qs = _dedupe_queries(r1 + r2 + r3 + r4, banned_pre1949)

  # Return statement
  return edges, plan, flat_qs


def build_prc_lineage_graph (arg1_units_2026, arg2_citas_1990, arg3_reforms_cfg, arg4_fz_cfg, arg5_edge_cases, arg6_areacodes=None, arg7_ctamap_events=None):
  """Construct the 1954-2026 PRC statutory lineage graph linking 2026 CTAmap units to 1990s CITAS & MCA history.

  @param arg1_units_2026 List of modern PRC adm_3 unit dictionaries (each carrying Shapely 'geom').
  @param arg2_citas_1990 List of 1990 CITAS county dictionaries.
  @param arg3_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dictionary.
  @param arg4_fz_cfg Parsed prc_functional_zones_and_sez.json5 dictionary.
  @param arg5_edge_cases Parsed local_history_edge_cases.json5 dictionary.
  @param arg6_areacodes Optional parsed yescallop/areacodes lineage dict.
  @param arg7_ctamap_events Optional CTAmap change_events_v2 row list.
  @return Lineage dictionary matching common/defines/prc_admin_lineage_1954_2026.json5 schema v1.
  """
  # Convert from parameters
  areacodes = arg6_areacodes or {}
  citas_1990 = [c for c in (arg2_citas_1990 or []) if str(c.get("gb") or "") not in ("0", "1", "")]
  ctamap_events = arg7_ctamap_events or []
  edge_cases = arg5_edge_cases or {}
  fz_cfg = arg4_fz_cfg or {}
  reforms_cfg = arg3_reforms_cfg or {}
  units_2026 = arg1_units_2026 or []

  # Declare local instance variables.
  ac_rows = []
  anc_codes = []
  c_by_gb = {}
  c_geoms = []
  c_ids = []
  c_item = {}
  c_tree = None
  fz_dict = fz_cfg.get("functional_zones", {})
  fz_out = {}
  gb = ""
  hotan_origins = fz_cfg.get("hotan_2024_origins", {})
  names_90 = []
  ov_pairs = []
  p90_ids = []
  rev_idx = _index_areacodes_backward(areacodes)
  u = {}
  uid = ""
  units_by_id = {}

  for c_item in citas_1990:
    gb_c = str(c_item.get("gb") or "").strip()
    cid = f"prc_{gb_c}_{gis_helpers.slugify_snake(c_item.get('name_en') or gb_c)}"
    c_item["citas_unit_id"] = cid
    c_by_gb.setdefault(gb_c, []).append(c_item)
    c_geoms.append(c_item["geom"])
    c_ids.append(c_item)

  if c_geoms:
    c_tree = STRtree(c_geoms)

  for u in units_2026:
    uid = str(u["unit_id"])
    gb = str(u.get("gb_code") or "")
    anc_codes, ac_rows = _trace_1990s_areacodes(gb, rev_idx)

    p90_ids = []
    names_90 = []
    gb_90s = []

    # 1. Known 2024 Hotan origin overrides / exact MCA reverse code chains
    if gb in hotan_origins:
      for pid in hotan_origins[gb].get("parent_1990s_unit_ids", []):
        if pid not in p90_ids:
          p90_ids.append(pid)
      for nzh in hotan_origins[gb].get("parent_1990s_names_zh", []):
        if nzh not in names_90:
          names_90.append(nzh)

    # Sort ancestors active in 1990-1999 (earlier enable_year first, exact gb match favoured)
    anc_sorted = sorted(anc_codes, key=lambda x: (0 if x[0] == gb else 1, x[2], x[0]))
    for code_90, name_90, _, _ in anc_sorted:
      if name_90 and name_90 not in names_90:
        names_90.append(name_90)
      if code_90 not in gb_90s:
        gb_90s.append(code_90)
      for c_hit in c_by_gb.get(code_90, []):
        if c_hit["citas_unit_id"] not in p90_ids:
          p90_ids.append(c_hit["citas_unit_id"])
        if c_hit.get("name_zh") and c_hit["name_zh"] not in names_90:
          names_90.append(c_hit["name_zh"])

    # 2. Spatial overlap fallback / fortification against CITAS 1990 polygons
    u_geom = u.get("geom")
    if u_geom is not None and c_tree is not None:
      ov_pairs = []
      for c_idx in c_tree.query(u_geom):
        c_obj = c_geoms[int(c_idx)]
        if not u_geom.intersects(c_obj):
          continue
        ov = float(u_geom.intersection(c_obj).area)
        if ov > 1e-6 and ov / max(float(u_geom.area), 1e-9) >= 0.08:
          ov_pairs.append((ov, c_ids[int(c_idx)]))
      ov_pairs.sort(key=lambda x: x[0], reverse=True)
      for _, c_item in ov_pairs[:4]:
        if c_item["citas_unit_id"] not in p90_ids:
          p90_ids.append(c_item["citas_unit_id"])
        if c_item.get("name_zh") and c_item["name_zh"] not in names_90:
          names_90.append(c_item["name_zh"])
        if c_item.get("gb") and c_item["gb"] not in gb_90s:
          gb_90s.append(c_item["gb"])

    if not names_90 and u.get("name_zh"):
      names_90 = [u["name_zh"]]
    if not gb_90s and gb:
      gb_90s = [gb]

    ev_hits = _match_unit_ctamap_events(set(names_90) | {u.get("name_zh", "")}, u.get("parent_adm1_zh", ""), ctamap_events)
    units_by_id[uid] = {
      "areacode_chain": [
        {
          "change_year": r.get("change_year"),
          "code": r["code"],
          "enable_year": r.get("enable_year"),
          "name_zh": r["name_zh"],
          "status": r["status"],
        }
        for r in ac_rows[:12]
      ],
      "ctamap_events": ev_hits,
      "gb_code_2026": gb,
      "is_functional_zone": False,
      "name_en": u.get("name_en", ""),
      "name_zh_2026": u.get("name_zh", ""),
      "parent_1990s_unit_ids": p90_ids,
      "parent_adm1": u.get("parent_adm1", ""),
      "parent_adm2": u.get("parent_adm2", ""),
      "unit_1990s_snapshot": {
        "gb_codes": gb_90s,
        "names_zh": names_90,
        "primary_name_zh": names_90[0] if names_90 else u.get("name_zh", ""),
      },
      "unit_2026_snapshot": {
        "gb_code": gb,
        "name_en": u.get("name_en", ""),
        "name_zh": u.get("name_zh", ""),
        "parent_adm1_zh": u.get("parent_adm1_zh", ""),
        "parent_adm2_zh": u.get("parent_adm2_zh", ""),
      },
      "unit_id": uid,
    }

  # 3. Functional zones / State New Areas (e.g. Xiongan, Liangjiang)
  for fz_id, fz_meta in sorted(fz_dict.items()):
    fz_names = [str(n) for n in fz_meta.get("parent_1990s_names_zh", []) if n]
    fz_pids = list(fz_meta.get("parent_1990s_unit_ids", []))
    fz_entry = {
      "established_year": fz_meta.get("established_year"),
      "gb_code_2026": str(fz_meta.get("gb_2026") or ""),
      "is_functional_zone": True,
      "kind": str(fz_meta.get("kind") or "functional_zone"),
      "name_zh_2026": str(fz_meta.get("name_zh") or ""),
      "parent_1990s_unit_ids": fz_pids,
      "parent_adm1_zh": str(fz_meta.get("parent_adm1_zh") or ""),
      "unit_1990s_snapshot": {
        "names_zh": fz_names,
        "primary_name_zh": fz_names[0] if fz_names else str(fz_meta.get("name_zh") or ""),
      },
      "unit_2026_snapshot": {
        "gb_code": str(fz_meta.get("gb_2026") or ""),
        "name_zh": str(fz_meta.get("name_zh") or ""),
        "parent_adm1_zh": str(fz_meta.get("parent_adm1_zh") or ""),
      },
      "unit_id": fz_id,
    }
    units_by_id[fz_id] = fz_entry
    fz_out[fz_id] = {
      "parent_1990s_names_zh": fz_names,
      "parent_1990s_unit_ids": fz_pids,
      "parent_adm1_zh": str(fz_meta.get("parent_adm1_zh") or ""),
      "target_unit_id": fz_pids[0] if fz_pids else fz_id,
    }

  # Return statement
  return {
    "coverage_years": [1954, 2026],
    "functional_zones": fz_out,
    "schema_version": 1,
    "source_datasets": [
      "CTAmap v2.0 tables/change_events_v2.csv (Zenodo 22179207)",
      "yescallop/areacodes result.csv (MCA 1981-2025)",
      "CHGIS v5 1990 CITAS counties",
    ],
    "total_units": len(units_by_id),
    "units_by_id": units_by_id,
  }


def strip_ethnicity_tokens_recursive (arg1_name_zh, arg2_tokens):
  """Iteratively strip recognised ethnic-group tokens and autonomy suffixes from a Chinese toponym.

  @param arg1_name_zh Chinese county/banner name string.
  @param arg2_tokens List of ethnic tokens ordered longest-first.
  @return Cleaned Chinese toponym with autonomous designations stripped.
  """
  # Convert from parameters
  name_zh = str(arg1_name_zh or "").strip()
  tokens = list(arg2_tokens or [])

  # Declare local instance variables.
  changed = True
  core = name_zh
  suffix = ""
  tok = ""

  if not name_zh:
    return ""

  for sfx in ("各族联合自治县", "联合自治县", "各族自治县", "自治县", "自治旗"):
    if name_zh.endswith(sfx):
      core = name_zh[:-len(sfx)]
      suffix = "旗" if "旗" in sfx else "县"
      break

  if core == name_zh:
    return name_zh

  while changed and len(core) > 2:
    changed = False
    for tok in tokens:
      if tok and core.endswith(tok) and len(core) - len(tok) >= 2:
        core = core[:-len(tok)]
        changed = True
        break

  # Return statement
  return f"{core}{suffix}"
