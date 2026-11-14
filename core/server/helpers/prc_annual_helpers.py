"""Helper functions for genuinely scraped 1954-2026 annual PRC, Taiwan, Mongolia, and Tuva divisions."""

import json
import os
import sys
import unicodedata

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from shapely.geometry import shape

from helpers import gis_helpers


def _adm1_en_by_prefix (arg1_gb_code):
  """Map a 6-digit GB/T 2260 administrative code prefix to its canonical English adm_1 name.

  @param arg1_gb_code 6-digit GB/T 2260 code string.
  @return Canonical English province/municipality/AR/SAR name string, or empty string.
  """
  # Convert from parameters
  gb_code = str(arg1_gb_code or "").strip()

  # Declare local instance variables.
  prefix_map = {
    "11": "Beijing", "12": "Tianjin", "13": "Hebei", "14": "Shanxi",
    "15": "Inner Mongolia Autonomous Region", "21": "Liaoning", "22": "Jilin",
    "23": "Heilongjiang", "31": "Shanghai", "32": "Jiangsu", "33": "Zhejiang",
    "34": "Anhui", "35": "Fujian", "36": "Jiangxi", "37": "Shandong",
    "41": "Henan", "42": "Hubei", "43": "Hunan", "44": "Guangdong",
    "45": "Guangxi Zhuang Autonomous Region", "46": "Hainan", "50": "Chongqing",
    "51": "Sichuan", "52": "Guizhou", "53": "Yunnan", "54": "Tibet Autonomous Region",
    "61": "Shaanxi", "62": "Gansu", "63": "Qinghai",
    "64": "Ningxia Hui Autonomous Region", "65": "Xinjiang Uygur Autonomous Region",
    "81": "Hong Kong SAR", "82": "Macau SAR",
  }

  # Return statement
  return prefix_map.get(gb_code[:2], "")


def _adm1_zh (arg1_prov_en, arg2_reforms_cfg):
  """Resolve Chinese province-level label for an English adm_1 name.

  @param arg1_prov_en English province/municipality/SAR/aimag name.
  @param arg2_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Chinese name string (empty if unmapped non-Sinitic unit).
  """
  # Convert from parameters
  prov_en = str(arg1_prov_en or "")
  reforms_cfg = dict(arg2_reforms_cfg or {})

  # Return statement
  return str(reforms_cfg.get("adm1_zh_names", {}).get(prov_en) or "")


def _apply_rare_char_simplification (arg1_name_ch, arg2_codes, arg3_year, arg4_reforms_cfg):
  """Restore pre-simplification rare Chinese county names prior to their reform effective year.

  @param arg1_name_ch Current Chinese unit name.
  @param arg2_codes Candidate GB/T 2260 codes for the unit.
  @param arg3_year Snapshot integer year.
  @param arg4_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Resolved Chinese county name for arg3_year.
  """
  # Convert from parameters
  codes = [str(c or "") for c in (arg2_codes or []) if str(c or "")]
  name_ch = str(arg1_name_ch or "")
  reforms_cfg = dict(arg4_reforms_cfg or {})
  yr = int(arg3_year)

  # Declare local instance variables.
  e1 = reforms_cfg.get("epoch_1_1954_1979", {})
  eff_yr = 9999
  new_z = ""
  old_z = ""
  sgb = ""
  sim = {}

  for sim in e1.get("rare_character_simplifications_1950s_1960s", []):
    eff_yr, new_z, old_z, sgb = int(sim.get("effective_year", 9999)), str(sim.get("new_name_zh") or ""), str(sim.get("old_name_zh") or ""), str(sim.get("gb_code") or "")
    if (sgb and sgb in codes) or (name_ch and name_ch in (old_z, new_z)):
      if yr < eff_yr and old_z:
        return old_z
      if yr >= eff_yr and new_z and yr <= 1979:
        return new_z
      break

  # Return statement
  return name_ch


def _build_hk_macau_props (arg1_unit, arg2_is_hk, arg3_is_sar):
  """Construct standardised feature property dict for Hong Kong or Macau colony/SAR units.

  @param arg1_unit Source unit dictionary.
  @param arg2_is_hk True for Hong Kong, False for Macau.
  @param arg3_is_sar True for PRC SAR period, False for colonial period.
  @return Standardised feature property dict.
  """
  # Convert from parameters
  is_hk = bool(arg2_is_hk)
  is_sar = bool(arg3_is_sar)
  unit = dict(arg1_unit or {})

  # Declare local instance variables.
  adm1_en = "Hong Kong" if is_hk else "Macau"
  adm1_zh = "香港" if is_hk else "澳门"
  cat = "sar" if is_sar else "colony"
  country = "People's Republic of China" if is_sar else ("United Kingdom (Hong Kong)" if is_hk else "Portugal (Macau)")
  gb = str(unit.get("gb_2000") or unit.get("gb_1980") or unit.get("gb_code") or ("810000" if is_hk else "820000"))

  if is_sar:
    adm1_en, adm1_zh = f"{adm1_en} SAR", f"{adm1_zh}特别行政区"

  # Return statement
  return {
    "category": cat, "country": country, "gb_1980": gb, "gb_2000": gb, "gb_code": gb, "merge_gb": "",
    "name_ch": str(unit.get("name_ch") or adm1_zh), "name_en": str(unit.get("name_en") or adm1_en),
    "occupied_by": "", "parent_adm1": adm1_en, "parent_adm1_zh": adm1_zh,
    "parent_adm2": adm1_en, "parent_adm2_zh": adm1_zh,
    "seat_lat": unit.get("seat_lat"), "seat_lon": unit.get("seat_lon"),
    "unit_id": unit.get("unit_id"), "unit_type": "sar_district" if is_sar else "colony_district",
  }


def _canonical_modern_adm1 (arg1_adm1_en):
  """Normalise GADM or CTAmap English adm_1 spellings into canonical English province names.

  @param arg1_adm1_en Raw adm_1 English string.
  @return Canonical English adm_1 name string.
  """
  # Convert from parameters
  raw = str(arg1_adm1_en or "").strip()

  # Declare local instance variables.
  mapping = {
    "Guangxi": "Guangxi Zhuang Autonomous Region", "Inner Mongolia": "Inner Mongolia Autonomous Region",
    "Nei Mongol": "Inner Mongolia Autonomous Region", "NeiMongol": "Inner Mongolia Autonomous Region",
    "Neimenggu": "Inner Mongolia Autonomous Region", "NewTaipei": "New Taipei",
    "Ningxia": "Ningxia Hui Autonomous Region", "NingxiaHui": "Ningxia Hui Autonomous Region",
    "Tibet": "Tibet Autonomous Region", "Xinjiang": "Xinjiang Uygur Autonomous Region",
    "XinjiangUygur": "Xinjiang Uygur Autonomous Region", "Xizang": "Tibet Autonomous Region",
  }

  # Return statement
  return mapping.get(raw, raw)


def _derive_tier_meta_1954_1979 (arg1_adm1_en, arg2_year, arg3_reforms_cfg):
  """Resolve province-level category, sovereign country, and unit_type for 1954-1979 China units.

  @param arg1_adm1_en Province/municipality English name.
  @param arg2_year Snapshot integer year (1954..1979).
  @param arg3_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Dict with category, country, name_ch, occupied_by, unit_type.
  """
  # Convert from parameters
  adm1 = str(arg1_adm1_en or "")
  reforms_cfg = dict(arg3_reforms_cfg or {})
  yr = int(arg2_year)

  # Declare local instance variables.
  category = "province"
  munis = reforms_cfg.get("epoch_1_1954_1979", {}).get("central_municipalities_1954_merged_1955", {})

  if adm1 in ("Beijing", "Shanghai", "Tianjin") or (yr == 1954 and adm1 in munis):
    category = "municipality"
  elif "Autonomous" in adm1:
    category = "autonomous_region"
  elif adm1 == "Chamdo":
    category = "special_region"

  # Return statement
  return {"category": category, "country": "People's Republic of China", "name_ch": _adm1_zh(adm1, reforms_cfg), "occupied_by": "", "unit_type": "county_level_unit"}


def _match_gb_prefixes (arg1_codes, arg2_prefixes):
  """Check whether any candidate GB/T 2260 code starts with any prefix in a list.

  @param arg1_codes Sequence of string code candidates.
  @param arg2_prefixes Sequence of prefix strings.
  @return Boolean True when any code matches any prefix.
  """
  # Convert from parameters
  codes = [str(c or "") for c in (arg1_codes or []) if str(c or "")]
  prefixes = [str(p or "") for p in (arg2_prefixes or []) if str(p or "")]

  # Declare local instance variables.
  code = ""
  pfx = ""

  for code in codes:
    for pfx in prefixes:
      if code.startswith(pfx):
        return True

  # Return statement
  return False


def _match_muni_entry (arg1_unit, arg2_muni_key, arg3_spec):
  """Check whether a 1980-anchored Mainland unit belonged to a short-lived 1954 central municipality.

  @param arg1_unit 1980-anchored unit dict.
  @param arg2_muni_key Municipality English key.
  @param arg3_spec Entry from central_municipalities_1954_merged_1955.
  @return Boolean True when matched.
  """
  # Convert from parameters
  muni_key = str(arg2_muni_key or "")
  spec = dict(arg3_spec or {})
  unit = dict(arg1_unit or {})

  # Declare local instance variables.
  adm1 = str(unit.get("parent_adm1") or "")
  adm2_zh = str(unit.get("parent_adm2_zh") or "")
  codes = [str(unit.get("gb_1980") or ""), str(unit.get("gb_2000") or ""), str(unit.get("gb_code") or "")]
  merge_into = str(spec.get("merge_into") or "")
  name_ch = str(unit.get("name_ch") or "")
  name_en = str(unit.get("name_en") or "")
  tok = ""

  if adm1 == muni_key or _match_gb_prefixes(codes, spec.get("gb_prefixes", [])):
    return True
  if adm1 in (merge_into, muni_key):
    for tok in spec.get("citas_or_names", []):
      tok = str(tok or "").strip()
      if len(tok) >= 2 and (tok in adm2_zh or tok == name_ch or tok == name_en):
        return True

  # Return statement
  return False


def _normalise_ascii_fold (arg1_text):
  """Strip Unicode diacritics and lowercase for robust aimag/kozhuun matching.

  @param arg1_text Input label string.
  @return Ascii-folded lowercase string.
  """
  # Convert from parameters
  raw = str(arg1_text or "")

  # Return statement
  return "".join(ch for ch in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(ch)).strip().lower()


def _normalise_gb6 (arg1_raw_code):
  """Normalise integer or string GB/T 2260 administrative codes to a zero-padded 6-digit string.

  @param arg1_raw_code Integer or string code value.
  @return 6-digit zero-padded string, or trimmed string if non-numeric.
  """
  # Convert from parameters
  raw = str(arg1_raw_code or "").strip()

  if not raw:
    return ""
  if raw.isdigit():
    return f"{int(raw):06d}"

  # Return statement
  return raw


def _parse_tusi_abolition_year (arg1_props, arg2_reforms_cfg):
  """Determine the final snapshot year in which a post-1953 Tusi polity remains active before abolition.

  @param arg1_props Property dictionary from tusi_1912_1953.geojson.
  @param arg2_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Integer last active snapshot year (1954, 1956, or 1958).
  """
  # Convert from parameters
  props = dict(arg1_props or {})
  reforms_cfg = dict(arg2_reforms_cfg or {})

  # Declare local instance variables.
  e1 = reforms_cfg.get("epoch_1_1954_1979", {})
  hay = " ".join([str(props.get("tusi_id") or ""), str(props.get("name_en") or ""), str(props.get("name_zh") or ""), str(props.get("region") or "")]).lower()
  prov = str(props.get("parent_province") or "")
  reg = str(props.get("region") or "")
  tusi_cfg = e1.get("tusi_abolition_schedule_1954_1958", {})
  reg_defaults = tusi_cfg.get("default_by_region", {})
  tok = ""

  for tok in tusi_cfg.get("frontier_late_1958_tokens", []):
    if str(tok or "").lower() in hay:
      return 1958

  if reg == "gansu_qinghai_banners" or prov in ("Gansu", "Qinghai"):
    return int(reg_defaults.get("gansu_qinghai_banners", 1954))
  if reg == "guizhou_guangxi_hunan" or prov in ("Guizhou", "Guangxi", "Hunan"):
    return int(reg_defaults.get("guizhou_guangxi_hunan", 1954))
  if reg == "yunnan" or prov == "Yunnan":
    return int(reg_defaults.get("yunnan", 1956))
  if reg == "sichuan_xikang" or prov in ("Sichuan", "Xikang"):
    return int(reg_defaults.get("sichuan_xikang", 1956))

  # Return statement
  return int(reg_defaults.get("tibet_himalaya_xinjiang", 1956))


def _resolve_1980_1999_areacodes (arg1_gb_2000, arg2_year, arg3_ac_index, arg4_active_2000_codes):
  """Resolve the 1980..1999 active GB code, Chinese name, parent adm2, and optional split merge target.

  @param arg1_gb_2000 6-digit GB code in T2000.
  @param arg2_year Snapshot integer year in 1980..1999.
  @param arg3_ac_index Output dict from build_areacodes_year_index().
  @param arg4_active_2000_codes Set of 6-digit GB codes present in T2000.
  @return Dict with gb_code, merge_gb, name_ch, parent_adm2_gb, parent_adm2_zh.
  """
  # Convert from parameters
  ac_index = dict(arg3_ac_index or {})
  active_2000 = set(arg4_active_2000_codes or ())
  gb_2000 = str(arg1_gb_2000 or "").strip()
  yr = int(arg2_year)

  # Declare local instance variables.
  cand_code = ""
  cur_code = ""
  depth = 0
  earliest_rec = None
  earliest_start = 9999
  edge = {}
  found_2000_host = ""
  pred_edges = ac_index.get("pred_edges", {})
  q = []
  rec = {}
  records_by_code = ac_index.get("records_by_code", {})
  seen = set()

  if not gb_2000 or gb_2000 not in records_by_code:
    return {"gb_code": gb_2000, "merge_gb": "", "name_ch": "", "parent_adm2_gb": "", "parent_adm2_zh": ""}

  for rec in records_by_code.get(gb_2000, []):
    if rec["start_year"] < earliest_start:
      earliest_start, earliest_rec = rec["start_year"], rec
    if (yr <= 1981 and rec["start_year"] <= 1983) or (rec["start_year"] <= yr and yr < rec["end_year"]):
      return {"gb_code": rec["code"], "merge_gb": "", "name_ch": rec["name_zh"], "parent_adm2_gb": rec["adm2_gb"], "parent_adm2_zh": rec["adm2_zh"]}

  q = [(gb_2000, 0)]
  seen.add(gb_2000)
  while q:
    cur_code, depth = q.pop(0)
    if depth >= 6:
      continue
    for edge in sorted(pred_edges.get(cur_code, []), key=lambda x: (x.get("desc", 0) == 18, -x.get("time", 9999), x.get("from_code", ""))):
      cand_code = edge["from_code"]
      if cand_code in seen:
        continue
      seen.add(cand_code)
      if cand_code != gb_2000 and cand_code in active_2000 and edge.get("time", 9999) > yr:
        found_2000_host = cand_code
      for rec in records_by_code.get(cand_code, []):
        if (yr <= 1981 and rec["start_year"] <= 1983) or (rec["start_year"] <= yr and yr < rec["end_year"]):
          return {"gb_code": rec["code"], "merge_gb": found_2000_host, "name_ch": rec["name_zh"], "parent_adm2_gb": rec["adm2_gb"], "parent_adm2_zh": rec["adm2_zh"]}
      q.append((cand_code, depth + 1))

  if earliest_rec is not None:
    return {"gb_code": earliest_rec["code"], "merge_gb": found_2000_host, "name_ch": earliest_rec["name_zh"], "parent_adm2_gb": earliest_rec["adm2_gb"], "parent_adm2_zh": earliest_rec["adm2_zh"]}

  # Return statement
  return {"gb_code": gb_2000, "merge_gb": "", "name_ch": "", "parent_adm2_gb": "", "parent_adm2_zh": ""}


def _to_adm1_en_from_zh (arg1_adm1_zh, arg2_gb_code, arg3_fallback_en, arg4_reforms_cfg):
  """Resolve canonical English adm_1 name from GB code prefix or Chinese province label.

  @param arg1_adm1_zh Chinese province-level string.
  @param arg2_gb_code 6-digit GB/T 2260 code string.
  @param arg3_fallback_en Fallback raw English name.
  @param arg4_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Canonical English adm_1 string.
  """
  # Convert from parameters
  adm1_zh = str(arg1_adm1_zh or "").strip()
  fallback_en = str(arg3_fallback_en or "").strip()
  gb_code = str(arg2_gb_code or "").strip()
  reforms_cfg = dict(arg4_reforms_cfg or {})

  # Declare local instance variables.
  by_prefix = _adm1_en_by_prefix(gb_code)
  k = ""
  v = ""

  if by_prefix:
    return by_prefix
  for k, v in reforms_cfg.get("adm1_zh_names", {}).items():
    if v == adm1_zh:
      return _canonical_modern_adm1(k)

  # Return statement
  return _canonical_modern_adm1(fallback_en)


def build_areacodes_year_index (arg1_areacodes_doc):
  """Index yescallop/areacodes hierarchical JSON and CSV rows into year-indexed code and lineage tables.

  @param arg1_areacodes_doc Output dictionary returned by ctamap_io_helpers.load_areacodes_lineage().
  @return Dict containing records_by_code and pred_edges lookup maps.
  """
  # Convert from parameters
  ac_doc = dict(arg1_areacodes_doc or {})

  # Declare local instance variables.
  adm2_raw = ""
  ch = {}
  code = ""
  e_yr = 9999
  item = {}
  items = list(ac_doc.get("codes_tree", {}).get("items", []))
  pred_edges = {}
  records_by_code = {}
  row = {}
  s_yr = 1980
  stack = [(item, "", "", "", "") for item in items]
  tgt = {}
  tgt_code = ""

  while stack:
    item, prov_code, prov_zh, pref_code, pref_zh = stack.pop()
    code = _normalise_gb6(item.get("code"))
    if not code:
      continue
    name_zh = str(item.get("name") or "").strip()
    children = item.get("children") or []
    s_yr = int(item["start"]) if item.get("start") is not None else 1980
    e_yr = int(item["end"]) if item.get("end") is not None else 9999
    if not children:
      records_by_code.setdefault(code, []).append({
        "adm1_gb": prov_code or code[:2] + "0000", "adm1_zh": prov_zh,
        "adm2_gb": pref_code or prov_code, "adm2_zh": pref_zh or prov_zh,
        "code": code, "end_year": e_yr, "name_zh": name_zh, "start_year": s_yr,
      })
      for s_item in item.get("succ") or []:
        tgt_code = _normalise_gb6(s_item.get("code"))
        if tgt_code and tgt_code != code:
          t_yr = int(s_item["time"]) if s_item.get("time") is not None else e_yr
          pred_edges.setdefault(tgt_code, []).append({"desc": int(s_item.get("desc") or 0), "from_code": code, "time": t_yr})
    else:
      for ch in children:
        if code.endswith("0000"):
          stack.append((ch, code, name_zh, code, name_zh))
        else:
          stack.append((ch, prov_code, prov_zh, code, name_zh))

  for row in ac_doc.get("rows", []):
    code = _normalise_gb6(row.get("code"))
    if not code or code.endswith("0000") or code.endswith("00"):
      continue
    s_yr = int(row["enable_year"]) if row.get("enable_year") else 1980
    e_yr = int(row["change_year"]) if row.get("change_year") else 9999
    if code not in records_by_code:
      adm2_raw = str(row.get("adm2_zh") or "").strip()
      records_by_code.setdefault(code, []).append({
        "adm1_gb": code[:2] + "0000", "adm1_zh": str(row.get("adm1_zh") or ""),
        "adm2_gb": code[:2] + "0000" if adm2_raw in ("", "直辖") else code[:4] + "00",
        "adm2_zh": str(row.get("adm1_zh") or "") if adm2_raw in ("", "直辖") else adm2_raw,
        "code": code, "end_year": e_yr, "name_zh": str(row.get("name_zh") or ""), "start_year": s_yr,
      })
    for tgt in row.get("new_targets", []):
      tgt_code = _normalise_gb6(tgt.get("code"))
      if tgt_code and tgt_code != code:
        t_yr = int(tgt["year"]) if tgt.get("year") else e_yr
        pred_edges.setdefault(tgt_code, []).append({"desc": 0, "from_code": code, "time": t_yr})

  # Return statement
  return {"pred_edges": pred_edges, "records_by_code": records_by_code}


def classify_1954_1979_mainland_unit (arg1_unit_1980, arg2_year, arg3_reforms_cfg):
  """Classify a 1980-anchored Mainland/HK/Macau county unit for a snapshot year in 1954..1979.

  @param arg1_unit_1980 1980-anchored county dict from classify_1980_1999_mainland_unit().
  @param arg2_year Snapshot integer year (1954..1979).
  @param arg3_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Classified county feature properties dict for arg2_year.
  """
  # Convert from parameters
  reforms_cfg = dict(arg3_reforms_cfg or {})
  unit = dict(arg1_unit_1980 or {})
  yr = int(arg2_year)

  # Declare local instance variables.
  adm1 = _canonical_modern_adm1(unit.get("parent_adm1") or "")
  adm2 = str(unit.get("parent_adm2") or adm1)
  adm2_zh = str(unit.get("parent_adm2_zh") or "")
  country = str(unit.get("country") or "People's Republic of China")
  diss = {}
  d_key = ""
  d_spec = {}
  eff = []
  e1 = reforms_cfg.get("epoch_1_1954_1979", {})
  gb1980 = str(unit.get("gb_1980") or unit.get("gb_code") or "")
  gb2000 = str(unit.get("gb_2000") or "")
  gb_codes = [c for c in (gb1980, gb2000) if c]
  im_span = []
  matched_muni = False
  meta = {}
  munis = e1.get("central_municipalities_1954_merged_1955", {})
  m_key = ""
  m_spec = {}
  name_ch = str(unit.get("name_ch") or "")
  pre_im_cfg = e1.get("inner_mongolia_partition_1970_1979", {})
  prov_cfg = e1.get("province_reorganisations", {})
  tianjin_span = []

  if "Hong Kong" in country or gb1980.startswith("81") or adm1 in ("Hong Kong", "Hong Kong SAR"):
    return _build_hk_macau_props(unit, True, False)
  if "Macau" in country or gb1980.startswith("82") or adm1 in ("Macau", "Macau SAR"):
    return _build_hk_macau_props(unit, False, False)

  if yr == 1954:
    for m_key, m_spec in munis.items():
      if _match_muni_entry(unit, m_key, m_spec):
        adm1, adm2, adm2_zh, matched_muni = m_key, m_key, str(m_spec.get("name_zh") or m_key), True
        break

  if not matched_muni:
    diss = e1.get("dissolved_provinces_1954_1955", {})
    for d_key, d_spec in diss.items():
      eff = d_spec.get("effective_years", [0, -1])
      if len(eff) == 2 and int(eff[0]) <= yr <= int(eff[1]) and _match_gb_prefixes(gb_codes, d_spec.get("gb_prefixes", [])):
        adm1 = d_key
        break

  if adm1 not in ("Ningxia", "Rehe", "Xikang", "Chamdo"):
    if _match_gb_prefixes(gb_codes, ["1529", "150304"]):
      adm1 = "Gansu" if yr == 1955 else "Inner Mongolia Autonomous Region"
    elif _match_gb_prefixes(gb_codes, ["6401", "6402", "6403", "6405", "6421"]):
      adm1 = "Gansu" if yr < int(prov_cfg.get("ningxia_hui_ar_year", 1959)) else "Ningxia Hui Autonomous Region"
    elif _match_gb_prefixes(gb_codes, ["6404", "6422"]):
      adm1 = "Gansu" if yr < int(prov_cfg.get("ningxia_hui_ar_year", 1959)) else "Ningxia Hui Autonomous Region"

  if _match_gb_prefixes(gb_codes, ["65"]):
    adm1 = "Xinjiang" if yr < int(prov_cfg.get("xinjiang_uygur_ar_year", 1956)) else "Xinjiang Uygur Autonomous Region"

  if _match_gb_prefixes(gb_codes, ["4505", "4506", "4507"]):
    if 1955 <= yr <= 1965:
      adm1 = "Guangdong"
    elif yr >= 1966:
      adm1 = "Guangxi Zhuang Autonomous Region"
    else:
      adm1 = "Guangxi"
  elif _match_gb_prefixes(gb_codes, ["45"]) or adm1 in ("Guangxi", "Guangxi Zhuang Autonomous Region"):
    adm1 = "Guangxi" if yr < int(prov_cfg.get("guangxi_zhuang_ar_year", 1959)) else "Guangxi Zhuang Autonomous Region"

  tianjin_span = prov_cfg.get("tianjin_in_hebei_years", [1959, 1966])
  if adm1 == "Tianjin" and int(tianjin_span[0]) <= yr <= int(tianjin_span[1]):
    adm1 = "Hebei"

  if _match_gb_prefixes(gb_codes, ["54"]) and adm1 != "Chamdo":
    adm1 = "Tibet Autonomous Region" if yr >= int(prov_cfg.get("tibet_ar_year", 1966)) else "Xizang"

  im_span = pre_im_cfg.get("effective_snapshot_years", [1970, 1979])
  if adm1 == "Inner Mongolia Autonomous Region" and int(im_span[0]) <= yr <= int(im_span[1]):
    if _match_gb_prefixes(gb_codes, pre_im_cfg.get("heilongjiang_prefixes", [])):
      adm1 = "Heilongjiang"
    elif _match_gb_prefixes(gb_codes, pre_im_cfg.get("jilin_prefixes", [])):
      adm1 = "Jilin"
    elif _match_gb_prefixes(gb_codes, pre_im_cfg.get("liaoning_prefixes", [])):
      adm1 = "Liaoning"
    elif _match_gb_prefixes(gb_codes, pre_im_cfg.get("gansu_prefixes", [])):
      adm1 = "Gansu"
    elif _match_gb_prefixes(gb_codes, pre_im_cfg.get("ningxia_prefixes", [])):
      adm1 = "Ningxia Hui Autonomous Region"

  meta = _derive_tier_meta_1954_1979(adm1, yr, reforms_cfg)
  name_ch = _apply_rare_char_simplification(name_ch, gb_codes, yr, reforms_cfg)

  # Return statement
  return {
    "category": meta["category"], "country": meta["country"], "gb_code": gb1980 or gb2000,
    "name_ch": name_ch, "name_en": str(unit.get("name_en") or ""), "occupied_by": "",
    "parent_adm1": adm1, "parent_adm1_zh": meta["name_ch"],
    "parent_adm2": adm2, "parent_adm2_zh": adm2_zh,
    "seat_lat": unit.get("seat_lat"), "seat_lon": unit.get("seat_lon"),
    "unit_id": unit.get("unit_id"), "unit_type": str(unit.get("unit_type") or "county"),
  }


def classify_1954_2026_outer_atom (arg1_region, arg2_atom, arg3_year, arg4_reforms_cfg):
  """Classify a Taiwan, Mongolia, or Tuva modern atom for a snapshot year in 1954..2026.

  @param arg1_region Region key ('taiwan', 'mongolia', 'tuva_republic').
  @param arg2_atom Atom property dict.
  @param arg3_year Target snapshot year (1954..2026).
  @param arg4_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Dict with props + optional merge_target_name.
  """
  # Convert from parameters
  atom = dict(arg2_atom or {})
  reforms_cfg = dict(arg4_reforms_cfg or {})
  region = str(arg1_region or "")
  yr = int(arg3_year)

  # Declare local instance variables.
  adm1 = ""
  adm1_fold = ""
  adm2 = ""
  cat = ""
  epoch_row = {}
  is_urban = False
  k_creations = {}
  merge_target = ""
  m_cfg = {}
  m_upg = {}
  name_en = str(atom.get("name_en") or "")
  name_zh = ""
  tuv_cfg = {}

  if region == "taiwan":
    m_upg = reforms_cfg.get("taiwan_1954_2026", {}).get("municipal_upgrades", {})
    adm2, name_zh = str(atom.get("parent_adm2") or ""), str(atom.get("name_zh") or "")
    if atom.get("roc_fujian_offshore"):
      adm1 = "Fujian (ROC)"
    elif adm2 == "Taipei City":
      adm1 = "Taipei" if yr >= int(m_upg.get("Taipei", {}).get("snapshot_year", 1968)) else "Taiwan"
    elif adm2 == "Kaohsiung City":
      is_urban = any(name_zh.startswith(p) for p in m_upg.get("Kaohsiung", {}).get("urban_prefixes", []))
      if yr >= int(m_upg.get("Kaohsiung", {}).get("snapshot_year", 2011)) or (yr >= 1980 and is_urban):
        adm1 = "Kaohsiung"
      else:
        adm1, adm2 = "Taiwan", "Kaohsiung City" if is_urban else "Kaohsiung County"
    elif adm2 == "New Taipei City":
      adm1 = "New Taipei" if yr >= int(m_upg.get("NewTaipei", {}).get("snapshot_year", 2011)) else "Taiwan"
      if adm1 == "Taiwan":
        adm2 = "Taipei County"
    elif adm2 == "Taichung City":
      is_urban = name_zh in m_upg.get("Taichung", {}).get("urban_towns", [])
      if yr >= int(m_upg.get("Taichung", {}).get("snapshot_year", 2011)):
        adm1 = "Taichung"
      else:
        adm1, adm2 = "Taiwan", "Taichung City" if is_urban else "Taichung County"
    elif adm2 == "Tainan City":
      is_urban = name_zh in m_upg.get("Tainan", {}).get("urban_towns", [])
      if yr >= int(m_upg.get("Tainan", {}).get("snapshot_year", 2011)):
        adm1 = "Tainan"
      else:
        adm1, adm2 = "Taiwan", "Tainan City" if is_urban else "Tainan County"
    elif adm2 == "Taoyuan City":
      adm1 = "Taoyuan" if yr >= int(m_upg.get("Taoyuan", {}).get("snapshot_year", 2015)) else "Taiwan"
      if adm1 == "Taiwan":
        adm2 = "Taoyuan County"
    elif adm2 == "Hsinchu City":
      adm1 = "Taiwan"
      adm2 = "Hsinchu City" if yr >= int(m_upg.get("HsinchuCity", {}).get("snapshot_year", 1983)) else "Hsinchu County"
    elif adm2 == "Chiayi City":
      adm1 = "Taiwan"
      adm2 = "Chiayi City" if yr >= int(m_upg.get("ChiayiCity", {}).get("snapshot_year", 1983)) else "Chiayi County"
    else:
      adm1 = "Taiwan"

    return {
      "category": "municipality" if adm1 in ("Taipei", "Kaohsiung", "New Taipei", "Taichung", "Tainan", "Taoyuan") else "province",
      "country": "Republic of China", "gb_code": "", "merge_target_name": "", "name_ch": name_zh, "name_en": name_en, "occupied_by": "",
      "parent_adm1": adm1, "parent_adm1_zh": _adm1_zh(adm1, reforms_cfg), "parent_adm2": adm2,
      "seat_lat": atom.get("seat_lat"), "seat_lon": atom.get("seat_lon"),
      "unit_id": atom.get("modern_unit_id") or atom.get("unit_id"), "unit_type": str(atom.get("unit_type") or "township"),
    }

  if region == "mongolia":
    m_cfg = reforms_cfg.get("mongolia_1954_2026", {})
    adm1 = str(atom.get("parent_adm1") or "")
    adm1_fold = _normalise_ascii_fold(adm1)
    for enc_key, enc_spec in m_cfg.get("enclave_aimag_creations", {}).items():
      if adm1_fold == _normalise_ascii_fold(enc_key) and yr < int(enc_spec.get("snapshot_year", 1995)):
        adm1 = str(enc_spec.get("parent_aimag") or adm1)
        break
    return {
      "category": "aimag", "country": "Mongolian People's Republic" if yr < int(m_cfg.get("state_rename_year", 1993)) else "Mongolia",
      "gb_code": "", "merge_target_name": "", "name_ch": str(atom.get("name_mn_cyrl") or name_en), "name_en": name_en, "occupied_by": "",
      "parent_adm1": adm1, "parent_adm1_zh": "", "parent_adm2": adm1,
      "seat_lat": atom.get("seat_lat"), "seat_lon": atom.get("seat_lon"),
      "unit_id": atom.get("modern_unit_id") or atom.get("unit_id"), "unit_type": str(atom.get("unit_type") or "soum"),
    }

  tuv_cfg = reforms_cfg.get("tuva_1954_2026", {})
  epoch_row = {"country": "Russian Federation", "name_en": "Republic of Tyva", "name_zh": "图瓦共和国"}
  for ep in tuv_cfg.get("state_epochs", []):
    if int(ep.get("start_year", 0)) <= yr <= int(ep.get("end_year", 9999)):
      epoch_row = ep
      break
  k_creations = tuv_cfg.get("post_1953_kozhuun_creations", {})
  if name_en in k_creations and yr < int(k_creations[name_en].get("snapshot_year", 1999)):
    merge_target = str(k_creations[name_en].get("merge_into") or "")
  adm1 = str(epoch_row.get("name_en") or "Republic of Tyva")
  cat = "autonomous_oblast" if "Oblast" in adm1 else ("autonomous_republic" if "Soviet" in adm1 else "republic")

  # Return statement
  return {
    "category": cat, "country": str(epoch_row.get("country") or "Russian Federation"), "gb_code": "", "merge_target_name": merge_target,
    "name_ch": str(atom.get("name_tyv") or atom.get("name_ru") or name_en), "name_en": merge_target or name_en, "occupied_by": "",
    "parent_adm1": adm1, "parent_adm1_zh": str(epoch_row.get("name_zh") or ""), "parent_adm2": merge_target or name_en,
    "seat_lat": atom.get("seat_lat"), "seat_lon": atom.get("seat_lon"),
    "unit_id": atom.get("modern_unit_id") or atom.get("unit_id"), "unit_type": str(atom.get("unit_type") or "kozhuun"),
  }


def classify_1980_1999_mainland_unit (arg1_unit_2000, arg2_year, arg3_ac_index, arg4_reforms_cfg, arg5_active_2000_codes=None):
  """Classify a T2000 Mainland/HK/Macau county unit for a snapshot year in 1980..1999.

  @param arg1_unit_2000 Formatted unit dict from T2000 CTAmap layer.
  @param arg2_year Snapshot integer year in 1980..1999.
  @param arg3_ac_index Index dict from build_areacodes_year_index().
  @param arg4_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @param arg5_active_2000_codes Optional set of 6-digit GB codes active in T2000.
  @return Dict of feature properties plus merge_gb and gb_2000.
  """
  # Convert from parameters
  ac_index = dict(arg3_ac_index or {})
  active_2000 = set(arg5_active_2000_codes or ())
  reforms_cfg = dict(arg4_reforms_cfg or {})
  unit = dict(arg1_unit_2000 or {})
  yr = int(arg2_year)

  # Declare local instance variables.
  ac_res = {}
  adm1 = _canonical_modern_adm1(unit.get("parent_adm1") or "")
  adm1_zh = str(unit.get("parent_adm1_zh") or _adm1_zh(adm1, reforms_cfg))
  adm2 = str(unit.get("parent_adm2") or adm1)
  adm2_zh = str(unit.get("parent_adm2_zh") or "")
  category = "province"
  c2c = {}
  c_gb = ""
  e2 = reforms_cfg.get("epoch_2_1980_2000", {})
  gb = str(unit.get("gb_code") or "")
  gb_2000 = gb
  name_ch = str(unit.get("name_ch") or "")

  if gb_2000.startswith("81") or "Hong Kong" in adm1:
    return _build_hk_macau_props(unit, True, yr >= int(e2.get("hong_kong_sar_year", 1998)))
  if gb_2000.startswith("82") or "Macau" in adm1:
    return _build_hk_macau_props(unit, False, yr >= int(e2.get("macau_sar_year", 2000)))

  ac_res = _resolve_1980_1999_areacodes(gb_2000, yr, ac_index, active_2000)
  if ac_res.get("gb_code"):
    gb = ac_res["gb_code"]
  if ac_res.get("name_ch"):
    name_ch = ac_res["name_ch"]
  if ac_res.get("parent_adm2_zh"):
    adm2_zh = ac_res["parent_adm2_zh"]
    if adm2_zh == adm1_zh:
      adm2 = adm1

  if (adm1 == "Hainan" or gb_2000.startswith("46")) and yr < int(e2.get("hainan_province_year", 1989)):
    adm1, adm1_zh = "Guangdong", "广东省"
  if (adm1 == "Chongqing" or gb_2000.startswith("50")) and yr < int(e2.get("chongqing_municipality_year", 1998)):
    adm1, adm1_zh = "Sichuan", "四川省"

  for c2c in e2.get("county_to_city_1983_2000", []):
    c_gb = str(c2c.get("gb_1990") or "")
    if yr < int(c2c.get("snapshot_year", 9999)) and (gb == c_gb or gb_2000 == c_gb or name_ch == str(c2c.get("to_name") or "")):
      name_ch = str(c2c.get("from_name") or name_ch)
      break

  name_ch = _apply_rare_char_simplification(name_ch, [gb, gb_2000], yr, reforms_cfg)
  if adm1 in ("Beijing", "Shanghai", "Tianjin", "Chongqing"):
    category = "municipality"
  elif "Autonomous" in adm1:
    category = "autonomous_region"

  # Return statement
  return {
    "category": category, "country": "People's Republic of China",
    "gb_1980": gb, "gb_2000": gb_2000, "gb_code": gb, "merge_gb": str(ac_res.get("merge_gb") or ""),
    "name_ch": name_ch, "name_en": str(unit.get("name_en") or ""), "occupied_by": "",
    "parent_adm1": adm1, "parent_adm1_zh": adm1_zh, "parent_adm2": adm2, "parent_adm2_zh": adm2_zh,
    "seat_lat": unit.get("seat_lat"), "seat_lon": unit.get("seat_lon"),
    "unit_id": unit.get("unit_id"), "unit_type": str(unit.get("unit_type") or "county"),
  }


def format_ctamap_year_units (arg1_raw_rows, arg2_year, arg3_reforms_cfg):
  """Normalise raw CTAmap county GeoPackage rows for a snapshot year (2000..2026) into standard dicts.

  @param arg1_raw_rows Output list of (props, geom) from ctamap_io_helpers.read_ctamap_county_year().
  @param arg2_year Snapshot integer year (2000..2026).
  @param arg3_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return List of (unit_dict, shapely_geom) tuples.
  """
  # Convert from parameters
  raw_rows = list(arg1_raw_rows or [])
  reforms_cfg = dict(arg3_reforms_cfg or {})
  yr = int(arg2_year)

  # Declare local instance variables.
  adm1_en, adm1_gb, adm1_zh, adm2_en, adm2_gb, adm2_zh, category, cls_zh, eng_stem = "", "", "", "", "", "", "", "", ""
  eng_type_map = {"区": "Qu", "县": "Xian", "县级市": "Shi", "市辖区": "Qu", "自治县": "Zizhixian", "自治旗": "Zizhiqi", "旗": "Qi", "林区": "Linqu", "特区": "Tequ", "特别行政区": "SAR"}
  gb_code, geom = "", None
  hotan_map = {str(h.get("gb_code") or ""): h for h in reforms_cfg.get("epoch_3_2001_2026", {}).get("hotan_2024_new_counties", [])}
  muni_or_sar = {"110000", "120000", "310000", "500000", "810000", "820000"}
  name_en, name_zh, out_rows, props, p2_gb, p2_zh, rep_pt = "", "", [], {}, "", "", None
  seen_adm2, seen_adm2_names, seen_ids, sfx_en, synth_seq, uid, unit_type = {}, set(), set(), "", 0, "", ""
  utype_map = {
    "市辖区": "urban_district", "县": "county", "县级市": "county_level_city",
    "自治县": "autonomous_county", "自治旗": "autonomous_banner", "旗": "banner",
    "林区": "forestry_district", "特区": "special_district", "特别行政区": "special_administrative_region",
  }

  for props, geom in raw_rows:
    if geom is None or geom.is_empty:
      continue
    adm1_gb = _normalise_gb6(props.get("省级码"))
    if adm1_gb in ("", "0", "000000", "710000"):
      continue
    adm1_zh = str(props.get("省级") or "").strip()
    adm1_en = _to_adm1_en_from_zh(adm1_zh, adm1_gb, props.get("NAME_1"), reforms_cfg)

    gb_code = _normalise_gb6(props.get("区划码"))
    if gb_code in ("", "0", "000000"):
      synth_seq += 1
      gb_code = f"{adm1_gb[:2]}99{synth_seq:02d}"

    name_zh = str(props.get("地名") or "").strip()
    if yr >= 2025 and gb_code in hotan_map:
      name_zh = str(hotan_map[gb_code].get("name_zh") or name_zh)
      eng_stem = str(hotan_map[gb_code].get("name_en") or name_zh)
    else:
      eng_stem = str(props.get("ENG_NAME") or props.get("NAME_3") or props.get("VARNAME_3") or props.get("VAR_NAME3") or gb_code).strip()

    cls_zh = str(props.get("县级类") or "").strip()
    if gb_code == "810000":
      name_en, unit_type, category = "Hong Kong SAR", "sar_district", "sar"
    elif gb_code == "820000":
      name_en, unit_type, category = "Macau SAR", "sar_district", "sar"
    else:
      sfx_en = eng_type_map.get(cls_zh, "") if cls_zh in ("县", "市辖区", "自治县", "旗", "自治旗") else ""
      name_en = f"{eng_stem} {sfx_en}".strip() if (sfx_en and not eng_stem.endswith(sfx_en)) else eng_stem
      unit_type = utype_map.get(cls_zh, "county")
      if adm1_gb in ("110000", "120000", "310000", "500000"):
        category = "municipality"
      elif "Autonomous" in adm1_en:
        category = "autonomous_region"
      else:
        category = "province"

    if adm1_gb in muni_or_sar:
      adm2_gb, adm2_zh, adm2_en = adm1_gb, adm1_zh, adm1_en
    else:
      p2_gb, p2_zh = _normalise_gb6(props.get("地级码")), str(props.get("地级") or "").strip()
      if p2_gb in ("", "0", "000000") or p2_zh in ("", "不统计", "直辖"):
        adm2_gb, adm2_zh, adm2_en = gb_code, name_zh, name_en
      else:
        adm2_gb, adm2_zh, adm2_en = p2_gb, p2_zh, str(props.get("NAME_2") or p2_zh or gb_code).strip()

    if (adm1_en, adm2_gb) in seen_adm2:
      adm2_en = seen_adm2[(adm1_en, adm2_gb)]
    else:
      if (adm1_en, adm2_en) in seen_adm2_names:
        adm2_en = f"{adm2_en} ({adm2_gb})"
      seen_adm2_names.add((adm1_en, adm2_en))
      seen_adm2[(adm1_en, adm2_gb)] = adm2_en

    uid_base = f"prc_{yr}_{gb_code}_{gis_helpers.slugify_snake(name_en)}"
    uid = uid_base
    if uid in seen_ids:
      uid = f"{uid_base}_{len(seen_ids)}"
    seen_ids.add(uid)

    rep_pt = geom.representative_point()
    out_rows.append(({
      "_wkb_hex": str(props.get("_wkb_hex") or ""), "category": category, "country": "People's Republic of China",
      "gb_code": gb_code, "name_ch": name_zh, "name_en": name_en, "occupied_by": "",
      "parent_adm1": adm1_en, "parent_adm1_gb": adm1_gb, "parent_adm1_zh": adm1_zh or _adm1_zh(adm1_en, reforms_cfg),
      "parent_adm2": adm2_en, "parent_adm2_gb": adm2_gb, "parent_adm2_zh": adm2_zh,
      "seat_lat": round(float(rep_pt.y), 5), "seat_lon": round(float(rep_pt.x), 5),
      "unit_id": uid, "unit_type": unit_type,
    }, geom))

  # Return statement
  return out_rows


def load_active_tusi_cohorts (arg1_tusi_geojson_path, arg2_reforms_cfg, arg3_grid_size=1e-5):
  """Load post-1953 active Tusi polities and group them into 1954-1958 abolition cohorts.

  @param arg1_tusi_geojson_path Path to output/gis/layers/tusi_1912_1953.geojson.
  @param arg2_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @param arg3_grid_size Snap grid precision for Shapely geometries.
  @return Dict mapping cohort end_year (1954, 1956, 1958) to list of Tusi dicts with geom.
  """
  # Convert from parameters
  grid_size = float(arg3_grid_size)
  reforms_cfg = dict(arg2_reforms_cfg or {})
  tusi_path = str(arg1_tusi_geojson_path or "")

  # Declare local instance variables.
  ab_yr, cohorts, data, end_yr, ft, geom, props, rp = 1954, {1954: [], 1956: [], 1958: []}, {}, 0, {}, None, {}, None

  if not tusi_path or not os.path.exists(tusi_path):
    return cohorts

  with open(tusi_path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

  for ft in data.get("features", []):
    props = dict(ft.get("properties") or {})
    end_yr = int(props.get("end_year") or 0)
    if end_yr < 1953 or not ft.get("geometry"):
      continue
    geom = gis_helpers.clean_polygonal_geometry(shape(ft["geometry"]))
    if geom is None or geom.is_empty:
      continue
    ab_yr = _parse_tusi_abolition_year(props, reforms_cfg)
    rp = geom.representative_point()
    cohorts.setdefault(ab_yr, []).append({
      "abolition_year": ab_yr, "category": "tusi", "country": "People's Republic of China",
      "gb_code": "", "geom": geom, "grid_size": grid_size,
      "name_ch": str(props.get("name_zh") or props.get("name_en") or ""),
      "name_en": str(props.get("name_en") or ""), "occupied_by": "",
      "parent_adm1": str(props.get("parent_province") or "Yunnan"),
      "parent_adm1_zh": _adm1_zh(str(props.get("parent_province") or ""), reforms_cfg),
      "parent_adm2": str(props.get("name_en") or ""),
      "seat_lat": props.get("seat_lat") if props.get("seat_lat") is not None else round(float(rp.y), 5),
      "seat_lon": props.get("seat_lon") if props.get("seat_lon") is not None else round(float(rp.x), 5),
      "unit_id": str(props.get("tusi_id") or gis_helpers.slugify_snake(props.get("name_en") or "tusi")),
      "unit_type": "tusi",
    })

  # Return statement
  return cohorts


def load_geojson_features (arg1_path):
  """Load valid polygonal features from a GeoJSON file.

  @param arg1_path Path to GeoJSON file.
  @return List of (props_dict, shapely_geom) tuples.
  """
  # Convert from parameters
  path = str(arg1_path or "")

  if not os.path.exists(path):
    return []

  # Declare local instance variables.
  data, ft, geom, out = {}, {}, None, []

  with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)
  for ft in data.get("features", []):
    geom = gis_helpers.clean_polygonal_geometry(shape(ft["geometry"])) if ft.get("geometry") else None
    if geom is not None and not geom.is_empty:
      out.append((dict(ft.get("properties") or {}), geom))

  # Return statement
  return out
