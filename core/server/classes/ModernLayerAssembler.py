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
from helpers import gis_helpers, path_helpers


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
    self.modern_dir = path_helpers.resolve_path("input.gis.modern_dir", base_dir)
    self.precision = int(self.cfg.get("coordinate_precision", 5))
    self.st_map = {}
    self.ts_map = {}

    self._download_modern_sources()
    self._load_opencc_maps()

  def _assign_frontier_citas_pieces (self, arg1_citas, arg2_gadm_items):
    """Fill GADM CHN_3 frontier holes (Southern Tibet, Aksai Chin, Heixiazi) from CITAS 1990 polygons.

    @param arg1_citas List of CITAS 1990 dicts with 'gb', 'geom', 'name_zh'.
    @param arg2_gadm_items List of cleaned PRC GADM unit dicts.
    @return Updated arg2_gadm_items with frontier remainder pieces merged into matching counties.
    """
    # Convert from parameters
    citas_list = arg1_citas
    items = arg2_gadm_items

    # Declare local instance variables.
    by_gb = {}
    gadm_union = gis_helpers.clean_polygonal_geometry(unary_union([it["geom"] for it in items]))
    item_tree = STRtree([it["geom"] for it in items])

    for idx, it in enumerate(items):
      if it.get("gb_1990"):
        by_gb[it["gb_1990"]] = idx
      if it.get("gb_code"):
        by_gb[it["gb_code"]] = idx

    for c_rec in citas_list:
      gb = c_rec["gb"]
      if gb.startswith(("71", "81", "82")) or len(gb) != 6:
        continue
      cg = c_rec["geom"]
      if cg is None or cg.is_empty:
        continue
      rem = gis_helpers.clean_polygonal_geometry(cg.difference(gadm_union))
      if rem is None or rem.area <= 0.008:
        continue
      target_idx = by_gb.get(gb)
      if target_idx is None:
        prov2 = gb[:2]
        best_dist = 1e9
        for cand_idx in item_tree.query(rem.buffer(0.5)):
          if items[cand_idx]["gb_code"][:2] != prov2:
            continue
          d_val = items[cand_idx]["geom"].distance(rem)
          if d_val < best_dist:
            best_dist = d_val
            target_idx = cand_idx
      if target_idx is not None:
        merged = gis_helpers.clean_polygonal_geometry(unary_union([items[target_idx]["geom"], rem]))
        if merged is not None:
          items[target_idx]["geom"] = merged
          if "citas_frontier_hole_filled" not in items[target_idx]["edge_cases"]:
            items[target_idx]["edge_cases"].append("citas_frontier_hole_filled")

    # Return statement
    return items

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

    c1 = gis_helpers.write_geojson(os.path.join(self.modern_dir, "mng_adm_1.geojson"), m1_feats, self.precision)
    c2 = gis_helpers.write_geojson(os.path.join(self.modern_dir, "mng_adm_2.geojson"), m2_feats, self.precision)

    # Return statement
    return {"mng_adm_1": c1, "mng_adm_2": c2}

  def _build_prc_layers (self):
    """Build and export ./input/gis/modern/prc_adm_1.geojson, prc_adm_2.geojson, and prc_adm_3.geojson."""
    # Declare local instance variables.
    adm1_buckets = {}
    adm2_buckets = {}
    citas_list = self._load_citas_1990()
    citas_tree = STRtree([c["geom"] for c in citas_list])
    gb_lookup = self._load_gb2260_lookup()
    prc_cfg = self.edge_cases["mainland_prc"]
    raw_chn = self._load_gadm_features(self.cfg["gadm"]["files"]["gadm_chn_3"]["filename"])
    seen_ids = set()
    units = []

    for props, geom in raw_chn:
      n1 = str(props.get("NAME_1") or "").strip()
      n2 = str(props.get("NAME_2") or "").strip()
      n3 = str(props.get("NAME_3") or "").strip()
      nl1 = str(props.get("NL_NAME_1") or "").strip()
      nl2 = str(props.get("NL_NAME_2") or "").strip()
      nl3 = str(props.get("NL_NAME_3") or "").strip()
      t3 = str(props.get("TYPE_3") or "").strip()

      if n1 == "NA":
        n1, n2, n3 = "Hong Kong", "Hong Kong", "Hong Kong"
        nl1, nl2, nl3 = "香港特别行政区", "香港特别行政区", "香港特别行政区"
        t3 = "SAR"
      elif n1 == "Shanghai" and n3 == "Shengsi":
        n1, n2 = "Zhejiang", "Zhoushan"
        nl1, nl2, nl3 = "浙江省", "舟山市", "嵊泗县"

      prov2 = prc_cfg["prc_prov_name_to_gb2"].get(n1, "00")
      # Find best-overlapping CITAS 1990 polygon
      citas_hit = None
      best_ov = 0.0
      for idx in citas_tree.query(geom):
        cg = citas_list[idx]["geom"]
        if not geom.intersects(cg):
          continue
        ov = geom.intersection(cg).area
        if ov > best_ov:
          best_ov = ov
          citas_hit = citas_list[idx]

      gb_1990 = citas_hit["gb"] if citas_hit is not None else ""
      citas_zh = citas_hit["name_zh"] if citas_hit is not None else ""
      citas_en = citas_hit["name_en"] if citas_hit is not None else ""

      name_zh = self._resolve_prc_name_zh(n1, n3, nl3, citas_zh)
      gb_code, official_zh, city_zh = self._resolve_gb2260(prov2, n1, n2, n3, name_zh, gb_1990, gb_lookup)
      if official_zh and not (official_zh.isascii()):
        name_zh = official_zh
      if name_zh.isascii():
        c4 = gb_lookup["cities"].get(gb_code[:4], {}).get("name", "")
        if c4 and c4 not in ("市辖区", "县", "省直辖县级行政区划", "自治区直辖县级行政区划"):
          name_zh = f"{c4}辖区" if not c4.endswith("市") else f"{c4}区"
        elif prov2 in gb_lookup["provs"]:
          name_zh = f"{gb_lookup['provs'][prov2]['name']}辖区"

      name_zh_hant = self._to_hant(name_zh)
      unit_type = self._classify_prc_subtype(n1, t3, name_zh)
      prov_zh = self._resolve_prov_zh(prov2, n1, nl1, gb_lookup)
      if not city_zh or city_zh in ("县", "市辖区"):
        city_zh = self._clean_gadm_zh(nl2) or prov_zh

      uid_base = f"prc_{gb_code}_{gis_helpers.slugify_snake(n3)}"
      uid = uid_base
      if uid in seen_ids:
        uid = f"{uid_base}_{len(seen_ids)}"
      seen_ids.add(uid)

      edges, queries = self._generate_prc_queries(gb_code, n1, n3, name_zh, name_zh_hant, prov_zh, city_zh, unit_type, citas_zh, prc_cfg)
      units.append({
        "edge_cases": edges,
        "gb_code": gb_code,
        "gb_1990": gb_1990,
        "geom": geom,
        "name_en": n3,
        "name_py": str(props.get("VARNAME_3") or n3) if props.get("VARNAME_3") not in (None, "NA") else n3,
        "name_zh": name_zh,
        "name_zh_hant": name_zh_hant,
        "parent_adm1": n1,
        "parent_adm1_gb": f"{prov2}0000",
        "parent_adm1_zh": prov_zh,
        "parent_adm2": n2,
        "parent_adm2_gb": gb_code[:4] + "00",
        "parent_adm2_zh": city_zh,
        "region": "mainland_prc",
        "search_queries": queries,
        "unit_id": uid,
        "unit_type": unit_type,
      })

    units = self._assign_frontier_citas_pieces(citas_list, units)

    adm3_feats = []
    for u in units:
      props_out = {k: v for k, v in u.items() if k not in ("geom", "gb_1990", "unit_id")}
      props_out["modern_unit_id"] = u["unit_id"]
      adm3_feats.append((props_out, u["geom"]))

      p1_key = (u["parent_adm1_gb"], u["parent_adm1"], u["parent_adm1_zh"])
      adm1_buckets.setdefault(p1_key, []).append(u["geom"])
      p2_key = (u["parent_adm1_gb"], u["parent_adm1"], u["parent_adm1_zh"], u["parent_adm2_gb"], u["parent_adm2"], u["parent_adm2_zh"])
      adm2_buckets.setdefault(p2_key, []).append(u["geom"])

    adm2_feats = []
    seen_p2 = set()
    for (p1_gb, p1_en, p1_zh, p2_gb, p2_en, p2_zh), geoms in sorted(adm2_buckets.items()):
      merged = gis_helpers.clean_polygonal_geometry(unary_union(geoms))
      if merged is None:
        continue
      uid2 = f"prc_adm2_{p2_gb}_{gis_helpers.slugify_snake(p2_en)}"
      if uid2 in seen_p2:
        uid2 = f"{uid2}_{len(seen_p2)}"
      seen_p2.add(uid2)
      base2 = p2_zh.rstrip("市地区盟州")
      adm2_feats.append(({
        "gb_code": p2_gb,
        "modern_unit_id": uid2,
        "name_en": p2_en,
        "name_zh": p2_zh,
        "name_zh_hant": self._to_hant(p2_zh),
        "parent_adm1": p1_en,
        "parent_adm1_gb": p1_gb,
        "parent_adm1_zh": p1_zh,
        "region": "mainland_prc",
        "search_queries": [f"{p2_zh}志", f"{base2}地区志", f"{base2}市志·大事记", f"{base2}市志·军事志", f"{base2}地名志"],
        "unit_type": "prefecture_level_unit",
      }, merged))

    adm1_feats = []
    for (p1_gb, p1_en, p1_zh), geoms in sorted(adm1_buckets.items()):
      merged = gis_helpers.clean_polygonal_geometry(unary_union(geoms))
      if merged is None:
        continue
      base1 = p1_zh.replace("特别行政区", "").replace("壮族自治区", "").replace("回族自治区", "").replace("维吾尔自治区", "").replace("自治区", "").rstrip("省市")
      uid1 = f"prc_adm1_{p1_gb}_{gis_helpers.slugify_snake(p1_en)}"
      adm1_feats.append(({
        "gb_code": p1_gb,
        "modern_unit_id": uid1,
        "name_en": p1_en,
        "name_zh": p1_zh,
        "name_zh_hant": self._to_hant(p1_zh),
        "region": "mainland_prc",
        "search_queries": [f"{base1}通志", f"{base1}省志·大事记", f"{base1}省志·军事志", f"{base1}省志·地名志", f"{base1}省志·建置沿革志", f"{base1}省志·公安志", f"{base1}省志·报业志"],
        "unit_type": "province_level_unit",
      }, merged))

    c1 = gis_helpers.write_geojson(os.path.join(self.modern_dir, "prc_adm_1.geojson"), adm1_feats, self.precision)
    c2 = gis_helpers.write_geojson(os.path.join(self.modern_dir, "prc_adm_2.geojson"), adm2_feats, self.precision)
    c3 = gis_helpers.write_geojson(os.path.join(self.modern_dir, "prc_adm_3.geojson"), adm3_feats, self.precision)

    # Return statement
    return {"prc_adm_1": c1, "prc_adm_2": c2, "prc_adm_3": c3}

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

    tuva_adm1_geom = gis_helpers.clean_polygonal_geometry(unary_union([g for _, g in t2_feats]))
    t1_feats = [({
      "edge_cases": ["tuva_tigpi_compendium_pairing"],
      "modern_unit_id": "tuva_adm1_republic_of_tyva",
      "name_en": "Republic of Tyva",
      "name_ru": "Республика Тыва",
      "name_tyv": "Тыва Республика",
      "region": "tuva_republic",
      "search_queries": tigpi_list,
      "unit_type": "republic",
    }, tuva_adm1_geom)]

    c1 = gis_helpers.write_geojson(os.path.join(self.modern_dir, "tuva_adm_1.geojson"), t1_feats, self.precision)
    c2 = gis_helpers.write_geojson(os.path.join(self.modern_dir, "tuva_adm_2.geojson"), t2_feats, self.precision)

    # Return statement
    return {"tuva_adm_1": c1, "tuva_adm_2": c2}

  def _build_twn_layers (self):
    """Build and export ./input/gis/modern/twn_adm_1.geojson, twn_adm_2.geojson, and twn_adm_3.geojson."""
    # Declare local instance variables.
    adm1_buckets = {}
    gb_twn_path = path_helpers.resolve_provider_file(self.cfg, "modern_reference", "tw_townships_geoboundaries", self.base_dir)
    g0v_path = path_helpers.resolve_provider_file(self.cfg, "modern_reference", "tw_townships_g0v", self.base_dir)
    indig_set = set(s.replace("臺", "台") for s in self.edge_cases["taiwan"]["indigenous_mountain_townships"])
    raw_twn2 = self._load_gadm_features(self.cfg["gadm"]["files"]["gadm_twn_2"]["filename"])
    t2_by_zh = {}
    t2_feats = []
    t2_meta = self.edge_cases["taiwan"]["gadm_twn2_metadata"]
    t3_buckets = {}
    t3_feats = []

    for props, geom in raw_twn2:
      n1 = str(props.get("NAME_1") or "").strip()
      n2 = str(props.get("NAME_2") or "").strip()
      meta = t2_meta.get(n2, {})
      canon_en = meta.get("name_en", n2)
      name_zh = meta.get("name_zh", str(props.get("NL_NAME_2") or n2))
      name_zh_hans = self._to_hans(name_zh)
      is_offshore = bool(meta.get("roc_fujian_offshore", False))
      slug = gis_helpers.slugify_snake(canon_en.replace(" County", "").replace(" City", "").replace(" (Matsu)", ""))
      uid2 = f"twn_adm2_{slug}"
      edges = ["prefer_1990_2015_chongxiu", "pair_japanese_colonial_surveys"]
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

      edges = ["prefer_1990_2015_chongxiu", "pair_japanese_colonial_surveys"]
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

    t1_feats = []
    for adm1_name, geoms in sorted(adm1_buckets.items()):
      merged = gis_helpers.clean_polygonal_geometry(unary_union(geoms))
      if merged is None:
        continue
      t1_feats.append(({
        "modern_unit_id": f"twn_adm1_{gis_helpers.slugify_snake(adm1_name)}",
        "name_en": adm1_name,
        "region": "taiwan",
        "unit_type": "province_or_special_municipality",
      }, merged))

    c1 = gis_helpers.write_geojson(os.path.join(self.modern_dir, "twn_adm_1.geojson"), t1_feats, self.precision)
    c2 = gis_helpers.write_geojson(os.path.join(self.modern_dir, "twn_adm_2.geojson"), t2_feats, self.precision)
    c3 = gis_helpers.write_geojson(os.path.join(self.modern_dir, "twn_adm_3.geojson"), t3_feats, self.precision)

    # Return statement
    return {"twn_adm_1": c1, "twn_adm_2": c2, "twn_adm_3": c3}

  def _classify_prc_subtype (self, arg1_prov, arg2_gadm_type, arg3_name_zh):
    """Classify a PRC adm_3 unit into canonical local-history subtype."""
    # Convert from parameters
    gtype = arg2_gadm_type
    name_zh = arg3_name_zh
    prov = arg1_prov

    if prov in ("Hong Kong", "Macau"):
      return "sar_district"
    if name_zh.endswith("林区"):
      return "linqu"
    if name_zh.endswith("特区"):
      return "tequ"
    if name_zh.endswith("自治旗") or gtype == "Zìzhìqí":
      return "autonomous_qi"
    if name_zh.endswith("旗") or gtype == "Qí":
      return "banner_qi"
    if name_zh.endswith("自治县") or gtype == "Zìzhìxiàn":
      return "autonomous_xian"
    if name_zh.endswith("区") or gtype in ("Shìxiáqū", "Xīnqū", "Zhíxiáshì"):
      return "urban_qu"
    if name_zh.endswith("市") or gtype == "Xiànjíshì":
      return "county_level_shi"

    # Return statement
    return "xian"

  def _clean_gadm_zh (self, arg1_raw):
    """Extract primary Simplified Chinese string from GADM NL_NAME fields."""
    # Convert from parameters
    raw = str(arg1_raw or "").strip()

    if raw in ("", "NA"):
      return ""
    parts = [p.strip() for p in raw.split("|") if p.strip() and p.strip() != "NA"]
    if not parts:
      return ""

    # Return statement
    return self._to_hans(parts[-1])

  def _download_modern_sources (self):
    """Ensure all modern reference sources configured in data_sources.json5 are cached locally."""
    for key, meta in self.cfg.get("modern_reference", {}).get("files", {}).items():
      dest = path_helpers.resolve_provider_file(self.cfg, "modern_reference", key, self.base_dir)
      ok = gis_helpers.download_with_cache(meta["url"], dest)
      if not ok:
        print(f"[WARN] Failed to cache modern_reference source {key}: {meta['url']}", file=sys.stderr)

  def _generate_prc_queries (self, arg1_gb, arg2_n1, arg3_n3, arg4_name_zh, arg5_hant, arg6_prov_zh, arg7_city_zh, arg8_utype, arg9_citas_zh, arg10_cfg):
    """Build edge_cases flags and candidate gazetteer/dimingzhi search queries for a PRC adm_3 unit."""
    # Convert from parameters
    cfg = arg10_cfg
    citas_zh = arg9_citas_zh
    city_zh = arg7_city_zh
    gb = arg1_gb
    n1 = arg2_n1
    n3 = arg3_n3
    name_zh = arg4_name_zh
    name_hant = arg5_hant
    prov_zh = arg6_prov_zh
    utype = arg8_utype

    # Declare local instance variables.
    base_name = name_zh
    edges = []
    queries = []
    renamings = cfg["post_1953_renamings"]

    def _add_q (arg1_q):
      q_str = str(arg1_q or "").strip()
      if q_str and q_str not in queries:
        queries.append(q_str)

    if gb == "810000":
      edges.append("hong_kong_sar")
      for q in cfg["hong_kong_and_macau"]["810000"]["search_queries"]:
        _add_q(q)
      return edges, queries

    if gb.startswith("82"):
      edges.append("macau_sar")
      for q in cfg["hong_kong_and_macau"]["820000"]["search_queries"]:
        _add_q(q)
      return edges, queries

    if gb == "350122":
      edges.append("mainland_fuzhou_lianjiang_disambig")

    if utype in ("autonomous_xian", "autonomous_qi"):
      edges.append("autonomous_suffix_strip")
      stem = name_zh
      for sfx in ("自治县", "自治旗"):
        if stem.endswith(sfx):
          stem = stem[:-len(sfx)]
      for tok in cfg["autonomous_ethnicity_tokens"]:
        if stem.endswith(tok) and len(stem) > len(tok):
          stem = stem[:-len(tok)]
          break
      base_name = stem
      tail = "旗志" if utype == "autonomous_qi" else "县志"
      _add_q(f"{base_name}{tail}")
      _add_q(f"{name_zh}志")
    else:
      for sfx in ("自治县", "自治旗", "林区", "特区", "市", "区", "县", "旗"):
        if base_name.endswith(sfx) and len(base_name) > len(sfx):
          base_name = base_name[:-len(sfx)]
          break
      if utype == "county_level_shi":
        edges.append("che_xian_she_shi")
        _add_q(f"{base_name}县志")
        _add_q(f"{name_zh}志")
      elif utype == "urban_qu":
        edges.append("che_xian_she_qu")
        _add_q(f"{name_zh}志")
        _add_q(f"{base_name}区志")
        _add_q(f"{base_name}县志")
      else:
        _add_q(f"{name_zh}志")

    if base_name in renamings:
      edges.append("post_1953_renaming")
      for old_name in renamings[base_name]:
        _add_q(f"{old_name}志" if not old_name.endswith("志") else old_name)

    for metro_key, m_info in cfg["metropolitan_core_districts"].items():
      if gb.startswith(m_info["gb_prefix"]) or n1 == metro_key or n3 == metro_key:
        if utype == "urban_qu":
          if "metropolitan_core_district" not in edges:
            edges.append("metropolitan_core_district")
          if "big_city_fenzhi" not in edges:
            edges.append("big_city_fenzhi")
          for h_cnty in m_info["historic_counties"]:
            _add_q(f"{h_cnty}志" if not h_cnty.endswith("志") else h_cnty)
          for fz in m_info["fenzhi_suffixes"]:
            _add_q(f"{m_info['city_zh']}{fz}")

    if city_zh and city_zh != name_zh and city_zh != prov_zh:
      if utype == "urban_qu" and "big_city_fenzhi" not in edges:
        edges.append("big_city_fenzhi")
        city_stem = city_zh.rstrip("市")
        _add_q(f"{city_stem}市志")
        _add_q(f"{city_stem}市志·大事记")
        _add_q(f"{city_stem}市志·军事志")
        _add_q(f"{city_stem}市志·地名志")

    if citas_zh and citas_zh != name_zh and "市轄區" not in citas_zh:
      c_hans = self._to_hans(citas_zh).split(" ")[-1]
      if c_hans and c_hans not in base_name:
        _add_q(f"{c_hans}县志" if not c_hans.endswith(("县", "市", "旗", "区")) else f"{c_hans}志")

    edges.append("dimingzhi_check")
    _add_q(f"{name_zh}地名志")
    if name_hant != name_zh:
      _add_q(f"{name_hant}志")

    # Return statement
    return edges, queries

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

  def _load_gb2260_lookup (self):
    """Load modood/Administrative-divisions-of-China GB/T 2260 lookup indices."""
    # Declare local instance variables.
    areas_by_code = {}
    by_prov_stem = {}
    cities_by_code = {}
    provs_by_code = {}

    for fname, target in (("gb2260_provinces", provs_by_code), ("gb2260_cities", cities_by_code), ("gb2260_areas", areas_by_code)):
      p = path_helpers.resolve_provider_file(self.cfg, "modern_reference", fname, self.base_dir)
      with open(p, "r", encoding="utf-8") as fh:
        rows = json.load(fh)
      for r in rows:
        target[r["code"]] = r

    for code, r in areas_by_code.items():
      prov2, nm = r["provinceCode"], r["name"]
      by_prov_stem.setdefault((prov2, nm), []).append(r)
      by_prov_stem.setdefault((prov2, self._strip_zh_suffix(nm)), []).append(r)

    # Return statement
    return {"areas": areas_by_code, "by_prov_stem": by_prov_stem, "cities": cities_by_code, "provs": provs_by_code}


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


  def _resolve_gb2260 (self, arg1_prov2, arg2_n1, arg3_n2, arg4_n3, arg5_name_zh, arg6_gb1990, arg7_lookup):
    """Resolve modern 6-digit GB/T 2260 code, official Chinese name, and city name."""
    # Convert from parameters
    gb1990, lookup, n1, n2, n3, name_zh, prov2 = arg6_gb1990, arg7_lookup, arg2_n1, arg3_n2, arg4_n3, arg5_name_zh, arg1_prov2

    if n1 == "Hong Kong":
      return "810000", "香港特别行政区", "香港特别行政区"
    if n1 == "Macau":
      zh_m, code_m = self.edge_cases["mainland_prc"]["hong_kong_and_macau"]["820000"]["parishes"].get(n3, [n3, "820000"])
      return code_m, zh_m, "澳门特别行政区"

    areas, by_stem, cities = lookup["areas"], lookup["by_prov_stem"], lookup["cities"]

    def _fmt (arg1_row):
      c_zh = cities.get(arg1_row["cityCode"], {}).get("name", "")
      if c_zh in ("市辖区", "省直辖县级行政区划", "自治区直辖县级行政区划"):
        c_zh = lookup["provs"].get(prov2, {}).get("name", "")
      return arg1_row["code"], arg1_row["name"], c_zh

    cands = by_stem.get((prov2, name_zh)) or by_stem.get((prov2, self._strip_zh_suffix(name_zh))) or []
    if len(cands) == 1:
      return _fmt(cands[0])
    if gb1990 in areas:
      return _fmt(areas[gb1990])
    if len(cands) > 1:
      for r in cands:
        if r["name"] == name_zh:
          return _fmt(r)
      return _fmt(cands[0])

    # Return statement
    return (gb1990 if len(gb1990) == 6 else f"{prov2}0000"), name_zh, ""


  def _resolve_prc_name_zh (self, arg1_n1, arg2_n3, arg3_nl3, arg4_citas_zh):
    """Resolve cleanest Simplified Chinese county/district name from GADM NL_NAME_3 and CITAS."""
    # Convert from parameters
    citas_zh, n1, n3, nl3 = arg4_citas_zh, arg1_n1, arg2_n3, arg3_nl3

    cleaned_nl3 = self._clean_gadm_zh(nl3)
    if cleaned_nl3:
      return cleaned_nl3
    if citas_zh:
      c_hans = self._to_hans(citas_zh).strip().split(" ")[-1].strip()
      if c_hans and "辖区" not in c_hans:
        return c_hans
    if n1 == "Macau":
      parishes = self.edge_cases["mainland_prc"]["hong_kong_and_macau"]["820000"]["parishes"]
      if n3 in parishes:
        return parishes[n3][0]

    # Return statement
    return n3


  def _resolve_prov_zh (self, arg1_prov2, arg2_n1, arg3_nl1, arg4_lookup):
    """Resolve official Simplified Chinese provincial name."""
    # Convert from parameters
    lookup, n1, nl1, prov2 = arg4_lookup, arg2_n1, arg3_nl1, arg1_prov2

    if n1 == "Hong Kong":
      return "香港特别行政区"
    if n1 == "Macau":
      return "澳门特别行政区"
    if prov2 in lookup["provs"]:
      return lookup["provs"][prov2]["name"]

    # Return statement
    return self._clean_gadm_zh(nl1) or n1


  def _strip_zh_suffix (self, arg1_name):
    """Strip standard Chinese county/district administrative suffix to yield the base stem."""
    # Convert from parameters
    stem = str(arg1_name or "")

    for sfx in ("自治县", "自治旗", "林区", "特区", "市", "区", "县", "旗"):
      if stem.endswith(sfx) and len(stem) > len(sfx):
        return stem[:-len(sfx)]

    # Return statement
    return stem


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
    os.makedirs(self.modern_dir, exist_ok=True)
    summary = {}
    for fn in (self._build_prc_layers, self._build_twn_layers, self._build_mng_layers, self._build_tuva_layers):
      summary.update(fn())

    # Return statement
    return summary
