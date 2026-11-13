"""Step 6 modern PRC, Taiwan, Mongolia, and Tuva GIS crosswalk and raster audit pipeline."""

import hashlib
import json
import os
import re
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely import STRtree
from shapely.geometry import Point, shape

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)
from classes.ModernLayerAssembler import ModernLayerAssembler
from classes.ScanlineRasteriser import ScanlineRasteriser
from helpers import gis_helpers, path_helpers


class ModernGisCrosswalkBuilder:
  """Intersects 1912-1953 CHGIS/Tusi layers with modern local-history layers and exports crosswalk + audit PNGs."""

  def __init__ (self, arg1_base_dir):
    """Initialise paths, configurations, and lookup structures.

    @param arg1_base_dir Project root directory.
    """
    # Convert from parameters
    base_dir = os.path.abspath(arg1_base_dir)

    # Declare local instance variables.
    self.adm_annual_dir = path_helpers.resolve_path("output.gis.adm_annual_dir", base_dir)
    self.base_dir = base_dir
    self.cfg = gis_helpers.load_json5(path_helpers.resolve_path("common.data_sources", base_dir))
    self.defines = gis_helpers.load_json5(path_helpers.resolve_path("common.province_defines", base_dir))
    self.edge_cases = gis_helpers.load_json5(path_helpers.resolve_path("common.local_history_edge_cases", base_dir))
    self.layers_dir = path_helpers.resolve_path("output.gis.layers_dir", base_dir)
    self.modern_dir = path_helpers.resolve_path("input.gis.modern_dir", base_dir)
    self.precision = int(self.cfg.get("coordinate_precision", 5))
    self.tests_outputs_dir = path_helpers.resolve_path("tests.outputs_dir", base_dir)
    self.tusi_catalog = gis_helpers.load_json5(path_helpers.resolve_path("common.tusi_catalog", base_dir))

  def _build_twn_zh_to_slug (self):
    """Build Traditional and Simplified Chinese Taiwan county/city name to ASCII slug map."""
    # Declare local instance variables.
    out = {}
    t2_meta = self.edge_cases["taiwan"]["gadm_twn2_metadata"]

    for gadm_key, meta in t2_meta.items():
      slug = gis_helpers.slugify_snake(meta["name_en"].replace(" County", "").replace(" City", "").replace(" (Matsu)", ""))
      n_zh = meta["name_zh"]
      out[n_zh] = slug
      out[n_zh.replace("臺", "台")] = slug
      out[n_zh.rstrip("縣市")] = slug
      out[n_zh.replace("臺", "台").rstrip("縣市")] = slug
      out[gadm_key] = slug
      out[meta["name_en"]] = slug

    # Return statement
    return out

  def _canonical_hist_ids (self, arg1_props, arg2_twn_map):
    """Resolve canonical (province_slug, county_slug, sys_id) for an adm_3 feature.

    @param arg1_props Feature properties dictionary from adm_3_<year>.geojson.
    @param arg2_twn_map Mapping of Taiwan Chinese/English names to ASCII slugs.
    @return Tuple (province_slug, county_slug, sys_id_str).
    """
    # Convert from parameters
    props = arg1_props
    twn_map = arg2_twn_map

    # Declare local instance variables.
    cat = str(props.get("category") or "").strip()
    disambig = self.edge_cases["chgis_homophone_disambiguation"]
    name_ch = str(props.get("name_ch") or "").strip()
    name_en = str(props.get("name_en") or "").strip()
    p1 = str(props.get("parent_adm1") or "").strip()
    sys_id = ""
    uid = str(props.get("unit_id") or "").strip()

    if cat == "tusi" and uid.startswith("tusi_"):
      tslug = gis_helpers.slugify_snake(uid[5:])
      return tslug, tslug, ""

    prov_slug = gis_helpers.slugify_snake(p1)
    if "_twn_" in uid:
      c_slug = twn_map.get(name_en) or twn_map.get(name_ch) or gis_helpers.slugify_snake(name_en)
      return prov_slug, c_slug, ""

    m_sys = re.search(r"_(\d{5,7})_\d{4}$", uid)
    if m_sys:
      sys_id = m_sys.group(1)
      if sys_id in disambig:
        return prov_slug, disambig[sys_id], sys_id

    c_slug = gis_helpers.slugify_snake(name_en)

    # Return statement
    return prov_slug, c_slug, sys_id

  def _collect_historical_geometries (self):
    """Scan adm_3_1912..1953 and tusi_1912_1953 to collect deduplicated geometries and seat points."""
    # Declare local instance variables.
    hist_units = {}
    seats_by_sysid, seats_by_name = self._load_1911_seat_points()
    tusi_seats = {}
    twn_map = self._build_twn_zh_to_slug()
    unique_geoms = {}

    for t_entry in self.tusi_catalog.get("tusis", []):
      tid = str(t_entry.get("tusi_id") or "").strip()
      slon = t_entry.get("seat_lon")
      slat = t_entry.get("seat_lat")
      if tid and slon is not None and slat is not None:
        tusi_seats[tid] = Point(float(slon), float(slat))

    for year in range(1911, 1954):
      path = os.path.join(self.adm_annual_dir, f"adm_3_{year}.geojson")
      if not os.path.exists(path):
        continue
      with open(path, "r", encoding="utf-8") as fh:
        feats = json.load(fh).get("features", [])
      for ft in feats:
        props = ft.get("properties", {})
        geom_dict = ft.get("geometry")
        if not geom_dict:
          continue
        g_key = hashlib.sha1(json.dumps(geom_dict, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
        if g_key not in unique_geoms:
          g = gis_helpers.clean_polygonal_geometry(shape(geom_dict))
          if g is None or g.is_empty:
            continue
          unique_geoms[g_key] = g
        p_slug, c_slug, sys_id = self._canonical_hist_ids(props, twn_map)
        u_key = (p_slug, c_slug)
        if u_key not in hist_units:
          seat_pt = None
          if str(props.get("category") or "") == "tusi":
            seat_pt = tusi_seats.get(c_slug)
          elif sys_id and sys_id in seats_by_sysid:
            seat_pt = seats_by_sysid[sys_id]
          else:
            seat_pt = seats_by_name.get((p_slug, c_slug))
          hist_units[u_key] = {
            "category": str(props.get("category") or "province"),
            "county_slug": c_slug,
            "geom_keys": set(),
            "name_ch": str(props.get("name_ch") or ""),
            "name_en": str(props.get("name_en") or ""),
            "province_slug": p_slug,
            "seat_pt": seat_pt,
          }
        hist_units[u_key]["geom_keys"].add(g_key)

    # Ensure all 425 Tusis in tusi_1912_1953.geojson are included even if inactive in adm_3
    tusi_geo_path = path_helpers.resolve_path("output.gis.tusi", self.base_dir)
    if os.path.exists(tusi_geo_path):
      with open(tusi_geo_path, "r", encoding="utf-8") as fh:
        t_feats = json.load(fh).get("features", [])
      for ft in t_feats:
        props = ft.get("properties", {})
        tid = gis_helpers.slugify_snake(props.get("tusi_id") or "")
        if not tid:
          continue
        geom_dict = ft.get("geometry")
        if not geom_dict:
          continue
        g_key = hashlib.sha1(json.dumps(geom_dict, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
        if g_key not in unique_geoms:
          g = gis_helpers.clean_polygonal_geometry(shape(geom_dict))
          if g is not None and not g.is_empty:
            unique_geoms[g_key] = g
        if g_key in unique_geoms:
          u_key = (tid, tid)
          if u_key not in hist_units:
            hist_units[u_key] = {
              "category": "tusi",
              "county_slug": tid,
              "geom_keys": {g_key},
              "name_ch": str(props.get("name_zh") or ""),
              "name_en": str(props.get("name_en") or tid),
              "province_slug": tid,
              "seat_pt": tusi_seats.get(tid),
            }
          else:
            hist_units[u_key]["geom_keys"].add(g_key)

    # Return statement
    return unique_geoms, hist_units

  def _load_1911_seat_points (self):
    """Extract historical county seat points from v6_1911_cnty_pgn_utf.zip."""
    # Declare local instance variables.
    by_name = {}
    by_sysid = {}
    c_path = path_helpers.resolve_provider_file(self.cfg, "chgis_dataverse", "chgis_1911_cnty", self.base_dir)
    raw = gis_helpers.read_zip_shapefile_wgs84(c_path, "utf-8", self.precision)

    for rec, _ in raw:
      xc = rec.get("X_COORD")
      yc = rec.get("Y_COORD")
      if xc in (None, "", 0) or yc in (None, "", 0):
        continue
      xf = float(xc)
      yf = float(yc)
      if abs(xf) > 360.0:
        lon, lat = gis_helpers.gk19_array_to_lonlat([[xf, yf]])[0]
      else:
        lon, lat = xf, yf
      pt = Point(lon, lat)
      sid = str(rec.get("SYS_ID") or "").strip()
      if sid:
        by_sysid[sid] = pt
      l1 = gis_helpers.normalise_lev1_name(rec.get("LEV1_PY"), rec.get("LEV1_CH"))
      by_name[(gis_helpers.slugify_snake(l1), gis_helpers.slugify_snake(rec.get("NAME_PY")))] = pt

    # Return statement
    return by_sysid, by_name

  def _load_modern_crosswalk_index (self):
    """Load modern local-history polygon layers (prc_adm_3, twn_adm_2/3, mng_adm_1/2, tuva_adm_2)."""
    # Declare local instance variables.
    files = [
      ("prc_adm_3.geojson", "mainland_prc", 3),
      ("twn_adm_2.geojson", "taiwan", 2),
      ("twn_adm_3.geojson", "taiwan", 3),
      ("mng_adm_1.geojson", "mongolia", 1),
      ("mng_adm_2.geojson", "mongolia", 2),
      ("tuva_adm_2.geojson", "tuva_republic", 2),
    ]
    mod_items = []

    for fname, region, lvl in files:
      path = os.path.join(self.modern_dir, fname)
      with open(path, "r", encoding="utf-8") as fh:
        feats = json.load(fh).get("features", [])
      for ft in feats:
        props = ft.get("properties", {})
        g = gis_helpers.clean_polygonal_geometry(shape(ft["geometry"]))
        if g is None or g.is_empty:
          continue
        mod_items.append({
          "adm_level": lvl,
          "area": max(g.area, 1e-12),
          "edge_cases": list(props.get("edge_cases") or []),
          "gb_code": str(props.get("gb_code") or ""),
          "geom": g,
          "modern_unit_id": str(props.get("modern_unit_id") or ""),
          "name_en": str(props.get("name_en") or ""),
          "name_zh": str(props.get("name_zh") or props.get("name_mn_cyrl") or props.get("name_ru") or ""),
          "region": str(props.get("region") or region),
          "search_queries": list(props.get("search_queries") or []),
          "unit_type": str(props.get("unit_type") or ""),
        })

    # Return statement
    return mod_items

  def _rasterise_modern_level (self, arg1_rasteriser, arg2_layer_files, arg3_level, arg4_png_path, arg5_tusi_geoms):
    """Rasterise combined modern layers for a given administrative level into ./tests/PRC_modern_adm_<level>.png."""
    # Convert from parameters
    layer_files = arg2_layer_files
    level = int(arg3_level)
    png_path = arg4_png_path
    rasteriser = arg1_rasteriser
    tusi_geoms = arg5_tusi_geoms

    # Declare local instance variables.
    all_borders = []
    ocean_rgb = tuple(rasteriser.palette.get("ocean_rgb", [224, 235, 245]))
    fb = np.full((rasteriser.height, rasteriser.width, 3), ocean_rgb, dtype=np.uint8)
    prov_buf = np.zeros((rasteriser.height, rasteriser.width), dtype=np.int32)
    prov_ids = {}
    total_units = 0
    tusi_borders = []

    for fname, country_lbl in layer_files:
      path = os.path.join(self.modern_dir, fname)
      with open(path, "r", encoding="utf-8") as fh:
        feats = json.load(fh).get("features", [])
      total_units += len(feats)
      for ft in feats:
        props = dict(ft.get("properties", {}))
        geom_dict = ft.get("geometry")
        if not geom_dict:
          continue
        if fname.startswith("twn_") and not props.get("parent_adm1") and props.get("name_en") != "Fujian":
          props["parent_adm1"] = "Taiwan"
        props["country"] = country_lbl
        props["unit_id"] = props.get("modern_unit_id") or props.get("name_en")
        props["occupied_by"] = ""
        prov_key = str(props.get("parent_adm1") or props.get("name_en") or "unknown")
        pkey = (country_lbl, prov_key)
        if pkey not in prov_ids:
          prov_ids[pkey] = len(prov_ids) + 1
        pid = prov_ids[pkey]
        (sy, sx0, sx1), blines = rasteriser._get_cached_spans(geom_dict)
        col = rasteriser._colour_for_feature(props)
        for i in range(len(sy)):
          y = int(sy[i])
          x0 = int(sx0[i])
          x1 = int(sx1[i])
          fb[y, x0:x1] = col
          prov_buf[y, x0:x1] = pid
        all_borders.extend(blines)

    if level in (1, 2):
      for g_dict in tusi_geoms:
        _, blines = rasteriser._get_cached_spans(g_dict)
        tusi_borders.extend(blines)

    img = Image.fromarray(fb, mode="RGB")
    draw = ImageDraw.Draw(img)
    border_col = tuple(rasteriser.palette.get("county_border_rgb" if level == 3 else "admin_border_rgb", [96, 88, 78] if level == 3 else [52, 48, 44]))
    for pts in all_borders:
      if len(pts) >= 2:
        draw.line(pts, fill=border_col, width=1)
    fb = rasteriser.draw_provincial_boundaries(np.asarray(img, dtype=np.uint8).copy(), prov_buf)
    img = Image.fromarray(fb, mode="RGB")
    draw = ImageDraw.Draw(img)
    feud_border = tuple(rasteriser.palette.get("feudatory_border_rgb", [150, 32, 24]))
    for pts in tusi_borders:
      if len(pts) >= 2:
        draw.line(pts, fill=feud_border, width=1)

    draw.rectangle([0, 0, rasteriser.width, 44], fill=(28, 34, 46))
    draw.rectangle([0, rasteriser.height - 34, rasteriser.width, rasteriser.height], fill=(28, 34, 46))
    font = ImageFont.load_default()
    title = f"Modern Local-History Reference Layer  |  Admin Level {level}  |  Units: {total_units}"
    draw.text((18, 15), title, fill=(242, 245, 248), font=font)

    legend_items = [
      ((226, 204, 156), "Mainland PRC & Taiwan"),
      (tuple(rasteriser.palette.get("mongolia_base_rgb", [118, 176, 214])), "Mongolia (Aimags / Soums)"),
      (tuple(rasteriser.palette.get("tuva_base_rgb", [168, 146, 204])), "Tuvan Republic (Kozhuuns)"),
      (feud_border, "1911-1953 Feudatories Outlines (Ref.)"),
    ]
    lx = 18
    ly = rasteriser.height - 23
    for lcol, ltxt in legend_items:
      draw.rectangle([lx, ly, lx + 14, ly + 12], fill=lcol, outline=(220, 220, 220))
      draw.text((lx + 20, ly), ltxt, fill=(230, 234, 240), font=font)
      lx += 320

    os.makedirs(os.path.dirname(png_path), exist_ok=True)
    img.save(png_path, format="PNG", optimize=False)

    # Return statement
    return total_units

  def _write_json5 (self, arg1_path, arg2_header, arg3_payload):
    """Write formatted JSON5 payload with leading // header and 2-space indentation."""
    # Convert from parameters
    header = str(arg2_header).strip()
    out_path = str(arg1_path)
    payload = arg3_payload

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    body = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    with open(out_path, "w", encoding="utf-8") as fh:
      fh.write(f"// {header}\n")
      fh.write(body)
      fh.write("\n")

  def build_crosswalk_and_rasters (self):
    """Assemble modern layers, intersect with 1912-1953 polygons, write crosswalk, and render PNG audits."""
    # 1. Build ./input/gis/modern/ GeoJSONs
    layer_counts = ModernLayerAssembler(self.base_dir).build_all()

    # 2. Load historical geometries and modern local-history index
    unique_geoms, hist_units = self._collect_historical_geometries()
    mod_items = self._load_modern_crosswalk_index()
    mod_geoms = [it["geom"] for it in mod_items]
    mod_tree = STRtree(mod_geoms)
    min_ratio = float(self.edge_cases["overlap_thresholds"]["min_area_overlap_ratio"])

    # 3. Precompute intersections once per unique historical atomic geometry
    geom_overlaps = {}
    for g_key, h_geom in unique_geoms.items():
      h_area = max(h_geom.area, 1e-12)
      hits = {}
      best_fallback = None
      best_inter = -1.0
      for idx in mod_tree.query(h_geom):
        m_it = mod_items[idx]
        m_geom = m_it["geom"]
        if not h_geom.intersects(m_geom):
          continue
        inter_area = h_geom.intersection(m_geom).area
        if inter_area <= 0.0:
          continue
        if inter_area > best_inter:
          best_inter = inter_area
          best_fallback = idx
        r_hist = inter_area / h_area
        r_mod = inter_area / m_it["area"]
        if r_hist >= min_ratio or r_mod >= min_ratio:
          hits[idx] = inter_area
      if not hits and best_fallback is not None:
        hits[best_fallback] = max(best_inter, 1e-9)
      elif not hits:
        # Nearest modern unit fallback if coastal island sliver misses slightly
        nearest_idx = int(mod_tree.nearest(h_geom))
        hits[nearest_idx] = 1e-9
      geom_overlaps[g_key] = (h_area, hits)

    # 4. Aggregate overlaps per (province_slug, county_slug) and build bidirectional tables
    by_hist_prov = {p_slug: {} for p_slug in sorted(self.defines.get("provinces", {}).keys())}
    by_mod_unit = {}
    by_tusi = {}
    unmatched_hist = 0

    for m_it in mod_items:
      by_mod_unit[m_it["modern_unit_id"]] = {
        "covered_historical_adm3": set(),
        "covered_provinces": set(),
        "covered_tusis": set(),
        "edge_cases": list(m_it["edge_cases"]),
        "gb_code": m_it["gb_code"],
        "name_en": m_it["name_en"],
        "name_zh": m_it["name_zh"],
        "region": m_it["region"],
        "search_queries": list(m_it["search_queries"]),
        "unit_type": m_it["unit_type"],
      }

    for (_, _), hu in sorted(hist_units.items()):
      p_slug = hu["province_slug"]
      c_slug = hu["county_slug"]
      seat_pt = hu["seat_pt"]
      total_h_area = 0.0
      agg_inter = {}

      for g_key in hu["geom_keys"]:
        h_area, hits = geom_overlaps[g_key]
        total_h_area += h_area
        for idx, i_area in hits.items():
          agg_inter[idx] = agg_inter.get(idx, 0.0) + i_area

      if seat_pt is not None:
        for idx in mod_tree.query(seat_pt):
          if mod_geoms[idx].contains(seat_pt) and idx not in agg_inter:
            agg_inter[idx] = 1e-9

      # Filter combined overlaps to >= min_ratio or seat containment (retaining best fallback if none pass)
      kept = []
      best_any = None
      best_any_area = -1.0
      for idx, i_area in agg_inter.items():
        m_it = mod_items[idx]
        m_geom = m_it["geom"]
        has_seat = bool(seat_pt is not None and m_geom.contains(seat_pt))
        r_hist = min(1.0, i_area / max(total_h_area, 1e-12))
        r_mod = min(1.0, i_area / m_it["area"])
        if i_area > best_any_area:
          best_any_area = i_area
          best_any = (idx, r_hist, has_seat)
        if r_hist >= min_ratio or r_mod >= min_ratio or has_seat:
          kept.append((idx, r_hist, has_seat, False))

      if not kept and best_any is not None:
        kept.append((best_any[0], best_any[1], best_any[2], True))

      if not kept:
        unmatched_hist += 1
        continue

      # Detect frontier subdivision (historical unit split across >= 2 modern PRC counties or >= 2 top-level modern units)
      prc_count = sum(1 for idx, _, _, _ in kept if mod_items[idx]["region"] == "mainland_prc")
      twn2_count = sum(1 for idx, _, _, _ in kept if mod_items[idx]["region"] == "taiwan" and mod_items[idx]["adm_level"] == 2)
      tuva_count = sum(1 for idx, _, _, _ in kept if mod_items[idx]["region"] == "tuva_republic")
      is_frontier_split = (prc_count >= 2) or (twn2_count >= 2) or (tuva_count >= 2)

      entries = []
      for idx, r_hist, has_seat, is_fb in kept:
        m_it = mod_items[idx]
        e_flags = list(m_it["edge_cases"])
        if is_frontier_split and "frontier_subdivision" not in e_flags:
          e_flags.append("frontier_subdivision")
        if is_fb and "fallback_nearest_match" not in e_flags:
          e_flags.append("fallback_nearest_match")
        entries.append({
          "area_overlap_ratio": round(r_hist, 4),
          "contains_historical_seat": has_seat,
          "edge_cases": e_flags,
          "modern_unit_id": m_it["modern_unit_id"],
          "search_queries": list(m_it["search_queries"]),
          "unit_type": m_it["unit_type"],
        })

        bm = by_mod_unit[m_it["modern_unit_id"]]
        bm["covered_provinces"].add(p_slug)
        if hu["category"] == "tusi":
          bm["covered_tusis"].add(c_slug)
        else:
          bm["covered_historical_adm3"].add(c_slug)

      entries.sort(key=lambda x: (-x["area_overlap_ratio"], x["modern_unit_id"]))
      by_hist_prov.setdefault(p_slug, {})[c_slug] = entries
      if hu["category"] == "tusi":
        by_tusi[c_slug] = entries

    for bm in by_mod_unit.values():
      bm["covered_historical_adm3"] = sorted(bm["covered_historical_adm3"])
      bm["covered_provinces"] = sorted(bm["covered_provinces"])
      bm["covered_tusis"] = sorted(bm["covered_tusis"])

    crosswalk_payload = {
      "by_historical_province": by_hist_prov,
      "by_modern_unit": by_mod_unit,
      "by_tusi": by_tusi,
      "schema_version": 1,
      "summary": {
        "historical_county_pairs": len(hist_units),
        "historical_provinces_and_tusis": len(by_hist_prov),
        "modern_units_indexed": len(by_mod_unit),
        "tusis_mapped": len(by_tusi),
        "unmatched_historical_units": unmatched_hist,
      },
    }
    crosswalk_path = path_helpers.resolve_path("common.modern_gazetteer_crosswalk", self.base_dir)
    self._write_json5(
      crosswalk_path,
      "Bidirectional spatial crosswalk from 1912-1953 historical divisions and Tusis to modern local-history units.",
      crosswalk_payload,
    )

    # 5. Rasterise ./tests/PRC_modern_adm_<1|2|3>.png (retained for user visual inspection)
    tusi_geoms = []
    tusi_geo_path = path_helpers.resolve_path("output.gis.tusi", self.base_dir)
    if os.path.exists(tusi_geo_path):
      with open(tusi_geo_path, "r", encoding="utf-8") as fh:
        tusi_geoms = [ft["geometry"] for ft in json.load(fh).get("features", []) if ft.get("geometry")]

    rasteriser = ScanlineRasteriser(self.cfg)
    level_specs = [
      (1, [("prc_adm_1.geojson", "China (PRC)"), ("twn_adm_1.geojson", "Taiwan"), ("mng_adm_1.geojson", "Mongolia"), ("tuva_adm_1.geojson", "Tuva")]),
      (2, [("prc_adm_2.geojson", "China (PRC)"), ("twn_adm_2.geojson", "Taiwan"), ("mng_adm_2.geojson", "Mongolia"), ("tuva_adm_2.geojson", "Tuva")]),
      (3, [("prc_adm_3.geojson", "China (PRC)"), ("twn_adm_3.geojson", "Taiwan"), ("mng_adm_2.geojson", "Mongolia"), ("tuva_adm_2.geojson", "Tuva")]),
    ]
    png_counts = {}
    for lvl, files_spec in level_specs:
      png_out = os.path.join(self.tests_outputs_dir, f"PRC_modern_adm_{lvl}.png")
      png_counts[f"PRC_modern_adm_{lvl}.png"] = self._rasterise_modern_level(rasteriser, files_spec, lvl, png_out, tusi_geoms)

    # Return statement
    return {
      "crosswalk_path": crosswalk_path,
      "modern_layers": layer_counts,
      "raster_units": png_counts,
      "summary": crosswalk_payload["summary"],
    }
