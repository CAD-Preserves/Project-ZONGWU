"""Modern PRC, Taiwan, Mongolia, and Tuvan Republic GIS reference layer assembler."""

import json
import os
import sys
import zipfile
from shapely import STRtree
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)
from helpers import ctamap_io_helpers, gis_helpers, modern_gis_helpers, path_helpers, planar_topology_helpers, prc_lineage_helpers


class ModernLayerAssembler:
  """Builds clean WGS84 modern local-history GeoJSON layers under ./input/gis/modern/."""

  def __init__ (self, arg1_base_dir):
    """Initialise paths, configs, and OpenCC character tables.

    @param arg1_base_dir Project root directory.
    """
    # Convert from parameters
    base_dir = os.path.abspath(arg1_base_dir)

    # Declare local instance variables.
    self.base_dir = base_dir
    self.cfg = gis_helpers.load_json5(path_helpers.resolve_path("common.data_sources", base_dir))
    self.edge_cases = gis_helpers.load_json5(path_helpers.resolve_path("common.local_history_edge_cases", base_dir))
    self.fz_cfg = gis_helpers.load_json5(path_helpers.resolve_path("common.prc_functional_zones", base_dir)) or {}
    self.last_areacodes = {}
    self.last_ctamap_tables = {}
    self.last_lineage_doc = {}
    self.last_prc_units = []
    self.mng_adm1_meta_by_name = {}
    self.mng_adm2_features = []
    self.modern_dir = path_helpers.resolve_path("input.gis.modern_dir", base_dir)
    self.prc_adm3_features = []
    self.precision = int(self.cfg.get("coordinate_precision", 5))
    self.reforms_1954_2026 = gis_helpers.load_json5(path_helpers.resolve_path("common.prc_admin_reforms", base_dir)) or {}
    self.roc_fujian_mask = None
    self.st_map = {}
    self.ts_map = {}
    self.tuva_adm1_meta = {}
    self.tuva_adm2_features = []
    self.twn_adm2_meta_by_id = {}
    self.twn_adm3_features = []

    self._download_modern_sources()
    self._load_opencc_maps()

  def _aggregate_prc_layers (self, arg1_adm3_feats):
    """Aggregate globally noded Mainland PRC adm_3 features into watertight adm_2 and adm_1 layers."""
    # Convert from parameters
    adm3_feats = list(arg1_adm3_feats or [])

    # Declare local instance variables.
    adm1_feats = []
    adm2_feats = []

    adm2_feats = planar_topology_helpers.aggregate_coverage_by_key(
      adm3_feats,
      lambda p: (str(p.get("parent_adm1_gb") or ""), str(p.get("parent_adm2_gb") or ""), str(p.get("parent_adm2") or "")),
      lambda k, ms: {
        "gb_code": ms[0]["parent_adm2_gb"],
        "modern_unit_id": f"prc_adm2_{ms[0]['parent_adm2_gb']}_{gis_helpers.slugify_snake(ms[0]['parent_adm2'])}",
        "name_en": ms[0]["parent_adm2"],
        "name_zh": ms[0]["parent_adm2_zh"],
        "name_zh_hant": self._to_hant(ms[0]["parent_adm2_zh"]),
        "parent_adm1": ms[0]["parent_adm1"],
        "parent_adm1_gb": ms[0]["parent_adm1_gb"],
        "parent_adm1_zh": ms[0]["parent_adm1_zh"],
        "region": "mainland_prc",
        "search_queries": [f"{ms[0]['parent_adm2_zh']}志", f"{ms[0]['parent_adm2_zh'].rstrip('市地区盟州')}地区志", f"{ms[0]['parent_adm2_zh'].rstrip('市地区盟州')}市志·大事记", f"{ms[0]['parent_adm2_zh'].rstrip('市地区盟州')}市志·军事志", f"{ms[0]['parent_adm2_zh'].rstrip('市地区盟州')}地名志"],
        "unit_type": "prefecture_level_unit",
      },
      1e-5,
      0.05,
    )
    adm1_feats = planar_topology_helpers.aggregate_coverage_by_key(
      adm3_feats,
      lambda p: (str(p.get("parent_adm1_gb") or ""), str(p.get("parent_adm1") or ""), str(p.get("parent_adm1_zh") or "")),
      lambda k, ms: {
        "gb_code": k[0],
        "modern_unit_id": f"prc_adm1_{k[0]}_{gis_helpers.slugify_snake(k[1])}",
        "name_en": k[1],
        "name_zh": k[2],
        "name_zh_hant": self._to_hant(k[2]),
        "region": "mainland_prc",
        "search_queries": [
          f"{k[2].replace('特别行政区', '').replace('壮族自治区', '').replace('回族自治区', '').replace('维吾尔自治区', '').replace('自治区', '').rstrip('省市')}通志",
          f"{k[2].replace('特别行政区', '').replace('壮族自治区', '').replace('回族自治区', '').replace('维吾尔自治区', '').replace('自治区', '').rstrip('省市')}省志·大事记",
          f"{k[2].replace('特别行政区', '').replace('壮族自治区', '').replace('回族自治区', '').replace('维吾尔自治区', '').replace('自治区', '').rstrip('省市')}省志·军事志",
          f"{k[2].replace('特别行政区', '').replace('壮族自治区', '').replace('回族自治区', '').replace('维吾尔自治区', '').replace('自治区', '').rstrip('省市')}省志·地名志",
          f"{k[2].replace('特别行政区', '').replace('壮族自治区', '').replace('回族自治区', '').replace('维吾尔自治区', '').replace('自治区', '').rstrip('省市')}省志·建置沿革志",
        ],
        "unit_type": "province_level_unit",
      },
      1e-5,
      0.05,
    )

    # Return statement
    return adm1_feats, adm2_feats

  def _build_mng_layers (self):
    """Build and export ./input/gis/modern/mng_adm_1.geojson and mng_adm_2.geojson."""
    # Declare local instance variables.
    mng_cfg = self.edge_cases["mongolia"]
    cyrl_map = mng_cfg["aimag_cyrillic_names"]
    enclave_map = mng_cfg["enclave_aimag_remapping_post_1994"]
    khoshuun_map = mng_cfg["bogd_khanate_and_1924_crosswalk"]
    kazakh_aimags = set(mng_cfg["bilingual_kazakh_aimags"])
    m1_feats = []
    m2_feats = []
    seen_ids = set()

    with open(path_helpers.resolve_provider_file(self.cfg, "gadm", "gadm_mng_1", self.base_dir), "r", encoding="utf-8") as fh:
      m1_raw = json.load(fh).get("features", [])

    for ft in m1_raw:
      props = ft.get("properties", {})
      geom = gis_helpers.clean_polygonal_geometry(shape(ft["geometry"]))
      if geom is None:
        continue
      name_en = str(props.get("NAME_1") or "").strip()
      meta = cyrl_map.get(name_en, {})
      name_cyrl = meta.get("name_mn_cyrl") or name_en
      name_zh = meta.get("name_zh") or ""
      parent_1932 = enclave_map.get(name_en, name_en)
      kh_info = khoshuun_map.get(name_en, {})
      is_kazakh = name_en in kazakh_aimags
      edges = []
      if parent_1932 != name_en:
        edges.append("post_1994_enclave_aimag")
      if is_kazakh:
        edges.append("bilingual_kazakh_mongolian")
      slug = gis_helpers.slugify_snake(name_en)
      queries = [
        f"{name_cyrl} түүх",
        f"{name_cyrl.replace(' аймаг', '').replace(' хот', '')} аймгийн нэвтэрхий толь",
        "БНМАУ-ын түүх",
      ]
      if is_kazakh:
        queries.append("Баян-Өлгий тарихы")
      m1_feats.append(({
        "bilingual_kazakh": is_kazakh,
        "edge_cases": edges,
        "gid_1": str(props.get("GID_1") or ""),
        "historical_1912_1923": kh_info.get("1912_1923", ""),
        "historical_1924_1931": kh_info.get("1924_1931", ""),
        "modern_unit_id": f"mng_adm1_{slug}",
        "name_en": name_en,
        "name_mn_cyrl": name_cyrl,
        "name_zh": name_zh,
        "parent_1932_1953_aimag": parent_1932,
        "region": "mongolia",
        "search_queries": queries,
        "unit_type": "municipality" if name_en == "Ulaanbaatar" else "aimag",
      }, geom))

    m2_raw = self._load_gadm_features(self.cfg["gadm"]["files"]["gadm_mng_2"]["filename"])
    for props, geom in m2_raw:
      n1 = str(props.get("NAME_1") or "").strip()
      n2 = str(props.get("NAME_2") or "").strip()
      nl2 = str(props.get("NL_NAME_2") or "").strip()
      if nl2 in ("", "NA"):
        nl2 = mng_cfg["soum_cyrl_fallback"].get(n2, n2)
      parent_1932 = enclave_map.get(n1, n1)
      kh_info = khoshuun_map.get(n1, {})
      is_kazakh = n1 in kazakh_aimags
      aimag_cyrl = cyrl_map.get(n1, {}).get("name_mn_cyrl", n1)
      edges = ["mongolia_tiered_fallback"]
      if parent_1932 != n1:
        edges.append("post_1994_enclave_aimag")
      if is_kazakh:
        edges.append("bilingual_kazakh_mongolian")
      uid = f"mng_adm2_{gis_helpers.slugify_snake(n1)}_{gis_helpers.slugify_snake(n2)}"
      if uid in seen_ids:
        uid = f"{uid}_{len(seen_ids)}"
      seen_ids.add(uid)
      queries = [
        f"{nl2} сумын түүх",
        f"{aimag_cyrl} түүх",
        f"{aimag_cyrl.replace(' аймаг', '').replace(' хот', '')} нэвтэрхий толь",
      ]
      if is_kazakh:
        queries.append(f"{nl2} тарихы")
      m2_feats.append(({
        "bilingual_kazakh": is_kazakh,
        "edge_cases": edges,
        "gid_2": str(props.get("GID_2") or ""),
        "historical_1912_1923": kh_info.get("1912_1923", ""),
        "historical_1924_1931": kh_info.get("1924_1931", ""),
        "modern_unit_id": uid,
        "name_en": n2,
        "name_mn_cyrl": nl2,
        "parent_1932_1953_aimag": parent_1932,
        "parent_adm1": n1,
        "parent_adm1_mn_cyrl": aimag_cyrl,
        "region": "mongolia",
        "search_queries": queries,
        "unit_type": "soum",
      }, geom))

    m1_meta_by_name = {str(p.get("name_en") or ""): dict(p) for p, _ in m1_feats}
    m2_feats, _ = planar_topology_helpers.harmonise_international_seams(self.prc_adm3_features, m2_feats, 1e-5, 0.03)
    m2_feats = planar_topology_helpers.clean_planar_coverage(m2_feats, 1e-5, 0.05, 1e-4)
    self.mng_adm1_meta_by_name = m1_meta_by_name
    self.mng_adm2_features = m2_feats

    # Return statement
    return {"mng_adm_2": len(m2_feats)}

  def _build_prc_layers (self):
    """Build and export ./input/gis/modern/prc_adm_{1,2,3}.geojson strictly from CTAmap T2026_county.gpkg."""
    # Declare local instance variables.
    adm1_en = ""
    adm1_gb = ""
    adm1_zh = ""
    adm2_en = ""
    adm2_gb = ""
    adm2_meta = {}
    adm2_zh = ""
    canon_adm1_by_gb = {
      "110000": "Beijing",
      "120000": "Tianjin",
      "130000": "Hebei",
      "140000": "Shanxi",
      "150000": "Inner Mongolia Autonomous Region",
      "210000": "Liaoning",
      "220000": "Jilin",
      "230000": "Heilongjiang",
      "310000": "Shanghai",
      "320000": "Jiangsu",
      "330000": "Zhejiang",
      "340000": "Anhui",
      "350000": "Fujian",
      "360000": "Jiangxi",
      "370000": "Shandong",
      "410000": "Henan",
      "420000": "Hubei",
      "430000": "Hunan",
      "440000": "Guangdong",
      "450000": "Guangxi Zhuang Autonomous Region",
      "460000": "Hainan",
      "500000": "Chongqing",
      "510000": "Sichuan",
      "520000": "Guizhou",
      "530000": "Yunnan",
      "540000": "Tibet Autonomous Region",
      "610000": "Shaanxi",
      "620000": "Gansu",
      "630000": "Qinghai",
      "640000": "Ningxia Hui Autonomous Region",
      "650000": "Xinjiang Uygur Autonomous Region",
      "810000": "Hong Kong SAR",
      "820000": "Macau SAR",
    }
    citas_list = self._load_citas_1990()
    cleaned_pairs = []
    ctamap_dir = path_helpers.resolve_path("input.gis.ctamap_dir", self.base_dir)
    eng_type_map = {
      "区": "Qu",
      "县": "Xian",
      "县级市": "Shi",
      "市辖区": "Qu",
      "自治县": "Zizhixian",
      "自治旗": "Zizhiqi",
      "旗": "Qi",
      "林区": "Linqu",
      "特区": "Tequ",
      "特别行政区": "SAR",
    }
    gpkg_2026 = os.path.join(ctamap_dir, "T2026_county.gpkg")
    kept_parts = []
    muni_or_sar = {"110000", "120000", "310000", "500000", "810000", "820000"}
    raw_2026 = ctamap_io_helpers.read_ctamap_county_year(gpkg_2026, {}, self.precision)
    raw_pairs = []
    rep_pt = None
    seen_adm2_names = set()
    seen_ids = set()
    synth_seq = 0
    uid = ""
    unit_type = ""
    units = []
    utype_map = {
      "市辖区": "urban_district",
      "县": "county",
      "县级市": "county_level_city",
      "自治县": "autonomous_county",
      "自治旗": "autonomous_banner",
      "旗": "banner",
      "林区": "forestry_district",
      "特区": "special_district",
      "特别行政区": "special_administrative_region",
    }

    for props, geom in raw_2026:
      adm1_gb = str(props.get("省级码") or "").strip()
      if adm1_gb in ("0", "710000", ""):
        continue
      adm1_zh = str(props.get("省级") or "").strip()
      adm1_en = canon_adm1_by_gb.get(adm1_gb, str(props.get("NAME_1") or adm1_gb).strip())
      gb_code = str(props.get("区划码") or "").strip()
      if gb_code in ("", "0"):
        synth_seq += 1
        gb_code = f"{adm1_gb[:2]}99{synth_seq:02d}"

      name_zh = str(props.get("地名") or "").strip()
      if gb_code in ("350527", "352427") or name_zh == "金门县":
        continue
      if adm1_gb in ("350000", "440000") and self.roc_fujian_mask is not None and geom.intersects(self.roc_fujian_mask):
        kept_parts = [
          pt for pt in planar_topology_helpers._extract_polygons(geom)
          if not (pt.area < 0.05 and pt.intersects(self.roc_fujian_mask))
        ]
        if not kept_parts:
          continue
        geom = kept_parts[0] if len(kept_parts) == 1 else MultiPolygon(kept_parts)
      eng_stem = str(props.get("ENG_NAME") or props.get("NAME_3") or gb_code).strip()
      cls_zh = str(props.get("县级类") or "").strip()
      if gb_code == "810000":
        name_en = "Hong Kong SAR"
      elif gb_code == "820000":
        name_en = "Macau SAR"
      elif cls_zh in ("县", "市辖区", "自治县", "旗", "自治旗"):
        sfx_en = eng_type_map.get(cls_zh, "")
        name_en = f"{eng_stem} {sfx_en}".strip() if sfx_en and not eng_stem.endswith(sfx_en) else eng_stem
      else:
        name_en = eng_stem

      if adm1_gb in muni_or_sar:
        adm2_gb = adm1_gb
        adm2_en = adm1_en
        adm2_zh = adm1_zh
      else:
        raw_p2_gb = str(props.get("地级码") or "").strip()
        raw_p2_zh = str(props.get("地级") or "").strip()
        if raw_p2_gb in ("", "0") or raw_p2_zh in ("", "不统计"):
          adm2_gb = gb_code
          adm2_zh = name_zh
          adm2_en = name_en
        else:
          adm2_gb = raw_p2_gb
          adm2_zh = raw_p2_zh
          adm2_en = str(props.get("NAME_2") or raw_p2_zh or gb_code).strip()

      if (adm1_en, adm2_gb) not in adm2_meta:
        cand_en = adm2_en
        if (adm1_en, cand_en) in seen_adm2_names:
          cand_en = f"{cand_en} ({adm2_gb})"
        seen_adm2_names.add((adm1_en, cand_en))
        adm2_meta[(adm1_en, adm2_gb)] = (adm1_gb, adm1_en, adm1_zh, adm2_gb, cand_en, adm2_zh)
      adm2_en = adm2_meta[(adm1_en, adm2_gb)][4]

      unit_type = utype_map.get(cls_zh, "special_administrative_region" if gb_code in ("810000", "820000") else "county")
      uid_base = f"prc_{gb_code}_{gis_helpers.slugify_snake(name_en)}"
      uid = uid_base
      if uid in seen_ids:
        uid = f"{uid_base}_{len(seen_ids)}"
      seen_ids.add(uid)

      rep_pt = geom.representative_point()
      raw_pairs.append(({
        "edge_cases": [],
        "gb_code": gb_code,
        "name_en": name_en,
        "name_py": str(props.get("VARNAME_3") or eng_stem).strip(),
        "name_zh": name_zh,
        "name_zh_hant": self._to_hant(name_zh),
        "parent_adm1": adm1_en,
        "parent_adm1_gb": adm1_gb,
        "parent_adm1_zh": adm1_zh,
        "parent_adm2": adm2_en,
        "parent_adm2_gb": adm2_gb,
        "parent_adm2_zh": adm2_zh,
        "region": "mainland_prc",
        "search_queries": [],
        "seat_lat": round(float(rep_pt.y), 5),
        "seat_lon": round(float(rep_pt.x), 5),
        "unit_id": uid,
        "unit_type": unit_type,
      }, geom))

    cleaned_pairs = planar_topology_helpers.simplify_and_clean_coverage(raw_pairs, 0.002, 1e-5, 0.05, 1e-4)
    cleaned_pairs, _ = planar_topology_helpers.enforce_adm1_contiguity(cleaned_pairs, "parent_adm1", 0.005, 1e-5)

    for p_item, g_item in cleaned_pairs:
      rec = dict(p_item)
      rec["geom"] = g_item
      units.append(rec)

    self.last_lineage_doc = prc_lineage_helpers.build_prc_lineage_graph(
      units,
      citas_list,
      self.reforms_1954_2026,
      self.fz_cfg,
      self.edge_cases,
      self.last_areacodes,
      self.last_ctamap_tables.get("change_events_v2", []),
    )
    lineage_by_id = self.last_lineage_doc.get("units_by_id", {})
    for u in units:
      u["name_zh_hant"] = self._to_hant(u["name_zh"])
      lin_entry = lineage_by_id.get(u["unit_id"], {})
      edges, s_plan, flat_qs = prc_lineage_helpers.build_chronicle_search_plan(u, lin_entry, self.edge_cases, self.reforms_1954_2026)
      u["edge_cases"] = edges
      u["search_queries"] = flat_qs
      u["chronicle_search_plan"] = s_plan
      if lin_entry:
        u["unit_1990s_snapshot"] = lin_entry.get("unit_1990s_snapshot", {})
        u["unit_2026_snapshot"] = lin_entry.get("unit_2026_snapshot", {})
        u["parent_1990s_unit_ids"] = lin_entry.get("parent_1990s_unit_ids", [])

    self.last_prc_units = units
    adm3_feats = []
    for u in units:
      props_out = {k: v for k, v in u.items() if k not in ("_wkb_hex", "citas_zh", "geom", "gb_1990", "unit_id")}
      props_out["modern_unit_id"] = u["unit_id"]
      adm3_feats.append((props_out, u["geom"]))

    self.prc_adm3_features = adm3_feats

    # Return statement
    return {"prc_adm_3": len(adm3_feats)}

  def _build_tuva_layers (self):
    """Build and export ./input/gis/modern/tuva_adm_1.geojson and tuva_adm_2.geojson (17 kozhuuns + 2 cities)."""
    # Declare local instance variables.
    gadm_r2 = self._load_gadm_features(self.cfg["gadm"]["files"]["gadm_rus_2"]["filename"])
    gadm_tuva_geoms = [g for p, g in gadm_r2 if "tuva" in str(p.get("NAME_1") or "").lower()]
    gadm_tuva_union = gis_helpers.clean_polygonal_geometry(unary_union(gadm_tuva_geoms))
    gb_path = path_helpers.resolve_provider_file(self.cfg, "modern_reference", "rus_adm2_geoboundaries", self.base_dir)
    tuva_cfg = self.edge_cases["tuva"]
    kmeta = tuva_cfg["kozhuun_metadata"]
    tigpi_list = tuva_cfg["tigpi_republic_compendia"]
    units = []

    with open(gb_path, "r", encoding="utf-8") as fh:
      gb_feats = json.load(fh).get("features", [])

    for ft in gb_feats:
      sn = str(ft.get("properties", {}).get("shapeName") or "").strip()
      if sn not in kmeta:
        continue
      g = gis_helpers.clean_polygonal_geometry(shape(ft["geometry"]))
      if g is None:
        continue
      if gadm_tuva_union is not None:
        clipped = gis_helpers.clean_polygonal_geometry(g.intersection(gadm_tuva_union))
        if clipped is not None:
          g = clipped
      meta = kmeta[sn]
      units.append({"geom": g, "meta": meta, "shape_name": sn})

    # Snap outer boundary gaps from GADM Tuva union to adjacent kozhuuns so coverage is watertight
    if gadm_tuva_union is not None and units:
      gb_union = gis_helpers.clean_polygonal_geometry(unary_union([u["geom"] for u in units]))
      outer_diff = gis_helpers.clean_polygonal_geometry(gadm_tuva_union.difference(gb_union))
      if outer_diff is not None and outer_diff.area > 1e-6:
        parts = [outer_diff] if outer_diff.geom_type == "Polygon" else list(outer_diff.geoms)
        for part in parts:
          if part.area <= 1e-6:
            continue
          best_i = 0
          best_d = 1e9
          for i, u in enumerate(units):
            d_val = u["geom"].distance(part)
            if d_val < best_d:
              best_d = d_val
              best_i = i
          merged = gis_helpers.clean_polygonal_geometry(unary_union([units[best_i]["geom"], part]))
          if merged is not None:
            units[best_i]["geom"] = merged

    t2_feats = []
    for u in sorted(units, key=lambda x: x["meta"]["slug"]):
      m = u["meta"]
      edges = ["tuva_tigpi_compendium_pairing"] + list(m.get("border_flags", []))
      queries = [
        f"{m['name_ru']} история",
        f"{m['name_tyv']} төөгүзү",
        "История Тувы (ТНИИЯЛИ / ТИГПИ)",
        "Учёные записки ТНИИЯЛИ",
      ]
      t2_feats.append(({
        "border_adjustment_flags": m.get("border_flags", []),
        "edge_cases": edges,
        "modern_unit_id": f"tuva_adm2_{m['slug']}",
        "name_en": m["name_en"],
        "name_ru": m["name_ru"],
        "name_tyv": m["name_tyv"],
        "parent_1922_1953_khoshuuns": m["parent_1922_1953_khoshuuns"],
        "parent_adm1": "Republic of Tyva",
        "region": "tuva_republic",
        "search_queries": queries,
        "tigpi_compendia": tigpi_list,
        "unit_type": m["unit_type"],
      }, u["geom"]))

    t2_feats, _ = planar_topology_helpers.harmonise_international_seams(self.prc_adm3_features + self.mng_adm2_features, t2_feats, 1e-5, 0.03)
    t2_feats = planar_topology_helpers.clean_planar_coverage(t2_feats, 1e-5, 0.05, 1e-4)
    self.tuva_adm2_features = t2_feats
    self.tuva_adm1_meta = {
      "edge_cases": ["tuva_tigpi_compendium_pairing"],
      "modern_unit_id": "tuva_adm1_republic_of_tyva",
      "name_en": "Republic of Tyva",
      "name_ru": "Республика Тыва",
      "name_tyv": "Тыва Республика",
      "region": "tuva_republic",
      "search_queries": tigpi_list,
      "unit_type": "republic",
    }

    # Return statement
    return {"tuva_adm_2": len(t2_feats)}

  def _build_twn_layers (self):
    """Build and export ./input/gis/modern/twn_adm_1.geojson, twn_adm_2.geojson, and twn_adm_3.geojson."""
    # Declare local instance variables.
    adm1_buckets = {}
    dongding_parts = []
    gb_twn_path = path_helpers.resolve_provider_file(self.cfg, "modern_reference", "tw_townships_geoboundaries", self.base_dir)
    g0v_path = path_helpers.resolve_provider_file(self.cfg, "modern_reference", "tw_townships_g0v", self.base_dir)
    indig_set = set(s.replace("臺", "台") for s in self.edge_cases["taiwan"]["indigenous_mountain_townships"])
    offshore_geoms = []
    pratas_parts = []
    raw_twn2 = self._load_gadm_features(self.cfg["gadm"]["files"]["gadm_twn_2"]["filename"])
    t2_by_zh = {}
    t2_feats = []
    t2_meta = self.edge_cases["taiwan"]["gadm_twn2_metadata"]
    t3_buckets = {}
    t3_feats = []

    for props, geom in raw_twn2:
      n1 = str(props.get("NAME_1") or "").strip()
      n2 = str(props.get("NAME_2") or "").strip()
      if n2 == "Pingtung":
        kept_p2 = []
        for pt in planar_topology_helpers._extract_polygons(geom):
          if pt.centroid.x < 117.5 and pt.centroid.y < 21.5:
            pratas_parts.append(pt)
          else:
            kept_p2.append(pt)
        if kept_p2:
          geom = kept_p2[0] if len(kept_p2) == 1 else MultiPolygon(kept_p2)
      elif n2 == "Kinmen":
        for pt in planar_topology_helpers._extract_polygons(geom):
          if 118.48 <= pt.centroid.x <= 118.53 and 24.41 <= pt.centroid.y <= 24.45:
            dongding_parts.append(pt)
      meta = t2_meta.get(n2, {})
      canon_en = meta.get("name_en", n2)
      name_zh = meta.get("name_zh", str(props.get("NL_NAME_2") or n2))
      name_zh_hans = self._to_hans(name_zh)
      is_offshore = bool(meta.get("roc_fujian_offshore", False))
      slug = gis_helpers.slugify_snake(canon_en.replace(" County", "").replace(" City", "").replace(" (Matsu)", ""))
      uid2 = f"twn_adm2_{slug}"
      edges = ["prefer_1985_2005_chongxiu", "pair_japanese_colonial_surveys"]
      if n2 == "Kinmen":
        edges.append("roc_fujian_kinmen_disambig")
      elif n2 == "Lienkiang":
        edges.append("roc_fujian_matsu_lianjiang_disambig")

      base_zh = name_zh.rstrip("縣市")
      queries = [
        f"{name_zh}志",
        f"重修{name_zh}志",
        f"{meta.get('shu_1921_1945', '')}管內概況及事務概要",
      ]
      if n2 == "Lienkiang":
        queries.append("馬祖列島志")
      if n1 not in ("Fujian",):
        queries.append(f"{base_zh}郡要覽")

      rec2 = {
        "edge_cases": edges,
        "gid_2": str(props.get("GID_2") or ""),
        "japanese_1912_1920_cho": meta.get("cho_1912_1920", ""),
        "japanese_1921_1945_shu_cho": meta.get("shu_1921_1945", ""),
        "modern_unit_id": uid2,
        "name_en": canon_en,
        "name_zh": name_zh,
        "name_zh_hans": name_zh_hans,
        "parent_adm1": n1,
        "region": "taiwan",
        "roc_1946_1950_county": meta.get("roc_1946_1950", ""),
        "roc_fujian_offshore": is_offshore,
        "search_queries": queries,
        "unit_type": meta.get("unit_type", "county"),
      }
      t2_feats.append((rec2, geom))
      t2_by_zh[name_zh.replace("臺", "台")] = rec2
      if name_zh == "桃園市":
        t2_by_zh["桃園縣"] = rec2
      adm1_buckets.setdefault(n1, []).append(geom)

    # Load geoBoundaries TWN ADM2 (368 units) for English names + Namasia/Wuqiu polygons
    with open(gb_twn_path, "r", encoding="utf-8") as fh:
      gb_feats = json.load(fh).get("features", [])
    gb_items = []
    wuqiu_geom = None
    for ft in gb_feats:
      sn = str(ft.get("properties", {}).get("shapeName") or "").strip()
      gg = gis_helpers.clean_polygonal_geometry(shape(ft["geometry"]))
      if gg is None:
        continue
      gb_items.append((sn, gg))
      if sn == "Wuqiu":
        wuqiu_geom = gg
    gb_tree = STRtree([it[1] for it in gb_items])

    # Load twTown1982 and dissolve harbour extensions + split Sanmin/Namasia
    with open(g0v_path, "r", encoding="utf-8") as fh:
      g0v_feats = json.load(fh).get("features", [])
    for ft in g0v_feats:
      p = ft.get("properties", {})
      cn = str(p.get("COUNTYNAME") or "").strip().replace("臺", "台")
      tn = str(p.get("TOWNNAME") or "").strip().replace("(海)", "").replace("(海區", "")
      if cn == "台中市" and tn in ("梧棲鎮", "清水鎮"):
        tn = tn[:-1] + "區"
      g = gis_helpers.clean_polygonal_geometry(shape(ft["geometry"]))
      if g is None:
        continue
      if cn == "高雄市" and tn == "三民區" and g.geom_type == "MultiPolygon":
        for poly in g.geoms:
          sub_tn = "那瑪夏區" if poly.centroid.x > 120.5 else "三民區"
          t3_buckets.setdefault((cn, sub_tn), []).append(poly)
      else:
        t3_buckets.setdefault((cn, tn), []).append(g)

    if wuqiu_geom is not None:
      t3_buckets.setdefault(("金門縣", "烏坵鄉"), []).append(wuqiu_geom)
    if pratas_parts:
      t3_buckets.setdefault(("高雄市", "旗津區"), []).extend(pratas_parts)
    if dongding_parts:
      t3_buckets.setdefault(("金門縣", "金湖鎮"), []).extend(dongding_parts)

    seen_t3 = set()
    for (cn_norm, tn_zh), geoms in sorted(t3_buckets.items()):
      merged = gis_helpers.clean_polygonal_geometry(unary_union(geoms))
      if merged is None:
        continue
      p2_rec = t2_by_zh.get(cn_norm)
      if p2_rec is None:
        continue
      best_en = tn_zh
      best_ov = 0.0
      for idx in gb_tree.query(merged):
        sn, gg = gb_items[idx]
        if merged.intersects(gg):
          ov = merged.intersection(gg).area
          if ov > best_ov:
            best_ov = ov
            best_en = sn
      if tn_zh == "烏坵鄉":
        best_en = "Wuqiu"
      elif tn_zh == "那瑪夏區":
        best_en = "Namasia"

      is_indig = (tn_zh.replace("臺", "台") in indig_set) or (cn_norm == "桃園縣" and tn_zh == "復興鄉")
      if tn_zh.endswith("鄉"):
        utype = "indigenous_mountain_township" if is_indig else "rural_township"
      elif tn_zh.endswith("鎮"):
        utype = "urban_township"
      elif tn_zh.endswith("市"):
        utype = "county_administered_city"
      else:
        utype = "indigenous_mountain_district" if is_indig else "urban_district"

      slug3 = gis_helpers.slugify_snake(best_en)
      p2_slug = p2_rec["modern_unit_id"].replace("twn_adm2_", "")
      uid3 = f"twn_adm3_{p2_slug}_{slug3}"
      if uid3 in seen_t3:
        uid3 = f"{uid3}_{len(seen_t3)}"
      seen_t3.add(uid3)

      edges = ["prefer_1985_2005_chongxiu", "pair_japanese_colonial_surveys"]
      if is_indig:
        edges.append("indigenous_mountain_township")
      if p2_rec["roc_fujian_offshore"]:
        edges.append("roc_fujian_offshore_disambig")

      queries = [
        f"{tn_zh}志",
        f"{p2_rec['name_zh']}{tn_zh}志",
        f"重修{p2_rec['name_zh']}志",
      ]
      if is_indig:
        queries.extend(["理蕃誌稿", "高砂族調查書"])

      t3_feats.append(({
        "edge_cases": edges,
        "is_indigenous_mountain_township": is_indig,
        "japanese_1912_1920_cho": p2_rec["japanese_1912_1920_cho"],
        "japanese_1921_1945_shu_cho": p2_rec["japanese_1921_1945_shu_cho"],
        "modern_unit_id": uid3,
        "name_en": best_en,
        "name_zh": tn_zh,
        "name_zh_hans": self._to_hans(tn_zh),
        "parent_adm1": p2_rec["parent_adm1"],
        "parent_adm2": p2_rec["name_en"],
        "parent_adm2_id": p2_rec["modern_unit_id"],
        "parent_adm2_zh": p2_rec["name_zh"],
        "region": "taiwan",
        "roc_fujian_offshore": p2_rec["roc_fujian_offshore"],
        "search_queries": queries,
        "unit_type": utype,
      }, merged))

    t3_feats = planar_topology_helpers.simplify_and_clean_coverage(t3_feats, 0.0005, 1e-5, 0.05, 1e-4)
    offshore_geoms = [g for p, g in t3_feats if p.get("roc_fujian_offshore")] + [g for p, g in t2_feats if p.get("roc_fujian_offshore")] + pratas_parts
    if offshore_geoms:
      self.roc_fujian_mask = unary_union(offshore_geoms).buffer(0.015)
    self.twn_adm2_meta_by_id = {str(p.get("modern_unit_id") or ""): dict(p) for p, _ in t2_feats}
    self.twn_adm3_features = t3_feats

    # Return statement
    return {"twn_adm_3": len(t3_feats)}

  def _download_modern_sources (self):
    """Ensure all modern reference sources configured in data_sources.json5 and CTAmap tables/2026 are cached locally."""
    for key, meta in self.cfg.get("modern_reference", {}).get("files", {}).items():
      dest = path_helpers.resolve_provider_file(self.cfg, "modern_reference", key, self.base_dir)
      ok = gis_helpers.download_with_cache(meta["url"], dest)
      if not ok:
        print(f"[WARN] Failed to cache modern_reference source {key}: {meta['url']}", file=sys.stderr)
    ctamap_io_helpers.download_ctamap_archive(self.cfg, self.base_dir, [2000, 2026], 2)
    ac_res = path_helpers.resolve_provider_file(self.cfg, "modern_reference", "areacodes_result", self.base_dir)
    ac_json = path_helpers.resolve_provider_file(self.cfg, "modern_reference", "areacodes_codes", self.base_dir)
    self.last_areacodes = ctamap_io_helpers.load_areacodes_lineage(ac_res, ac_json)
    tables_zip = os.path.join(path_helpers.resolve_path("input.gis.ctamap_dir", self.base_dir), self.cfg.get("ctamap_zenodo", {}).get("tables_filename", "tables.zip"))
    self.last_ctamap_tables = ctamap_io_helpers.load_ctamap_events(tables_zip)

  def _load_citas_1990 (self):
    """Load 1990 CITAS county polygons in WGS84 for GB/T 2260 alignment and hole filling."""
    citas_path = path_helpers.resolve_provider_file(self.cfg, "chgis_dataverse", "chgis_1990_citas_cnty", self.base_dir)
    raw = gis_helpers.read_zip_shapefile_wgs84(citas_path, "utf-8", self.precision)
    out = []
    for rec, geom in raw:
      gb = str(rec.get("GBCENMQ") or "").strip()
      if len(gb) < 4:
        continue
      out.append({
        "gb": gb,
        "geom": geom,
        "name_en": str(rec.get("NMFULL") or "").strip(),
        "name_zh": str(rec.get("NMHANZI") or "").strip(),
      })

    # Return statement
    return out

  def _load_gadm_features (self, arg1_filename):
    """Load and clean polygonal features from a GADM JSON or JSON.zip archive."""
    # Convert from parameters
    path = path_helpers.resolve_source_file("gadm", arg1_filename, self.base_dir)

    if path.lower().endswith(".zip"):
      with zipfile.ZipFile(path, "r") as zf:
        jname = [n for n in zf.namelist() if n.lower().endswith(".json")][0]
        data = json.loads(zf.read(jname).decode("utf-8"))
    else:
      with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    out = []
    for feat in data.get("features", []):
      geom = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
      if geom is not None and not geom.is_empty:
        out.append((feat.get("properties", {}), geom))

    # Return statement
    return out

  def _load_opencc_maps (self):
    """Load OpenCC STCharacters and TSCharacters tables for Simplified/Traditional conversion."""
    for fname, target in (("opencc_st_chars", self.st_map), ("opencc_ts_chars", self.ts_map)):
      path = path_helpers.resolve_provider_file(self.cfg, "modern_reference", fname, self.base_dir)
      if not os.path.exists(path):
        continue
      with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
          if line and not line.startswith("#") and "\t" in line:
            k, v = line.rstrip("\r\n").split("\t", 1)
            if k and v:
              target[k] = v.split(" ")[0]


  def _to_hans (self, arg1_text):
    """Convert Traditional Chinese characters to Simplified Chinese using OpenCC TS table."""
    # Return statement
    return "".join(self.ts_map.get(ch, ch) for ch in str(arg1_text or ""))


  def _to_hant (self, arg1_text):
    """Convert Simplified Chinese characters to Traditional Chinese using OpenCC ST table."""
    # Return statement
    return "".join(self.st_map.get(ch, ch) for ch in str(arg1_text or ""))


  def build_all (self):
    """Build and export all 10 modern local-history reference GeoJSON layers under ./input/gis/modern/."""
    # Declare local instance variables.
    combined_atoms = []
    grid_size = 10.0 ** (-self.precision)
    mng_adm1, mng_adm2 = [], []
    noded_atoms = []
    prc_adm1, prc_adm2, prc_adm3 = [], [], []
    rp = None
    src_prio = {"mng": 1, "prc": 2, "tuva": 0, "twn": 3}
    src_tag = ""
    summary = {}
    tuva_adm1, tuva_adm1_geom, tuva_adm2 = [], None, []
    twn_adm1, twn_adm2, twn_adm3 = [], [], []

    os.makedirs(self.modern_dir, exist_ok=True)
    for fn in (self._build_twn_layers, self._build_prc_layers, self._build_mng_layers, self._build_tuva_layers):
      fn()

    for src_tag, feat_list in (
      ("twn", self.twn_adm3_features),
      ("prc", self.prc_adm3_features),
      ("mng", self.mng_adm2_features),
      ("tuva", self.tuva_adm2_features),
    ):
      for props, geom in feat_list:
        cp = dict(props)
        cp["_src"] = src_tag
        combined_atoms.append((cp, geom))

    noded_atoms = planar_topology_helpers.node_planar_coverage(
      combined_atoms,
      grid_size,
      0.05,
      lambda p, g: (src_prio.get(p.get("_src"), 0), float(g.area)),
    )
    for props, geom in noded_atoms:
      src_tag = str(props.pop("_src", ""))
      if src_tag == "prc":
        rp = geom.representative_point()
        props["seat_lat"] = round(float(rp.y), self.precision)
        props["seat_lon"] = round(float(rp.x), self.precision)
        prc_adm3.append((props, geom))
      elif src_tag == "twn":
        twn_adm3.append((props, geom))
      elif src_tag == "mng":
        mng_adm2.append((props, geom))
      elif src_tag == "tuva":
        tuva_adm2.append((props, geom))

    self.twn_adm3_features = twn_adm3
    self.prc_adm3_features = prc_adm3
    self.mng_adm2_features = mng_adm2
    self.tuva_adm2_features = tuva_adm2

    prc_adm1, prc_adm2 = self._aggregate_prc_layers(prc_adm3)
    twn_adm2 = planar_topology_helpers.aggregate_coverage_by_key(
      twn_adm3,
      lambda p: str(p.get("parent_adm2_id") or ""),
      lambda k, ms: dict(self.twn_adm2_meta_by_id.get(k, {
        "modern_unit_id": k,
        "name_en": ms[0]["parent_adm2"],
        "parent_adm1": ms[0]["parent_adm1"],
        "region": "taiwan",
      })),
      grid_size,
      0.05,
    )
    twn_adm1 = planar_topology_helpers.aggregate_coverage_by_key(
      twn_adm2,
      lambda p: str(p.get("parent_adm1") or ""),
      lambda k, ms: {
        "modern_unit_id": f"twn_adm1_{gis_helpers.slugify_snake(k)}",
        "name_en": k,
        "region": "taiwan",
        "unit_type": "province_or_special_municipality",
      },
      grid_size,
      0.05,
    )
    mng_adm1 = planar_topology_helpers.aggregate_coverage_by_key(
      mng_adm2,
      lambda p: str(p.get("parent_adm1") or ""),
      lambda k, ms: dict(self.mng_adm1_meta_by_name.get(k, {
        "edge_cases": ["mongolia_aimag_national_search"],
        "modern_unit_id": f"mng_adm1_{gis_helpers.slugify_snake(k)}",
        "name_en": k,
        "region": "mongolia",
        "unit_type": "aimag",
      })),
      grid_size,
      0.05,
    )
    tuva_adm1_geom = planar_topology_helpers._pointwise_snap(
      planar_topology_helpers._union_polygons([g for _, g in tuva_adm2], True),
      grid_size,
    )
    tuva_adm1 = [(dict(self.tuva_adm1_meta), tuva_adm1_geom)] if tuva_adm1_geom is not None else []

    for fname, feats in (
      ("twn_adm_1", twn_adm1),
      ("twn_adm_2", twn_adm2),
      ("twn_adm_3", twn_adm3),
      ("prc_adm_1", prc_adm1),
      ("prc_adm_2", prc_adm2),
      ("prc_adm_3", prc_adm3),
      ("mng_adm_1", mng_adm1),
      ("mng_adm_2", mng_adm2),
      ("tuva_adm_1", tuva_adm1),
      ("tuva_adm_2", tuva_adm2),
    ):
      summary[fname] = gis_helpers.write_geojson(os.path.join(self.modern_dir, f"{fname}.geojson"), feats, self.precision)

    # Return statement
    return summary
