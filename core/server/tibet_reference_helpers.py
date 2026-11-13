"""Vectorise Tibetan, Yushu, Hor, Arunachal and Western Kham reference polities via planar shared-arc tracing."""

import json
import math
import os
import sys
import cv2
import numpy as np
from scipy import ndimage
from scipy.interpolate import RBFInterpolator
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, shape
from shapely.ops import polygonize, unary_union

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import gis_helpers
import tusi_topo_helpers


def _build_arc_graph (arg1_dense_lbl):
  """Extract maximal edge chains between junction nodes (degree != 2) on pixel-corner lattice.

  @param arg1_dense_lbl 2D integer label array of segmented reference canvas.
  @return Tuple (edges_by_arc, pair_to_arcs) where edges_by_arc is list of [(u, v), coord_list].
  """
  # Convert from parameters
  dense_lbl = arg1_dense_lbl

  # Declare local instance variables.
  adj = {}
  arc_list = []
  dir_arcs = {}
  h, w = dense_lbl.shape
  padded = np.zeros((h + 2, w + 2), dtype=dense_lbl.dtype)
  segment_owner = {}
  visited = set()

  padded[1:h + 1, 1:w + 1] = dense_lbl

  # Collect horizontal boundary segments (between row y - 1 and row y in padded -> corner row y - 1 in canvas)
  diff_v = padded[1:, 1:w + 1] != padded[:-1, 1:w + 1]
  ys, xs = np.where(diff_v)
  for i in range(len(ys)):
    cy = int(ys[i])
    cx = int(xs[i])
    l_top = int(padded[cy, cx + 1])
    l_bot = int(padded[cy + 1, cx + 1])
    if l_top == 0 and l_bot == 0:
      continue
    # Orient edge so left_label = min(l_top, l_bot) or consistent pair key
    u = (cx, cy)
    v = (cx + 1, cy)
    adj.setdefault(u, []).append(v)
    adj.setdefault(v, []).append(u)
    ek = (u, v) if u < v else (v, u)
    segment_owner[ek] = (l_top, l_bot) if u < v else (l_bot, l_top)

  # Collect vertical boundary segments
  diff_h = padded[1:h + 1, 1:] != padded[1:h + 1, :-1]
  ys, xs = np.where(diff_h)
  for i in range(len(ys)):
    cy = int(ys[i])
    cx = int(xs[i])
    l_left = int(padded[cy + 1, cx])
    l_right = int(padded[cy + 1, cx + 1])
    if l_left == 0 and l_right == 0:
      continue
    u = (cx, cy)
    v = (cx, cy + 1)
    adj.setdefault(u, []).append(v)
    adj.setdefault(v, []).append(u)
    ek = (u, v) if u < v else (v, u)
    segment_owner[ek] = (l_left, l_right) if u < v else (l_right, l_left)

  # Walk chains starting from junction nodes (deg != 2) where pair owner stays constant
  def _norm_pair (arg1_u, arg2_v):
    ek = (arg1_u, arg2_v) if arg1_u < arg2_v else (arg2_v, arg1_u)
    a, b = segment_owner[ek]
    return (a, b) if a < b else (b, a)

  for node, nbrs in adj.items():
    if len(nbrs) == 2:
      p0 = _norm_pair(node, nbrs[0])
      p1 = _norm_pair(node, nbrs[1])
      if p0 == p1:
        continue
    for nxt in nbrs:
      ek = (node, nxt) if node < nxt else (nxt, node)
      if ek in visited:
        continue
      pair = _norm_pair(node, nxt)
      chain = [node, nxt]
      visited.add(ek)
      prev, cur = node, nxt
      while len(adj[cur]) == 2:
        nbs = adj[cur]
        cand = nbs[1] if nbs[0] == prev else nbs[0]
        ek2 = (cur, cand) if cur < cand else (cand, cur)
        if ek2 in visited or _norm_pair(cur, cand) != pair:
          break
        visited.add(ek2)
        chain.append(cand)
        prev, cur = cur, cand
      arc_idx = len(arc_list)
      arc_list.append((pair, chain))
      a_lbl, b_lbl = pair
      dir_arcs.setdefault(a_lbl, []).append(arc_idx)
      dir_arcs.setdefault(b_lbl, []).append(arc_idx)

  # Any remaining isolated pure cycles (all deg == 2, constant pair)
  for ek, ow in segment_owner.items():
    if ek in visited:
      continue
    u, v = ek
    pair = (ow[0], ow[1]) if ow[0] < ow[1] else (ow[1], ow[0])
    chain = [u, v]
    visited.add(ek)
    prev, cur = u, v
    while True:
      nbs = adj[cur]
      cand = nbs[1] if nbs[0] == prev else nbs[0]
      if cand == chain[0]:
        chain.append(cand)
        break
      ek2 = (cur, cand) if cur < cand else (cand, cur)
      if ek2 in visited or _norm_pair(cur, cand) != pair:
        break
      visited.add(ek2)
      chain.append(cand)
      prev, cur = cur, cand
    arc_idx = len(arc_list)
    arc_list.append((pair, chain))
    a_lbl, b_lbl = pair
    dir_arcs.setdefault(a_lbl, []).append(arc_idx)
    dir_arcs.setdefault(b_lbl, []).append(arc_idx)

  # Return statement
  return (arc_list, dir_arcs)


def _calibrate_transform (arg1_cfg):
  """Fit EPSG:3857 affine + lightly regularised thin-plate spline from control points.

  @param arg1_cfg Parsed tibet_reference_config dict.
  @return Dict containing affine slopes/intercepts and forward/inverse RBFInterpolators.
  """
  # Convert from parameters
  cfg = arg1_cfg

  # Declare local instance variables.
  cps = cfg["control_points"]
  lons = np.asarray([c[0] for c in cps], dtype=np.float64)
  lats = np.asarray([c[1] for c in cps], dtype=np.float64)
  mys = merc_y(lats)
  pxs = np.asarray([c[2] for c in cps], dtype=np.float64)
  pys = np.asarray([c[3] for c in cps], dtype=np.float64)
  smooth = float(cfg.get("tps_smoothing", 4.0))

  ax, bx = np.polyfit(lons, pxs, 1)
  ay, by = np.polyfit(mys, pys, 1)

  # Inverse TPS: (px, py) -> delta (lon, merc_y) from affine inverse
  dst_pts = np.column_stack([pxs, pys])
  d_lon = lons - (pxs - bx)/ax
  d_my = mys - (pys - by)/ay
  rbf_inv = RBFInterpolator(dst_pts, np.column_stack([d_lon, d_my]), kernel="thin_plate_spline", smoothing=smooth*0.0001)

  # Forward TPS: (lon, merc_y) -> delta (px, py) from affine forward
  src_pts = np.column_stack([lons, mys])
  d_px = pxs - (ax*lons + bx)
  d_py = pys - (ay*mys + by)
  rbf_fwd = RBFInterpolator(src_pts, np.column_stack([d_px, d_py]), kernel="thin_plate_spline", smoothing=smooth)

  # Verify inlier RMS error
  pred_px, pred_py = lonlat_to_px(lons, lats, {"ax": float(ax), "bx": float(bx), "ay": float(ay), "by": float(by), "rbf_fwd": rbf_fwd, "rbf_inv": rbf_inv})
  rms_px = float(np.sqrt(np.mean((pred_px - pxs)**2 + (pred_py - pys)**2)))

  # Return statement
  return {
    "ax": float(ax),
    "ay": float(ay),
    "bx": float(bx),
    "by": float(by),
    "rbf_fwd": rbf_fwd,
    "rbf_inv": rbf_inv,
    "rms_px": rms_px,
  }


def _collect_uncovered_audit (arg1_cfg, arg2_dense_lbl, arg3_cls_map, arg4_names, arg5_assigned_fids, arg6_transform, arg7_ref_rgb):
  """Audit every non-exterior face >= 50 px inside Tibet/Yushu/Arunachal/Kham bbox not yet claimed.

  @param arg1_cfg Reference config dictionary.
  @param arg2_dense_lbl Segmented dense face ID array.
  @param arg3_cls_map Nearest-palette class map.
  @param arg4_names Palette class names list.
  @param arg5_assigned_fids Set of already-mapped face IDs.
  @param arg6_transform Calibrated transform dict.
  @param arg7_ref_rgb Reference RGB image array.
  @return List of uncovered face dicts sorted by area descending.
  """
  # Convert from parameters
  assigned_fids = arg5_assigned_fids
  cfg = arg1_cfg
  cls_map = arg3_cls_map
  dense_lbl = arg2_dense_lbl
  names = arg4_names
  ref_rgb = arg7_ref_rgb
  transform = arg6_transform

  # Declare local instance variables.
  counts = None
  skip_doms = {"ext_white", "ext_xinjiang", "ext_nepal", "ext_qaidam", "ext_bhutan", "ext_india", "enclave_coral1", "lake"}
  uncovered = []
  uniq = None
  x_off = int(cfg["canvas_x_offset"])
  canvas = ref_rgb[:, x_off:, :]

  uniq, counts = np.unique(dense_lbl, return_counts=True)
  for i in range(len(uniq)):
    fid = int(uniq[i])
    area = int(counts[i])
    if fid in assigned_fids or area < 50:
      continue
    ys, xs = np.where(dense_lbl == fid)
    vals, vcnts = np.unique(cls_map[ys, xs], return_counts=True)
    dom = names[int(vals[np.argmax(vcnts)])]
    if dom in skip_doms:
      continue
    lx = int(np.median(xs)) + x_off
    ly = int(np.median(ys))
    if ly < 420:
      continue
    lon_arr, lat_arr = px_to_lonlat([lx], [ly], transform)
    lon = float(lon_arr[0])
    lat = float(lat_arr[0])
    if lon > 99.18 or lon < 78.28 or lat < 26.85:
      continue
    med = np.median(canvas[ys, xs], axis=0)
    uncovered.append({
      "area_px": area,
      "dom": dom,
      "fid": fid,
      "lat": round(lat, 3),
      "lon": round(lon, 3),
      "px": lx,
      "py": ly,
      "rgb": [int(v) for v in med],
    })

  uncovered.sort(key=lambda r: -r["area_px"])

  # Return statement
  return uncovered


def _dissolve_text_holes_px (arg1_px_polities, arg2_px_masks, arg3_canvas_16, arg4_canvas_22):
  """Strip unclaimed font-stroke holes while keeping real enclaves, Beiyang garrisons, and Himalayan glaciers.

  @param arg1_px_polities Dict mapping tusi_id -> (pixel_geom, entry).
  @param arg2_px_masks Dict mapping mask_id -> (pixel_geom, entry).
  @param arg3_canvas_16 1916 reference canvas RGB (x >= x_off).
  @param arg4_canvas_22 1922 reference frame RGB (x >= x_off).
  @return Filtered tuple (clean_polities, clean_masks) in pixel coordinates.
  """
  # Convert from parameters
  canvas_16 = arg3_canvas_16
  canvas_22 = arg4_canvas_22
  px_masks = arg2_px_masks
  px_polities = arg1_px_polities

  # Declare local instance variables.
  h, w, _ = canvas_16.shape
  pol_union_px = unary_union([g for g, _ in px_polities.values()]) if px_polities else None

  def _keep_hole (arg1_hr, arg2_canvas):
    hp = Polygon(arg1_hr)
    if hp.is_empty or hp.area <= 0.0:
      return False
    if pol_union_px is not None:
      if (hp.intersection(pol_union_px).area / max(hp.area, 1e-9)) > 0.15:
        return True
    rp = hp.representative_point()
    ix = max(0, min(w - 1, int(round(rp.x))))
    iy = max(0, min(h - 1, int(round(rp.y))))
    r_v, g_v, b_v = [int(v) for v in arg2_canvas[iy, ix]]
    if r_v > 140 and g_v < 60:
      return True
    if r_v > 235 and 145 <= g_v <= 185 and 135 <= b_v <= 175:
      return True
    if r_v >= 228 and g_v >= 228 and b_v >= 228 and iy > 1650:
      return True
    return False

  def _clean_map (arg1_map):
    out = {}
    for k, (geom, meta) in arg1_map.items():
      cvs = canvas_16 if meta.get("source", "ref_1916") == "ref_1916" else canvas_22
      parts = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
      kept_parts = []
      for p in parts:
        if p.geom_type != "Polygon":
          continue
        kept_holes = [list(hr.coords) for hr in p.interiors if _keep_hole(hr, cvs)]
        kept_parts.append(Polygon(p.exterior.coords, kept_holes))
      if kept_parts:
        cg = gis_helpers.clean_polygonal_geometry(kept_parts[0] if len(kept_parts) == 1 else unary_union(kept_parts))
        if cg is not None and not cg.is_empty:
          out[k] = (cg, meta)
    return out

  # Return statement
  return (_clean_map(px_polities), _clean_map(px_masks))


def _load_external_clip_shell (arg1_base_dir):
  """Build surveyed outer boundary shell from CHGIS 1911 Xizang/Yushu, GADM Arunachal and Sichuan W.

  @param arg1_base_dir Project root directory.
  @return Cleaned Shapely geometry representing surveyed outer geographic extent.
  """
  # Convert from parameters
  base_dir = arg1_base_dir

  # Declare local instance variables.
  adm_path = os.path.join(base_dir, "gis", "chgis_1911_adm3_base.geojson")
  gadm_path = os.path.join(base_dir, "gis", "sources", "gadm_arunachal.geojson")
  parts = []

  if os.path.exists(adm_path):
    with open(adm_path, "r", encoding="utf-8") as fh:
      feats = json.load(fh)["features"]
    for feat in feats:
      props = feat["properties"]
      uid = str(props.get("orig_uid") or props.get("unit_id") or "")
      l1 = str(props.get("parent_adm1") or "")
      if "xizang" in uid.lower() or "qinghai" in l1.lower() or "sichuan" in l1.lower():
        g = shape(feat["geometry"])
        if not g.is_empty:
          parts.append(g)

  if os.path.exists(gadm_path):
    with open(gadm_path, "r", encoding="utf-8") as fh:
      feats = json.load(fh)["features"]
    for feat in feats:
      g = shape(feat["geometry"])
      if not g.is_empty:
        parts.append(g)

  # Return statement
  return gis_helpers.clean_polygonal_geometry(unary_union(parts)) if parts else None


def _smooth_pixel_arcs (arg1_arcs, arg2_cfg):
  """Smooth each pixel-lattice arc gently in pixel space while preserving exact junction endpoints.

  @param arg1_arcs Arc list [(pair, chain), ...] from _build_arc_graph.
  @param arg2_cfg Reference config dictionary.
  @return List of shapely LineStrings in pixel canvas coordinates.
  """
  # Convert from parameters
  arcs = arg1_arcs
  cfg = arg2_cfg

  # Declare local instance variables.
  chaikin_iters = int(cfg.get("chaikin_iters", 1))
  simp_px = float(cfg.get("chaikin_simplify_px", 0.65))
  sm_lines = []

  for i in range(len(arcs)):
    _, chain = arcs[i]
    pts = [(float(pt[0]), float(pt[1])) for pt in chain]
    if len(pts) < 3:
      sm_lines.append(LineString(pts))
      continue
    line = LineString(pts)
    sm_line = tusi_topo_helpers._chaikin_chain(line, simp_px, chaikin_iters)
    coords = list(sm_line.coords)
    # Keep exact junction coordinates bitwise identical across adjacent arcs
    coords[0] = pts[0]
    coords[-1] = pts[-1]
    sm_lines.append(LineString(coords))

  # Return statement
  return sm_lines


def _project_pixel_geom_dict (arg1_geom_map, arg2_transform, arg3_x_off):
  """Batch-project all pixel-space geometries to WGS84 while keeping shared vertices bitwise identical.

  @param arg1_geom_map Dict mapping key -> (pixel_geom, meta_dict).
  @param arg2_transform Calibrated transform dict from _calibrate_transform.
  @param arg3_x_off Canvas x-offset in full image pixels.
  @return Dict mapping key -> (wgs84_geom, meta_dict).
  """
  # Convert from parameters
  geom_map = arg1_geom_map
  transform = arg2_transform
  x_off = int(arg3_x_off)

  # Declare local instance variables.
  out_map = {}
  uniq_pts = []
  vert_idx = {}

  def _collect_ring (arg1_coords):
    for c in arg1_coords:
      k = (float(c[0]), float(c[1]))
      if k not in vert_idx:
        vert_idx[k] = len(uniq_pts)
        uniq_pts.append(k)

  for _, (g, _) in geom_map.items():
    if g is None or g.is_empty:
      continue
    parts = list(g.geoms) if hasattr(g, "geoms") else [g]
    for p in parts:
      if p.geom_type != "Polygon":
        continue
      _collect_ring(p.exterior.coords)
      for hole in p.interiors:
        _collect_ring(hole.coords)

  if not uniq_pts:
    return out_map

  px_arr = np.asarray([pt[0] + x_off for pt in uniq_pts], dtype=np.float64)
  py_arr = np.asarray([pt[1] for pt in uniq_pts], dtype=np.float64)
  lons, lats = px_to_lonlat(px_arr, py_arr, transform)
  wgs_lookup = [(float(lons[i]), float(lats[i])) for i in range(len(uniq_pts))]

  def _map_ring (arg1_coords):
    return [wgs_lookup[vert_idx[(float(c[0]), float(c[1]))]] for c in arg1_coords]

  for k, (g, meta) in geom_map.items():
    if g is None or g.is_empty:
      continue
    parts = list(g.geoms) if hasattr(g, "geoms") else [g]
    polys = []
    for p in parts:
      if p.geom_type != "Polygon":
        continue
      ext = _map_ring(p.exterior.coords)
      holes = [_map_ring(h.coords) for h in p.interiors]
      poly = Polygon(ext, holes)
      if not poly.is_valid:
        poly = poly.buffer(0)
      if not poly.is_empty:
        polys.append(poly)
    if polys:
      cg = gis_helpers.clean_polygonal_geometry(polys[0] if len(polys) == 1 else unary_union(polys))
      if cg is not None and not cg.is_empty:
        out_map[k] = (cg, meta)

  # Return statement
  return out_map


def build_reference_polygons (arg1_base_dir):
  """Segment reference plates, build planar shared-arc vector polygons, and export GeoJSON.

  @param arg1_base_dir Project root directory.
  @return Output GeoJSON path written on disk.
  """
  # Convert from parameters
  base_dir = arg1_base_dir

  # Declare local instance variables.
  assigned_ref_fids = set()
  cfg_path = os.path.join(base_dir, "common", "tusi", "tibet_reference_config.json5")
  cfg = gis_helpers.load_json5(cfg_path)
  f22_path = os.path.join(base_dir, cfg["video_frame_1922"])
  f22_rgb = cv2.cvtColor(cv2.imread(f22_path), cv2.COLOR_BGR2RGB)
  features_out = []
  min_area = int(cfg.get("min_seed_area", 15))
  out_path = os.path.join(base_dir, cfg["output_geojson"])
  pal_dict = cfg["palette"]
  ref_path = os.path.join(base_dir, cfg["reference_image"])
  ref_rgb = cv2.cvtColor(cv2.imread(ref_path), cv2.COLOR_BGR2RGB)
  transform = _calibrate_transform(cfg)
  x_off = int(cfg["canvas_x_offset"])

  print(f"[REF] Calibrated EPSG:3857 + TPS (RMS = {transform['rms_px']:.3f} px across {len(cfg['control_points'])} CPs)")

  dense_16, cls_16, names = segment_reference_canvas(
    ref_rgb[:, x_off:, :],
    pal_dict,
    int(cfg.get("grad_thresh_1916", 8)),
    min_area,
    float(cfg.get("lake_max_rgb_dist", 12.0)),
    cfg.get("micro_ovals", []),
    x_off,
    int(cfg.get("font_counter_ring_px", 25)),
  )
  print(f"[REF] Segmented 1916 canvas: {len(np.unique(dense_16))} faces")

  f22_med = cv2.medianBlur(f22_rgb[:, x_off:, :], 3)
  dense_22, _, _ = segment_reference_canvas(
    f22_med,
    pal_dict,
    int(cfg.get("grad_thresh_video", 14)),
    max(min_area, 30),
    float(cfg.get("lake_max_rgb_dist", 12.0)),
    [],
    x_off,
    int(cfg.get("font_counter_ring_px", 25)),
  )
  print(f"[REF] Segmented 1922 frame: {len(np.unique(dense_22))} faces")

  # Extract shared-arc planar graphs and smooth arcs in pixel space
  arcs_16, dir_16 = _build_arc_graph(dense_16)
  sm_arcs_16 = _smooth_pixel_arcs(arcs_16, cfg)

  arcs_22, dir_22 = _build_arc_graph(dense_22)
  sm_arcs_22 = _smooth_pixel_arcs(arcs_22, cfg)

  def _poly_for_fid (arg1_fid, arg2_dir, arg3_sm_arcs, arg4_dense):
    arc_indices = arg2_dir.get(arg1_fid, [])
    if not arc_indices:
      return None
    lines = [arg3_sm_arcs[a_i] for a_i in arc_indices if len(arg3_sm_arcs[a_i].coords) >= 2]
    if not lines:
      return None
    polys = list(polygonize(unary_union(lines)))
    if not polys:
      return None
    h_d, w_d = arg4_dense.shape
    kept = []
    for p in polys:
      rp = p.representative_point()
      rx = max(0, min(w_d - 1, int(math.floor(rp.x))))
      ry = max(0, min(h_d - 1, int(math.floor(rp.y))))
      if int(arg4_dense[ry, rx]) == arg1_fid:
        kept.append(p)
        continue
      patch = arg4_dense[max(0, ry - 1):min(h_d, ry + 2), max(0, rx - 1):min(w_d, rx + 2)]
      if np.any(patch == arg1_fid):
        kept.append(p)
    if not kept:
      return None
    return gis_helpers.clean_polygonal_geometry(kept[0] if len(kept) == 1 else unary_union(kept))

  face_geom_16 = {}
  face_geom_22 = {}

  def _build_entry_geom (arg1_seeds, arg2_source):
    dense = dense_16 if arg2_source == "ref_1916" else dense_22
    dir_map = dir_16 if arg2_source == "ref_1916" else dir_22
    sm_arcs = sm_arcs_16 if arg2_source == "ref_1916" else sm_arcs_22
    cache = face_geom_16 if arg2_source == "ref_1916" else face_geom_22
    fids = []
    parts = []
    h_c, w_c = dense.shape
    for pt in arg1_seeds:
      ix = max(0, min(w_c - 1, int(round(float(pt[0]) - x_off))))
      iy = max(0, min(h_c - 1, int(round(float(pt[1])))))
      fid = int(dense[iy, ix])
      if fid <= 0 or fid in fids:
        continue
      fids.append(fid)
      if arg2_source == "ref_1916":
        assigned_ref_fids.add(fid)
      if fid not in cache:
        cache[fid] = _poly_for_fid(fid, dir_map, sm_arcs, dense)
      fg = cache[fid]
      if fg is not None and not fg.is_empty:
        parts.append(fg)
    if not parts:
      return (None, fids)
    u = gis_helpers.clean_polygonal_geometry(parts[0] if len(parts) == 1 else unary_union(parts))
    return (u, fids)

  px_polities = {}
  for entry in cfg["polities"]:
    tid = entry["tusi_id"]
    src = entry.get("source", "ref_1916")
    geom, fids = _build_entry_geom(entry["seeds"], src)
    if geom is None or geom.is_empty:
      print(f"[REF WARN] Empty geometry for {tid} ({src} fids={fids})")
      continue
    px_polities[tid] = (geom, entry)

  px_masks = {}
  for mask_entry in cfg.get("masks", []):
    mid = mask_entry["mask_id"]
    src = mask_entry.get("source", "ref_1916")
    geom, _ = _build_entry_geom(mask_entry["seeds"], src)
    if geom is not None and not geom.is_empty:
      px_masks[mid] = (geom, mask_entry)

  # Audit uncovered 1916 faces inside domain after both polities and masks claim faces
  uncovered = _collect_uncovered_audit(cfg, dense_16, cls_16, names, assigned_ref_fids, transform, ref_rgb)
  print(f"[REF] Uncovered faces (>= 50 px) in 1916 bbox: {len(uncovered)}")
  for row in uncovered[:45]:
    print(f"  UNCOVERED fid={row['fid']} dom={row['dom']} area={row['area_px']} px=({row['px']},{row['py']}) ll=({row['lon']},{row['lat']}) rgb={row['rgb']}")

  px_polities, px_masks = _dissolve_text_holes_px(px_polities, px_masks, ref_rgb[:, x_off:, :], f22_rgb[:, x_off:, :])

  # Batch-project all pixel geometries to WGS84 preserving bitwise-identical shared seams
  all_px = {}
  for tid, val in px_polities.items():
    all_px[f"P::{tid}"] = val
  for mid, val in px_masks.items():
    all_px[f"M::{mid}"] = val
  all_wgs = _project_pixel_geom_dict(all_px, transform, x_off)

  polity_geoms = {k[3:]: v for k, v in all_wgs.items() if k.startswith("P::")}
  mask_geoms = {k[3:]: v for k, v in all_wgs.items() if k.startswith("M::")}

  # Subtract non-Chamdo polities from post-1918 mask so Lingtsang/Choling/Jomda/Derge stay clean holes
  if "__mask_dalai_lama_post1918__" in mask_geoms:
    m18, me = mask_geoms["__mask_dalai_lama_post1918__"]
    sub_post18 = [g for k, (g, _) in polity_geoms.items() if k != "chamdo_phagpalha_estate"]
    if sub_post18:
      m18 = gis_helpers.clean_polygonal_geometry(m18.difference(unary_union(sub_post18)))
      mask_geoms["__mask_dalai_lama_post1918__"] = (m18, me)

  # Ensure zero pairwise overlap between 1916 polities and 1922 polities
  p16_parts = [g for _, (g, ent) in polity_geoms.items() if ent.get("source") == "ref_1916"]
  p16_union = gis_helpers.clean_polygonal_geometry(unary_union(p16_parts)) if p16_parts else None
  for tid, (g, ent) in list(polity_geoms.items()):
    if ent.get("source") == "frame_1092" and p16_union is not None and g.intersects(p16_union):
      g_diff = gis_helpers.clean_polygonal_geometry(g.difference(p16_union))
      if g_diff is not None and not g_diff.is_empty:
        polity_geoms[tid] = (g_diff, ent)

  # Check pairwise overlap among exported polities
  p_keys = sorted(polity_geoms.keys())
  max_pair_ov = 0.0
  for i in range(len(p_keys)):
    ga = polity_geoms[p_keys[i]][0]
    for x in range(i + 1, len(p_keys)):
      gb = polity_geoms[p_keys[x]][0]
      if not ga.intersects(gb):
        continue
      ov = ga.intersection(gb).area
      if ov > max_pair_ov:
        max_pair_ov = ov
      if ov > 1e-6:
        print(f"[REF WARN] Pairwise overlap {p_keys[i]} vs {p_keys[x]}: {ov:.6f}")
  print(f"[REF] Exported polities: {len(polity_geoms)} | masks: {len(mask_geoms)} | max_pairwise_overlap={max_pair_ov:.2e}")

  # Assemble (props, geom) tuples for gis_helpers.write_geojson
  for tid, (g, ent) in sorted(polity_geoms.items()):
    props = {
      "feature_role": "polity",
      "rgb_1916": ent["rgb_1916"],
      "rgb_1917": ent["rgb_1917"],
      "rgb_1919": ent["rgb_1919"],
      "rgb_1929": ent["rgb_1929"],
      "source_frame": ent.get("source", "ref_1916"),
      "tusi_id": tid,
    }
    features_out.append((props, g))

  for mid, (g, ent) in sorted(mask_geoms.items()):
    props = {
      "feature_role": "mask",
      "source_frame": ent.get("source", "ref_1916"),
      "tusi_id": mid,
    }
    features_out.append((props, g))

  gis_helpers.write_geojson(out_path, features_out, 5)
  print(f"[REF] Wrote {len(features_out)} features to {out_path}")

  # Return statement
  return out_path


def lonlat_to_px (arg1_lons, arg2_lats, arg3_transform):
  """Project WGS84 longitude/latitude arrays to full 3840x2160 image pixel coordinates.

  @param arg1_lons Array or scalar of WGS84 longitudes.
  @param arg2_lats Array or scalar of WGS84 latitudes.
  @param arg3_transform Calibrated transform dict from _calibrate_transform.
  @return Tuple (px_arr, py_arr) of float64 numpy arrays.
  """
  # Convert from parameters
  lats = np.asarray(arg2_lats, dtype=np.float64)
  lons = np.asarray(arg1_lons, dtype=np.float64)
  transform = arg3_transform

  # Declare local instance variables.
  mys = merc_y(lats)
  pts = np.column_stack([lons, mys])
  corr = transform["rbf_fwd"](pts)
  px = transform["ax"]*lons + transform["bx"] + corr[:, 0]
  py = transform["ay"]*mys + transform["by"] + corr[:, 1]

  # Return statement
  return (px, py)


def merc_y (arg1_lats):
  """Compute EPSG:3857 spherical Mercator northing in degrees.

  @param arg1_lats Latitude values in degrees.
  @return Numpy array of Mercator northings in degrees.
  """
  # Convert from parameters
  lats = np.asarray(arg1_lats, dtype=np.float64)

  # Return statement
  return np.degrees(np.log(np.tan(np.pi / 4.0 + np.radians(lats) / 2.0)))


def inv_merc_y (arg1_mys):
  """Invert EPSG:3857 Mercator northing back to WGS84 latitude in degrees.

  @param arg1_mys Mercator northing values in degrees.
  @return Numpy array of WGS84 latitudes in degrees.
  """
  # Convert from parameters
  mys = np.asarray(arg1_mys, dtype=np.float64)

  # Return statement
  return np.degrees(2.0*np.arctan(np.exp(np.radians(mys))) - np.pi / 2.0)


def px_to_lonlat (arg1_px, arg2_py, arg3_transform):
  """Project full 3840x2160 pixel coordinates back to WGS84 longitude and latitude.

  @param arg1_px Array or list of full image x coordinates.
  @param arg2_py Array or list of full image y coordinates.
  @param arg3_transform Calibrated transform dict from _calibrate_transform.
  @return Tuple (lons, lats) of float64 numpy arrays.
  """
  # Convert from parameters
  px = np.asarray(arg1_px, dtype=np.float64)
  py = np.asarray(arg2_py, dtype=np.float64)
  transform = arg3_transform

  # Declare local instance variables.
  corr = transform["rbf_inv"](np.column_stack([px, py]))
  lon_lin = (px - transform["bx"]) / transform["ax"]
  my_lin = (py - transform["by"]) / transform["ay"]
  lons = lon_lin + corr[:, 0]
  lats = inv_merc_y(my_lin + corr[:, 1])

  # Return statement
  return (lons, lats)


def segment_reference_canvas (arg1_canvas_rgb, arg2_palette, arg3_grad_thresh, arg4_min_seed_area, arg5_lake_dist, arg6_micro_ovals, arg7_x_off, arg8_ring_px):
  """Segment reference map canvas with 3x3 morphological gradient, micro-oval whitelist, and counter merger.

  @param arg1_canvas_rgb RGB uint8 array cropped to map canvas (x >= x_off).
  @param arg2_palette Dictionary mapping palette class name -> [R, G, B].
  @param arg3_grad_thresh Maximum 3x3 morphological gradient for flat interiors.
  @param arg4_min_seed_area Minimum pixel count for autonomous seeds.
  @param arg5_lake_dist Euclidean RGB distance threshold around lake blue.
  @param arg6_micro_ovals List of micro-oval override dicts.
  @param arg7_x_off Full image x-offset of canvas left edge.
  @param arg8_ring_px Dilation kernel size for font-counter enclosure test.
  @return Tuple (dense_lbl, cls_map, names).
  """
  # Convert from parameters
  canvas_rgb = arg1_canvas_rgb
  grad_thresh = int(arg3_grad_thresh)
  lake_dist = float(arg5_lake_dist)
  micro_ovals = list(arg6_micro_ovals or [])
  min_seed_area = int(arg4_min_seed_area)
  palette = arg2_palette
  ring_px = int(arg8_ring_px)
  x_off = int(arg7_x_off)

  # Declare local instance variables.
  best_d2 = None
  best_idx = None
  cls_d = None
  cls_map = None
  dense_lbl = None
  dil3 = None
  ero3 = None
  flat = None
  grad3 = None
  h, w, _ = canvas_rgb.shape
  is_flat = None
  is_lake = None
  kern3 = np.ones((3, 3), dtype=np.uint8)
  lake_i = None
  names = list(palette.keys())
  pal_arr = np.asarray([palette[k] for k in names], dtype=np.float32)

  flat = canvas_rgb.reshape(-1, 3).astype(np.float32)
  best_idx = np.zeros(flat.shape[0], dtype=np.int32)
  best_d2 = np.full(flat.shape[0], 1e9, dtype=np.float32)
  for i in range(len(names)):
    diff = flat - pal_arr[i]
    d2 = np.sum(diff*diff, axis=1)
    m = d2 < best_d2
    best_d2[m] = d2[m]
    best_idx[m] = i
  cls_map = best_idx.reshape(h, w)
  cls_d = np.sqrt(best_d2).reshape(h, w)

  lake_i = names.index("lake")
  is_lake = (cls_map == lake_i) & (cls_d < lake_dist)

  dil3 = cv2.dilate(canvas_rgb, kern3)
  ero3 = cv2.erode(canvas_rgb, kern3)
  grad3 = np.max(dil3.astype(np.int16) - ero3.astype(np.int16), axis=2)
  is_flat = (grad3 <= grad_thresh) & (~is_lake)

  n_cc, cc_img, cc_stats, _ = cv2.connectedComponentsWithStats(is_flat.astype(np.uint8), connectivity=4)
  extra_id = n_cc
  protected_ids = set()

  # Inject & protect whitelisted micro-ovals (Gartok NE/SW, Shelkar, Pala Manor, Sera circle)
  for oval in micro_ovals:
    ix = int(round(float(oval["x"]) - x_off))
    iy = int(round(float(oval["y"])))
    if not (0 <= ix < w and 0 <= iy < h):
      continue
    mode = str(oval.get("mode", "grad_18"))
    if mode == "ring_fill":
      bx0, bx1, by0, by1 = [int(v) for v in oval["ring_box"]]
      cx0, cx1 = max(0, bx0 - x_off), min(w, bx1 - x_off)
      patch = canvas_rgb[by0:by1, cx0:cx1]
      ring_bin = ((patch[:, :, 0] < 205) & (patch[:, :, 0] > 70) & (patch[:, :, 1] < 195)).astype(np.uint8)
      ring_close = cv2.morphologyEx(ring_bin, cv2.MORPH_CLOSE, kern3)
      ff = ring_close.copy()
      cv2.floodFill(ff, np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8), (0, 0), 2)
      int_mask = (ff == 0)
      if np.sum(int_mask) >= 6:
        cc_img[by0:by1, cx0:cx1][int_mask] = extra_id
        protected_ids.add(extra_id)
        extra_id += 1
      continue
    if mode == "color_diff":
      bg = np.asarray(oval["bg_rgb"], dtype=np.float32)
      md = float(oval.get("min_dist", 25.0))
      cx0, cx1 = max(0, ix - 8), min(w, ix + 9)
      cy0, cy1 = max(0, iy - 8), min(h, iy + 9)
      patch = canvas_rgb[cy0:cy1, cx0:cx1].astype(np.float32)
      dist = np.linalg.norm(patch - bg, axis=2)
      nc_s, cc_s, st_s, _ = cv2.connectedComponentsWithStats((dist >= md).astype(np.uint8), connectivity=4)
      sc = int(cc_s[iy - cy0, ix - cx0])
      if sc > 0 and 4 <= st_s[sc, 4] <= 400:
        cc_img[cy0:cy1, cx0:cx1][cc_s == sc] = extra_id
        protected_ids.add(extra_id)
        extra_id += 1
      continue
    # Default grad_18
    cur_cid = int(cc_img[iy, ix])
    if cur_cid > 0 and int(cc_stats[cur_cid, 4]) < 1000:
      protected_ids.add(cur_cid)
      continue
    cx0, cx1 = max(0, ix - 14), min(w, ix + 15)
    cy0, cy1 = max(0, iy - 14), min(h, iy + 15)
    nc_s, cc_s, st_s, _ = cv2.connectedComponentsWithStats((grad3[cy0:cy1, cx0:cx1] <= 18).astype(np.uint8), connectivity=4)
    sc = int(cc_s[iy - cy0, ix - cx0])
    if sc > 0 and 4 <= st_s[sc, 4] <= 500:
      cc_img[cy0:cy1, cx0:cx1][cc_s == sc] = extra_id
      protected_ids.add(extra_id)
      extra_id += 1

  # Compute component stats & median RGBs
  n_total = extra_id
  areas_full = np.zeros(n_total, dtype=np.int32)
  bbox_cache = {}
  med_rgb = {}
  valid_ids = []
  # Count all pixels once using bincount
  flat_cc = cc_img.ravel()
  bc = np.bincount(flat_cc, minlength=n_total)
  for i in range(1, n_total):
    cnt = int(bc[i])
    if cnt < min_seed_area and i not in protected_ids:
      continue
    if i < n_cc:
      x0, y0, bw, bh = int(cc_stats[i, 0]), int(cc_stats[i, 1]), int(cc_stats[i, 2]), int(cc_stats[i, 3])
      bbox_cache[i] = (x0, y0, x0 + bw, y0 + bh)
      pts = canvas_rgb[y0:y0 + bh, x0:x0 + bw][cc_img[y0:y0 + bh, x0:x0 + bw] == i]
    else:
      ys, xs = np.where(cc_img == i)
      bbox_cache[i] = (int(np.min(xs)), int(np.min(ys)), int(np.max(xs)) + 1, int(np.max(ys)) + 1)
      pts = canvas_rgb[ys, xs]
    if pts.size == 0:
      continue
    areas_full[i] = cnt
    med_rgb[i] = np.median(pts, axis=0)
    valid_ids.append(i)

  # Strip interior font counters enclosed in uniform parent faces
  kern_ring = np.ones((ring_px, ring_px), dtype=np.uint8)
  merged_to = {}
  pad_r = ring_px // 2 + 3
  small_ids = sorted([i for i in valid_ids if areas_full[i] < 1200 and i not in protected_ids], key=lambda i: areas_full[i])
  for i in small_ids:
    bx0, by0, bx1, by1 = bbox_cache[i]
    x0, y0 = max(0, bx0 - pad_r), max(0, by0 - pad_r)
    x1, y1 = min(w, bx1 + pad_r), min(h, by1 + pad_r)
    sub_cc = cc_img[y0:y1, x0:x1]
    c_mask = (sub_cc == i)
    ring_mask = (cv2.dilate(c_mask.astype(np.uint8), kern_ring) > 0) & (~c_mask) & (sub_cc > 0)
    nbrs = sub_cc[ring_mask]
    if nbrs.size == 0:
      merged_to[i] = 0
      continue
    nbr_vals, nbr_cnts = np.unique(nbrs, return_counts=True)
    best_p = int(nbr_vals[np.argmax(nbr_cnts)])
    while best_p in merged_to and merged_to[best_p] != 0:
      best_p = merged_to[best_p]
    frac = float(np.max(nbr_cnts)) / float(nbrs.size)
    rgb_diff = float(np.max(np.abs(med_rgb[i] - med_rgb[best_p]))) if best_p in med_rgb else 999.0
    if frac >= 0.68 and rgb_diff <= 12.0 and areas_full[best_p] > areas_full[i]:
      merged_to[i] = best_p

  remap = np.zeros(n_total, dtype=np.int32)
  for i in valid_ids:
    a = i
    while a in merged_to and merged_to[a] != 0:
      a = merged_to[a]
    remap[i] = a
  seeds = remap[cc_img]
  _, nearest_rc = ndimage.distance_transform_edt(seeds == 0, return_indices=True)
  dense_lbl = seeds[nearest_rc[0], nearest_rc[1]]

  # Return statement
  return (dense_lbl, cls_map, names)


def main ():
  """CLI entrypoint to generate tibet_yushu_reference_polygons.geojson."""
  base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
  build_reference_polygons(base_dir)

  # Return statement
  return 0


if __name__ == "__main__":
  sys.exit(main())
