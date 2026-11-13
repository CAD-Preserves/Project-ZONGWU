"""Pure-topographic watershed, river, lake-shoreline, smoothing, and reach-scale helpers for BorderpoolGraphEngine."""

import math
import os
import sys
from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union
from shapely.prepared import prep

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)
from helpers import gis_helpers, path_helpers


def _append_clipped_line (arg1_line, arg2_clip_geom, arg3_prep_clip, arg4_lines):
  """Append arg1_line directly when inside arg3_prep_clip, or clip with arg2_clip_geom only on boundary crossings.

  @param arg1_line Candidate Shapely geometry to extract boundaries/lines from.
  @param arg2_clip_geom Clipping Shapely polygon.
  @param arg3_prep_clip Prepared geometry for arg2_clip_geom.
  @param arg4_lines Destination list accumulating cutter LineStrings.
  """
  # Convert from parameters
  clip_geom = arg2_clip_geom
  line = arg1_line
  lines = arg4_lines
  prep_clip = arg3_prep_clip

  if line is None or line.is_empty:
    return

  if prep_clip.contains(line):
    lines.append(line)
  elif prep_clip.intersects(line):
    clipped = line.intersection(clip_geom)
    if clipped is not None and not clipped.is_empty:
      lines.append(clipped)


def _chaikin_chain (arg1_line, arg2_simplify_tol, arg3_iters):
  """Simplify and Chaikin-smooth an internal planar arc while keeping junctions pinned and preventing straight chords.

  @param arg1_line Source LineString chain between topological junctions.
  @param arg2_simplify_tol Simplification tolerance in degrees.
  @param arg3_iters Number of Chaikin corner-cutting passes.
  @return Smoothed LineString.
  """
  # Convert from parameters
  iters = int(arg3_iters)
  line = arg1_line
  simp_tol = float(arg2_simplify_tol)

  # Declare local instance variables.
  coords = list(line.coords)
  is_ring = len(coords) >= 4 and math.hypot(coords[0][0] - coords[-1][0], coords[0][1] - coords[-1][1]) < 1e-9

  if len(coords) < 3:
    return line

  if is_ring:
    if float(line.length) < 0.10:
      return line
    s_ring = Polygon(coords).simplify(min(simp_tol, 0.016), preserve_topology=False)
    pts = list(s_ring.exterior.coords)[:-1] if s_ring.geom_type == "Polygon" else coords[:-1]
    if len(pts) < 4:
      pts = coords[:-1]
    for _ in range(min(2, iters)):
      nxt = []
      m_pts = len(pts)
      for i in range(m_pts):
        ax, ay = pts[i][0], pts[i][1]
        bx, by = pts[(i + 1) % m_pts][0], pts[(i + 1) % m_pts][1]
        nxt.append((0.75*ax + 0.25*bx, 0.75*ay + 0.25*by))
        nxt.append((0.25*ax + 0.75*bx, 0.25*ay + 0.75*by))
      pts = nxt
    pts.append(pts[0])

    # Return statement
    return LineString(pts)

  p0 = coords[0]
  p1 = coords[-1]
  simp = line.simplify(simp_tol, preserve_topology=False)
  sc = list(simp.coords)
  sc[0] = p0
  sc[-1] = p1

  chord = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
  if chord >= 0.06 and len(sc) <= 3:
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    best_pt = None
    best_dist = -1.0
    for vx, vy in coords[1:-1]:
      perp = abs(dx*(p0[1] - vy) - dy*(p0[0] - vx)) / max(1e-9, chord)
      if perp > best_dist:
        best_dist = perp
        best_pt = (vx, vy)
    if best_pt is not None and best_dist < 0.045*chord:
      nx = -dy / chord
      ny = dx / chord
      sign = 1.0 if ((best_pt[0] - p0[0])*nx + (best_pt[1] - p0[1])*ny) >= 0.0 else -1.0
      best_pt = (0.5*(p0[0] + p1[0]) + sign*0.05*chord*nx, 0.5*(p0[1] + p1[1]) + sign*0.05*chord*ny)
    if len(sc) == 2 and best_pt is not None:
      sc = [p0, best_pt, p1]
    elif len(sc) == 3 and best_pt is not None:
      sc[1] = best_pt

  pts = list(sc)
  for _ in range(iters):
    if len(pts) < 3:
      break
    nxt = [pts[0]]
    for i in range(len(pts) - 1):
      ax, ay = pts[i][0], pts[i][1]
      bx, by = pts[i + 1][0], pts[i + 1][1]
      nxt.append((0.75*ax + 0.25*bx, 0.75*ay + 0.25*by))
      nxt.append((0.25*ax + 0.75*bx, 0.25*ay + 0.75*by))
    nxt.append(pts[-1])
    pts = nxt

  out_ln = LineString(pts)
  if chord >= 0.06 and float(out_ln.length) / chord < 1.022:
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    nx, ny = -dy / chord, dx / chord
    best_sign = 1.0
    best_perp = -1.0
    for vx, vy in coords[1:-1]:
      proj = (vx - p0[0])*nx + (vy - p0[1])*ny
      if abs(proj) > best_perp:
        best_perp = abs(proj)
        best_sign = 1.0 if proj >= 0.0 else -1.0
    arch_mid = (0.5*(p0[0] + p1[0]) + best_sign*0.12*chord*nx, 0.5*(p0[1] + p1[1]) + best_sign*0.12*chord*ny)
    pts = [p0, arch_mid, p1]
    for _ in range(iters):
      nxt = [pts[0]]
      for i in range(len(pts) - 1):
        ax, ay = pts[i][0], pts[i][1]
        bx, by = pts[i + 1][0], pts[i + 1][1]
        nxt.append((0.75*ax + 0.25*bx, 0.75*ay + 0.25*by))
        nxt.append((0.25*ax + 0.75*bx, 0.25*ay + 0.75*by))
      nxt.append(pts[-1])
      pts = nxt
    out_ln = LineString(pts)

  # Return statement
  return out_ln


def _collect_fast_poly_boundaries (arg1_engine, arg2_tree, arg3_geoms, arg4_clip_geom, arg5_prep_clip, arg6_lines):
  """Query spatial index inside arg4_clip_geom, skipping intersection on strictly internal polygons.

  @param arg1_engine BorderpoolGraphEngine instance.
  @param arg2_tree STRtree over arg3_geoms.
  @param arg3_geoms List of Shapely polygons.
  @param arg4_clip_geom Clipping Shapely polygon.
  @param arg5_prep_clip Prepared geometry for arg4_clip_geom.
  @param arg6_lines Destination list accumulating cutter LineStrings.
  """
  # Convert from parameters
  clip_geom = arg4_clip_geom
  engine = arg1_engine
  geoms = arg3_geoms
  lines = arg6_lines
  prep_clip = arg5_prep_clip
  tree = arg2_tree

  if tree is None:
    return

  for idx in tree.query(clip_geom):
    geom = geoms[int(idx)]
    if prep_clip.contains(geom):
      lines.extend(engine._extract_boundaries(geom))
    elif prep_clip.intersects(geom):
      for b_ln in engine._extract_boundaries(geom):
        _append_clipped_line(b_ln, clip_geom, prep_clip, lines)


def _smooth_planar_tiles (arg1_engine, arg2_raw_polys, arg3_polities, arg4_host_domain, arg5_cfg):
  """Apply topology-preserving Chaikin smoothing to internal modelled arcs while keeping outer and lake borders exact.

  @param arg1_engine BorderpoolGraphEngine instance.
  @param arg2_raw_polys Dict mapping tusi_id -> assembled Shapely Polygon.
  @param arg3_polities List of polity dicts in the cluster.
  @param arg4_host_domain Shapely host domain geometry.
  @param arg5_cfg Cluster config dictionary.
  @return Dict mapping tusi_id -> smoothed Shapely Polygon.
  """
  # Convert from parameters
  cfg = arg5_cfg if isinstance(arg5_cfg, dict) else {}
  engine = arg1_engine
  host_domain = arg4_host_domain
  polities = list(arg3_polities or [])
  raw_polys = dict(arg2_raw_polys)

  # Declare local instance variables.
  bnds = engine._extract_boundaries(host_domain)
  chaikin_iters = int(cfg.get("smooth_chaikin_iters") or 3)
  ext_buf = host_domain.boundary.buffer(3e-4)
  lake_buf = None
  out_chains = []
  pol_union = unary_union(list(raw_polys.values())) if raw_polys else None
  prep_host = prep(host_domain)
  simp_tol = float(cfg.get("smooth_simplify_deg") or 0.022)
  tiles = [(tid, g) for tid, g in raw_polys.items()]

  if not raw_polys:
    return raw_polys

  bg_geom = gis_helpers.clean_polygonal_geometry(host_domain.difference(pol_union)) if pol_union is not None else host_domain
  if bg_geom is not None and not bg_geom.is_empty:
    bg_parts = [bg_geom] if bg_geom.geom_type == "Polygon" else (list(bg_geom.geoms) if hasattr(bg_geom, "geoms") else [])
    for sub in bg_parts:
      if sub.area > 1e-8:
        tiles.append(("__bg__", sub))

  for _, tg in tiles:
    bnds.extend(engine._extract_boundaries(tg))

  ensure_lake_index(engine)
  near_lakes = [lg for lg in getattr(engine, "lake_geoms", []) if lg.intersects(host_domain)]
  if near_lakes:
    lake_buf = unary_union(near_lakes).boundary.buffer(3e-4)

  noded = unary_union([b for b in bnds if b is not None and not b.is_empty])
  merged_lns = linemerge(noded)
  chains = [merged_lns] if merged_lns.geom_type == "LineString" else (list(merged_lns.geoms) if hasattr(merged_lns, "geoms") else [])
  seat_union = unary_union([Point(float(p["seat_lon"]), float(p["seat_lat"])) for p in polities]) if polities else None

  for ch in chains:
    if ch.length < 0.02 or ch.intersection(ext_buf).length >= 0.4*ch.length or (lake_buf is not None and ch.intersection(lake_buf).length >= 0.5*ch.length):
      out_chains.append(ch)
    else:
      d_sp = float(ch.distance(seat_union)) if seat_union is not None else 1.0
      local_tol = min(simp_tol, max(0.002, 0.35*d_sp))
      out_chains.append(_chaikin_chain(ch, local_tol, chaikin_iters))

  faces = list(polygonize(unary_union([c for c in out_chains if c is not None and not c.is_empty])))
  if not faces:
    return raw_polys

  other_sps = [(p["tusi_id"], Point(float(p["seat_lon"]), float(p["seat_lat"]))) for p in polities]
  tile_geoms = [tg for _, tg in tiles]
  tile_ids = [tid for tid, _ in tiles]
  t_tree = STRtree(tile_geoms)
  by_tid = {}

  for f in faces:
    if f.area <= 1e-8 or not prep_host.contains(f.representative_point()):
      continue
    best_a = -1.0
    owner = None
    for idx in t_tree.query(f):
      ov_a = f.intersection(tile_geoms[int(idx)]).area
      if ov_a > best_a:
        best_a = ov_a
        owner = tile_ids[int(idx)]
    if owner is not None and owner != "__bg__":
      by_tid.setdefault(owner, []).append(f)

  smoothed = {}
  for t in polities:
    tid = t["tusi_id"]
    f_list = by_tid.get(tid, [])
    if not f_list:
      if tid in raw_polys:
        smoothed[tid] = raw_polys[tid]
      continue
    sp = Point(float(t["seat_lon"]), float(t["seat_lat"]))
    mg = gis_helpers.clean_polygonal_geometry(unary_union(f_list))
    if mg is None or mg.is_empty:
      smoothed[tid] = raw_polys.get(tid)
      continue
    if mg.geom_type == "MultiPolygon":
      mg = next((sub for sub in mg.geoms if sub.contains(sp) or sub.distance(sp) < 1e-6), max(mg.geoms, key=lambda s: s.area))
    if mg.geom_type == "Polygon" and len(mg.interiors) > 0:
      kept_rings = [r for r in mg.interiors if any(Polygon(r).contains(osp) or Polygon(r).distance(osp) < 1e-5 for pid, osp in other_sps if pid != tid) or Polygon(r).difference(host_domain).area >= 0.5*Polygon(r).area]
      mg = Polygon(mg.exterior, kept_rings)
    if not (mg.contains(sp) or mg.distance(sp) < 1e-6):
      mg = raw_polys.get(tid, mg)
    smoothed[tid] = mg

  # Return statement
  return {k: v for k, v in smoothed.items() if v is not None and not v.is_empty}


def assemble_and_smooth_cluster_polygons (arg1_engine, arg2_atoms, arg3_labels, arg4_polities, arg5_host_domain, arg6_cfg=None):
  """Assemble raw atom assignments into single Polygons per polity, applying optional shared-arc Chaikin smoothing.

  @param arg1_engine BorderpoolGraphEngine instance.
  @param arg2_atoms List of atom Shapely polygons.
  @param arg3_labels Integer label list aligned with arg2_atoms.
  @param arg4_polities List of polity dicts in the cluster.
  @param arg5_host_domain Shapely host domain geometry.
  @param arg6_cfg Optional cluster config dictionary.
  @return Dict mapping tusi_id -> final Shapely Polygon.
  """
  # Convert from parameters
  atoms = list(arg2_atoms)
  cfg = arg6_cfg if isinstance(arg6_cfg, dict) else {}
  engine = arg1_engine
  host_domain = arg5_host_domain
  labels = list(arg3_labels)
  polities = list(arg4_polities or [])

  # Declare local instance variables.
  other_sps = [(p["tusi_id"], Point(float(p["seat_lon"]), float(p["seat_lat"]))) for p in polities]
  raw_geoms = {}

  for k, t in enumerate(polities):
    k_atoms = [atoms[i] for i in range(len(atoms)) if labels[i] == k]
    if not k_atoms:
      continue
    sp = Point(float(t["seat_lon"]), float(t["seat_lat"]))
    merged = gis_helpers.clean_polygonal_geometry(unary_union(k_atoms))
    if merged is None or merged.is_empty:
      continue
    if merged.geom_type == "MultiPolygon":
      merged = next((sub for sub in merged.geoms if sub.contains(sp) or sub.distance(sp) < 1e-6), max(merged.geoms, key=lambda s: s.area))
    if merged.geom_type == "Polygon" and len(merged.interiors) > 0:
      kept_rings = [r for r in merged.interiors if any(Polygon(r).contains(osp) or Polygon(r).distance(osp) < 1e-5 for pid, osp in other_sps if pid != t["tusi_id"]) or Polygon(r).difference(host_domain).area >= 0.5*Polygon(r).area]
      merged = Polygon(merged.exterior, kept_rings)
    if not (merged.contains(sp) or merged.distance(sp) < 1e-6):
      merged = gis_helpers.clean_polygonal_geometry(unary_union([merged, sp.buffer(0.002).intersection(host_domain)]))
    raw_geoms[t["tusi_id"]] = merged

  if bool(cfg.get("smooth_internal_borders", False)):
    return _smooth_planar_tiles(engine, raw_geoms, polities, host_domain, cfg)

  # Return statement
  return raw_geoms


def build_pure_topographic_cutters (arg1_engine, arg2_host_domain, arg3_seat_pts, arg4_bg_pts, arg5_barrier_names, arg6_cfg=None):
  """Collect pure natural cutter LineStrings (HyBAS 8/9/10, HydroRIVERS, 1820 lakes, high-altitude DEM contours) with zero PRC adm3 boundaries.

  @param arg1_engine BorderpoolGraphEngine instance.
  @param arg2_host_domain Shapely host domain Polygon/MultiPolygon.
  @param arg3_seat_pts List of (lon, lat) polity seat coordinates.
  @param arg4_bg_pts List of (lon, lat) curated background seat coordinates.
  @param arg5_barrier_names List of river name substrings to treat as major barriers.
  @param arg6_cfg Optional cluster config dictionary.
  @return List of shapely LineString/MultiLineString geometries clipped near arg2_host_domain.
  """
  # Convert from parameters
  barrier_names = [b.lower() for b in (arg5_barrier_names or [])]
  bg_pts = list(arg4_bg_pts or [])
  cfg = arg6_cfg if isinstance(arg6_cfg, dict) else {}
  engine = arg1_engine
  host_domain = arg2_host_domain
  seat_pts = list(arg3_seat_pts or [])

  # Declare local instance variables.
  buf_dom = host_domain.buffer(0.01)
  contour_levels = cfg.get("topo_contour_levels", [4200, 4800, 5300])
  core_r = float(cfg.get("topo_hybas10_radius_deg") or 0.55)
  core_zones = None
  lines = engine._extract_boundaries(host_domain)
  min_contour_len = float(cfg.get("topo_min_contour_length_deg") or 0.22)
  min_ord_core = int(cfg.get("topo_min_hydrorivers_core") or 4)
  min_ord_global = int(cfg.get("topo_min_hydrorivers_global") or 5)
  prep_core = None
  prep_dom = prep(buf_dom)
  simp_tol = float(cfg.get("topo_contour_simplify_deg") or 0.0025)

  # 1. Historical CHGIS 1820 lake shorelines so polities wrap cleanly around Tibetan lakes
  ensure_lake_index(engine)
  if getattr(engine, "lake_tree", None) is not None:
    _collect_fast_poly_boundaries(engine, engine.lake_tree, engine.lake_geoms, buf_dom, prep_dom, lines)

  # 2. HydroBASINS Level 8 & 9 macro/meso watersheds across the entire domain
  for lvl in (8, 9):
    _collect_fast_poly_boundaries(engine, engine.hybas_trees.get(lvl), engine.hybas.get(lvl, []), buf_dom, prep_dom, lines)

  # 3. HydroBASINS Level 10 fine valley basins around polity seats and curated dzongs
  t10 = engine.hybas_trees.get(10)
  zone_polys = [Point(sx, sy).buffer(core_r) for sx, sy in (seat_pts + bg_pts)]
  if zone_polys:
    core_zones = unary_union(zone_polys).intersection(buf_dom)
    if core_zones is not None and not core_zones.is_empty:
      prep_core = prep(core_zones)
      if t10 is not None:
        _collect_fast_poly_boundaries(engine, t10, engine.hybas.get(10, []), core_zones, prep_core, lines)

  # 4. HydroRIVERS & Named Waterways (ORD_STRA >= min_ord_global globally; >= min_ord_core around seeds)
  if engine.hydrorivers_tree is not None:
    for idx in engine.hydrorivers_tree.query(buf_dom):
      ord_s, rg = engine.hydrorivers[int(idx)]
      if ord_s >= min_ord_global or (ord_s >= min_ord_core and prep_core is not None and prep_core.intersects(rg)):
        _append_clipped_line(rg, buf_dom, prep_dom, lines)
  for wp, wg in engine.waterways:
    nm = (str(wp.get("name_en") or "") + " " + str(wp.get("name_ch") or "")).lower()
    if any(bn in nm for bn in barrier_names) or "NaturalEarth" in str(wp.get("source") or ""):
      _append_clipped_line(wg, buf_dom, prep_dom, lines)

  # 5. High-altitude Terrarium DEM ridge/basin contours
  if contour_levels:
    for _, cg in engine.elev_builder.extract_local_contours(host_domain.bounds, contour_levels):
      if cg.length < min_contour_len or not prep_dom.intersects(cg):
        continue
      simp_cg = cg.simplify(simp_tol, preserve_topology=False)
      if simp_cg.length >= min_contour_len:
        _append_clipped_line(simp_cg, buf_dom, prep_dom, lines)

  # Return statement
  return lines


def ensure_lake_index (arg1_engine):
  """Lazy-load and cache CHGIS 1820 lake polygons on arg1_engine for natural shoreline cuts.

  @param arg1_engine BorderpoolGraphEngine instance.
  @return Count of indexed lake polygons.
  """
  # Convert from parameters
  engine = arg1_engine

  if hasattr(engine, "lake_geoms"):
    return len(engine.lake_geoms)

  # Declare local instance variables.
  lakes = []
  lks_zip = path_helpers.resolve_source_file("chgis", "v6_1820_lks_pgn_utf.zip", engine.base_dir)

  if os.path.exists(lks_zip):
    for _, geom in gis_helpers.read_zip_shapefile_wgs84(lks_zip, "utf-8", 5):
      cg = gis_helpers.clean_polygonal_geometry(geom)
      if cg is not None and not cg.is_empty and cg.area >= 0.001:
        lakes.append(cg)

  engine.lake_geoms = lakes
  engine.lake_tree = STRtree(lakes) if lakes else None

  # Return statement
  return len(lakes)


def resolve_polity_reach_scales (arg1_polities, arg2_cluster_cfg, arg3_allow_bg):
  """Resolve per-class outbound Dijkstra step multipliers for polities and optional background class.

  @param arg1_polities List of polity dictionaries in the cluster.
  @param arg2_cluster_cfg Cluster configuration dictionary.
  @param arg3_allow_bg Boolean indicating whether background class k_pol is active.
  @return List of positive float scale factors (length len(arg1_polities) + (1 if arg3_allow_bg else 0)).
  """
  # Convert from parameters
  allow_bg = bool(arg3_allow_bg)
  cfg = arg2_cluster_cfg if isinstance(arg2_cluster_cfg, dict) else {}
  polities = list(arg1_polities or [])

  # Declare local instance variables.
  bg_scale = max(0.05, float(cfg.get("bg_reach_scale") or 1.0))
  scale_map = cfg.get("polity_reach_scales", {})
  scales = []

  for t in polities:
    tid = str(t.get("tusi_id") or "")
    val = float(scale_map.get(tid, 1.0))
    scales.append(max(0.05, val))

  if allow_bg:
    scales.append(bg_scale)

  # Return statement
  return scales
