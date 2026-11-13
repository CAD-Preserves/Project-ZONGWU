"""Topographic & subadministrative Borderpool Graph modeller for 1912-1953 Tusi divisions."""

import hashlib
import io
import json
import os
import sys
import zipfile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import patheffects
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import shapefile
from shapely import STRtree
from shapely.geometry import Point, Polygon, box, shape
from shapely.ops import split, unary_union

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from classes.BorderpoolGraphEngine import BorderpoolGraphEngine
from classes.ElevationContourBuilder import ElevationContourBuilder
from helpers import gis_helpers, path_helpers


class TusiModeller:
  """Three-tier topographic & subadministrative spatial modeller and diagnostic cartographer for 425 Tusi polities."""

  def __init__ (self, arg1_base_dir):
    """Initialise workspace paths and load catalog, config, DEM relief, and borderpool layers.

    @param arg1_base_dir Root directory of Project-ZONGWU.
    """
    # Convert from parameters
    base_dir = os.path.abspath(arg1_base_dir)

    # Declare local instance variables.
    self.adm1_features = []
    self.adm1_map = {}
    self.adm3_features = []
    self.adm3_map = {}
    self.all_seats = np.zeros((0, 2), dtype=np.float64)
    self.base_dir = base_dir
    self.bp_engine = None
    self.catalog_path = path_helpers.resolve_path("common.tusi_catalog", base_dir)
    self.chgis_1911_adm1_base = path_helpers.resolve_path("input.gis.chgis_1911_adm1_base", base_dir)
    self.chgis_1911_adm3_base = path_helpers.resolve_path("input.gis.chgis_1911_adm3_base", base_dir)
    self.china_land = None
    self.config_path = path_helpers.resolve_path("common.tusi_modelling_config", base_dir)
    self.ds_path = path_helpers.resolve_path("common.data_sources", base_dir)
    self.elev_builder = None
    self.gadm_ap_adm2 = {}
    self.gadm_ap_union = None
    self.layers_dir = path_helpers.resolve_path("output.gis.layers_dir", base_dir)
    self.precision = 5
    self.priors_dir = path_helpers.resolve_path("input.gis.priors_dir", base_dir)
    self.roads = []
    self.tests_outputs_dir = path_helpers.resolve_path("tests.outputs_dir", base_dir)
    self.tier_map = {}
    self.town_pts = np.zeros((0, 2), dtype=np.float64)
    self.town_recs = []
    self.tusi_by_id = {}
    self.tusi_geoms = {}
    self.tusis = []
    self.waterways = []

    self.config = gis_helpers.load_json5(self.config_path)
    cat_obj = gis_helpers.load_json5(self.catalog_path)
    self.tusis = cat_obj.get("tusis", []) if isinstance(cat_obj, dict) else list(cat_obj)
    for t in self.tusis:
      self.tusi_by_id[t["tusi_id"]] = t
    self.all_seats = np.asarray([(float(t["seat_lon"]), float(t["seat_lat"])) for t in self.tusis], dtype=np.float64)
    self._load_base_layers()

    ds_cfg = gis_helpers.load_json5(self.ds_path)
    self.elev_builder = ElevationContourBuilder(ds_cfg, self.priors_dir, self.layers_dir)
    self.bp_engine = BorderpoolGraphEngine(self.base_dir, self.config, self.elev_builder, self.adm3_map, self.waterways, self.roads, (self.town_pts, self.town_recs), self.adm3_features)

  def _resolve_cluster_raw_domain (self, arg1_cluster):
    """Build raw host domain polygon for a cluster from CHGIS units, CITAS prefixes, and GADM Arunachal."""
    cluster = arg1_cluster
    host_polys = []

    for uid in cluster.get("host_unit_ids", []):
      if uid in self.adm3_map:
        host_polys.append(self.adm3_map[uid])
      else:
        print(f"[WARN] Unknown host_unit_id: {uid}", file=sys.stderr)

    ap_adm2s = [str(n) for n in cluster.get("gadm_ind_arunachal_adm2", []) if n in self.gadm_ap_adm2]
    if ap_adm2s:
      host_polys.extend(self.gadm_ap_adm2[n] for n in ap_adm2s)
    if not host_polys:
      return None

    domain = gis_helpers.clean_polygonal_geometry(unary_union(host_polys))
    if not ap_adm2s and not cluster.get("allow_outside_china_land", False) and self.china_land is not None and domain is not None:
      domain = gis_helpers.clean_polygonal_geometry(domain.intersection(self.china_land))

    inc_gb = [str(p) for p in cluster.get("citas_gb_prefixes", [])]
    if inc_gb and domain is not None and self.bp_engine is not None:
      c_geoms = [c["geom"] for c in self.bp_engine.citas_counties if any(c["gb"].startswith(pref) for pref in inc_gb)]
      keep_parts = [domain.intersection(unary_union(c_geoms))] if c_geoms else []
      rem_bbox = cluster.get("include_citas_uncovered_in_bbox")
      if rem_bbox and len(rem_bbox) == 4:
        all_c = [c["geom"] for c in self.bp_engine.citas_counties if c["geom"].intersects(domain)]
        uncov = domain.difference(unary_union(all_c)) if all_c else domain
        keep_parts.append(uncov.intersection(box(float(rem_bbox[0]), float(rem_bbox[1]), float(rem_bbox[2]), float(rem_bbox[3]))))
      if keep_parts:
        domain = gis_helpers.clean_polygonal_geometry(unary_union([p for p in keep_parts if p is not None and not p.is_empty]))

    exc_gb = [str(p) for p in cluster.get("exclude_citas_gb_prefixes", [])]
    if exc_gb and domain is not None and self.bp_engine is not None:
      e_geoms = [c["geom"] for c in self.bp_engine.citas_counties if any(c["gb"].startswith(pref) for pref in exc_gb)]
      if e_geoms:
        domain = gis_helpers.clean_polygonal_geometry(domain.difference(unary_union(e_geoms)))

    if cluster.get("exclude_gadm_ind_arunachal", False) and self.gadm_ap_union is not None and domain is not None:
      domain = gis_helpers.clean_polygonal_geometry(domain.difference(self.gadm_ap_union))

    # Return statement
    return domain

  def _build_host_domain (self, arg1_cluster, arg2_excluded_union, arg3_seat_pts):
    """Construct the clean, disjoint CHGIS frontier domain polygon for a Tier C cluster.

    @param arg1_cluster Cluster configuration dict.
    @param arg2_excluded_union Union of all locked Tier A + Tier B CHGIS polygons.
    @param arg3_seat_pts List of (lon, lat) seat coordinates belonging to this cluster.
    @return Clean Shapely host domain polygon.
    """
    # Convert from parameters
    cluster = arg1_cluster
    excluded_union = arg2_excluded_union
    seat_pts = list(arg3_seat_pts)

    # Declare local instance variables.
    domain = self._resolve_cluster_raw_domain(cluster)
    if domain is None or domain.is_empty:
      return None

    if excluded_union is not None and domain is not None:
      domain = gis_helpers.clean_polygonal_geometry(domain.difference(excluded_union))

    split_names = [s.lower() for s in cluster.get("split_east_of_river", [])]
    seat_objs = [Point(sx, sy) for sx, sy in seat_pts]
    if split_names and domain is not None:
      r_lines = [wg for wp, wg in self.waterways if "NaturalEarth" in str(wp.get("source") or "") and any(rn in str(wp.get("name_en") or "").lower() for rn in split_names)]
      if r_lines:
        parts = split(domain, unary_union(r_lines))
        kept = [sub for sub in parts.geoms if any(sub.contains(sp) or sub.distance(sp) < 1e-6 for sp in seat_objs)]
        if kept:
          domain = gis_helpers.clean_polygonal_geometry(unary_union(kept))

    if domain is not None and domain.geom_type == "MultiPolygon":
      kept = [sub for sub in domain.geoms if any(sub.contains(sp) or sub.distance(sp) < 1e-6 for sp in seat_objs)]
      if kept:
        domain = gis_helpers.clean_polygonal_geometry(unary_union(kept))

    # Return statement
    return domain

  def _build_tier_a_direct (self):
    """Build exact locked CHGIS 1911 polygons for all 121 chgis_direct entries.

    @return Tuple (direct_geoms_dict, tier_a_union).
    """
    # Declare local instance variables.
    direct_geoms = {}

    for t in self.tusis:
      if t.get("geometry_mode") != "chgis_direct":
        continue
      tid = t["tusi_id"]
      geoms = [self.adm3_map[u] for u in t.get("chgis_unit_ids", []) if u in self.adm3_map]
      if not geoms:
        print(f"[ERROR] Missing adm_3 geometry for chgis_direct {tid}", file=sys.stderr)
        continue
      merged = gis_helpers.clean_polygonal_geometry(geoms[0] if len(geoms) == 1 else unary_union(geoms))
      direct_geoms[tid] = merged
      self.tier_map[tid] = "tier_a"

    tier_a_union = gis_helpers.clean_polygonal_geometry(unary_union(list(direct_geoms.values())))

    # Return statement
    return direct_geoms, tier_a_union

  def _build_tier_b_subdivided (self, arg1_tier_b_cfg):
    """Partition a Tier B parent CHGIS polygon among its enclosed polities using Borderpool Graph.

    @param arg1_tier_b_cfg Tier B parent configuration dict.
    @return Tuple (parent_poly, partitioned_geoms_dict).
    """
    # Convert from parameters
    cfg = arg1_tier_b_cfg

    # Declare local instance variables.
    enclosed = []
    parent_id = cfg["parent_tusi_id"]
    parent_entry = self.tusi_by_id[parent_id]
    parent_geoms = [self.adm3_map[u] for u in parent_entry.get("chgis_unit_ids", []) if u in self.adm3_map]
    parent_poly = gis_helpers.clean_polygonal_geometry(parent_geoms[0] if len(parent_geoms) == 1 else unary_union(parent_geoms))

    for t in self.tusis:
      if t.get("geometry_mode") in ("chgis_direct", "reference_vectorised"):
        continue
      sp = Point(float(t["seat_lon"]), float(t["seat_lat"]))
      if parent_poly.contains(sp) or parent_poly.distance(sp) < 1e-6:
        enclosed.append(t)
        self.tier_map[t["tusi_id"]] = "tier_b"

    out_geoms, n_atoms, n_anc, n_edges = self.bp_engine.partition_cluster_borderpool(enclosed, parent_poly, cfg, False, self.all_seats)
    print(f"[STEP 2] Tier B {parent_id:16s}: {len(out_geoms):2d}/{len(enclosed):2d} polities | atoms={n_atoms:4d} | anchors={n_anc:4d} | edges={n_edges:5d}")

    # Return statement
    return parent_poly, out_geoms

  def _build_tier_c_cluster (self, arg1_cluster, arg2_polities, arg3_excluded_union):
    """Model all Tier C polities inside a disjoint frontier cluster via Borderpool Graph.

    @param arg1_cluster Tier C cluster config dict.
    @param arg2_polities List of catalog dicts belonging to this cluster.
    @param arg3_excluded_union Union of all 126 locked Tier A + B CHGIS polygons.
    @return Dict mapping tusi_id -> clean Shapely Polygon.
    """
    # Convert from parameters
    cluster = arg1_cluster
    excluded_union = arg3_excluded_union
    polities = list(arg2_polities)

    # Declare local instance variables.
    allow_bg = bool(cluster.get("allow_background", True))
    cid = cluster["cluster_id"]
    seat_pts = [(float(t["seat_lon"]), float(t["seat_lat"])) for t in polities]
    host_domain = self._build_host_domain(cluster, excluded_union, seat_pts)

    if host_domain is None or host_domain.is_empty:
      print(f"[ERROR] Empty host domain for cluster {cid}", file=sys.stderr)
      return {}

    for t in polities:
      self.tier_map[t["tusi_id"]] = "tier_c"

    out_geoms, n_atoms, n_anc, n_edges = self.bp_engine.partition_cluster_borderpool(polities, host_domain, cluster, allow_bg, self.all_seats)
    print(f"[STEP 2] Tier C {cid:21s}: {len(out_geoms):2d}/{len(polities):2d} polities | atoms={n_atoms:4d} | anchors={n_anc:4d} | edges={n_edges:5d}")

    # Return statement
    return out_geoms

  def _load_base_layers (self):
    """Load CHGIS 1911 boundaries, waterways, roads, and CHGIS town points."""
    adm1_path = self.chgis_1911_adm1_base
    adm3_path = self.chgis_1911_adm3_base
    road_path = os.path.join(self.layers_dir, "roads_1912_1953.geojson")
    ww_path = os.path.join(self.layers_dir, "waterways_1912_1953.geojson")

    with open(adm1_path, "r", encoding="utf-8") as fh:
      self.adm1_features = json.load(fh).get("features", [])
    china_parts = []
    for feat in self.adm1_features:
      props = feat.get("properties", {})
      g = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
      if g is not None:
        self.adm1_map[props.get("name_en", "")] = g
        if props.get("country") == "Qing Empire":
          china_parts.append(g)
    self.china_land = gis_helpers.clean_polygonal_geometry(unary_union(china_parts)) if china_parts else None

    with open(adm3_path, "r", encoding="utf-8") as fh:
      self.adm3_features = json.load(fh).get("features", [])
    for feat in self.adm3_features:
      uid = feat.get("properties", {}).get("unit_id")
      g = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
      if uid and g is not None:
        self.adm3_map[uid] = g

    with open(ww_path, "r", encoding="utf-8") as fh:
      for feat in json.load(fh).get("features", []):
        g = shape(feat["geometry"])
        if not g.is_empty:
          self.waterways.append((feat.get("properties", {}), g))

    with open(road_path, "r", encoding="utf-8") as fh:
      for feat in json.load(fh).get("features", []):
        g = shape(feat["geometry"])
        if not g.is_empty:
          self.roads.append((feat.get("properties", {}), g))

    twn_zip = path_helpers.resolve_source_file("chgis", "v6_1911_twn_pts_utf.zip", self.base_dir)
    if os.path.exists(twn_zip):
      self.town_pts, self.town_recs = self._read_point_zip_wgs84(twn_zip)

    ind_zip = path_helpers.resolve_source_file("gadm", "gadm41_IND_3.json.zip", self.base_dir)
    if os.path.exists(ind_zip):
      ap_groups = {}
      with zipfile.ZipFile(ind_zip, "r") as zf:
        jn = next((n for n in zf.namelist() if n.lower().endswith((".json", ".geojson"))), None)
        feats = json.loads(zf.read(jn).decode("utf-8")).get("features", []) if jn else []
      for feat in feats:
        p = feat.get("properties", {})
        if str(p.get("NAME_1") or "") == "ArunachalPradesh":
          n2 = str(p.get("NAME_2") or "").strip()
          g = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
          if n2 and g is not None and not g.is_empty:
            ap_groups.setdefault(n2, []).append(g)
      self.gadm_ap_adm2 = {k: gis_helpers.clean_polygonal_geometry(unary_union(v)) for k, v in ap_groups.items()}
      if self.gadm_ap_adm2:
        self.gadm_ap_union = gis_helpers.clean_polygonal_geometry(unary_union(list(self.gadm_ap_adm2.values())))

  def _read_point_zip_wgs84 (self, arg1_zip_path):
    """Read a point shapefile inside a zip archive and reproject GK19 metres to WGS84.

    @param arg1_zip_path Path to source zip archive.
    @return Tuple (coords_array (N,2), records_list).
    """
    # Convert from parameters
    zip_path = arg1_zip_path

    # Declare local instance variables.
    arr = np.zeros((0, 2), dtype=np.float64)
    recs = []

    with zipfile.ZipFile(zip_path, "r") as zf:
      names = zf.namelist()
      shp_n = next((n for n in names if n.lower().endswith(".shp")), None)
      dbf_n = next((n for n in names if n.lower().endswith(".dbf")), None)
      if not shp_n or not dbf_n:
        return arr, recs
      enc = "gb18030" if "gbk" in os.path.basename(zip_path).lower() else "utf-8"
      sf = shapefile.Reader(shp=io.BytesIO(zf.read(shp_n)), dbf=io.BytesIO(zf.read(dbf_n)), encoding=enc, encodingErrors="replace")
      pts = [s.points[0] for s in sf.shapes() if s.points]
      fields = [f[0] for f in sf.fields[1:]]
      recs = [dict(zip(fields, r)) for r in sf.records()]

    if not pts:
      return arr, recs

    arr = np.asarray(pts, dtype=np.float64)
    if abs(arr[0, 0]) > 360.0 or abs(arr[0, 1]) > 90.0:
      arr = np.asarray(gis_helpers.gk19_array_to_lonlat(arr), dtype=np.float64)

    # Return statement
    return arr, recs

  def _build_tier_r_reference (self):
    """Load planar reference-vectorised polygons for Tibet, Yushu, Hor, Arunachal and Western Kham.

    @return Tuple (ref_geoms_dict, tier_r_union).
    """
    # Declare local instance variables.
    geo_rel = self.config.get("reference_geojson", "input/gis/priors/tibet_yushu_reference_polygons.geojson")
    geo_path = os.path.join(self.base_dir, geo_rel)
    ref_geoms = {}

    if not os.path.exists(geo_path):
      print(f"[ERROR] Missing reference_geojson at {geo_path}", file=sys.stderr)
      return ref_geoms, None

    with open(geo_path, "r", encoding="utf-8") as fh:
      feats = json.load(fh).get("features", [])

    for feat in feats:
      props = feat.get("properties", {})
      if props.get("feature_role") != "polity":
        continue
      tid = props.get("tusi_id")
      if tid not in self.tusi_by_id or self.tusi_by_id[tid].get("geometry_mode") != "reference_vectorised":
        continue
      geom = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
      if geom is not None and not geom.is_empty:
        ref_geoms[tid] = geom
        self.tier_map[tid] = "tier_r"

    tier_r_union = gis_helpers.clean_polygonal_geometry(unary_union(list(ref_geoms.values()))) if ref_geoms else None
    print(f"[STEP 1B] Tier R reference: {len(ref_geoms)} polities loaded from {geo_rel}")

    # Return statement
    return ref_geoms, tier_r_union

  def _resolve_all_overlaps (self, arg1_tusi_geoms, arg2_tusi_by_id):
    """Round all modelled polygons to 5 decimals and resolve every pairwise overlap sliver.

    @param arg1_tusi_geoms Dict mapping tusi_id to Shapely polygon.
    @param arg2_tusi_by_id Dict mapping tusi_id to catalog entry.
    @return Tuple (cleaned_dict, max_overlap_deg2, overlap_pairs_list).
    """
    # Convert from parameters
    tusi_by_id = arg2_tusi_by_id
    tusi_geoms = arg1_tusi_geoms

    # Declare local instance variables.
    all_sps = [(tid_o, Point(float(t_o["seat_lon"]), float(t_o["seat_lat"]))) for tid_o, t_o in tusi_by_id.items()]
    buf_eps = 1.2*(10.0**(-self.precision))
    cleaned = {}
    tier_prio = {"tier_r": 0, "tier_a": 1, "tier_b": 2, "tier_c": 3}
    ordered_ids = sorted(tusi_geoms.keys(), key=lambda tid: (tier_prio.get(self.tier_map.get(tid, "tier_c"), 3), tid))

    def sanitize_part (geom, tid_key, keep_holes=False):
      if geom is None or geom.is_empty:
        return geom
      if self.tier_map.get(tid_key) in ("tier_r", "tier_a"):
        return gis_helpers.clean_polygonal_geometry(geom)
      if geom.geom_type == "MultiPolygon":
        sp = Point(float(tusi_by_id[tid_key]["seat_lon"]), float(tusi_by_id[tid_key]["seat_lat"]))
        geom = next((sub for sub in geom.geoms if sub.contains(sp) or sub.distance(sp) < 1e-9), max(geom.geoms, key=lambda s: s.area))
      if geom.geom_type == "Polygon" and len(geom.interiors) > 0:
        if keep_holes:
          geom = Polygon(geom.exterior, [r for r in geom.interiors if Polygon(r).area > 1e-9])
        else:
          geom = Polygon(geom.exterior, [r for r in geom.interiors if any(Polygon(r).contains(osp) or Polygon(r).distance(osp) < 1e-5 for tid_o, osp in all_sps if tid_o != tid_key)])
      return geom

    for tid in ordered_ids:
      g = sanitize_part(gis_helpers.round_geometry(tusi_geoms[tid], self.precision), tid, False)
      if g is not None and not g.is_empty:
        cleaned[tid] = g

    for pass_i in range(6):
      changed = False
      for i in range(len(ordered_ids)):
        tid_a = ordered_ids[i]
        if tid_a not in cleaned:
          continue
        ga = cleaned[tid_a]
        pa = tier_prio.get(self.tier_map.get(tid_a, "tier_c"), 3)
        for x in range(i + 1, len(ordered_ids)):
          tid_b = ordered_ids[x]
          if tid_b not in cleaned:
            continue
          gb = cleaned[tid_b]
          if ga.bounds[0] > gb.bounds[2] or gb.bounds[0] > ga.bounds[2] or ga.bounds[1] > gb.bounds[3] or gb.bounds[1] > ga.bounds[3]:
            continue
          if ga.intersects(gb) and ga.intersection(gb).area > 1e-11:
            changed = True
            pb = tier_prio.get(self.tier_map.get(tid_b, "tier_c"), 3)
            trim_b = (pb > pa) or (pb == pa and gb.area >= ga.area)
            keep_g, trim_id = (ga, tid_b) if trim_b else (gb, tid_a)
            cut_g = keep_g if pass_i == 0 else keep_g.buffer(buf_eps, join_style="mitre")
            rem = sanitize_part(gis_helpers.round_geometry(cleaned[trim_id].difference(cut_g), self.precision), trim_id, True)
            if rem is not None and not rem.is_empty:
              cleaned[trim_id] = rem
              if not trim_b:
                ga = rem
      if not changed:
        break

    max_ov = 0.0
    ov_pairs = []
    for i in range(len(ordered_ids)):
      tid_a = ordered_ids[i]
      ga = cleaned[tid_a]
      for x in range(i + 1, len(ordered_ids)):
        tid_b = ordered_ids[x]
        gb = cleaned[tid_b]
        if ga.bounds[0] > gb.bounds[2] or gb.bounds[0] > ga.bounds[2] or ga.bounds[1] > gb.bounds[3] or gb.bounds[1] > ga.bounds[3]:
          continue
        if ga.intersects(gb):
          ia = ga.intersection(gb).area
          if ia > max_ov:
            max_ov = ia
          if ia > 1e-9:
            ov_pairs.append((tid_a, tid_b, ia))

    # Return statement
    return cleaned, max_ov, ov_pairs

  def _validate_all_assertions (self, arg1_tusi_geoms, arg2_max_ov, arg3_ov_pairs):
    """Enforce hard topological, seat-containment, hole, and anti-Voronoi assertions on final geometries.

    @param arg1_tusi_geoms Final cleaned dict mapping tusi_id -> Shapely geometry.
    @param arg2_max_ov Maximum pairwise intersection area in deg2.
    @param arg3_ov_pairs List of overlap tuples with area > 1e-9.
    @return Summary validation dict.
    """
    # Convert from parameters
    max_ov = float(arg2_max_ov)
    ov_pairs = list(arg3_ov_pairs)
    tusi_geoms = arg1_tusi_geoms

    # Declare local instance variables.
    all_id_list = list(tusi_geoms.keys())
    all_g_list = [tusi_geoms[k] for k in all_id_list]
    all_g_tree = STRtree(all_g_list)
    hole_issues = []
    missing = [t["tusi_id"] for t in self.tusis if t["tusi_id"] not in tusi_geoms]
    multipart_issues = []
    seat_inside_cnt = 0
    seat_issues = []

    assert len(tusi_geoms) == len(self.tusis) and not missing, f"Missing polities: {missing}"
    for t in self.tusis:
      tid = t["tusi_id"]
      g = tusi_geoms[tid]
      assert g is not None and not g.is_empty and g.is_valid and g.area > 0.0, f"Invalid geometry for {tid}"
      sp = Point(round(float(t["seat_lon"]), self.precision), round(float(t["seat_lat"]), self.precision))
      if g.contains(sp) or g.distance(sp) == 0.0:
        seat_inside_cnt += 1
      else:
        seat_issues.append((tid, float(g.distance(sp))))
      if self.tier_map.get(tid) in ("tier_b", "tier_c"):
        if g.geom_type != "Polygon":
          multipart_issues.append((tid, g.geom_type))
        elif len(g.interiors) > 0:
          unclaimed = 0
          for r in g.interiors:
            hp = Polygon(r)
            cov_area = sum(hp.intersection(all_g_list[int(m)]).area for m in all_g_tree.query(hp) if all_id_list[int(m)] != tid)
            if cov_area < 0.8*hp.area:
              unclaimed += 1
          if unclaimed > 0:
            hole_issues.append((tid, unclaimed))

    voronoi = self.bp_engine.audit_voronoi_artefacts(tusi_geoms, self.tier_map)
    print(f"[STEP 2 VALIDATE] total={len(tusi_geoms)}/{len(self.tusis)} seats={seat_inside_cnt}/{len(self.tusis)} multi={len(multipart_issues)} holes={len(hole_issues)} ov={len(ov_pairs)} max_ov={max_ov:.9f} v_chains={voronoi['checked_chains']} sin={voronoi['mean_sinuosity']} v_viol={len(voronoi['voronoi_violations'])}")
    if voronoi["voronoi_violations"]:
      print(f"[VORONOI VIOLATIONS] {voronoi['voronoi_violations'][:15]}", file=sys.stderr)
    assert not seat_issues, f"Seats outside polygons: {seat_issues[:10]}"
    assert not multipart_issues, f"Multi-part modelled polygons: {multipart_issues[:10]}"
    assert not hole_issues, f"Interior holes in modelled polygons: {hole_issues[:10]}"
    assert not ov_pairs, f"Pairwise overlaps > 1e-9: {ov_pairs[:10]}"
    assert len(voronoi["voronoi_violations"]) == 0, f"Straight Voronoi chords >=0.08 deg found: {voronoi['voronoi_violations'][:10]}"

    # Return statement
    return {"mean_sinuosity": voronoi["mean_sinuosity"], "modelled_holes": len(hole_issues), "modelled_multiparts": len(multipart_issues), "seats_inside": seat_inside_cnt, "total": len(tusi_geoms), "voronoi_violations": len(voronoi["voronoi_violations"])}

  def build_all_tusis (self):
    """Execute the spatial pipeline for all catalog polities and verify assertions."""
    direct_geoms, tier_a_union = self._build_tier_a_direct()
    ref_geoms, tier_r_union = self._build_tier_r_reference()
    excluded_parts = []
    if tier_a_union is not None:
      excluded_parts.append(tier_a_union)
    if tier_r_union is not None:
      excluded_parts.append(tier_r_union)
    raw_geoms, tier_b_geoms, tier_c_geoms = dict(direct_geoms), {}, {}
    raw_geoms.update(ref_geoms)

    for tb_cfg in self.config.get("tier_b_clusters", []):
      parent_poly, b_part = self._build_tier_b_subdivided(tb_cfg)
      excluded_parts.append(parent_poly)
      tier_b_geoms.update(b_part)
      raw_geoms.update(b_part)

    excluded_union = gis_helpers.clean_polygonal_geometry(unary_union(excluded_parts))
    tier_c_candidates = [t for t in self.tusis if t.get("geometry_mode") not in ("chgis_direct", "reference_vectorised") and t["tusi_id"] not in tier_b_geoms]
    clusters = self.config.get("kriging_clusters", [])
    cluster_doms = {cl["cluster_id"]: self._resolve_cluster_raw_domain(cl) for cl in clusters}
    assigned_c = {cl["cluster_id"]: [] for cl in clusters}

    for t in tier_c_candidates:
      sp = Point(float(t["seat_lon"]), float(t["seat_lat"]))
      hit_cid = next((cl["cluster_id"] for cl in clusters if cluster_doms[cl["cluster_id"]] is not None and (cluster_doms[cl["cluster_id"]].contains(sp) or cluster_doms[cl["cluster_id"]].distance(sp) < 1e-6)), None)
      if hit_cid is None:
        print(f"[ERROR] Tier C polity {t['tusi_id']} unmapped to any cluster", file=sys.stderr)
        continue
      assigned_c[hit_cid].append(t)

    for cl in clusters:
      pols = assigned_c.get(cl["cluster_id"], [])
      if not pols:
        continue
      c_part = self._build_tier_c_cluster(cl, pols, excluded_union)
      tier_c_geoms.update(c_part)
      raw_geoms.update(c_part)

    cleaned, max_ov, ov_pairs = self._resolve_all_overlaps(raw_geoms, self.tusi_by_id)
    val_summary = self._validate_all_assertions(cleaned, max_ov, ov_pairs)
    self.tusi_geoms = cleaned

    # Return statement
    return {"borderpool_modelled": len(tier_b_geoms) + len(tier_c_geoms), "chgis_direct": len(direct_geoms), "max_overlap_deg2": max_ov, "overlap_pairs": ov_pairs, "reference_vectorised": len(ref_geoms), "tier_b": len(tier_b_geoms), "tier_c": len(tier_c_geoms), "total": val_summary["total"], "validation": val_summary}

  def export_geojson (self):
    """Write all modelled polity features to ./output/gis/layers/tusi_1912_1953.geojson (WGS84, 5 decimals).

    @return Tuple (output_filepath, feature_count).
    """
    # Declare local instance variables.
    out_features = []
    out_path = os.path.join(self.layers_dir, "tusi_1912_1953.geojson")

    for t in self.tusis:
      tid = t["tusi_id"]
      geom = self.tusi_geoms.get(tid)
      if geom is None or geom.is_empty:
        continue
      props = {
        "abolition_note": t.get("abolition_note", ""), "chgis_unit_ids": t.get("chgis_unit_ids", []),
        "de_facto_end_year": int(t.get("de_facto_end_year", t["end_year"])),
        "de_facto_start_year": int(t.get("de_facto_start_year", t["start_year"])),
        "de_jure_gaituguiliu_year": t.get("de_jure_gaituguiliu_year"), "end_year": int(t["end_year"]),
        "geometry_mode": t["geometry_mode"], "name_en": t["name_en"], "name_zh": t["name_zh"],
        "parent_province": t["parent_province"], "polity_type": t.get("polity_type", "tusi"),
        "rank_title": t.get("rank_title", "Tusi"), "region": t["region"],
        "seat_lat": round(float(t["seat_lat"]), self.precision), "seat_lon": round(float(t["seat_lon"]), self.precision),
        "start_year": int(t["start_year"]), "tusi_id": tid, "tusi_status": t.get("tusi_status", "de_jure_and_de_facto"),
      }
      out_features.append((props, geom))
    written = gis_helpers.write_geojson(out_path, out_features, self.precision)

    # Return statement
    return out_path, written

  def load_existing_geojson (self):
    """Populate tusi_geoms and tier_map from the previously compiled GeoJSON without rebuilding partitions.

    @return Number of loaded polity geometries.
    """
    # Declare local instance variables.
    in_path = os.path.join(self.layers_dir, "tusi_1912_1953.geojson")

    with open(in_path, "r", encoding="utf-8") as fh:
      data = json.load(fh)
    self.tusi_geoms = {}
    self.tier_map = {}
    for feat in data.get("features", []):
      props = feat.get("properties", {})
      tid = props.get("tusi_id")
      if not tid:
        continue
      g = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
      if g is not None and not g.is_empty:
        self.tusi_geoms[tid] = g
        self.tier_map[tid] = props.get("geometry_mode", "")

    # Return statement
    return len(self.tusi_geoms)

  def render_diagnostic_maps (self):
    """Render all 7 regional, zoomed, & overview diagnostic PNG verification maps in ./tests/.

    @return List of generated PNG filepaths.
    """
    os.makedirs(self.tests_outputs_dir, exist_ok=True)
    generated = []
    leg_handles = [
      Patch(facecolor="#88c999", edgecolor="#1a3b2a", linewidth=0.9, label="chgis_direct (CHGIS 1911 Surveyed)"),
      Patch(facecolor="#e8a47c", edgecolor="#6b1b1b", linewidth=1.1, label="borderpool_modelled (Topographic & Subadmin Partition)"),
      Line2D([0], [0], color="#1f68a8", linewidth=1.5, label="Major Rivers"),
      Line2D([0], [0], color="#cbbba8", linewidth=0.6, label="DEM Contours (1k-4k m)"),
      Line2D([0], [0], marker="*", color="w", markerfacecolor="#f5d142", markeredgecolor="#111111", markersize=9, label="Feudatory Seat (*)"),
    ]
    iter_polys = lambda g: [g] if g.geom_type == "Polygon" else (list(g.geoms) if g.geom_type == "MultiPolygon" else [])
    iter_lines = lambda g: [g] if g.geom_type == "LineString" else (list(g.geoms) if g.geom_type == "MultiLineString" else [])

    for mcfg in self.config.get("diagnostic_maps", []):
      minx, maxx, miny, maxy = [float(v) for v in mcfg["extent"]]
      vp_box, year_flt = box(minx, miny, maxx, maxy), mcfg.get("active_year_filter")
      is_overview = (year_flt is not None or (maxx - minx) > 35.0)
      min_lbl_area = 0.65 if is_overview else (0.18 if (maxx - minx) > 22.0 else 0.005)
      fig, ax = plt.subplots(figsize=(14.5, 10.5), dpi=210)
      ax.set_facecolor("#e9f0f5")

      for feat in self.adm1_features:
        g = shape(feat["geometry"])
        if g.intersects(vp_box):
          for poly in iter_polys(g):
            ax.fill(*poly.exterior.xy, facecolor="#f4f1ea", edgecolor="#5c5c5c", linewidth=0.95, zorder=1)

      if not is_overview:
        for lvl, cg in self.bp_engine.contour_lines:
          if lvl in (1000, 2000, 3000, 4000) and cg.intersects(vp_box):
            for line in iter_lines(cg.intersection(vp_box)):
              ax.plot(*line.xy, color="#cbbba8", linewidth=0.30, alpha=0.50, zorder=2)
        if self.bp_engine.citas_tree is not None:
          for c_idx in self.bp_engine.citas_tree.query(vp_box):
            c_rec = self.bp_engine.citas_counties[int(c_idx)]
            if str(c_rec.get("gb") or "").startswith("54"):
              continue
            for poly in iter_polys(c_rec["geom"]):
              ax.plot(*poly.exterior.xy, color="#bfb5a4", linewidth=0.35, linestyle="-.", alpha=0.65, zorder=2)
        for feat in self.adm3_features:
          g = shape(feat["geometry"])
          if g.intersects(vp_box):
            for poly in iter_polys(g):
              ax.plot(*poly.exterior.xy, color="#d4cfc4", linewidth=0.28, zorder=2)

      for _, rg in self.roads:
        if rg.intersects(vp_box):
          for line in iter_lines(rg):
            ax.plot(*line.xy, color="#9e7b56", linewidth=0.55, linestyle="--", alpha=0.45, zorder=3)
      for props, wg in self.waterways:
        is_ne = "NaturalEarth" in str(props.get("source") or "")
        if (not is_overview or is_ne) and wg.intersects(vp_box):
          for line in iter_lines(wg):
            ax.plot(*line.xy, color="#1f68a8" if is_ne else "#5394cb", linewidth=1.4 if is_ne else 0.65, alpha=0.82, zorder=4)
      for rx, ry, rtxt in mcfg.get("river_labels", []):
        ax.text(float(rx), float(ry), rtxt, color="#154d80", fontsize=8.5, fontstyle="italic", fontweight="bold", zorder=9, path_effects=[patheffects.withStroke(linewidth=2.4, foreground="#ffffff")])

      raw_labels = []
      for t in self.tusis:
        if year_flt is not None and not (int(t.get("de_facto_start_year", t["start_year"])) <= int(year_flt) <= int(t.get("de_facto_end_year", t["end_year"]))):
          continue
        tid = t["tusi_id"]
        geom = self.tusi_geoms.get(tid)
        if geom is None or geom.is_empty or not geom.intersects(vp_box):
          continue
        is_direct = (t["geometry_mode"] == "chgis_direct")
        digest = hashlib.md5(tid.encode("utf-8")).digest()
        rgb = plt.cm.hsv((int.from_bytes(digest[:2], "big") % 360) / 360.0)[:3]
        fill_col = (0.35 + 0.55*rgb[0], 0.35 + 0.55*rgb[1], 0.35 + 0.55*rgb[2])
        edge_col = "#1a3b2a" if is_direct else "#6b1b1b"
        for poly in iter_polys(geom):
          ax.fill(*poly.exterior.xy, facecolor=fill_col, edgecolor=edge_col, linewidth=0.7 if is_direct else 0.95, alpha=0.75, zorder=5)
          for hole in poly.interiors:
            ax.fill(*hole.xy, facecolor="#f4f1ea", edgecolor=edge_col, linewidth=0.45, zorder=5)
        sx, sy = float(t["seat_lon"]), float(t["seat_lat"])
        if not is_overview and minx <= sx <= maxx and miny <= sy <= maxy:
          ax.scatter([sx], [sy], marker="*", s=38, color="#f5d142" if not is_direct else "#ffffff", edgecolor="#111111", linewidth=0.45, zorder=8)
        rp = geom.representative_point()
        if geom.area >= min_lbl_area and minx <= rp.x <= maxx and miny <= rp.y <= maxy:
          sn = t["name_en"].split("(")[0].strip()
          sn = sn[:16] + ".." if len(sn) > 18 else sn
          raw_labels.append([rp.x, rp.y, rp.x, rp.y, sn if is_overview else f"{sn}\n[{tid}]"])

      min_dx, min_dy = 0.042*(maxx - minx), 0.020*(maxy - miny)
      max_sx, max_sy = 0.032*(maxx - minx), 0.026*(maxy - miny)
      for _ in range(16):
        for i in range(len(raw_labels)):
          for x in range(i + 1, len(raw_labels)):
            dx, dy = raw_labels[i][0] - raw_labels[x][0], raw_labels[i][1] - raw_labels[x][1]
            if abs(dx) < min_dx and abs(dy) < min_dy:
              px_off, py_off = (0.10*min_dx if dx >= 0.0 else -0.10*min_dx), (0.18*min_dy if dy >= 0.0 else -0.18*min_dy)
              for sgn, idx in ((1.0, i), (-1.0, x)):
                raw_labels[idx][0] = min(maxx - 0.25, max(minx + 0.25, min(raw_labels[idx][2] + max_sx, max(raw_labels[idx][2] - max_sx, raw_labels[idx][0] + sgn*px_off))))
                raw_labels[idx][1] = min(maxy - 0.15, max(miny + 0.15, min(raw_labels[idx][3] + max_sy, max(raw_labels[idx][3] - max_sy, raw_labels[idx][1] + sgn*py_off))))
      for lx, ly, ox, oy, txt in raw_labels:
        if np.hypot(lx - ox, ly - oy) > (0.40 if is_overview else 0.12):
          ax.plot([ox, lx], [oy, ly], color="#333333", linewidth=0.4, alpha=0.6, zorder=9)
        ax.text(lx, ly, txt, fontsize=4.5 if is_overview else 3.7, ha="center", va="center", color="#141414", fontweight="semibold", zorder=10, path_effects=[patheffects.withStroke(linewidth=1.5, foreground="#ffffff", alpha=0.9)])

      ax.set_xlim(minx, maxx)
      ax.set_ylim(miny, maxy)
      ax.set_aspect(1.0 / np.cos(np.deg2rad(0.5*(miny + maxy))))
      ax.grid(True, linestyle=":", linewidth=0.45, color="#999999", alpha=0.6)
      ax.set_xlabel("Longitude (WGS84)", fontsize=9)
      ax.set_ylabel("Latitude (WGS84)", fontsize=9)
      ax.set_title(mcfg["title"], fontsize=11.0, fontweight="bold", pad=10)
      leg_loc = mcfg.get("legend_loc", "lower left")
      ax.legend(handles=leg_handles, loc="upper center" if leg_loc == "outside_bottom" else leg_loc, bbox_to_anchor=(0.5, -0.075) if leg_loc == "outside_bottom" else None, ncol=5 if leg_loc == "outside_bottom" else 1, fontsize=7.5, framealpha=0.95)
      out_png = os.path.join(self.tests_outputs_dir, mcfg["filename"])
      fig.tight_layout()
      fig.savefig(out_png, dpi=210)
      plt.close(fig)
      generated.append(out_png)
      print(f"[STEP 2] Rendered diagnostic PNG: {out_png}")

    # Return statement
    return generated
