"""Helper functions for continuous 1954-2026 annual PRC, Taiwan, Mongolia, and Tuva division snapshots."""

import json
import os
import sys
import unicodedata

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from shapely.geometry import shape

from helpers import gis_helpers, modern_gis_helpers


def _adm1_zh (arg1_prov_en, arg2_reforms_cfg):
  """Resolve Chinese province-level label for an English adm_1 name.

  @param arg1_prov_en English province/municipality/SAR/aimag name.
  @param arg2_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Chinese name string (empty if unmapped non-Sinitic unit).
  """
  # Convert from parameters
  prov_en = str(arg1_prov_en or "")
  reforms_cfg = dict(arg2_reforms_cfg or {})

  # Declare local instance variables.
  zh_map = reforms_cfg.get("adm1_zh_names", {})

  # Return statement
  return str(zh_map.get(prov_en) or "")


def _canonical_modern_adm1 (arg1_adm1_en):
  """Normalise GADM adm_1 spelling into canonical English names used in 1954-2026 outputs.

  @param arg1_adm1_en Raw adm_1 English string from modern layer properties.
  @return Canonical English adm_1 name string.
  """
  # Convert from parameters
  raw = str(arg1_adm1_en or "").strip()

  # Declare local instance variables.
  mapping = {
    "Guangxi": "Guangxi Zhuang Autonomous Region",
    "NeiMongol": "Inner Mongolia Autonomous Region",
    "NewTaipei": "New Taipei",
    "NingxiaHui": "Ningxia Hui Autonomous Region",
    "XinjiangUygur": "Xinjiang Uygur Autonomous Region",
    "Xizang": "Tibet Autonomous Region",
  }

  # Return statement
  return mapping.get(raw, raw)


def _match_gb_prefixes (arg1_codes, arg2_prefixes):
  """Check whether any candidate GB/T 2260 code starts with any prefix in a list.

  @param arg1_codes Sequence of string code candidates.
  @param arg2_prefixes Sequence of prefix strings.
  @return Boolean True when any code matches any prefix.
  """
  # Convert from parameters
  codes = [str(c or "") for c in (arg1_codes or []) if str(c or "")]
  prefixes = [str(p or "") for p in (arg2_prefixes or []) if str(p or "")]

  for code in codes:
    for pfx in prefixes:
      if code.startswith(pfx):
        return True

  # Return statement
  return False


def _match_muni_entry (arg1_atom, arg2_muni_key, arg3_spec):
  """Check whether a 1953 Mainland atom belongs to a 1954 central municipality.

  @param arg1_atom 1953 Mainland atom metadata dict.
  @param arg2_muni_key Municipality English key.
  @param arg3_spec Entry from central_municipalities_1954_merged_1955.
  @return Boolean True when matched.
  """
  # Convert from parameters
  atom = dict(arg1_atom or {})
  muni_key = str(arg2_muni_key or "")
  spec = dict(arg3_spec or {})

  # Declare local instance variables.
  adm1 = str(atom.get("parent_adm1") or "")
  adm2 = str(atom.get("parent_adm2") or "")
  codes = [str(atom.get("gb_1990") or ""), str(atom.get("gb_2026") or "")]
  name_ch = str(atom.get("name_ch") or "")
  name_en = str(atom.get("name_en") or "")

  if adm1 == muni_key:
    return True
  if _match_gb_prefixes(codes, spec.get("gb_prefixes", [])):
    return True
  for tok in spec.get("citas_or_names", []):
    if len(tok) >= 2 and (tok in name_ch or tok in name_en or tok == adm2):
      if adm1 in (spec.get("merge_into"), muni_key, "Liaodong", "Liaoxi", "Songjiang"):
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

  # Declare local instance variables.
  decomposed = unicodedata.normalize("NFKD", raw)
  stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))

  # Return statement
  return stripped.strip().lower()


def _tusi_abolition_year (arg1_atom, arg2_reforms_cfg):
  """Determine the final snapshot year in which a 1953 Tusi polity remains active before abolition.

  @param arg1_atom 1953 Tusi atom dict.
  @param arg2_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Integer last active snapshot year (1954, 1956, or 1958).
  """
  # Convert from parameters
  atom = dict(arg1_atom or {})
  reforms_cfg = dict(arg2_reforms_cfg or {})

  # Declare local instance variables.
  adm1 = str(atom.get("parent_adm1") or "")
  e1 = reforms_cfg.get("epoch_1_1954_1979", {})
  hay = " ".join([
    str(atom.get("unit_id") or ""),
    str(atom.get("name_en") or ""),
    str(atom.get("parent_adm2") or ""),
  ]).lower()
  tusi_cfg = e1.get("tusi_abolition_schedule_1954_1958", {})
  reg_defaults = tusi_cfg.get("default_by_region", {})

  for tok in tusi_cfg.get("frontier_late_1958_tokens", []):
    if str(tok).lower() in hay:
      return 1958

  if adm1 in ("Gansu", "Qinghai"):
    return int(reg_defaults.get("gansu_qinghai_banners", 1954))
  if adm1 in ("Guizhou", "Guangxi", "Hunan"):
    return int(reg_defaults.get("guizhou_guangxi_hunan", 1954))
  if adm1 == "Yunnan":
    return int(reg_defaults.get("yunnan", 1956))
  if adm1 in ("Sichuan", "Xikang"):
    return int(reg_defaults.get("sichuan_xikang", 1956))

  # Return statement
  return int(reg_defaults.get("tibet_himalaya_xinjiang", 1956))


def build_1954_1979_prov_meta (arg1_adm1_en, arg2_year, arg3_reforms_cfg):
  """Resolve province-level category and country metadata for 1954-1979 China units.

  @param arg1_adm1_en Province/municipality English name.
  @param arg2_year Snapshot integer year (1954..1979).
  @param arg3_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Dict with country, category, name_ch, occupied_by, unit_type.
  """
  # Convert from parameters
  adm1 = str(arg1_adm1_en or "")
  reforms_cfg = dict(arg3_reforms_cfg or {})
  yr = int(arg2_year)

  if adm1 == "Hong Kong":
    return {"category": "colony", "country": "United Kingdom (Hong Kong)", "name_ch": "香港", "occupied_by": "", "unit_type": "colony_district"}
  if adm1 == "Macau":
    return {"category": "colony", "country": "Portugal (Macau)", "name_ch": "澳门", "occupied_by": "", "unit_type": "colony_district"}

  # Declare local instance variables.
  category = "province"
  munis = reforms_cfg.get("epoch_1_1954_1979", {}).get("central_municipalities_1954_merged_1955", {})
  unit_type = "county_level_unit"

  if adm1 in ("Beijing", "Shanghai", "Tianjin") or (yr == 1954 and adm1 in munis):
    category = "municipality"
  elif "Autonomous" in adm1:
    category = "autonomous_region"
  elif adm1 == "Chamdo":
    category = "special_region"

  # Return statement
  return {
    "category": category,
    "country": "People's Republic of China",
    "name_ch": _adm1_zh(adm1, reforms_cfg),
    "occupied_by": "",
    "unit_type": unit_type,
  }


def classify_1954_1979_china_atom (arg1_atom, arg2_year, arg3_reforms_cfg):
  """Classify a 1953 Mainland/HK/Macau/Tusi atom for a snapshot year in 1954..1979.

  @param arg1_atom Annotated 1953 atom dict.
  @param arg2_year Target snapshot year (1954..1979).
  @param arg3_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Classified feature properties dict for this year.
  """
  # Convert from parameters
  atom = dict(arg1_atom or {})
  reforms_cfg = dict(arg3_reforms_cfg or {})
  yr = int(arg2_year)

  # Declare local instance variables.
  adm1 = str(atom.get("parent_adm1") or "")
  adm2 = str(atom.get("parent_adm2") or adm1)
  cat = str(atom.get("category") or "province")
  country = str(atom.get("country") or "People's Republic of China")
  e1 = reforms_cfg.get("epoch_1_1954_1979", {})
  gb1990 = str(atom.get("gb_1990") or "")
  gb2026 = str(atom.get("gb_2026") or "")
  gb_codes = [gb1990, gb2026]
  lat = float(atom.get("seat_lat") or 0.0)
  lon = float(atom.get("seat_lon") or 0.0)
  munis = e1.get("central_municipalities_1954_merged_1955", {})
  name_ch = str(atom.get("name_ch") or "")
  name_en = str(atom.get("name_en") or "")
  pre_im_cfg = e1.get("inner_mongolia_partition_1970_1979", {})
  prov_cfg = e1.get("province_reorganisations", {})
  unit_type = "tusi" if cat == "tusi" else "county_level_unit"

  if "Hong Kong" in country or adm1 == "Hong Kong":
    return {
      "category": "colony",
      "country": "United Kingdom (Hong Kong)",
      "gb_code": gb2026 or "810000",
      "name_ch": name_ch or "香港",
      "name_en": name_en or "Hong Kong",
      "occupied_by": "",
      "parent_adm1": "Hong Kong",
      "parent_adm1_zh": "香港",
      "parent_adm2": adm2 or "Hong Kong",
      "seat_lat": atom.get("seat_lat"),
      "seat_lon": atom.get("seat_lon"),
      "unit_id": atom.get("unit_id"),
      "unit_type": "colony_district",
    }
  if "Macau" in country or adm1 == "Macau":
    return {
      "category": "colony",
      "country": "Portugal (Macau)",
      "gb_code": gb2026 or "820000",
      "name_ch": name_ch or "澳门",
      "name_en": name_en or "Macau",
      "occupied_by": "",
      "parent_adm1": "Macau",
      "parent_adm1_zh": "澳门",
      "parent_adm2": adm2 or "Macau",
      "seat_lat": atom.get("seat_lat"),
      "seat_lon": atom.get("seat_lon"),
      "unit_id": atom.get("unit_id"),
      "unit_type": "colony_district",
    }

  # 1954 municipalities (11 short-lived central municipalities before 1955 mergers)
  if cat != "tusi":
    for m_key, m_spec in munis.items():
      if _match_muni_entry(atom, m_key, m_spec):
        if yr < int(m_spec.get("merge_snapshot_year", 1955)):
          adm1 = m_key
          adm2 = m_key
        elif adm1 == m_key:
          adm1 = str(m_spec.get("merge_into") or adm1)
        break

  # Provincial abolitions & merges
  if adm1 in ("Liaodong", "Liaoxi") and yr >= int(prov_cfg.get("liaodong_liaoxi_merge_year", 1955)):
    if _match_gb_prefixes(gb_codes, ["2204", "2205", "2206"]):
      adm1 = "Jilin"
    else:
      adm1 = "Liaoning"

  if adm1 == "Songjiang" and yr >= int(prov_cfg.get("songjiang_merge_heilongjiang_year", 1955)):
    adm1 = "Heilongjiang"

  if adm1 == "Inner Mongolia" or (adm1 == "Suiyuan" and yr >= int(prov_cfg.get("suiyuan_merge_inner_mongolia_year", 1955))):
    adm1 = "Inner Mongolia Autonomous Region"

  if adm1 == "Ningxia" and yr >= int(prov_cfg.get("ningxia_merge_gansu_year", 1955)):
    if yr >= 1956 and (_match_gb_prefixes(gb_codes, ["1529"]) or (lon < 105.6 and lat > 37.3)):
      adm1 = "Inner Mongolia Autonomous Region"
    elif yr < int(prov_cfg.get("ningxia_hui_ar_year", 1959)):
      adm1 = "Gansu"
    else:
      adm1 = "Ningxia Hui Autonomous Region"
  elif adm1 == "Gansu" and yr >= int(prov_cfg.get("ningxia_hui_ar_year", 1959)):
    if _match_gb_prefixes(gb_codes, ["6404", "6405"]):
      adm1 = "Ningxia Hui Autonomous Region"

  if adm1 == "Rehe" and yr >= int(prov_cfg.get("rehe_abolition_year", 1956)):
    if _match_gb_prefixes(gb_codes, ["1504", "1526"]) or (lat > 41.6 and lon >= 117.4 and not _match_gb_prefixes(gb_codes, ["13"])):
      adm1 = "Inner Mongolia Autonomous Region"
    elif _match_gb_prefixes(gb_codes, ["2109", "2113", "2114"]) or (lon >= 118.85 and lat <= 42.1 and not _match_gb_prefixes(gb_codes, ["13"])):
      adm1 = "Liaoning"
    else:
      adm1 = "Hebei"

  if adm1 == "Xikang" and yr >= int(prov_cfg.get("xikang_merge_sichuan_year", 1956)):
    adm1 = "Xizang" if _match_gb_prefixes(gb_codes, ["5403", "5421"]) else "Sichuan"

  if adm1 == "Xinjiang" and yr >= int(prov_cfg.get("xinjiang_uygur_ar_year", 1956)):
    adm1 = "Xinjiang Uygur Autonomous Region"

  if _match_gb_prefixes(gb_codes, ["4505", "4506", "4507"]):
    if 1955 <= yr <= 1965:
      adm1 = "Guangdong"
    elif yr >= 1966:
      adm1 = "Guangxi Zhuang Autonomous Region"
  elif adm1 == "Guangxi" and yr >= int(prov_cfg.get("guangxi_zhuang_ar_year", 1959)):
    adm1 = "Guangxi Zhuang Autonomous Region"

  tianjin_span = prov_cfg.get("tianjin_in_hebei_years", [1959, 1966])
  if adm1 == "Tianjin" and int(tianjin_span[0]) <= yr <= int(tianjin_span[1]):
    adm1 = "Hebei"

  if adm1 == "Chamdo" and yr >= 1956:
    adm1 = "Tibet Autonomous Region" if yr >= int(prov_cfg.get("tibet_ar_year", 1966)) else "Xizang"
  elif adm1 == "Xizang" and yr >= int(prov_cfg.get("tibet_ar_year", 1966)):
    adm1 = "Tibet Autonomous Region"

  # 1970-1979 Inner Mongolia league/banner temporary transfer out
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

  meta = build_1954_1979_prov_meta(adm1, yr, reforms_cfg)
  out_cat = meta["category"]
  if cat == "tusi":
    ab_yr = _tusi_abolition_year(atom, reforms_cfg)
    if yr <= ab_yr:
      out_cat = "tusi"
      unit_type = "tusi"

  # Rare-character county simplifications in 1956-1964
  for sim in e1.get("rare_character_simplifications_1950s_1960s", []):
    sgb = str(sim.get("gb_code") or "")
    old_z = str(sim.get("old_name_zh") or "")
    new_z = str(sim.get("new_name_zh") or "")
    if (sgb and sgb in gb_codes) or (name_ch and name_ch in (old_z, new_z)):
      name_ch = new_z if yr >= int(sim.get("effective_year", 1999)) else old_z
      break

  # Return statement
  return {
    "category": out_cat,
    "country": meta["country"],
    "gb_code": gb1990 or gb2026,
    "name_ch": name_ch,
    "name_en": name_en,
    "occupied_by": "",
    "parent_adm1": adm1,
    "parent_adm1_zh": _adm1_zh(adm1, reforms_cfg),
    "parent_adm2": adm2,
    "seat_lat": atom.get("seat_lat"),
    "seat_lon": atom.get("seat_lon"),
    "unit_id": atom.get("unit_id"),
    "unit_type": unit_type,
  }


def classify_1954_2026_outer_atom (arg1_region, arg2_atom, arg3_year, arg4_reforms_cfg):
  """Classify a Taiwan, Mongolia, or Tuva modern atom for a snapshot year in 1954..2026.

  @param arg1_region Region key ('taiwan', 'mongolia', 'tuva_republic').
  @param arg2_atom Atom property dict.
  @param arg3_year Target snapshot year (1954..2026).
  @param arg4_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Dict with props + optional merge_target_adm2_en / merge_target_adm1.
  """
  # Convert from parameters
  atom = dict(arg2_atom or {})
  reforms_cfg = dict(arg4_reforms_cfg or {})
  region = str(arg1_region or "")
  yr = int(arg3_year)

  # Declare local instance variables.
  name_en = str(atom.get("name_en") or "")

  if region == "taiwan":
    t_cfg = reforms_cfg.get("taiwan_1954_2026", {})
    m_upg = t_cfg.get("municipal_upgrades", {})
    adm2 = str(atom.get("parent_adm2") or "")
    name_zh = str(atom.get("name_zh") or "")
    if atom.get("roc_fujian_offshore"):
      adm1 = "Fujian (ROC)"
    elif adm2 == "Taipei City":
      adm1 = "Taipei" if yr >= int(m_upg.get("Taipei", {}).get("snapshot_year", 1968)) else "Taiwan"
    elif adm2 == "Kaohsiung City":
      k_cfg = m_upg.get("Kaohsiung", {})
      is_urban = any(name_zh.startswith(p) for p in k_cfg.get("urban_prefixes", []))
      if yr >= int(k_cfg.get("snapshot_year", 2011)):
        adm1 = "Kaohsiung"
      elif yr >= 1980 and is_urban:
        adm1 = "Kaohsiung"
      else:
        adm1 = "Taiwan"
        adm2 = "Kaohsiung City" if is_urban else "Kaohsiung County"
    elif adm2 == "New Taipei City":
      if yr >= int(m_upg.get("NewTaipei", {}).get("snapshot_year", 2011)):
        adm1 = "New Taipei"
      else:
        adm1 = "Taiwan"
        adm2 = "Taipei County"
    elif adm2 == "Taichung City":
      tc_cfg = m_upg.get("Taichung", {})
      is_urban = name_zh in tc_cfg.get("urban_towns", [])
      if yr >= int(tc_cfg.get("snapshot_year", 2011)):
        adm1 = "Taichung"
      else:
        adm1 = "Taiwan"
        adm2 = "Taichung City" if is_urban else "Taichung County"
    elif adm2 == "Tainan City":
      tn_cfg = m_upg.get("Tainan", {})
      is_urban = name_zh in tn_cfg.get("urban_towns", [])
      if yr >= int(tn_cfg.get("snapshot_year", 2011)):
        adm1 = "Tainan"
      else:
        adm1 = "Taiwan"
        adm2 = "Tainan City" if is_urban else "Tainan County"
    elif adm2 == "Taoyuan City":
      if yr >= int(m_upg.get("Taoyuan", {}).get("snapshot_year", 2015)):
        adm1 = "Taoyuan"
      else:
        adm1 = "Taiwan"
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
      "country": "Republic of China",
      "gb_code": "",
      "merge_target_name": "",
      "name_ch": name_zh,
      "name_en": name_en,
      "occupied_by": "",
      "parent_adm1": adm1,
      "parent_adm1_zh": _adm1_zh(adm1, reforms_cfg),
      "parent_adm2": adm2,
      "seat_lat": atom.get("seat_lat"),
      "seat_lon": atom.get("seat_lon"),
      "unit_id": atom.get("modern_unit_id") or atom.get("unit_id"),
      "unit_type": str(atom.get("unit_type") or "township"),
    }

  if region == "mongolia":
    m_cfg = reforms_cfg.get("mongolia_1954_2026", {})
    adm1 = str(atom.get("parent_adm1") or "")
    adm1_fold = _normalise_ascii_fold(adm1)
    for enc_key, enc_spec in m_cfg.get("enclave_aimag_creations", {}).items():
      if adm1_fold == _normalise_ascii_fold(enc_key) and yr < int(enc_spec.get("snapshot_year", 1995)):
        adm1 = str(enc_spec.get("parent_aimag") or adm1)
        break
    country = "Mongolian People's Republic" if yr < int(m_cfg.get("state_rename_year", 1993)) else "Mongolia"
    return {
      "category": "aimag",
      "country": country,
      "gb_code": "",
      "merge_target_name": "",
      "name_ch": str(atom.get("name_mn_cyrl") or name_en),
      "name_en": name_en,
      "occupied_by": "",
      "parent_adm1": adm1,
      "parent_adm1_zh": "",
      "parent_adm2": adm1,
      "seat_lat": atom.get("seat_lat"),
      "seat_lon": atom.get("seat_lon"),
      "unit_id": atom.get("modern_unit_id") or atom.get("unit_id"),
      "unit_type": str(atom.get("unit_type") or "soum"),
    }

  # Tuva 1954-2026
  tuv_cfg = reforms_cfg.get("tuva_1954_2026", {})
  epoch_row = {"country": "Russian Federation", "name_en": "Republic of Tyva", "name_zh": "图瓦共和国"}
  for ep in tuv_cfg.get("state_epochs", []):
    if int(ep.get("start_year", 0)) <= yr <= int(ep.get("end_year", 9999)):
      epoch_row = ep
      break
  merge_target = ""
  k_creations = tuv_cfg.get("post_1953_kozhuun_creations", {})
  if name_en in k_creations and yr < int(k_creations[name_en].get("snapshot_year", 1999)):
    merge_target = str(k_creations[name_en].get("merge_into") or "")
  adm1 = str(epoch_row.get("name_en") or "Republic of Tyva")
  cat = "autonomous_oblast" if "Oblast" in adm1 else ("autonomous_republic" if "Soviet" in adm1 else "republic")

  # Return statement
  return {
    "category": cat,
    "country": str(epoch_row.get("country") or "Russian Federation"),
    "gb_code": "",
    "merge_target_name": merge_target,
    "name_ch": str(atom.get("name_tyv") or atom.get("name_ru") or name_en),
    "name_en": merge_target or name_en,
    "occupied_by": "",
    "parent_adm1": adm1,
    "parent_adm1_zh": str(epoch_row.get("name_zh") or ""),
    "parent_adm2": merge_target or name_en,
    "seat_lat": atom.get("seat_lat"),
    "seat_lon": atom.get("seat_lon"),
    "unit_id": atom.get("modern_unit_id") or atom.get("unit_id"),
    "unit_type": str(atom.get("unit_type") or "kozhuun"),
  }


def classify_1980_2026_prc_atom (arg1_atom, arg2_year, arg3_reforms_cfg):
  """Classify a modern PRC GeoJSON atom for a snapshot year in 1980..2026.

  @param arg1_atom Property dict from input/gis/modern/prc_adm_3.geojson.
  @param arg2_year Target snapshot year (1980..2026).
  @param arg3_reforms_cfg Parsed prc_admin_reforms_1954_2026.json5 dict.
  @return Classified dict including optional merge_gb for pre-creation units.
  """
  # Convert from parameters
  atom = dict(arg1_atom or {})
  reforms_cfg = dict(arg3_reforms_cfg or {})
  yr = int(arg2_year)

  # Declare local instance variables.
  adm1 = _canonical_modern_adm1(atom.get("parent_adm1"))
  adm1_zh = str(atom.get("parent_adm1_zh") or _adm1_zh(adm1, reforms_cfg))
  adm2 = str(atom.get("parent_adm2") or adm1)
  adm2_zh = str(atom.get("parent_adm2_zh") or "")
  e1 = reforms_cfg.get("epoch_1_1954_1979", {})
  e2 = reforms_cfg.get("epoch_2_1980_2000", {})
  e3 = reforms_cfg.get("epoch_3_2001_2026", {})
  gb = str(atom.get("gb_code") or "")
  merge_gb = ""
  name_ch = str(atom.get("name_zh") or "")
  name_en = str(atom.get("name_en") or "")
  snap_1990 = dict(atom.get("unit_1990s_snapshot") or {})
  unit_type = str(atom.get("unit_type") or "county_level_unit")

  if gb.startswith("81") or "Hong Kong" in adm1:
    if yr < int(e2.get("hong_kong_sar_year", 1998)):
      return {
        "category": "colony",
        "country": "United Kingdom (Hong Kong)",
        "gb_code": gb or "810000",
        "merge_gb": "",
        "name_ch": name_ch,
        "name_en": name_en,
        "occupied_by": "",
        "parent_adm1": "Hong Kong",
        "parent_adm1_zh": "香港",
        "parent_adm2": "Hong Kong",
        "parent_adm2_zh": "香港",
        "seat_lat": atom.get("seat_lat"),
        "seat_lon": atom.get("seat_lon"),
        "unit_id": atom.get("modern_unit_id"),
        "unit_type": "colony_district",
      }
    return {
      "category": "sar",
      "country": "People's Republic of China",
      "gb_code": gb or "810000",
      "merge_gb": "",
      "name_ch": name_ch,
      "name_en": name_en,
      "occupied_by": "",
      "parent_adm1": "Hong Kong SAR",
      "parent_adm1_zh": "香港特别行政区",
      "parent_adm2": "Hong Kong SAR",
      "parent_adm2_zh": "香港特别行政区",
      "seat_lat": atom.get("seat_lat"),
      "seat_lon": atom.get("seat_lon"),
      "unit_id": atom.get("modern_unit_id"),
      "unit_type": "sar_district",
    }

  if gb.startswith("82") or "Macau" in adm1:
    if yr < int(e2.get("macau_sar_year", 2000)):
      return {
        "category": "colony",
        "country": "Portugal (Macau)",
        "gb_code": gb or "820000",
        "merge_gb": "",
        "name_ch": name_ch,
        "name_en": name_en,
        "occupied_by": "",
        "parent_adm1": "Macau",
        "parent_adm1_zh": "澳门",
        "parent_adm2": "Macau",
        "parent_adm2_zh": "澳门",
        "seat_lat": atom.get("seat_lat"),
        "seat_lon": atom.get("seat_lon"),
        "unit_id": atom.get("modern_unit_id"),
        "unit_type": "colony_district",
      }
    return {
      "category": "sar",
      "country": "People's Republic of China",
      "gb_code": gb or "820000",
      "merge_gb": "",
      "name_ch": name_ch,
      "name_en": name_en,
      "occupied_by": "",
      "parent_adm1": "Macau SAR",
      "parent_adm1_zh": "澳门特别行政区",
      "parent_adm2": "Macau SAR",
      "parent_adm2_zh": "澳门特别行政区",
      "seat_lat": atom.get("seat_lat"),
      "seat_lon": atom.get("seat_lon"),
      "unit_id": atom.get("modern_unit_id"),
      "unit_type": "sar_district",
    }

  # Hainan inside Guangdong until 1988 (1989 snapshot splits Hainan)
  if adm1 == "Hainan" and yr < int(e2.get("hainan_province_year", 1989)):
    adm1 = "Guangdong"
    adm1_zh = "广东省"

  # Chongqing inside Sichuan until 1997 (1998 snapshot splits Chongqing municipality)
  if adm1 == "Chongqing" and yr < int(e2.get("chongqing_municipality_year", 1998)):
    adm1 = "Sichuan"
    adm1_zh = "四川省"

  # Pre-carving geometric merges for 2024 Hotan new counties & 2002-2023 XPCC cities
  if gb in ("653228", "653229") and yr < 2025:
    merge_gb = "653221"
  elif gb.startswith("6590") and gb != "659001" and yr < int(atom.get("snapshot_year") or 2026):
    merge_gb = str(atom.get("host_gb_2026") or "")

  # Apply historical names & ranks backwards before conversion snapshot years
  for ev in e3.get("conversion_events", []):
    if yr < int(ev.get("snapshot_year", 9999)) and (gb == str(ev.get("gb_2026") or "") or name_ch == str(ev.get("to_name") or "")):
      if ev.get("event_type") not in ("merged_into_qu", "merged_into_pref"):
        name_ch = str(ev.get("from_name") or name_ch)
        gb90_snap = str(snap_1990.get("gb_1990") or snap_1990.get("gb_code") or "")
        if gb90_snap:
          gb = gb90_snap

  for c2c in e2.get("county_to_city_1983_2000", []):
    if yr < int(c2c.get("snapshot_year", 9999)) and (gb == str(c2c.get("gb_1990") or "") or name_ch == str(c2c.get("to_name") or "")):
      name_ch = str(c2c.get("from_name") or name_ch)

  for t_upg in e3.get("tibetan_prefecture_upgrades", []):
    if yr < int(t_upg.get("snapshot_year", 9999)):
      if adm2_zh == str(t_upg.get("pref_name_zh") or ""):
        adm2_zh = str(t_upg.get("pref_name_old") or adm2_zh)
      if gb == str(t_upg.get("county_2026_gb") or "") or name_ch == str(t_upg.get("county_2026_name") or ""):
        name_ch = str(t_upg.get("county_1990_name") or name_ch)

  for sim in e1.get("rare_character_simplifications_1950s_1960s", []):
    if gb == str(sim.get("gb_code") or "") and yr < int(sim.get("effective_year", 1900)):
      name_ch = str(sim.get("old_name_zh") or name_ch)

  category = "municipality" if adm1 in ("Beijing", "Shanghai", "Tianjin", "Chongqing") else (
    "autonomous_region" if "Autonomous" in adm1 else "province"
  )

  # Return statement
  return {
    "category": category,
    "country": "People's Republic of China",
    "gb_code": gb,
    "merge_gb": merge_gb,
    "name_ch": name_ch,
    "name_en": name_en,
    "occupied_by": "",
    "parent_adm1": adm1,
    "parent_adm1_zh": adm1_zh,
    "parent_adm2": adm2,
    "parent_adm2_zh": adm2_zh,
    "seat_lat": atom.get("seat_lat"),
    "seat_lon": atom.get("seat_lon"),
    "unit_id": atom.get("modern_unit_id"),
    "unit_type": unit_type,
  }


def clean_and_populate_year_layers (arg1_adm1_items, arg2_adm2_items, arg3_adm3_items, arg4_precision):
  """Strip unclaimed sliver rings, populate seat_lon/seat_lat/parent_adm2, and format feature pairs.

  @param arg1_adm1_items List of (props_dict, geom) tuples for adm_1.
  @param arg2_adm2_items List of (props_dict, geom) tuples for adm_2.
  @param arg3_adm3_items List of (props_dict, geom) tuples for adm_3.
  @param arg4_precision Coordinate decimal rounding precision.
  @return Tuple (adm1_feats, adm2_feats, adm3_feats) ready for export_geojson.
  """
  # Convert from parameters
  adm1_items = list(arg1_adm1_items or [])
  adm2_items = list(arg2_adm2_items or [])
  adm3_items = list(arg3_adm3_items or [])
  precision = int(arg4_precision)

  # Declare local instance variables.
  cleaned_1 = modern_gis_helpers.strip_unclaimed_holes_in_features(adm1_items, 0.05)
  cleaned_2 = modern_gis_helpers.strip_unclaimed_holes_in_features(adm2_items, 0.02)
  cleaned_3 = modern_gis_helpers.strip_unclaimed_holes_in_features(adm3_items, 0.01)

  for layer in (cleaned_1, cleaned_2, cleaned_3):
    for props, geom in layer:
      if "parent_adm2" not in props:
        props["parent_adm2"] = ""
      if "parent_adm1" not in props:
        props["parent_adm1"] = ""
      if ("seat_lon" not in props or "seat_lat" not in props or props["seat_lon"] is None or props["seat_lat"] is None) and geom is not None and not geom.is_empty:
        rp = geom.representative_point()
        props["seat_lat"] = round(float(rp.y), precision)
        props["seat_lon"] = round(float(rp.x), precision)

  # Return statement
  return cleaned_1, cleaned_2, cleaned_3


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
  out = []
  with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)
  for ft in data.get("features", []):
    geom = gis_helpers.clean_polygonal_geometry(shape(ft["geometry"])) if ft.get("geometry") else None
    if geom is not None and not geom.is_empty:
      out.append((dict(ft.get("properties") or {}), geom))

  # Return statement
  return out
