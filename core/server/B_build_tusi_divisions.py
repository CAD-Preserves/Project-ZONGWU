"""Hydrology-modulated Kriging & CHGIS polygon modeller for 1912-1953 Tusi divisions."""

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
from scipy import linalg, ndimage
import shapefile
import shapely
from shapely.geometry import Point, Polygon, box, shape
from shapely.ops import split, unary_union

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
  sys.path.insert(0, SCRIPT_DIR)

import gis_helpers


class TusiModeller:
  """Three-tier spatial modeller and diagnostic cartographer for 425 frontier Tusi polities."""

  def __init__ (self, arg1_base_dir):
    """Initialise workspace paths and load catalog, config, and CHGIS/hydrology layers.

    @param arg1_base_dir Root directory of Project-ZONGWU.
    """
    # Convert from parameters
    base_dir = os.path.abspath(arg1_base_dir)

    # Declare local instance variables.
    self.adm1_features = []
    self.adm1_map = {}
    self.adm3_features = []
    self.adm3_map = {}
    self.base_dir = base_dir
    self.catalog_path = os.path.join(base_dir, "common", "tusi", "tusi_catalog.json5")
    self.china_land = None
    self.config_path = os.path.join(base_dir, "common", "tusi", "tusi_modelling_config.json5")
    self.gis_dir = os.path.join(base_dir, "gis")
    self.gns_cache = {}
    self.precision = 5
    self.roads = []
    self.road_tree_pts = None
    self.sources_dir = os.path.join(self.gis_dir, "sources")
    self.tests_dir = os.path.join(base_dir, "tests")
    self.tier_map = {}
    self.tusi_by_id = {}
    self.tusi_geoms = {}
    self.tusis = []
    self.town_pts = None
    self.town_recs = []
    self.waterways = []

    self.config = gis_helpers.load_json5(self.config_path)
    cat_obj = gis_helpers.load_json5(self.catalog_path)
    self.tusis = cat_obj.get("tusis", []) if isinstance(cat_obj, dict) else list(cat_obj)
    for t in self.tusis:
      self.tusi_by_id[t["tusi_id"]] = t
    self._load_base_layers()

  def _build_host_domain (self, arg1_cluster, arg2_excluded_union, arg3_seat_pts):
    """Construct the clean, disjoint CHGIS frontier domain polygon for a Tier C cluster.

    @param arg1_cluster Cluster configuration dict.
    @param arg2_excluded_union Union of all 126 locked Tier A + Tier B CHGIS polygons.
    @param arg3_seat_pts List of (lon, lat) seat coordinates belonging to this cluster.
    @return Clean Shapely host domain polygon.
    """
    # Convert from parameters
    cluster = arg1_cluster
    excluded_union = arg2_excluded_union
    seat_pts = list(arg3_seat_pts)

    # Declare local instance variables.
    domain = None
    host_polys = []

    for uid in cluster.get("host_unit_ids", []):
      if uid in self.adm3_map:
        host_polys.append(self.adm3_map[uid])
      else:
        print(f"[WARN] Unknown host_unit_id: {uid}", file=sys.stderr)

    if not host_polys:
      return None

    domain = gis_helpers.clean_polygonal_geometry(unary_union(host_polys))
    if self.china_land is not None and domain is not None:
      domain = gis_helpers.clean_polygonal_geometry(domain.intersection(self.china_land))

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

    max_r = float(cluster.get("max_radius_deg") or 0.0)
    if max_r > 0.0 and domain is not None and seat_pts:
      pad_r = max_r + 0.55
      xs_s, ys_s = [sx for sx, _ in seat_pts], [sy for _, sy in seat_pts]
      domain = gis_helpers.clean_polygonal_geometry(domain.intersection(box(min(xs_s) - pad_r, min(ys_s) - pad_r, max(xs_s) + pad_r, max(ys_s) + pad_r)))

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
    geoms = []

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
    """Partition a Tier B parent CHGIS polygon among its enclosed polities.

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
      if t.get("geometry_mode") != "kriging_modelled":
        continue
      sp = Point(float(t["seat_lon"]), float(t["seat_lat"]))
      if parent_poly.contains(sp) or parent_poly.distance(sp) < 1e-6:
        enclosed.append(t)
        self.tier_map[t["tusi_id"]] = "tier_b"

    out_geoms, n_pix, n_samp, n_rseg = self._partition_domain_kriging(enclosed, parent_poly, cfg, False)
    print(f"[STEP 2] Tier B {parent_id:16s}: {len(out_geoms):2d}/{len(enclosed):2d} polities | grid={n_pix} | samples={n_samp} | rsegs={n_rseg}")

    # Return statement
    return parent_poly, out_geoms

  def _build_tier_c_cluster (self, arg1_cluster, arg2_polities, arg3_excluded_union):
    """Model all Tier C kriging_modelled polities inside a disjoint frontier cluster.

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

    out_geoms, n_pix, n_samp, n_rseg = self._partition_domain_kriging(polities, host_domain, cluster, allow_bg)
    print(f"[STEP 2] Tier C {cid:21s}: {len(out_geoms):2d}/{len(polities):2d} polities | grid={n_pix} | samples={n_samp} | rsegs={n_rseg}")

    # Return statement
    return out_geoms

  def _collect_cluster_samples (self, arg1_polities, arg2_host_domain, arg3_cluster, arg4_allow_bg):
    """Collect polity positive settlements and Z=0 background town/seed points for Kriging.

    @param arg1_polities List of catalog dicts in this cluster.
    @param arg2_host_domain Clean Shapely domain polygon.
    @param arg3_cluster Cluster configuration dict.
    @param arg4_allow_bg True when external background class is active.
    @return Tuple (samples_xy (N,2), z_mat (N, K_eff), n_polities).
    """
    # Convert from parameters
    allow_bg = bool(arg4_allow_bg)
    cluster = arg3_cluster
    host_domain = arg2_host_domain
    polities = list(arg1_polities)

    # Declare local instance variables.
    bg_exclude_r = float(cluster.get("bg_exclude_radius_deg") or 0.18)
    k_pol = len(polities)
    max_samples = int(self.config.get("max_samples_per_cluster") or 180)
    pos_pts = []
    pos_z = []
    samples_xy = []
    z_rows = []

    for idx, t in enumerate(polities):
      sx, sy = float(t["seat_lon"]), float(t["seat_lat"])
      pos_pts.append((sx, sy))
      pos_z.append(idx)
      for ks in t.get("known_settlements", []):
        kx, ky = float(ks[0]), float(ks[1])
        if np.hypot(kx - sx, ky - sy) < 1e-4:
          continue
        # Only admit known_settlements strictly nearest to this polity seat inside domain+0.15
        if host_domain.distance(Point(kx, ky)) > 0.15:
          continue
        d_own = np.hypot(kx - sx, ky - sy)
        if any(np.hypot(kx - float(ot["seat_lon"]), ky - float(ot["seat_lat"])) < 0.85*d_own for o_i, ot in enumerate(polities) if o_i != idx):
          continue
        pos_pts.append((kx, ky))
        pos_z.append(idx)

    pos_arr = np.asarray(pos_pts, dtype=np.float64)
    for idx in range(len(pos_pts)):
      row = np.zeros(k_pol + (1 if allow_bg else 0), dtype=np.float64)
      row[pos_z[idx]] = 1.0
      samples_xy.append(pos_pts[idx])
      z_rows.append(row)

    if allow_bg:
      bg_candidates = []
      for bgs in cluster.get("bg_seeds", []):
        bg_candidates.append((float(bgs[0]), float(bgs[1])))

      minx, miny, maxx, maxy = host_domain.bounds
      pad = 0.15
      town_pool = [self.town_pts] if self.town_pts is not None else []
      gns_arr = self._load_gns_points(cluster.get("gns_files", []))
      if gns_arr is not None and gns_arr.shape[0] > 0:
        town_pool.append(gns_arr)

      for pool_arr in town_pool:
        mask = (pool_arr[:, 0] >= minx - pad) & (pool_arr[:, 0] <= maxx + pad) & (pool_arr[:, 1] >= miny - pad) & (pool_arr[:, 1] <= maxy + pad)
        sub = pool_arr[mask]
        if sub.shape[0] == 0:
          continue
        d_pos = np.min(np.hypot(sub[:, 0:1] - pos_arr[None, :, 0], sub[:, 1:2] - pos_arr[None, :, 1]), axis=1)
        far_sub = sub[d_pos >= bg_exclude_r]
        if far_sub.shape[0] > 0:
          in_h = shapely.contains_xy(host_domain, far_sub[:, 0], far_sub[:, 1])
          for pt in far_sub[in_h]:
            bg_candidates.append((float(pt[0]), float(pt[1])))

      kept_bg = []
      budget = max(12, max_samples - len(samples_xy))
      step_stride = max(1, len(bg_candidates) // max(1, budget*2))
      for bx, by in bg_candidates[::step_stride]:
        if any(np.hypot(bx - kx, by - ky) < 0.06 for kx, ky in kept_bg):
          continue
        if any(np.hypot(bx - sx, by - sy) < 0.04 for sx, sy in samples_xy):
          continue
        kept_bg.append((bx, by))
        row = np.zeros(k_pol + 1, dtype=np.float64)
        row[k_pol] = 1.0
        samples_xy.append((bx, by))
        z_rows.append(row)
        if len(kept_bg) >= budget:
          break

    # Return statement
    return np.asarray(samples_xy, dtype=np.float64), np.asarray(z_rows, dtype=np.float64), k_pol

  def _compute_river_segments (self, arg1_barrier_names, arg2_bbox):
    """Extract barrier river line segments within an expanded bounding box.

    @param arg1_barrier_names List of downcased river name substrings.
    @param arg2_bbox Tuple (minx, miny, maxx, maxy).
    @return Float64 array of shape (R, 4) [x1, y1, x2, y2].
    """
    # Convert from parameters
    barrier_names = [b.lower() for b in (arg1_barrier_names or [])]
    minx, miny, maxx, maxy = arg2_bbox

    if not barrier_names:
      return np.zeros((0, 4), dtype=np.float64)

    # Declare local instance variables.
    clip_box = box(minx - 0.5, miny - 0.5, maxx + 0.5, maxy + 0.5)
    segs = []

    for props, geom in self.waterways:
      nm_en = str(props.get("name_en") or "").lower()
      nm_ch = str(props.get("name_ch") or "").lower()
      if not any(bn in nm_en or bn in nm_ch for bn in barrier_names):
        continue
      if not geom.intersects(clip_box):
        continue
      clipped = geom.intersection(clip_box)
      lines = [clipped] if clipped.geom_type == "LineString" else (list(clipped.geoms) if clipped.geom_type == "MultiLineString" else [])
      for line in lines:
        simp = line.simplify(0.035, preserve_topology=False)
        coords = list(simp.coords)
        for i in range(len(coords) - 1):
          segs.append((coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1]))

    # Return statement
    return np.asarray(segs, dtype=np.float64) if segs else np.zeros((0, 4), dtype=np.float64)

  def _load_base_layers (self):
    """Load CHGIS 1911 boundaries, waterways, roads, and CHGIS town points."""
    adm1_path = os.path.join(self.gis_dir, "adm_1_1911.geojson")
    adm3_path = os.path.join(self.gis_dir, "adm_3_1911.geojson")
    road_path = os.path.join(self.gis_dir, "roads_1912_1953.geojson")
    ww_path = os.path.join(self.gis_dir, "waterways_1912_1953.geojson")

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

    road_pts = []
    with open(road_path, "r", encoding="utf-8") as fh:
      for feat in json.load(fh).get("features", []):
        g = shape(feat["geometry"])
        if g.is_empty:
          continue
        self.roads.append((feat.get("properties", {}), g))
        lines = [g] if g.geom_type == "LineString" else (list(g.geoms) if g.geom_type == "MultiLineString" else [])
        for ln in lines:
          coords = list(ln.coords)
          for i in range(0, len(coords), 2):
            road_pts.append((coords[i][0], coords[i][1]))
    self.road_tree_pts = np.asarray(road_pts, dtype=np.float64) if road_pts else np.zeros((0, 2), dtype=np.float64)

    twn_zip = os.path.join(self.sources_dir, "v6_1911_twn_pts_utf.zip")
    if os.path.exists(twn_zip):
      self.town_pts, self.town_recs = self._read_point_zip_wgs84(twn_zip)

  def _load_gns_points (self, arg1_filenames):
    """Load and cache historical GNS settlement coordinates from source zip archives.

    @param arg1_filenames List of zip filenames inside ./gis/sources/.
    @return Float64 array of shape (M, 2) [lon, lat].
    """
    # Convert from parameters
    filenames = list(arg1_filenames or [])

    # Declare local instance variables.
    arrays = []

    for fn in filenames:
      if fn not in self.gns_cache:
        zp = os.path.join(self.sources_dir, fn)
        if os.path.exists(zp):
          arr, _ = self._read_point_zip_wgs84(zp)
          self.gns_cache[fn] = arr
        else:
          self.gns_cache[fn] = np.zeros((0, 2), dtype=np.float64)
      if self.gns_cache[fn].shape[0] > 0:
        arrays.append(self.gns_cache[fn])

    # Return statement
    return np.vstack(arrays) if arrays else np.zeros((0, 2), dtype=np.float64)

  def _partition_domain_kriging (self, arg1_polities, arg2_host_domain, arg3_cfg, arg4_allow_bg):
    """Run Kriging + 3x3 majority smoothing + seat-locked 4-connectivity + chain polygonisation.

    @param arg1_polities List of catalog dicts competing inside arg2_host_domain.
    @param arg2_host_domain Clean clipping Shapely Polygon/MultiPolygon.
    @param arg3_cfg Cluster or Tier B config dict.
    @param arg4_allow_bg True if external background class K is enabled.
    @return Tuple (geoms_dict, n_grid_pts, n_samples, n_river_segs).
    """
    # Convert from parameters
    allow_bg = bool(arg4_allow_bg)
    cfg = arg3_cfg
    host_domain = arg2_host_domain
    polities = list(arg1_polities)

    # Declare local instance variables.
    h = 0
    in_dom = None
    k_pol = len(polities)
    labels = None
    max_r = float(cfg.get("max_radius_deg") or 0.0)
    minx, miny, maxx, maxy = host_domain.bounds
    seat_pts = [(float(t["seat_lon"]), float(t["seat_lat"])) for t in polities]
    seat_rc = []
    step = float(cfg.get("grid_step_deg") or 0.01)
    w = 0

    w = max(4, int(np.ceil((maxx - minx) / step)) + 2)
    h = max(4, int(np.ceil((maxy - miny) / step)) + 2)
    x0 = minx
    y0 = miny
    xs = x0 + np.arange(w)*step
    ys = y0 + np.arange(h)*step
    gx, gy = np.meshgrid(xs, ys)
    in_centres = shapely.contains_xy(host_domain, gx.ravel(), gy.ravel()).reshape(h, w)
    in_dom = ndimage.binary_dilation(in_centres, structure=np.ones((3, 3), dtype=bool)) if not allow_bg else in_centres.copy()

    for sx, sy in seat_pts:
      sc = min(w - 1, max(0, int(np.floor((sx - (x0 - 0.5*step)) / step))))
      sr = min(h - 1, max(0, int(np.floor((sy - (y0 - 0.5*step)) / step))))
      seat_rc.append((sr, sc))
      in_dom[sr, sc] = True

    grid_xy = np.column_stack([gx[in_dom], gy[in_dom]])
    samples_xy, z_mat, _ = self._collect_cluster_samples(polities, host_domain, cfg, allow_bg)
    rsegs = self._compute_river_segments(cfg.get("barrier_rivers", []), host_domain.bounds)

    scores = self._solve_ordinary_kriging(samples_xy, z_mat, grid_xy, rsegs, cfg)
    if allow_bg and max_r > 0.0:
      for i, t in enumerate(polities):
        t_pts = [(float(t["seat_lon"]), float(t["seat_lat"]))]
        for ks in t.get("known_settlements", []):
          kx, ky = float(ks[0]), float(ks[1])
          if host_domain.distance(Point(kx, ky)) <= 0.15:
            t_pts.append((kx, ky))
        t_arr = np.asarray(t_pts, dtype=np.float64)
        d_min = np.min(np.hypot(grid_xy[:, 0:1] - t_arr[None, :, 0], grid_xy[:, 1:2] - t_arr[None, :, 1]), axis=1)
        scores[i, d_min > max_r] = -1e9

    pred_flat = np.argmax(scores, axis=0).astype(np.int32)
    labels = np.full((h, w), -1, dtype=np.int32)
    labels[in_dom] = pred_flat

    labels = gis_helpers.smooth_discrete_partition(labels, in_dom, seat_rc, k_pol, allow_bg, 3)
    labels = gis_helpers.extract_seat_connected_partition(labels, in_dom, seat_rc, k_pol, allow_bg)

    grid_meta = {"step": step, "x0": x0, "y0": y0}
    poly_map = gis_helpers.polygonize_smoothed_partition(labels, grid_meta, host_domain, seat_pts, k_pol, allow_bg)
    out_geoms = {}
    for i, t in enumerate(polities):
      if i in poly_map and poly_map[i] is not None and not poly_map[i].is_empty:
        out_geoms[t["tusi_id"]] = poly_map[i]

    # Return statement
    return out_geoms, int(grid_xy.shape[0]), int(samples_xy.shape[0]), int(rsegs.shape[0])

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
      recs = list(sf.records())

    if not pts:
      return arr, recs

    arr = np.asarray(pts, dtype=np.float64)
    if abs(arr[0, 0]) > 360.0 or abs(arr[0, 1]) > 90.0:
      arr = np.asarray(gis_helpers.gk19_array_to_lonlat(arr), dtype=np.float64)

    # Return statement
    return arr, recs

  def _resolve_all_overlaps (self, arg1_tusi_geoms, arg2_tusi_by_id):
    """Round all 425 polygons to 5 decimals and resolve every pairwise overlap sliver.

    @param arg1_tusi_geoms Dict mapping tusi_id to Shapely polygon.
    @param arg2_tusi_by_id Dict mapping tusi_id to catalog entry.
    @return Tuple (cleaned_dict, max_overlap_deg2, overlap_pairs_list).
    """
    # Convert from parameters
    tusi_by_id = arg2_tusi_by_id
    tusi_geoms = arg1_tusi_geoms

    # Declare local instance variables.
    buf_eps = 1.2*(10.0**(-self.precision))
    cleaned = {}
    tier_prio = {"tier_a": 0, "tier_b": 1, "tier_c": 2}
    ordered_ids = sorted(tusi_geoms.keys(), key=lambda tid: (tier_prio.get(self.tier_map.get(tid, "tier_c"), 2), tid))

    for tid in ordered_ids:
      g = gis_helpers.round_geometry(tusi_geoms[tid], self.precision)
      if g is not None and not g.is_empty:
        if self.tier_map.get(tid) != "tier_a":
          if g.geom_type == "MultiPolygon":
            sp = Point(float(tusi_by_id[tid]["seat_lon"]), float(tusi_by_id[tid]["seat_lat"]))
            g = next((sub for sub in g.geoms if sub.contains(sp) or sub.distance(sp) < 1e-9), max(g.geoms, key=lambda s: s.area))
          if g.geom_type == "Polygon" and len(g.interiors) > 0:
            g = Polygon(g.exterior, [r for r in g.interiors if Polygon(r).area >= 0.002])
        cleaned[tid] = g

    for pass_i in range(6):
      changed = False
      for i in range(len(ordered_ids)):
        tid_a = ordered_ids[i]
        if tid_a not in cleaned:
          continue
        ga = cleaned[tid_a]
        pa = tier_prio.get(self.tier_map.get(tid_a, "tier_c"), 2)
        for x in range(i + 1, len(ordered_ids)):
          tid_b = ordered_ids[x]
          if tid_b not in cleaned:
            continue
          gb = cleaned[tid_b]
          if ga.bounds[0] > gb.bounds[2] or gb.bounds[0] > ga.bounds[2] or ga.bounds[1] > gb.bounds[3] or gb.bounds[1] > ga.bounds[3]:
            continue
          if ga.intersects(gb) and ga.intersection(gb).area > 1e-11:
            changed = True
            pb = tier_prio.get(self.tier_map.get(tid_b, "tier_c"), 2)
            trim_b = (pb > pa) or (pb == pa and gb.area >= ga.area)
            keep_g, trim_id = (ga, tid_b) if trim_b else (gb, tid_a)
            cut_g = keep_g if pass_i == 0 else keep_g.buffer(buf_eps, join_style="mitre")
            rem = gis_helpers.round_geometry(cleaned[trim_id].difference(cut_g), self.precision)
            if rem is not None and not rem.is_empty:
              if rem.geom_type == "MultiPolygon" and self.tier_map.get(trim_id) != "tier_a":
                sp = Point(float(tusi_by_id[trim_id]["seat_lon"]), float(tusi_by_id[trim_id]["seat_lat"]))
                rem = next((sub for sub in rem.geoms if sub.contains(sp) or sub.distance(sp) < 1e-9), max(rem.geoms, key=lambda s: s.area))
              if rem.geom_type == "Polygon" and len(rem.interiors) > 0 and self.tier_map.get(trim_id) != "tier_a":
                rem = Polygon(rem.exterior, [r for r in rem.interiors if Polygon(r).area >= 0.002])
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

  def _segments_cross_rivers (self, arg1_pts_a, arg2_pts_b, arg3_river_segs):
    """Vectorised test whether straight segments from pts_a (N,2) to pts_b (G,2) cross any river segment.

    @param arg1_pts_a Array of shape (N, 2).
    @param arg2_pts_b Array of shape (G, 2).
    @param arg3_river_segs Array of shape (R, 4) with [x1, y1, x2, y2].
    @return Boolean matrix of shape (N, G).
    """
    # Convert from parameters
    pts_a = arg1_pts_a
    pts_b = arg2_pts_b
    rsegs = arg3_river_segs

    n_a, n_b = pts_a.shape[0], pts_b.shape[0]
    if rsegs.shape[0] == 0 or n_a == 0 or n_b == 0:
      return np.zeros((n_a, n_b), dtype=bool)

    # Declare local instance variables.
    ax, ay = pts_a[:, 0:1], pts_a[:, 1:2]
    bx, by = pts_b[None, :, 0], pts_b[None, :, 1]
    chunk = 25
    cross_mat = np.zeros((n_a, n_b), dtype=bool)
    ab_minx, ab_maxx = np.minimum(ax, bx), np.maximum(ax, bx)
    ab_miny, ab_maxy = np.minimum(ay, by), np.maximum(ay, by)

    for i in range(0, rsegs.shape[0], chunk):
      sub_r = rsegs[i:i + chunk]
      cx, cy = sub_r[:, 0][:, None, None], sub_r[:, 1][:, None, None]
      dx, dy = sub_r[:, 2][:, None, None], sub_r[:, 3][:, None, None]
      bbox_ok = (
        (ab_maxx[None, :, :] >= np.minimum(cx, dx)) & (np.maximum(cx, dx) >= ab_minx[None, :, :])
        & (ab_maxy[None, :, :] >= np.minimum(cy, dy)) & (np.maximum(cy, dy) >= ab_miny[None, :, :])
      )
      if not np.any(bbox_ok):
        continue
      abx, aby = (bx - ax)[None, :, :], (by - ay)[None, :, :]
      cdx, cdy = dx - cx, dy - cy
      o1 = abx*(cy - ay[None, :, :]) - aby*(cx - ax[None, :, :])
      o2 = abx*(dy - ay[None, :, :]) - aby*(dx - ax[None, :, :])
      o3 = cdx*(ay[None, :, :] - cy) - cdy*(ax[None, :, :] - cx)
      o4 = cdx*(by[None, :, :] - cy) - cdy*(bx[None, :, :] - cx)
      cross_mat |= np.any(bbox_ok & ((o1*o2) < 0.0) & ((o3*o4) < 0.0), axis=0)

    # Return statement
    return cross_mat

  def _solve_ordinary_kriging (self, arg1_samples_xy, arg2_z_mat, arg3_grid_xy, arg4_river_segs, arg5_cfg):
    """Solve Ordinary Indicator Kriging via scipy.linalg.solve with river-barrier and road-corridor modulation.

    @param arg1_samples_xy Sample coordinates array (N, 2).
    @param arg2_z_mat Indicator matrix (N, K_eff).
    @param arg3_grid_xy Grid pixel coordinates (G, 2).
    @param arg4_river_segs River barrier segments (R, 4).
    @param arg5_cfg Cluster/Tier-B configuration dict.
    @return Indicator scores matrix of shape (K_eff, G).
    """
    # Convert from parameters
    cfg = arg5_cfg
    grid_xy = arg3_grid_xy
    rsegs = arg4_river_segs
    samples_xy = arg1_samples_xy
    z_mat = arg2_z_mat

    # Declare local instance variables.
    c0 = float(self.config.get("variogram_nugget") or 0.04)
    c1 = float(self.config.get("variogram_sill") or 1.0) - c0
    n_pts = samples_xy.shape[0]
    n_grid = grid_xy.shape[0]
    k_eff = z_mat.shape[1]
    r_pen = float(cfg.get("river_penalty_deg") or 0.30)
    rng = float(cfg.get("variogram_range_deg") or 0.50)
    road_boost = float(self.config.get("road_boost_factor") or 0.85)
    road_corridor = float(self.config.get("road_corridor_deg") or 0.14)

    d_ss = np.hypot(samples_xy[:, 0:1] - samples_xy[None, :, 0], samples_xy[:, 1:2] - samples_xy[None, :, 1])
    if rsegs.shape[0] > 0:
      d_ss = d_ss + r_pen*self._segments_cross_rivers(samples_xy, samples_xy, rsegs).astype(np.float64)

    c_ss = c1*np.exp(-1.5*(d_ss / rng))
    np.fill_diagonal(c_ss, c0 + c1 + 1e-6)

    k_mat = np.ones((n_pts + 1, n_pts + 1), dtype=np.float64)
    k_mat[:n_pts, :n_pts] = c_ss
    k_mat[n_pts, n_pts] = 0.0

    # Solve augmented system once for all indicators + unbiasedness constraint
    aug_z = np.vstack([z_mat, np.zeros((1, k_eff), dtype=np.float64)])
    dual_w = linalg.solve(k_mat, aug_z, assume_a="sym")[:n_pts, :]

    road_mask = np.zeros(n_grid, dtype=bool)
    if self.road_tree_pts is not None and self.road_tree_pts.shape[0] > 0 and n_grid > 0:
      minx, miny = float(np.min(grid_xy[:, 0])) - 0.3, float(np.min(grid_xy[:, 1])) - 0.3
      maxx, maxy = float(np.max(grid_xy[:, 0])) + 0.3, float(np.max(grid_xy[:, 1])) + 0.3
      rmask = (
        (self.road_tree_pts[:, 0] >= minx) & (self.road_tree_pts[:, 0] <= maxx)
        & (self.road_tree_pts[:, 1] >= miny) & (self.road_tree_pts[:, 1] <= maxy)
      )
      sub_r = self.road_tree_pts[rmask]
      if sub_r.shape[0] > 0:
        for i in range(0, n_grid, 4000):
          sub_g = grid_xy[i:i + 4000]
          d_rd = np.min(np.hypot(sub_g[:, 0:1] - sub_r[None, :, 0], sub_g[:, 1:2] - sub_r[None, :, 1]), axis=1)
          road_mask[i:i + 4000] = (d_rd <= road_corridor)

    scores = np.zeros((k_eff, n_grid), dtype=np.float64)
    z_mean = np.mean(z_mat, axis=0)[:, None]
    for i in range(0, n_grid, 2000):
      sub_g = grid_xy[i:i + 2000]
      d_sg = np.hypot(samples_xy[:, 0:1] - sub_g[None, :, 0], samples_xy[:, 1:2] - sub_g[None, :, 1])
      if rsegs.shape[0] > 0:
        d_sg = d_sg + r_pen*self._segments_cross_rivers(samples_xy, sub_g, rsegs).astype(np.float64)
      d_sg[:, road_mask[i:i + 2000]] *= road_boost
      c_sg = c1*np.exp(-1.5*(d_sg / rng))
      scores[:, i:i + 2000] = (dual_w.T @ c_sg) + z_mean*(1.0 - np.sum(c_sg, axis=0, keepdims=True) / (c0 + c1))

    # Return statement
    return scores

  def _validate_all_assertions (self, arg1_tusi_geoms, arg2_max_ov, arg3_ov_pairs):
    """Enforce all hard topological, seat-containment, and hole assertions on final geometries.

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
          hole_issues.append((tid, len(g.interiors)))

    print(
      f"[STEP 2 VALIDATE] total={len(tusi_geoms)}/{len(self.tusis)} "
      f"seats_inside={seat_inside_cnt}/{len(self.tusis)} "
      f"kriged_multiparts={len(multipart_issues)} kriged_holes={len(hole_issues)} "
      f"overlaps(>1e-9)={len(ov_pairs)} max_ov={max_ov:.9f}"
    )
    assert not seat_issues, f"Seats outside polygons: {seat_issues[:10]}"
    assert not multipart_issues, f"Multi-part kriged polygons: {multipart_issues[:10]}"
    assert not hole_issues, f"Interior holes in kriged polygons: {hole_issues[:10]}"
    assert not ov_pairs, f"Pairwise overlaps > 1e-9: {ov_pairs[:10]}"

    # Return statement
    return {"kriged_holes": len(hole_issues), "kriged_multiparts": len(multipart_issues), "seats_inside": seat_inside_cnt, "total": len(tusi_geoms)}

  def build_all_tusis (self):
    """Execute the three-tier spatial pipeline for all 425 polities and verify assertions.

    @return Summary metrics dict.
    """
    # Declare local instance variables.
    direct_geoms, tier_a_union = self._build_tier_a_direct()
    excluded_parts = [tier_a_union] if tier_a_union is not None else []
    raw_geoms = dict(direct_geoms)
    tier_b_geoms = {}
    tier_c_geoms = {}

    for tb_cfg in self.config.get("tier_b_clusters", []):
      parent_poly, b_part = self._build_tier_b_subdivided(tb_cfg)
      excluded_parts.append(parent_poly)
      tier_b_geoms.update(b_part)
      raw_geoms.update(b_part)

    excluded_union = gis_helpers.clean_polygonal_geometry(unary_union(excluded_parts))

    # Assign remaining Tier C kriging_modelled polities strictly to disjoint clusters
    tier_c_candidates = [t for t in self.tusis if t.get("geometry_mode") == "kriging_modelled" and t["tusi_id"] not in tier_b_geoms]
    cluster_doms = {}
    for cl in self.config.get("kriging_clusters", []):
      huids = [self.adm3_map[u] for u in cl.get("host_unit_ids", []) if u in self.adm3_map]
      cluster_doms[cl["cluster_id"]] = unary_union(huids) if huids else None

    assigned_c = {cl["cluster_id"]: [] for cl in self.config.get("kriging_clusters", [])}
    for t in tier_c_candidates:
      sp = Point(float(t["seat_lon"]), float(t["seat_lat"]))
      hit_cid = next((cl["cluster_id"] for cl in self.config.get("kriging_clusters", []) if cluster_doms[cl["cluster_id"]] is not None and cluster_doms[cl["cluster_id"]].contains(sp)), None)
      if hit_cid is None:
        print(f"[ERROR] Tier C polity {t['tusi_id']} unmapped to any cluster", file=sys.stderr)
        continue
      assigned_c[hit_cid].append(t)

    for cl in self.config.get("kriging_clusters", []):
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
    return {
      "chgis_direct": len(direct_geoms), "kriging_modelled": len(tier_b_geoms) + len(tier_c_geoms),
      "max_overlap_deg2": max_ov, "overlap_pairs": ov_pairs, "tier_b": len(tier_b_geoms),
      "tier_c": len(tier_c_geoms), "total": val_summary["total"], "validation": val_summary,
    }

  def export_geojson (self):
    """Write all 425 modelled polity features to ./gis/tusi_1912_1953.geojson (WGS84, 5 decimals).

    @return Tuple (output_filepath, feature_count).
    """
    # Declare local instance variables.
    out_features = []
    out_path = os.path.join(self.gis_dir, "tusi_1912_1953.geojson")

    for t in self.tusis:
      tid = t["tusi_id"]
      geom = self.tusi_geoms.get(tid)
      if geom is None or geom.is_empty:
        continue
      props = {
        "abolition_note": t.get("abolition_note", ""), "chgis_unit_ids": t.get("chgis_unit_ids", []),
        "de_facto_end_year": int(t.get("de_facto_end_year", t["end_year"])), "de_facto_start_year": int(t.get("de_facto_start_year", t["start_year"])),
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

  def render_diagnostic_maps (self):
    """Render all 6 regional & overview diagnostic PNG verification maps in ./tests/.

    @return List of generated PNG filepaths.
    """
    os.makedirs(self.tests_dir, exist_ok=True)
    generated = []

    def iter_polys (g):
      return [g] if g.geom_type == "Polygon" else (list(g.geoms) if g.geom_type == "MultiPolygon" else [])

    def iter_lines (g):
      return [g] if g.geom_type == "LineString" else (list(g.geoms) if g.geom_type == "MultiLineString" else [])

    for mcfg in self.config.get("diagnostic_maps", []):
      minx, maxx, miny, maxy = [float(v) for v in mcfg["extent"]]
      vp_box = box(minx, miny, maxx, maxy)
      year_flt = mcfg.get("active_year_filter")
      is_overview = (year_flt is not None or (maxx - minx) > 25.0)
      fig, ax = plt.subplots(figsize=(14.5, 10.5), dpi=210)
      ax.set_facecolor("#e9f0f5")

      for feat in self.adm1_features:
        g = shape(feat["geometry"])
        if g.intersects(vp_box):
          for poly in iter_polys(g):
            ax.fill(*poly.exterior.xy, facecolor="#f4f1ea", edgecolor="#5c5c5c", linewidth=0.95, zorder=1)
      if not is_overview:
        for feat in self.adm3_features:
          g = shape(feat["geometry"])
          if g.intersects(vp_box):
            for poly in iter_polys(g):
              ax.plot(*poly.exterior.xy, color="#d4cfc4", linewidth=0.3, zorder=2)
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
        if geom.area >= (0.75 if is_overview else 0.012) and minx <= rp.x <= maxx and miny <= rp.y <= maxy:
          short_name = t["name_en"].split("(")[0].strip()
          short_name = short_name[:16] + ".." if len(short_name) > 18 else short_name
          raw_labels.append([rp.x, rp.y, rp.x, rp.y, short_name if is_overview else f"{short_name}\n[{tid}]"])

      min_dx, min_dy = 0.065*(maxx - minx), 0.028*(maxy - miny)
      for _ in range(20):
        for i in range(len(raw_labels)):
          for x in range(i + 1, len(raw_labels)):
            dx, dy = raw_labels[i][0] - raw_labels[x][0], raw_labels[i][1] - raw_labels[x][1]
            if abs(dx) < min_dx and abs(dy) < min_dy:
              px_off, py_off = (0.14*min_dx if dx >= 0.0 else -0.14*min_dx), (0.24*min_dy if dy >= 0.0 else -0.24*min_dy)
              for sgn, idx in ((1.0, i), (-1.0, x)):
                raw_labels[idx][0] = min(maxx - 0.3, max(minx + 0.3, raw_labels[idx][0] + sgn*px_off))
                raw_labels[idx][1] = min(maxy - 0.15, max(miny + 0.15, raw_labels[idx][1] + sgn*py_off))
      for lx, ly, ox, oy, txt in raw_labels:
        if np.hypot(lx - ox, ly - oy) > (0.45 if is_overview else 0.14):
          ax.plot([ox, lx], [oy, ly], color="#333333", linewidth=0.4, alpha=0.6, zorder=9)
        ax.text(lx, ly, txt, fontsize=4.5 if is_overview else 3.8, ha="center", va="center", color="#141414", fontweight="semibold", zorder=10, path_effects=[patheffects.withStroke(linewidth=1.5, foreground="#ffffff", alpha=0.9)])

      ax.set_xlim(minx, maxx)
      ax.set_ylim(miny, maxy)
      ax.set_aspect(1.0 / np.cos(np.deg2rad(0.5*(miny + maxy))))
      ax.grid(True, linestyle=":", linewidth=0.45, color="#999999", alpha=0.6)
      ax.set_xlabel("Longitude (WGS84)", fontsize=9)
      ax.set_ylabel("Latitude (WGS84)", fontsize=9)
      ax.set_title(mcfg["title"], fontsize=11.0, fontweight="bold", pad=10)
      ax.legend(handles=[
        Patch(facecolor="#88c999", edgecolor="#1a3b2a", linewidth=0.9, label="chgis_direct (CHGIS 1911 Surveyed)"),
        Patch(facecolor="#e8a47c", edgecolor="#6b1b1b", linewidth=1.1, label="kriging_modelled (Tier B/C Partition)"),
        Line2D([0], [0], color="#1f68a8", linewidth=1.5, label="Major Rivers"),
        Line2D([0], [0], color="#9e7b56", linewidth=0.8, linestyle="--", label="Historical Roads"),
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#f5d142", markeredgecolor="#111111", markersize=9, label="Tusi Seat (*)"),
      ], loc=mcfg.get("legend_loc", "lower left"), fontsize=7.5, framealpha=0.92)

      out_png = os.path.join(self.tests_dir, mcfg["filename"])
      fig.tight_layout()
      fig.savefig(out_png, dpi=210)
      plt.close(fig)
      generated.append(out_png)
      print(f"[STEP 2] Rendered diagnostic PNG: {out_png}")

    # Return statement
    return generated


def main ():
  """Execute Step 2 425-polity Tusi spatial modelling, GeoJSON export, and 6 diagnostic maps."""
  base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
  modeller = TusiModeller(base_dir)
  metrics = modeller.build_all_tusis()
  out_geojson, feat_count = modeller.export_geojson()
  pngs = modeller.render_diagnostic_maps()

  print(
    f"[STEP 2 DONE] features={feat_count} (direct={metrics['chgis_direct']}, "
    f"tier_b={metrics['tier_b']}, tier_c={metrics['tier_c']}) "
    f"max_overlap_deg2={metrics['max_overlap_deg2']:.9f} overlaps={len(metrics['overlap_pairs'])} "
    f"geojson={out_geojson} pngs={len(pngs)}"
  )
  return 0 if feat_count == 425 and len(metrics["overlap_pairs"]) == 0 else 1


if __name__ == "__main__":
  sys.exit(main())
