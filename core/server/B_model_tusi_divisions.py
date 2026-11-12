"""Step 2 pipeline: build watertight 1912-1953 Tusi polygons via CHGIS direct union and hydrology-modulated Ordinary Kriging."""

import hashlib
import io
import json
import os
import sys
import zipfile
import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as patheffects
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
from scipy.linalg import solve as linalg_solve
import shapefile
import shapely
from shapely import contains_xy, set_precision
from shapely.geometry import MultiPolygon, Point, box, shape
from shapely.ops import split, unary_union
from shapely.prepared import prep

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gis_helpers


class TusiModeller:
  """Constructs watertight 1912-1953 Tusi polygons and regional diagnostic maps."""

  def __init__ (self, arg1_base_dir):
    """Initialise TusiModeller with catalog, modelling config, CHGIS baselines, and gazetteers.

    @param arg1_base_dir Project root directory.
    """
    # Convert from parameters
    base_dir = os.path.abspath(arg1_base_dir)

    # Declare local instance variables.
    self.adm1_features = []
    self.adm3_by_id = {}
    self.adm3_features = []
    self.base_dir = base_dir
    self.catalog = gis_helpers.load_json5(os.path.join(base_dir, "common", "tusi", "tusi_catalog.json5"))
    self.config = gis_helpers.load_json5(os.path.join(base_dir, "common", "tusi", "tusi_modelling_config.json5"))
    self.ds_cfg = gis_helpers.load_json5(os.path.join(base_dir, "common", "gis", "data_sources.json5"))
    self.gis_dir = os.path.join(base_dir, "gis")
    self.gns_cache = {}
    self.precision = int(self.ds_cfg.get("coordinate_precision", 5))
    self.road_pts = np.empty((0, 2), dtype=np.float64)
    self.roads = []
    self.sources_dir = os.path.join(self.gis_dir, "sources")
    self.tests_dir = os.path.join(base_dir, "tests")
    self.tusi_geoms = {}
    self.tusis = self.catalog.get("tusis", [])
    self.twn_pts = np.empty((0, 2), dtype=np.float64)
    self.waterways = []

    self._load_base_layers()

  def _assign_corridor_flags (self, arg1_pts_xy, arg2_road_pts, arg3_radius):
    """Identify points lying within arg3_radius degrees of historical road corridors.

    @param arg1_pts_xy (N, 2) array of [lon, lat] points.
    @param arg2_road_pts (R, 2) array of sampled road vertex [lon, lat] points.
    @param arg3_radius Corridor proximity radius in degrees.
    @return Boolean NumPy array of shape (N,).
    """
    # Convert from parameters
    pts_xy = arg1_pts_xy
    radius = float(arg3_radius)
    road_pts = arg2_road_pts

    if pts_xy.shape[0] == 0 or road_pts.shape[0] == 0:
      return np.zeros(pts_xy.shape[0], dtype=bool)

    # Declare local instance variables.
    chunk = 800
    cos_lat = np.cos(np.deg2rad(np.mean(pts_xy[:, 1])))
    n_pts = pts_xy.shape[0]
    out_flags = np.zeros(n_pts, dtype=bool)
    r2 = radius*radius

    for i in range(0, n_pts, chunk):
      sub = pts_xy[i:i + chunk]
      dx = (sub[:, 0:1] - road_pts[None, :, 0])*cos_lat
      dy = sub[:, 1:2] - road_pts[None, :, 1]
      out_flags[i:i + chunk] = np.min(dx*dx + dy*dy, axis=1) <= r2

    # Return statement
    return out_flags

  def _build_chgis_direct (self):
    """Build exact dissolved polygons for all chgis_direct catalog entries.

    @return Tuple of (dict mapping tusi_id to Shapely geometry, union geometry of all direct Tusis).
    """
    # Declare local instance variables.
    direct_geoms = {}
    direct_list = []

    for t in self.tusis:
      if t.get("geometry_mode") != "chgis_direct":
        continue
      parts = [self.adm3_by_id[cid] for cid in t.get("chgis_unit_ids", []) if cid in self.adm3_by_id]
      if not parts:
        print(f"[WARN] Missing CHGIS geometry for {t['tusi_id']}", file=sys.stderr)
        continue
      merged = parts[0] if len(parts) == 1 else unary_union(parts)
      cleaned = gis_helpers.round_geometry(gis_helpers.clean_polygonal_geometry(merged), self.precision)
      if cleaned is not None and not cleaned.is_empty:
        direct_geoms[t["tusi_id"]] = cleaned
        direct_list.append(cleaned)

    direct_union = gis_helpers.clean_polygonal_geometry(unary_union(direct_list)) if direct_list else None

    # Return statement
    return direct_geoms, direct_union

  def _build_host_domain (self, arg1_cluster, arg2_direct_union):
    """Build clipped host frontier polygon domain for a Kriging cluster.

    @param arg1_cluster Cluster configuration dict.
    @param arg2_direct_union Union geometry of all chgis_direct Tusis to exclude.
    @return Clean Shapely host Polygon/MultiPolygon.
    """
    # Convert from parameters
    cluster = arg1_cluster
    direct_union = arg2_direct_union

    # Declare local instance variables.
    clip_map = cluster.get("clip_unit_bbox", {})
    parts = []

    for uid in cluster.get("host_unit_ids", []):
      g = self.adm3_by_id.get(uid)
      if g is not None and uid in clip_map:
        bb = clip_map[uid]
        g = gis_helpers.clean_polygonal_geometry(g.intersection(box(bb[0], bb[1], bb[2], bb[3])))
      if g is not None and not g.is_empty:
        parts.append(g)

    if not parts:
      return None

    domain = gis_helpers.clean_polygonal_geometry(unary_union(parts))
    if domain is None or domain.is_empty:
      return None

    for key, mode in (("split_east_of_river", "east"), ("split_southwest_of_river", "southwest"), ("clip_south_of_river", "south")):
      if key in cluster:
        domain = self._split_domain_by_river(domain, cluster[key], mode)

    if direct_union is not None and domain is not None and not domain.is_empty:
      domain = gis_helpers.clean_polygonal_geometry(domain.difference(direct_union))

    # Return statement
    return domain

  def _collect_cluster_samples (self, arg1_cluster, arg2_domain, arg3_tusi_by_id, arg4_river_segs):
    """Collect verified seat, known_settlement, CHGIS town, GNS, and background Z=0 sample points.

    @param arg1_cluster Cluster configuration dict.
    @param arg2_domain Host Shapely polygon domain.
    @param arg3_tusi_by_id Map from tusi_id to catalog entry dict.
    @param arg4_river_segs (R, 4) array of barrier river segments.
    @return Tuple (samples_xy, z_matrix, class_ids, has_bg).
    """
    # Convert from parameters
    cluster = arg1_cluster
    domain = arg2_domain
    river_segs = arg4_river_segs
    tusi_by_id = arg3_tusi_by_id

    # Declare local instance variables.
    allow_bg = bool(cluster.get("allow_background", True))
    bg_excl = float(cluster.get("bg_exclude_radius_deg", 0.25))
    bg_seeds = [(float(b[0]), float(b[1])) for b in cluster.get("bg_seeds", [])]
    defaults = self.config["kriging_defaults"]
    dom_prep = prep(domain)
    max_bg = int(defaults.get("max_bg_pts", 36))
    max_sup = int(defaults.get("max_support_pts_per_tusi", 8))
    minx, miny, maxx, maxy = domain.bounds
    raw_samples = []
    seats_xy = {tid: (float(tusi_by_id[tid]["seat_lon"]), float(tusi_by_id[tid]["seat_lat"])) for tid in cluster["tusi_ids"]}
    tusi_ids = cluster["tusi_ids"]

    # 1. Add Tusi seats and exclusive known_settlements
    for k, tid in enumerate(tusi_ids):
      sx, sy = seats_xy[tid]
      raw_samples.append((sx, sy, k))
      for pt_row in tusi_by_id[tid].get("known_settlements", []):
        kx, ky = float(pt_row[0]), float(pt_row[1])
        near_other = any(ot != tid and np.hypot(kx - ox, ky - oy) < 0.035 for ot, (ox, oy) in seats_xy.items())
        if not near_other:
          crosses_own = self._segments_cross_rivers(np.array([[sx, sy]]), np.array([[kx, ky]]), river_segs)[0, 0]
          if not crosses_own or dom_prep.contains(Point(kx, ky)):
            raw_samples.append((kx, ky, k))

    # 2. Gather candidate CHGIS 1911 towns + GNS populated places inside domain
    cand_pts = []
    for src_arr in [self.twn_pts] + [self._load_gns_points(fn) for fn in cluster.get("gns_files", [])]:
      if src_arr.shape[0] == 0:
        continue
      mask = (
        (src_arr[:, 0] >= minx - 0.1) & (src_arr[:, 0] <= maxx + 0.1)
        & (src_arr[:, 1] >= miny - 0.1) & (src_arr[:, 1] <= maxy + 0.1)
      )
      for pt in src_arr[mask]:
        if dom_prep.contains(Point(float(pt[0]), float(pt[1]))):
          cand_pts.append((float(pt[0]), float(pt[1])))

    # 3. Assign up to max_sup nearest unblocked support points per Tusi
    tusi_anchors = [(k, seats_xy[tid][0], seats_xy[tid][1]) for k, tid in enumerate(tusi_ids)]
    for k, tid in enumerate(tusi_ids):
      sx, sy = seats_xy[tid]
      scored = []
      for cx, cy in cand_pts:
        d_own = np.hypot(cx - sx, cy - sy)
        if d_own > 0.14 or d_own < 0.01:
          continue
        closest_other = min(
          [np.hypot(cx - ox, cy - oy) for ok, ox, oy in tusi_anchors if ok != k]
          + [np.hypot(cx - bx, cy - by) for bx, by in bg_seeds]
          + [999.0]
        )
        if d_own + 0.015 < closest_other and not self._segments_cross_rivers(np.array([[sx, sy]]), np.array([[cx, cy]]), river_segs)[0, 0]:
          scored.append((d_own, cx, cy))
      scored.sort(key=lambda r: r[0])
      for _, cx, cy in scored[:max_sup]:
        raw_samples.append((cx, cy, k))

    # 4. Background class (non-Tusi regular county settlements)
    bg_class = len(tusi_ids)
    has_bg = False
    use_distant = bool(cluster.get("use_distant_towns_as_bg", True))
    if allow_bg and (bg_seeds or (use_distant and cand_pts)):
      has_bg = True
      tusi_pts_xy = [(rx, ry) for rx, ry, _ in raw_samples]
      for bx, by in bg_seeds:
        raw_samples.append((bx, by, bg_class))
      if use_distant:
        bg_cands = [(min(np.hypot(cx - tx, cy - ty) for tx, ty in tusi_pts_xy), cx, cy) for cx, cy in cand_pts]
        bg_cands = [row for row in bg_cands if row[0] >= bg_excl]
        if bg_cands:
          step_pick = max(1, len(bg_cands) // max_bg)
          for i in range(0, len(bg_cands), step_pick):
            raw_samples.append((bg_cands[i][1], bg_cands[i][2], bg_class))

    # 5. Deduplicate points closer than 0.006 deg so Kriging matrix is well-conditioned
    dedup_xy = []
    dedup_cls = []
    for rx, ry, cls_id in raw_samples:
      if not any(np.hypot(rx - dx, ry - dy) < 0.006 for dx, dy in dedup_xy):
        dedup_xy.append([rx, ry])
        dedup_cls.append(cls_id)

    z_mat = np.zeros((len(dedup_xy), len(tusi_ids) + (1 if has_bg else 0)), dtype=np.float64)
    for i, cls_id in enumerate(dedup_cls):
      z_mat[i, cls_id] = 1.0

    # Return statement
    return np.asarray(dedup_xy, dtype=np.float64), z_mat, tusi_ids, has_bg

  def _compute_river_segments (self, arg1_cluster, arg2_bounds):
    """Extract barrier river line segments within padded cluster bounds as an (R, 4) array.

    @param arg1_cluster Cluster configuration dict.
    @param arg2_bounds Bounding box tuple (minx, miny, maxx, maxy).
    @return NumPy array of shape (R, 4) with [x1, y1, x2, y2].
    """
    # Convert from parameters
    bounds = arg2_bounds
    cluster = arg1_cluster

    # Declare local instance variables.
    clip_box = box(bounds[0] - 0.5, bounds[1] - 0.5, bounds[2] + 0.5, bounds[3] + 0.5)
    segs = []
    tokens = [tok.lower() for tok in cluster.get("barrier_rivers", [])]

    if not tokens:
      return np.empty((0, 4), dtype=np.float64)

    for props, geom in self.waterways:
      ne = str(props.get("name_en") or "").lower()
      if not any(tok in ne for tok in tokens) or not geom.intersects(clip_box):
        continue
      clipped = geom.intersection(clip_box)
      lines = [clipped] if clipped.geom_type == "LineString" else (
        [sub for sub in clipped.geoms if sub.geom_type == "LineString"]
        if clipped.geom_type in ("MultiLineString", "GeometryCollection") else []
      )
      for line in lines:
        coords = list(line.simplify(0.015, preserve_topology=False).coords)
        for i in range(len(coords) - 1):
          segs.append([coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1]])

    # Return statement
    return np.asarray(segs, dtype=np.float64) if segs else np.empty((0, 4), dtype=np.float64)

  def _extract_watertight_polygons (self, arg1_domain, arg2_grid_xy, arg3_step, arg4_winner, arg5_z_hat, arg6_tusi_ids):
    """Convert Kriging grid class assignments into smooth, zero-overlap polygons inside arg1_domain.

    @param arg1_domain Host Shapely polygon domain.
    @param arg2_grid_xy (G, 2) array of grid cell centres inside arg1_domain.
    @param arg3_step Grid spacing in degrees.
    @param arg4_winner Integer array of winning class indices (0..M-1 Tusis, M=background).
    @param arg5_z_hat (G, n_classes) array of Kriging indicator estimates.
    @param arg6_tusi_ids Ordered list of Tusi IDs in this cluster.
    @return Dictionary mapping tusi_id to clean Shapely polygon inside arg1_domain.
    """
    # Convert from parameters
    domain = arg1_domain
    grid_xy = arg2_grid_xy
    step = float(arg3_step)
    tusi_ids = arg6_tusi_ids
    winner = arg4_winner
    z_hat = arg5_z_hat

    # Declare local instance variables.
    half = 0.505*step
    placed_geoms = {}
    placed_union = None
    raw_polys = {}
    smooth_r = max(float(self.config["kriging_defaults"].get("smooth_buffer_deg", 0.032)), 0.85*step)

    for k, tid in enumerate(tusi_ids):
      idx_k = np.where(winner == k)[0]
      if idx_k.size == 0:
        idx_k = np.array([int(np.argmax(z_hat[:, k]))])
      cells = [box(float(grid_xy[i, 0]) - half, float(grid_xy[i, 1]) - half, float(grid_xy[i, 0]) + half, float(grid_xy[i, 1]) + half) for i in idx_k]
      merged = unary_union(cells)
      if smooth_r > 0.0 and merged.area > 0.008:
        smoothed = merged.buffer(smooth_r, quad_segs=6).buffer(-smooth_r, quad_segs=6)
        if smoothed is not None and not smoothed.is_empty and smoothed.area > 0.001:
          merged = smoothed.simplify(0.30*step, preserve_topology=True)
      clipped = gis_helpers.clean_polygonal_geometry(merged.intersection(domain))
      if clipped is not None and not clipped.is_empty:
        if clipped.geom_type == "MultiPolygon":
          parts = sorted(list(clipped.geoms), key=lambda p: p.area, reverse=True)
          keep = [parts[0]] + [p for p in parts[1:] if p.area >= 0.04*parts[0].area]
          clipped = keep[0] if len(keep) == 1 else MultiPolygon(keep)
        raw_polys[tid] = clipped

    # Resolve any overlap introduced by smoothing strictly via Z_hat priority
    for k, tid in enumerate(tusi_ids):
      geom = raw_polys.get(tid)
      if geom is None or geom.is_empty:
        continue
      if placed_union is not None and geom.intersects(placed_union):
        inter = gis_helpers.clean_polygonal_geometry(geom.intersection(placed_union))
        if inter is not None and inter.area > 1e-7:
          rep = inter.representative_point()
          g_idx = int(np.argmin(np.sum((grid_xy - np.array([rep.x, rep.y]))**2, axis=1)))
          if int(np.argmax(z_hat[g_idx, :len(tusi_ids)])) == k:
            for ot_tid in list(placed_geoms.keys()):
              if placed_geoms[ot_tid].intersects(inter):
                rem_ot = gis_helpers.clean_polygonal_geometry(placed_geoms[ot_tid].difference(inter))
                if rem_ot is not None:
                  placed_geoms[ot_tid] = rem_ot
            placed_geoms[tid] = geom
          else:
            rem = gis_helpers.clean_polygonal_geometry(geom.difference(placed_union))
            if rem is not None:
              placed_geoms[tid] = rem
        else:
          placed_geoms[tid] = geom
      else:
        placed_geoms[tid] = geom
      placed_union = gis_helpers.clean_polygonal_geometry(unary_union(list(placed_geoms.values())))

    # Fill tiny sliver gaps created by smoothing between adjacent Tusis
    tusi_grid_idx = np.where(winner < len(tusi_ids))[0]
    if tusi_grid_idx.size > 0 and placed_union is not None:
      tusi_raw = gis_helpers.clean_polygonal_geometry(unary_union([
        box(float(grid_xy[i, 0]) - half, float(grid_xy[i, 1]) - half, float(grid_xy[i, 0]) + half, float(grid_xy[i, 1]) + half)
        for i in tusi_grid_idx
      ]).intersection(domain))
      gaps = gis_helpers.clean_polygonal_geometry(tusi_raw.difference(placed_union)) if tusi_raw is not None else None
      if gaps is not None and not gaps.is_empty:
        for gp in ([gaps] if gaps.geom_type == "Polygon" else list(gaps.geoms)):
          if 1e-7 < gp.area <= 0.02:
            nbrs = [(pg.boundary.intersection(gp.boundary).length, tid) for tid, pg in placed_geoms.items() if pg.intersects(gp.buffer(1e-4))]
            if nbrs:
              best_tid = max(nbrs, key=lambda r: r[0])[1]
              mg = gis_helpers.clean_polygonal_geometry(unary_union([placed_geoms[best_tid], gp]))
              if mg is not None:
                placed_geoms[best_tid] = mg

    # Return statement
    return placed_geoms

  def _load_base_layers (self):
    """Load CHGIS 1911 boundaries, waterways, roads, and CHGIS 1911 town coordinates."""
    with open(os.path.join(self.gis_dir, "adm_1_1911.geojson"), "r", encoding="utf-8") as fh:
      self.adm1_features = json.load(fh).get("features", [])
    with open(os.path.join(self.gis_dir, "adm_3_1911.geojson"), "r", encoding="utf-8") as fh:
      self.adm3_features = json.load(fh).get("features", [])
    for feat in self.adm3_features:
      g = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
      if g is not None and not g.is_empty:
        self.adm3_by_id[feat["properties"]["unit_id"]] = g

    with open(os.path.join(self.gis_dir, "waterways_1912_1953.geojson"), "r", encoding="utf-8") as fh:
      for feat in json.load(fh).get("features", []):
        g = shape(feat["geometry"])
        if not g.is_empty:
          self.waterways.append((feat.get("properties", {}), g))

    road_pts_list = []
    with open(os.path.join(self.gis_dir, "roads_1912_1953.geojson"), "r", encoding="utf-8") as fh:
      for feat in json.load(fh).get("features", []):
        g = shape(feat["geometry"])
        if g.is_empty:
          continue
        self.roads.append((feat.get("properties", {}), g))
        for line in ([g] if g.geom_type == "LineString" else (list(g.geoms) if g.geom_type == "MultiLineString" else [])):
          coords = list(line.coords)
          for i in range(0, len(coords), 2):
            road_pts_list.append([coords[i][0], coords[i][1]])
    if road_pts_list:
      self.road_pts = np.asarray(road_pts_list, dtype=np.float64)

    twn_zip = os.path.join(self.sources_dir, self.ds_cfg["chgis_dataverse"]["files"]["chgis_1911_towns"]["filename"])
    if os.path.exists(twn_zip):
      self.twn_pts, _ = self._read_point_zip_wgs84(twn_zip, "utf-8")

  def _load_gns_points (self, arg1_filename):
    """Load and cache WGS84 populated-place coordinates from a GNS shapefile zip.

    @param arg1_filename Zip filename inside ./gis/sources/.
    @return NumPy array of shape (N, 2) with [lon, lat].
    """
    # Convert from parameters
    filename = arg1_filename

    if filename in self.gns_cache:
      return self.gns_cache[filename]

    # Declare local instance variables.
    pts_out = np.empty((0, 2), dtype=np.float64)
    zpath = os.path.join(self.sources_dir, filename)

    if os.path.exists(zpath):
      pts, recs = self._read_point_zip_wgs84(zpath, "gb18030")
      keep_idx = [i for i, r in enumerate(recs) if str(r.get("FC") or "").strip().upper() in ("P", "A", "")]
      pts_out = pts[keep_idx] if keep_idx else pts

    self.gns_cache[filename] = pts_out

    # Return statement
    return pts_out

  def _read_point_zip_wgs84 (self, arg1_zip_path, arg2_encoding):
    """Read a zipped point shapefile and vectorized-reproject Xian80 GK19 points to WGS84.

    @param arg1_zip_path Path to .zip archive.
    @param arg2_encoding DBF character encoding.
    @return Tuple (coords_lonlat_ndarray, records_list).
    """
    # Convert from parameters
    encoding = arg2_encoding
    zip_path = arg1_zip_path

    # Declare local instance variables.
    coords_raw = []
    prj_text = ""
    recs = []

    with zipfile.ZipFile(zip_path, "r") as zf:
      names = zf.namelist()
      shp_bytes = zf.read([n for n in names if n.lower().endswith(".shp")][0])
      dbf_bytes = zf.read([n for n in names if n.lower().endswith(".dbf")][0])
      prj_names = [n for n in names if n.lower().endswith(".prj")]
      if prj_names:
        prj_text = zf.read(prj_names[0]).decode("utf-8", errors="replace")

    is_proj = ("PROJCS" in prj_text) or ("Gauss_Kruger" in prj_text) or ("Transverse_Mercator" in prj_text)
    sf = shapefile.Reader(shp=io.BytesIO(shp_bytes), dbf=io.BytesIO(dbf_bytes), encoding=encoding, encodingErrors="replace")
    fields = [f[0] for f in sf.fields[1:]]
    if not is_proj and len(sf) > 0 and (abs(sf.bbox[0]) > 360.0 or abs(sf.bbox[2]) > 360.0):
      is_proj = True

    for i in range(len(sf)):
      shp_obj = sf.shape(i)
      if shp_obj.shapeType != shapefile.NULL and shp_obj.points:
        coords_raw.append(shp_obj.points[0][:2])
        recs.append(dict(zip(fields, sf.record(i))))

    if not coords_raw:
      return np.empty((0, 2), dtype=np.float64), []

    arr = np.asarray(coords_raw, dtype=np.float64)
    if is_proj:
      arr = np.asarray(gis_helpers.gk19_array_to_lonlat(arr), dtype=np.float64)

    # Return statement
    return arr, recs

  def _resolve_all_overlaps (self, arg1_tusi_geoms, arg2_tusi_by_id):
    """Snap all 130 Tusi polygons to 1e-5 grid and eliminate every pairwise overlap sliver.

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
    ordered_ids = sorted(
      tusi_geoms.keys(),
      key=lambda tid: (0 if tusi_by_id[tid].get("geometry_mode") == "chgis_direct" else 1, tid),
    )

    for tid in ordered_ids:
      g = gis_helpers.round_geometry(tusi_geoms[tid], self.precision)
      if g is not None and not g.is_empty:
        cleaned[tid] = g

    # Pass 0 uses exact boundary difference; passes 1..5 eliminate 5-decimal rounding slivers
    for pass_i in range(6):
      changed = False
      for i in range(len(ordered_ids)):
        tid_a = ordered_ids[i]
        if tid_a not in cleaned:
          continue
        ga = cleaned[tid_a]
        for x in range(i + 1, len(ordered_ids)):
          tid_b = ordered_ids[x]
          if tid_b not in cleaned:
            continue
          gb = cleaned[tid_b]
          if ga.bounds[0] > gb.bounds[2] or gb.bounds[0] > ga.bounds[2] or ga.bounds[1] > gb.bounds[3] or gb.bounds[1] > ga.bounds[3]:
            continue
          if ga.intersects(gb) and ga.intersection(gb).area > 0.0:
            changed = True
            trim_b = True
            if tusi_by_id[tid_a].get("geometry_mode") == tusi_by_id[tid_b].get("geometry_mode"):
              trim_b = (gb.area >= ga.area)
            if trim_b:
              cut_a = ga if pass_i == 0 else ga.buffer(buf_eps, join_style="mitre")
              rem = gis_helpers.round_geometry(gb.difference(cut_a), self.precision)
              if rem is not None and not rem.is_empty:
                cleaned[tid_b] = rem
            else:
              cut_b = gb if pass_i == 0 else gb.buffer(buf_eps, join_style="mitre")
              rem = gis_helpers.round_geometry(ga.difference(cut_b), self.precision)
              if rem is not None and not rem.is_empty:
                cleaned[tid_a] = rem
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
          if ia > 0.0:
            ov_pairs.append((tid_a, tid_b, ia))

    # Return statement
    return cleaned, max_ov, ov_pairs

  def _segments_cross_rivers (self, arg1_pts_a, arg2_pts_b, arg3_river_segs):
    """Vectorized test whether straight segments from pts_a (N,2) to pts_b (G,2) cross any river segment.

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

  def _solve_ordinary_kriging (self, arg1_samples_xy, arg2_z_mat, arg3_grid_xy, arg4_river_segs, arg5_cluster):
    """Solve Ordinary Indicator Kriging via scipy.linalg.solve with river-barrier and road-corridor modulation.

    @param arg1_samples_xy (N, 2) array of sample coordinates.
    @param arg2_z_mat (N, K) indicator matrix with Z in {0, 1}.
    @param arg3_grid_xy (G, 2) array of grid coordinates inside host domain.
    @param arg4_river_segs (R, 4) array of barrier river segments.
    @param arg5_cluster Cluster configuration dict.
    @return Tuple (z_hat (G, K), winner_idx (G,)).
    """
    # Convert from parameters
    cluster = arg5_cluster
    grid_xy = arg3_grid_xy
    river_segs = arg4_river_segs
    samples_xy = arg1_samples_xy
    z_mat = arg2_z_mat

    # Declare local instance variables.
    corr_bonus = float(self.config["kriging_defaults"].get("corridor_bonus", 0.85))
    corr_radius = float(self.config["kriging_defaults"].get("corridor_radius_deg", 0.08))
    cos_lat = np.cos(np.deg2rad(np.mean(grid_xy[:, 1])))
    nugget = float(self.config["kriging_defaults"].get("nugget", 0.02))
    n_samples = samples_xy.shape[0]
    n_grid = grid_xy.shape[0]
    pen = float(cluster.get("river_penalty_deg", 0.40))
    rng = float(cluster.get("variogram_range_deg", 0.50))
    sill = float(self.config["kriging_defaults"].get("sill", 1.0))

    d_ss = np.hypot((samples_xy[:, 0:1] - samples_xy[:, 0:1].T)*cos_lat, samples_xy[:, 1:2] - samples_xy[:, 1:2].T)
    c1 = sill - nugget
    cov_ss = c1*np.exp(-d_ss / rng)
    np.fill_diagonal(cov_ss, sill)

    k_mat = np.ones((n_samples + 1, n_samples + 1), dtype=np.float64)
    k_mat[:n_samples, :n_samples] = cov_ss
    k_mat[n_samples, n_samples] = 0.0

    s_on_road = self._assign_corridor_flags(samples_xy, self.road_pts, corr_radius)
    g_on_road = self._assign_corridor_flags(grid_xy, self.road_pts, corr_radius)
    z_hat = np.zeros((n_grid, z_mat.shape[1]), dtype=np.float64)
    chunk = 1800

    for i in range(0, n_grid, chunk):
      sub_g = grid_xy[i:i + chunk]
      d_sg = np.hypot((samples_xy[:, 0:1] - sub_g[None, :, 0])*cos_lat, samples_xy[:, 1:2] - sub_g[None, :, 1])
      if river_segs.shape[0] > 0 and pen > 0.0:
        d_sg = d_sg + self._segments_cross_rivers(samples_xy, sub_g, river_segs).astype(np.float64)*pen
      d_sg = np.where(s_on_road[:, None] & g_on_road[None, i:i + chunk], d_sg*corr_bonus, d_sg)

      rhs = np.ones((n_samples + 1, sub_g.shape[0]), dtype=np.float64)
      rhs[:n_samples, :] = c1*np.exp(-d_sg / rng)
      weights = linalg_solve(k_mat, rhs, assume_a="sym")
      z_hat[i:i + chunk, :] = weights[:n_samples, :].T @ z_mat

    # Return statement
    return z_hat, np.argmax(z_hat, axis=1)

  def _split_domain_by_river (self, arg1_geom, arg2_river_tokens, arg3_keep_mode):
    """Split a host polygon along a major river polyline and keep the historically appropriate side.

    @param arg1_geom Host Shapely polygon.
    @param arg2_river_tokens List of river name substrings.
    @param arg3_keep_mode One of 'east', 'southwest', 'south'.
    @return Clean Shapely geometry on the selected side of the river.
    """
    # Convert from parameters
    geom = arg1_geom
    keep_mode = arg3_keep_mode
    tokens = [t.lower() for t in arg2_river_tokens]

    # Declare local instance variables.
    lines = []
    minx, miny, maxx, maxy = geom.bounds
    pad_box = box(minx - 0.5, miny - 0.5, maxx + 0.5, maxy + 0.5)

    for src_filter in (True, False):
      for props, rg in self.waterways:
        ne = str(props.get("name_en") or "").lower()
        src = str(props.get("source") or "")
        if any(tok in ne for tok in tokens) and (not src_filter or "NaturalEarth" in src) and rg.intersects(pad_box):
          lines.append(rg.intersection(pad_box))
      if lines:
        break

    if not lines:
      return geom

    river_u = unary_union(lines)
    pieces = []
    for poly in ([geom] if geom.geom_type == "Polygon" else list(geom.geoms)):
      if not river_u.intersects(poly):
        pieces.append(poly)
        continue
      for sub in split(poly, river_u).geoms:
        if sub.geom_type == "Polygon" and sub.area > 1e-5:
          pieces.append(sub)

    if len(pieces) <= 1:
      return geom

    kept = []
    for pc in pieces:
      rp = pc.representative_point()
      if keep_mode == "east" and ((pc.area > 0.25 and rp.x >= 98.8) or rp.x >= 99.1):
        kept.append(pc)
      elif keep_mode == "southwest" and (rp.y < 23.38 or (rp.x < 102.20 and rp.y < 23.58)):
        kept.append(pc)
      elif keep_mode == "south" and rp.y < 29.28:
        kept.append(pc)

    if not kept:
      kept = [max(pieces, key=lambda p: p.area)]

    # Return statement
    return gis_helpers.clean_polygonal_geometry(unary_union(kept))

  def build_all_tusis (self):
    """Build all 130 Tusi geometries (85 chgis_direct + 45 kriging_modelled) and resolve overlaps.

    @return Summary metrics dictionary.
    """
    # Declare local instance variables.
    direct_geoms, direct_union = self._build_chgis_direct()
    kriged_geoms = {}
    tusi_by_id = {t["tusi_id"]: t for t in self.tusis}

    for cluster in self.config.get("clusters", []):
      cid = cluster["cluster_id"]
      domain = self._build_host_domain(cluster, direct_union)
      if domain is None or domain.is_empty:
        print(f"[WARN] Empty domain for cluster {cid}", file=sys.stderr)
        continue

      step = float(cluster.get("grid_step_deg", 0.04))
      minx, miny, maxx, maxy = domain.bounds
      gx, gy = np.meshgrid(np.arange(minx + 0.5*step, maxx, step), np.arange(miny + 0.5*step, maxy, step))
      cand_xy = np.column_stack([gx.ravel(), gy.ravel()])
      grid_xy = cand_xy[contains_xy(domain, cand_xy[:, 0], cand_xy[:, 1])]
      if grid_xy.shape[0] == 0:
        rep = domain.representative_point()
        grid_xy = np.array([[rep.x, rep.y]], dtype=np.float64)

      river_segs = self._compute_river_segments(cluster, domain.bounds)
      samples_xy, z_mat, t_ids, _ = self._collect_cluster_samples(cluster, domain, tusi_by_id, river_segs)
      z_hat, winner = self._solve_ordinary_kriging(samples_xy, z_mat, grid_xy, river_segs, cluster)
      cluster_polys = self._extract_watertight_polygons(domain, grid_xy, step, winner, z_hat, t_ids)

      kriged_geoms.update(cluster_polys)
      print(f"[STEP 2] Cluster {cid:20s}: {len(cluster_polys)}/{len(t_ids)} Tusis | grid={grid_xy.shape[0]} | samples={samples_xy.shape[0]} | rsegs={river_segs.shape[0]}")

    combined = {}
    combined.update(direct_geoms)
    combined.update(kriged_geoms)
    cleaned, max_ov, ov_pairs = self._resolve_all_overlaps(combined, tusi_by_id)
    self.tusi_geoms = cleaned

    # Return statement
    return {
      "chgis_direct": len(direct_geoms),
      "kriging_modelled": len(kriged_geoms),
      "max_overlap_deg2": max_ov,
      "overlap_pairs": ov_pairs,
      "total": len(cleaned),
    }

  def export_geojson (self):
    """Write all 130 modelled Tusi features to ./gis/tusi_1912_1953.geojson (WGS84, 5 decimals).

    @return Tuple (output_filepath, feature_count).
    """
    # Declare local instance variables.
    out_features = []
    out_path = os.path.join(self.gis_dir, "tusi_1912_1953.geojson")

    for t in self.tusis:
      tid = t["tusi_id"]
      geom = self.tusi_geoms.get(tid)
      if geom is None or geom.is_empty:
        print(f"[ERROR] Missing geometry for {tid}", file=sys.stderr)
        continue
      props = {
        "chgis_unit_ids": t.get("chgis_unit_ids", []),
        "end_year": int(t["end_year"]),
        "geometry_mode": t["geometry_mode"],
        "name_en": t["name_en"],
        "name_zh": t["name_zh"],
        "parent_province": t["parent_province"],
        "rank_title": t.get("rank_title", "Tusi"),
        "region": t["region"],
        "seat_lat": round(float(t["seat_lat"]), self.precision),
        "seat_lon": round(float(t["seat_lon"]), self.precision),
        "start_year": int(t["start_year"]),
        "tusi_id": tid,
      }
      out_features.append((props, geom))

    written = gis_helpers.write_geojson(out_path, out_features, self.precision)

    # Return statement
    return out_path, written

  def render_diagnostic_maps (self):
    """Render 4 high-resolution regional diagnostic PNG maps in ./tests/.

    @return List of generated PNG filepaths.
    """
    os.makedirs(self.tests_dir, exist_ok=True)

    # Declare local instance variables.
    generated = []

    for mcfg in self.config.get("diagnostic_maps", []):
      ext = mcfg["extent"]
      minx, maxx, miny, maxy = float(ext[0]), float(ext[1]), float(ext[2]), float(ext[3])
      vp_box = box(minx, miny, maxx, maxy)
      fig, ax = plt.subplots(figsize=(14, 10.5), dpi=210)
      ax.set_facecolor("#e9f0f5")

      for feat in self.adm1_features:
        g = shape(feat["geometry"])
        if g.intersects(vp_box):
          for poly in ([g] if g.geom_type == "Polygon" else (list(g.geoms) if g.geom_type == "MultiPolygon" else [])):
            px, py = poly.exterior.xy
            ax.fill(px, py, facecolor="#f4f1ea", edgecolor="#5c5c5c", linewidth=1.0, zorder=1)

      for feat in self.adm3_features:
        g = shape(feat["geometry"])
        if g.intersects(vp_box):
          for poly in ([g] if g.geom_type == "Polygon" else (list(g.geoms) if g.geom_type == "MultiPolygon" else [])):
            px, py = poly.exterior.xy
            ax.plot(px, py, color="#d4cfc4", linewidth=0.35, zorder=2)

      for _, rg in self.roads:
        if rg.intersects(vp_box):
          for line in ([rg] if rg.geom_type == "LineString" else (list(rg.geoms) if rg.geom_type == "MultiLineString" else [])):
            lx, ly = line.xy
            ax.plot(lx, ly, color="#9e7b56", linewidth=0.65, linestyle="--", alpha=0.55, zorder=3)

      for props, wg in self.waterways:
        if wg.intersects(vp_box):
          is_ne = "NaturalEarth" in str(props.get("source") or "")
          for line in ([wg] if wg.geom_type == "LineString" else (list(wg.geoms) if wg.geom_type == "MultiLineString" else [])):
            lx, ly = line.xy
            ax.plot(lx, ly, color="#1f68a8" if is_ne else "#5394cb", linewidth=1.6 if is_ne else 0.75, alpha=0.85, zorder=4)

      for rlbl in mcfg.get("river_labels", []):
        ax.text(
          float(rlbl[0]), float(rlbl[1]), rlbl[2], color="#154d80", fontsize=8.5, fontstyle="italic",
          fontweight="bold", zorder=9, path_effects=[patheffects.withStroke(linewidth=2.4, foreground="#ffffff")],
        )

      raw_labels = []
      for t in self.tusis:
        tid = t["tusi_id"]
        geom = self.tusi_geoms.get(tid)
        if geom is None or geom.is_empty or not geom.intersects(vp_box):
          continue
        is_direct = (t["geometry_mode"] == "chgis_direct")
        digest = hashlib.md5(tid.encode("utf-8")).digest()
        rgb = plt.cm.hsv((int.from_bytes(digest[:2], "big") % 360) / 360.0)[:3]
        fill_col = (0.35 + 0.55*rgb[0], 0.35 + 0.55*rgb[1], 0.35 + 0.55*rgb[2])
        edge_col = "#1a3b2a" if is_direct else "#6b1b1b"

        for poly in ([geom] if geom.geom_type == "Polygon" else list(geom.geoms)):
          px, py = poly.exterior.xy
          ax.fill(px, py, facecolor=fill_col, edgecolor=edge_col, linewidth=0.85 if is_direct else 1.25, alpha=0.72, zorder=5)
          for hole in poly.interiors:
            hx, hy = hole.xy
            ax.fill(hx, hy, facecolor="#f4f1ea", edgecolor=edge_col, linewidth=0.5, zorder=5)

        sx, sy = float(t["seat_lon"]), float(t["seat_lat"])
        if minx <= sx <= maxx and miny <= sy <= maxy:
          ax.scatter([sx], [sy], marker="*", s=62, color="#f5d142" if not is_direct else "#ffffff", edgecolor="#111111", linewidth=0.6, zorder=8)

        rp = geom.representative_point()
        if minx <= rp.x <= maxx and miny <= rp.y <= maxy:
          short_name = t["name_en"].split("(")[0].strip()
          if len(short_name) > 20:
            short_name = short_name[:18] + ".."
          raw_labels.append([rp.x, rp.y, rp.x, rp.y, f"{short_name}\n[{tid}]"])

      min_dx, min_dy = 0.08*(maxx - minx), 0.036*(maxy - miny)
      for _ in range(28):
        for i in range(len(raw_labels)):
          for x in range(i + 1, len(raw_labels)):
            dx, dy = raw_labels[i][0] - raw_labels[x][0], raw_labels[i][1] - raw_labels[x][1]
            if abs(dx) < min_dx and abs(dy) < min_dy:
              px_off = (0.16*min_dx) if dx >= 0.0 else (-0.16*min_dx)
              py_off = (0.26*min_dy) if dy >= 0.0 else (-0.26*min_dy)
              raw_labels[i][0] = min(maxx - 0.3, max(minx + 0.3, raw_labels[i][0] + px_off))
              raw_labels[i][1] = min(maxy - 0.15, max(miny + 0.15, raw_labels[i][1] + py_off))
              raw_labels[x][0] = min(maxx - 0.3, max(minx + 0.3, raw_labels[x][0] - px_off))
              raw_labels[x][1] = min(maxy - 0.15, max(miny + 0.15, raw_labels[x][1] - py_off))

      for lx, ly, ox, oy, txt in raw_labels:
        if np.hypot(lx - ox, ly - oy) > 0.14:
          ax.plot([ox, lx], [oy, ly], color="#333333", linewidth=0.45, alpha=0.65, zorder=9)
        ax.text(
          lx, ly, txt, fontsize=4.4, ha="center", va="center", color="#141414", fontweight="semibold",
          zorder=10, path_effects=[patheffects.withStroke(linewidth=1.8, foreground="#ffffff", alpha=0.92)],
        )

      ax.set_xlim(minx, maxx)
      ax.set_ylim(miny, maxy)
      ax.set_aspect(1.0 / np.cos(np.deg2rad(0.5*(miny + maxy))))
      ax.grid(True, linestyle=":", linewidth=0.45, color="#999999", alpha=0.6)
      ax.set_xlabel("Longitude (WGS84)", fontsize=9)
      ax.set_ylabel("Latitude (WGS84)", fontsize=9)
      ax.set_title(mcfg["title"], fontsize=11.5, fontweight="bold", pad=10)
      ax.legend(handles=[
        Patch(facecolor="#88c999", edgecolor="#1a3b2a", linewidth=0.9, label="chgis_direct (CHGIS 1911 Surveyed)"),
        Patch(facecolor="#e8a47c", edgecolor="#6b1b1b", linewidth=1.2, label="kriging_modelled (Hydrology-Modulated Kriging)"),
        Line2D([0], [0], color="#1f68a8", linewidth=1.6, label="Major Rivers"),
        Line2D([0], [0], color="#9e7b56", linewidth=0.9, linestyle="--", label="Historical Roads"),
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#f5d142", markeredgecolor="#111111", markersize=10, label="Tusi Seat (*)"),
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
  """Execute Step 2 Tusi spatial modelling, GeoJSON export, and diagnostic verification maps."""
  base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
  modeller = TusiModeller(base_dir)
  metrics = modeller.build_all_tusis()
  out_geojson, feat_count = modeller.export_geojson()
  pngs = modeller.render_diagnostic_maps()

  print(
    f"[STEP 2 DONE] features={feat_count} (direct={metrics['chgis_direct']}, kriged={metrics['kriging_modelled']}) "
    f"max_overlap_deg2={metrics['max_overlap_deg2']:.8f} overlaps={len(metrics['overlap_pairs'])} "
    f"geojson={out_geojson} pngs={len(pngs)}"
  )
  return 0 if feat_count == 130 and metrics["max_overlap_deg2"] == 0.0 else 1


if __name__ == "__main__":
  sys.exit(main())
