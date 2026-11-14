"""Planar coverage topology cleaning, hole repair, seam harmonisation and audit helpers."""

import os
import sys
from shapely import STRtree, coverage_simplify, coverage_union_all, get_precision, polygonize, prepare, set_precision, union_all
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union

if os.path.abspath(os.path.join(os.path.dirname(__file__), "..")) not in sys.path:
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from helpers import gis_helpers


def _assign_part_to_neighbour (arg1_part, arg2_geoms, arg3_tree, arg4_skip_idx=None, arg5_allowed_set=None):
  """Find the best neighbouring feature index to absorb a small hole or sliver polygon.

  @param arg1_part Polygon sliver or hole to reassign.
  @param arg2_geoms List of current feature Shapely geometries.
  @param arg3_tree Spatial index over arg2_geoms.
  @param arg4_skip_idx Optional index to exclude from candidates.
  @param arg5_allowed_set Optional set of allowed candidate indices.
  @return Best candidate integer index, or -1 if none found.
  """
  # Convert from parameters
  allowed_set = arg5_allowed_set
  geoms = arg2_geoms
  part = arg1_part
  skip_idx = arg4_skip_idx
  tree = arg3_tree

  # Declare local instance variables.
  best_dist = 1e12
  best_idx = -1
  best_score = (-1.0, 1e12)
  cand_idxs = []
  dist = 0.0
  idx = 0
  probe = part.buffer(0.002)
  score = (-1.0, 1e12)
  shared_len = 0.0

  cand_idxs = list(tree.query(probe))
  for idx in cand_idxs:
    idx = int(idx)
    if skip_idx is not None and idx == skip_idx:
      continue
    if allowed_set is not None and idx not in allowed_set:
      continue
    if geoms[idx] is None or geoms[idx].is_empty:
      continue
    shared_len = float(part.boundary.intersection(geoms[idx].boundary).length)
    dist = float(part.distance(geoms[idx]))
    score = (shared_len, -dist)
    if score > best_score:
      best_score = score
      best_idx = idx

  if best_idx < 0:
    for idx, geom in enumerate(geoms):
      if skip_idx is not None and idx == skip_idx:
        continue
      if allowed_set is not None and idx not in allowed_set:
        continue
      if geom is None or geom.is_empty:
        continue
      dist = float(part.distance(geom))
      if dist < best_dist:
        best_dist = dist
        best_idx = idx

  # Return statement
  return best_idx


def _extract_polygons (arg1_geom, arg2_min_area=0.0):
  """Extract valid non-empty Polygon parts exceeding min_area from any Shapely geometry.

  @param arg1_geom Input Shapely geometry.
  @param arg2_min_area Minimum polygon area threshold in square degrees.
  @return List of Polygon objects.
  """
  # Convert from parameters
  geom = arg1_geom
  min_area = float(arg2_min_area or 0.0)

  # Declare local instance variables.
  out = []
  sub = None

  if geom is None or geom.is_empty:
    return out

  if geom.geom_type == "Polygon":
    if geom.area > min_area:
      out.append(geom)
  elif geom.geom_type in ("MultiPolygon", "GeometryCollection"):
    for sub in geom.geoms:
      if sub.geom_type == "Polygon" and sub.area > min_area:
        out.append(sub)
      elif sub.geom_type in ("MultiPolygon", "GeometryCollection"):
        out.extend(_extract_polygons(sub, min_area))

  # Return statement
  return out


def _pointwise_snap (arg1_geom, arg2_grid_size):
  """Tag or round geometry coordinates pointwise to grid_size without re-running valid_output overlay.

  @param arg1_geom Input Shapely geometry.
  @param arg2_grid_size Precision grid spacing in degrees.
  @return Precision-tagged valid polygonal Shapely geometry or None.
  """
  # Convert from parameters
  geom = arg1_geom
  grid_size = float(arg2_grid_size)

  if geom is None or geom.is_empty:
    return None

  # Declare local instance variables.
  snapped = None

  if grid_size > 0.0:
    try:
      snapped = set_precision(geom, grid_size, mode="pointwise")
      if snapped is not None and not snapped.is_empty and snapped.is_valid:
        return snapped
    except Exception:
      pass

  # Return statement
  return gis_helpers.clean_polygonal_geometry(geom)


def _snap_and_clean (arg1_geom, arg2_grid_size):
  """Snap a polygonal geometry to precision grid and repair self-intersections.

  @param arg1_geom Input Shapely geometry.
  @param arg2_grid_size Precision grid spacing in degrees.
  @return Cleaned valid polygonal geometry or None.
  """
  # Convert from parameters
  geom = arg1_geom
  grid_size = float(arg2_grid_size)

  if geom is None or geom.is_empty:
    return None
  if (
    grid_size > 0.0
    and geom.geom_type in ("Polygon", "MultiPolygon")
    and geom.is_valid
    and abs(float(get_precision(geom)) - grid_size) < 1e-12
  ):
    return geom

  # Declare local instance variables.
  cleaned = gis_helpers.clean_polygonal_geometry(geom)
  snapped = None

  if cleaned is None:
    return None
  if grid_size > 0.0:
    try:
      snapped = set_precision(cleaned, grid_size)
      cleaned = gis_helpers.clean_polygonal_geometry(snapped)
    except Exception:
      pass

  # Return statement
  return cleaned


def _unclaimed_hole_geom (arg1_hole_poly, arg2_parent_poly, arg3_all_polys, arg4_poly_tree):
  """Subtract any disconnected island polygons nested inside an interior hole ring via STRtree.

  @param arg1_hole_poly Polygon constructed from an interior ring of a union geometry.
  @param arg2_parent_poly Parent Polygon containing arg1_hole_poly (excluded from subtraction).
  @param arg3_all_polys List of individual feature Shapely geometries in the layer.
  @param arg4_poly_tree Spatial STRtree built over arg3_all_polys.
  @return Sub-geometry representing only truly unclaimed interior space.
  """
  # Convert from parameters
  all_polys = arg3_all_polys
  hole_poly = arg1_hole_poly
  parent_poly = arg2_parent_poly
  poly_tree = arg4_poly_tree

  if hole_poly is None or hole_poly.is_empty or poly_tree is None:
    return hole_poly

  # Declare local instance variables.
  cand = None
  cands = []
  idx = 0
  sub = None

  for idx in poly_tree.query(hole_poly):
    cand = all_polys[int(idx)]
    if cand is None or cand.is_empty or cand is parent_poly:
      continue
    for sub in _extract_polygons(cand):
      if sub.area < hole_poly.area and hole_poly.intersects(sub):
        if hole_poly.intersection(sub).area > 1e-10:
          cands.append(sub)

  if not cands:
    return hole_poly

  # Return statement
  return hole_poly.difference(_union_polygons(cands, False))


def _union_polygons (arg1_geoms, arg2_disjoint=False):
  """Union a non-empty list of cleaned polygonal geometries, using coverage_union_all only when disjoint.

  @param arg1_geoms Iterable of Shapely polygonal geometries.
  @param arg2_disjoint True only when inputs are guaranteed non-overlapping coverage tiles.
  @return Valid combined Shapely geometry or None.
  """
  # Convert from parameters
  disjoint = bool(arg2_disjoint)
  geoms = [g for g in arg1_geoms if g is not None and not g.is_empty]

  # Declare local instance variables.
  idx = 0
  l1_tiles = []
  l2_tiles = []
  merged = None
  ordered = []

  if not geoms:
    return None
  if len(geoms) == 1:
    return gis_helpers.clean_polygonal_geometry(geoms[0])

  if disjoint:
    try:
      merged = coverage_union_all(geoms)
      if merged is not None and not merged.is_empty:
        return gis_helpers.clean_polygonal_geometry(merged)
    except Exception:
      pass

  if len(geoms) > 96:
    ordered = sorted(geoms, key=lambda g: (int(g.bounds[0] // 3.0), int(g.bounds[1] // 3.0)))
    l1_tiles = [unary_union(ordered[idx:idx + 48]) for idx in range(0, len(ordered), 48)]
    l2_tiles = [unary_union(l1_tiles[idx:idx + 8]) for idx in range(0, len(l1_tiles), 8)]
    merged = unary_union(l2_tiles)
  else:
    merged = unary_union(geoms)

  # Return statement
  return gis_helpers.clean_polygonal_geometry(merged)


def absorb_terrestrial_micro_shards (arg1_features, arg2_area_thresh=1e-4, arg3_grid_size=1e-5):
  """Absorb disconnected inland overlay slivers into adjacent features while preserving offshore islands.

  @param arg1_features List of (properties_dict, shapely_geom) tuples.
  @param arg2_area_thresh Maximum secondary polygon area eligible as a sliver.
  @param arg3_grid_size Precision grid size for final snapping.
  @return Cleaned list of (properties_dict, shapely_geom) tuples.
  """
  # Convert from parameters
  area_thresh = float(arg2_area_thresh)
  features = list(arg1_features)
  grid_size = float(arg3_grid_size)

  # Declare local instance variables.
  geoms = [_snap_and_clean(g, grid_size) for _, g in features]
  i = 0
  keep_parts = []
  nb_idx = -1
  out = []
  part = None
  parts = []
  perim = 0.0
  props_list = [dict(p) for p, _ in features]
  reassigned = False
  shared = 0.0
  tree = None

  if not geoms:
    return out

  tree = STRtree([g if g is not None else Polygon() for g in geoms])
  for i, g in enumerate(geoms):
    if g is None or g.is_empty or g.geom_type == "Polygon":
      continue
    parts = _extract_polygons(g)
    if len(parts) <= 1:
      continue
    parts.sort(key=lambda x: x.area, reverse=True)
    keep_parts = [parts[0]]
    reassigned = False
    for part in parts[1:]:
      if part.area > area_thresh:
        keep_parts.append(part)
        continue
      nb_idx = _assign_part_to_neighbour(part, geoms, tree, i)
      perim = float(part.boundary.length)
      if nb_idx >= 0 and perim > 0.0:
        shared = float(part.boundary.intersection(geoms[nb_idx].boundary).length)
        if shared / perim > 0.35:
          geoms[nb_idx] = _snap_and_clean(_union_polygons([geoms[nb_idx], part], False), grid_size)
          reassigned = True
          continue
      keep_parts.append(part)
    if reassigned:
      geoms[i] = _snap_and_clean(_union_polygons(keep_parts, True), grid_size)

  for props, geom in zip(props_list, geoms):
    if geom is not None and not geom.is_empty:
      out.append((props, geom))

  # Return statement
  return out


def aggregate_coverage_by_key (arg1_features, arg2_key_fn, arg3_meta_builder_fn, arg4_grid_size=1e-5, arg5_hole_thresh=0.05):
  """Aggregate a cleaned fine-grained planar coverage into parent units while preserving occupied enclaves.

  @param arg1_features List of (properties_dict, shapely_geom) tuples.
  @param arg2_key_fn Callable(props) returning grouping key or None to skip.
  @param arg3_meta_builder_fn Callable(key, member_props_list) returning aggregated properties dict.
  @param arg4_grid_size Precision grid spacing in degrees.
  @param arg5_hole_thresh Maximum unoccupied pinhole area in deg2 to fill automatically.
  @return List of (aggregated_props, shapely_geom) tuples.
  """
  # Convert from parameters
  features = list(arg1_features)
  grid_size = float(arg4_grid_size)
  hole_thresh = float(arg5_hole_thresh)
  key_fn = arg2_key_fn
  meta_fn = arg3_meta_builder_fn

  # Declare local instance variables.
  bucket_geoms = []
  bucket_rows = []
  bucket_tree = None
  buckets = {}
  geoms = []
  h_poly = None
  idx = 0
  key = None
  kept_rings = []
  members = []
  merged = None
  occupied = False
  other_g = None
  other_idx = 0
  out = []
  poly = None
  removed_any = False
  ring = None
  sub_polys = []

  for props, geom in features:
    if geom is None or geom.is_empty:
      continue
    key = key_fn(props)
    if key is None:
      continue
    if key not in buckets:
      buckets[key] = ([], [])
    buckets[key][0].append(props)
    buckets[key][1].append(geom)

  for key in sorted(buckets.keys()):
    members, geoms = buckets[key]
    merged = _pointwise_snap(_union_polygons(geoms, True), grid_size)
    if merged is None or merged.is_empty:
      continue
    bucket_rows.append((key, members, merged))
    bucket_geoms.append(merged)

  if not bucket_rows:
    return out

  bucket_tree = STRtree(bucket_geoms)
  for idx, (key, members, merged) in enumerate(bucket_rows):
    if hole_thresh > 0.0:
      removed_any = False
      sub_polys = []
      for poly in _extract_polygons(merged):
        kept_rings = []
        for ring in poly.interiors:
          h_poly = Polygon(ring)
          if h_poly.area > hole_thresh:
            kept_rings.append(ring)
            continue
          occupied = False
          for other_idx in bucket_tree.query(h_poly):
            other_idx = int(other_idx)
            if other_idx == idx:
              continue
            other_g = bucket_geoms[other_idx]
            if h_poly.intersects(other_g) and h_poly.intersection(other_g).area > 1e-10:
              occupied = True
              break
          if occupied:
            kept_rings.append(ring)
          else:
            removed_any = True
        sub_polys.append(Polygon(poly.exterior, kept_rings))
      if removed_any:
        merged = _pointwise_snap(_union_polygons(sub_polys, True), grid_size)
    if merged is not None and not merged.is_empty:
      out.append((meta_fn(key, members), merged))

  # Return statement
  return out


def audit_planar_layer (arg1_features, arg2_overlap_thresh=1e-5, arg3_hole_thresh=5e-4):
  """Inspect a GeoJSON feature list for validity errors, pairwise overlaps and interior holes.

  @param arg1_features List of (properties_dict, shapely_geom) tuples.
  @param arg2_overlap_thresh Minimum intersection area counted as an overlap defect.
  @param arg3_hole_thresh Minimum interior hole area in coverage union counted as a void.
  @return Audit dictionary with counts, max defect areas and hole centroids.
  """
  # Convert from parameters
  features = list(arg1_features)
  hole_thresh = float(arg3_hole_thresh)
  overlap_thresh = float(arg2_overlap_thresh)

  # Declare local instance variables.
  geoms = []
  hole_centroids = []
  hole_count = 0
  hp = None
  i = 0
  invalid_count = 0
  j = 0
  max_hole = 0.0
  max_overlap = 0.0
  ov_area = 0.0
  overlap_count = 0
  poly = None
  ring = None
  tree = None
  u_all = None
  unclaimed = None

  for _, geom in features:
    if geom is None or geom.is_empty:
      invalid_count += 1
      continue
    if not geom.is_valid:
      invalid_count += 1
    geoms.append(geom)

  if geoms:
    tree = STRtree(geoms)
    for i, g_i in enumerate(geoms):
      for j in tree.query(g_i):
        j = int(j)
        if j <= i:
          continue
        if not g_i.intersects(geoms[j]):
          continue
        ov_area = float(g_i.intersection(geoms[j]).area)
        if ov_area > overlap_thresh:
          overlap_count += 1
          if ov_area > max_overlap:
            max_overlap = ov_area

    u_all = _union_polygons(geoms, False)
    if u_all is not None:
      for poly in _extract_polygons(u_all):
        for ring in poly.interiors:
          hp = Polygon(ring)
          if hp.area <= hole_thresh:
            continue
          unclaimed = _unclaimed_hole_geom(hp, poly, geoms, tree)
          if unclaimed is not None and unclaimed.area > hole_thresh:
            hole_count += 1
            if unclaimed.area > max_hole:
              max_hole = float(unclaimed.area)
            hole_centroids.append((round(float(hp.centroid.x), 4), round(float(hp.centroid.y), 4), round(float(unclaimed.area), 6)))

  # Return statement
  return {
    "feature_count": len(features),
    "hole_centroids": hole_centroids,
    "hole_count": hole_count,
    "invalid_count": invalid_count,
    "max_hole_deg2": max_hole,
    "max_overlap_deg2": max_overlap,
    "overlap_count": overlap_count,
  }


def clean_planar_coverage (arg1_features, arg2_grid_size=1e-5, arg3_hole_thresh=0.05, arg4_sliver_thresh=1e-4, arg5_priority_fn=None):
  """Repair overlaps, slivers and unclaimed interior voids to yield a strict planar coverage.

  @param arg1_features List of (properties_dict, shapely_geom) tuples.
  @param arg2_grid_size Precision grid size in degrees (e.g. 1e-5).
  @param arg3_hole_thresh Maximum enclosed hole area in deg2 filled into neighbours.
  @param arg4_sliver_thresh Maximum disconnected inland sliver area reassigned to neighbours.
  @param arg5_priority_fn Optional Callable(props, geom) returning comparable priority tuple (higher wins overlaps).
  @return Cleaned list of (properties_dict, shapely_geom) tuples.
  """
  # Convert from parameters
  features = list(arg1_features)
  grid_size = float(arg2_grid_size)
  hole_thresh = float(arg3_hole_thresh)
  priority_fn = arg5_priority_fn
  sliver_thresh = float(arg4_sliver_thresh)

  # Declare local instance variables.
  blockers = []
  diff_geom = None
  geoms = []
  hp = None
  i = 0
  j = 0
  nb_idx = -1
  orig_geoms = []
  out = []
  part = None
  poly = None
  prios = []
  props_list = []
  ring = None
  tree = None
  u_all = None
  unclaimed = None

  for props, geom in features:
    cleaned = _snap_and_clean(geom, grid_size)
    if cleaned is None or cleaned.is_empty:
      continue
    geoms.append(cleaned)
    orig_geoms.append(cleaned)
    props_list.append(dict(props))
    if priority_fn is not None:
      prios.append(priority_fn(props, cleaned))
    else:
      prios.append((0, float(cleaned.area), -len(geoms)))

  if not geoms:
    return out

  # Pass 1: Subtract pairwise overlaps from lower-priority neighbours
  tree = STRtree(geoms)
  for i in range(len(geoms)):
    blockers = []
    for j in tree.query(geoms[i]):
      j = int(j)
      if j == i:
        continue
      if prios[j] > prios[i] and geoms[i].intersects(geoms[j]):
        if geoms[i].intersection(geoms[j]).area > 1e-8:
          blockers.append(geoms[j])
    if blockers:
      diff_geom = _snap_and_clean(geoms[i].difference(_union_polygons(blockers, False)), grid_size)
      if diff_geom is not None and not diff_geom.is_empty:
        geoms[i] = diff_geom
      else:
        geoms[i] = orig_geoms[i]

  # Pass 2: Absorb secondary overlay crumbs back into touching neighbours
  if sliver_thresh > 0.0:
    cleaned_pairs = absorb_terrestrial_micro_shards(list(zip(props_list, geoms)), sliver_thresh, grid_size)
    props_list = [p for p, _ in cleaned_pairs]
    geoms = [g for _, g in cleaned_pairs]

  # Pass 3: Fill any enclosed interior holes <= hole_thresh into longest-border neighbour
  if hole_thresh > 0.0 and geoms:
    u_all = _union_polygons(geoms, False)
    if u_all is not None:
      tree = STRtree(geoms)
      for poly in _extract_polygons(u_all):
        for ring in poly.interiors:
          hp = Polygon(ring)
          if hp.area > hole_thresh or hp.area <= 1e-8:
            continue
          unclaimed = _snap_and_clean(_unclaimed_hole_geom(hp, poly, geoms, tree), grid_size)
          for part in _extract_polygons(unclaimed, 1e-8):
            if part.area > hole_thresh:
              continue
            nb_idx = _assign_part_to_neighbour(part, geoms, tree)
            if nb_idx >= 0:
              geoms[nb_idx] = _snap_and_clean(_union_polygons([geoms[nb_idx], part], False), grid_size)

  for props, geom in zip(props_list, geoms):
    if geom is not None and not geom.is_empty:
      out.append((props, geom))

  # Return statement
  return out


def enforce_adm1_contiguity (arg1_features, arg2_adm1_key="parent_adm1", arg3_min_shard_area=0.008, arg4_grid_size=1e-5, arg5_skip_categories=None):
  """Absorb tiny inland disconnected county/province slivers wholly surrounded by another province.

  @param arg1_features List of (properties_dict, shapely_geom) tuples at adm_3 or adm_2 grain.
  @param arg2_adm1_key Property field name containing the province/adm_1 identifier.
  @param arg3_min_shard_area Maximum area in deg2 for a detached secondary sliver to reassign.
  @param arg4_grid_size Precision grid spacing in degrees.
  @param arg5_skip_categories Optional iterable of category values excluded as donors or recipients.
  @return Tuple of (updated_features, reassigned_count).
  """
  # Convert from parameters
  adm1_key = str(arg2_adm1_key or "parent_adm1")
  grid_size = float(arg4_grid_size)
  min_shard_area = float(arg3_min_shard_area)
  skip_cats = set(arg5_skip_categories or ())
  features = [(dict(p), _pointwise_snap(gis_helpers.clean_polygonal_geometry(g), grid_size)) for p, g in arg1_features if g is not None and not g.is_empty]

  # Declare local instance variables.
  adm1_labels = []
  allowed = set()
  cand = 0
  changed = False
  geoms = []
  i = 0
  k = ""
  kept_parts = []
  merged_nb = None
  nb_adm1s = set()
  nb_idx = -1
  out = []
  p_idx = 0
  part = None
  parts = []
  props_list = []
  reassigned_count = 0
  same_prov_touch = False
  tree = None

  for props, geom in features:
    if geom is None or geom.is_empty:
      continue
    k = str(props.get(adm1_key) or props.get("name_en") or "")
    geoms.append(geom)
    props_list.append(props)
    adm1_labels.append(k)

  if not geoms:
    return out, 0

  tree = STRtree(geoms)
  for i in range(len(geoms)):
    if skip_cats and str(props_list[i].get("category") or "") in skip_cats:
      continue
    k = adm1_labels[i]
    parts = _extract_polygons(geoms[i])
    if len(parts) <= 1:
      continue
    parts.sort(key=lambda x: x.area, reverse=True)
    kept_parts = [parts[0]]
    changed = False
    for p_idx, part in enumerate(parts[1:], 1):
      if part.area > min_shard_area:
        kept_parts.append(part)
        continue
      nb_adm1s = set()
      same_prov_touch = False
      allowed = set()
      for cand in tree.query(part.buffer(grid_size*4.0)):
        cand = int(cand)
        if cand == i:
          continue
        if skip_cats and str(props_list[cand].get("category") or "") in skip_cats:
          continue
        if part.boundary.intersection(geoms[cand].boundary).length > grid_size:
          allowed.add(cand)
          if adm1_labels[cand] == k:
            same_prov_touch = True
          else:
            nb_adm1s.add(adm1_labels[cand])
      if (not same_prov_touch) and len(nb_adm1s) >= 1 and allowed:
        nb_idx = _assign_part_to_neighbour(part, geoms, tree, i, allowed)
        if nb_idx >= 0:
          merged_nb = _pointwise_snap(_union_polygons([geoms[nb_idx], part], True), grid_size)
          if merged_nb is None or merged_nb.is_empty or not merged_nb.is_valid:
            merged_nb = _snap_and_clean(_union_polygons([geoms[nb_idx], part], False), grid_size)
          geoms[nb_idx] = merged_nb
          changed = True
          reassigned_count += 1
          continue
      kept_parts.append(part)
    if changed:
      geoms[i] = _pointwise_snap(kept_parts[0] if len(kept_parts) == 1 else MultiPolygon(kept_parts), grid_size)

  for props, geom in zip(props_list, geoms):
    if geom is not None and not geom.is_empty:
      out.append((props, geom))

  # Return statement
  return out, reassigned_count


def harmonise_international_seams (arg1_primary_features, arg2_secondary_features, arg3_grid_size=1e-5, arg4_seam_eps=0.008):
  """Make secondary country coverages flush and non-overlapping against primary CTAmap borders.

  @param arg1_primary_features Authoritative (properties, geom) list whose outer border stays invariant.
  @param arg2_secondary_features Neighbouring country (properties, geom) list clipped and snapped flush.
  @param arg3_grid_size Precision grid spacing in degrees.
  @param arg4_seam_eps Minimum border crack half-width in degrees for morphological bridging.
  @return Tuple of (cleaned_secondary_features, seam_gaps_filled).
  """
  # Convert from parameters
  grid_size = float(arg3_grid_size)
  prim_features = list(arg1_primary_features)
  seam_eps = float(arg4_seam_eps)
  sec_features = [(dict(p), _snap_and_clean(g, grid_size)) for p, g in arg2_secondary_features if g is not None and not g.is_empty]

  # Declare local instance variables.
  bridge_eps = max(seam_eps, 0.035)
  bridge_gaps = None
  clipped = None
  closed_band = None
  frontier_band = None
  gap_candidates = []
  gap_union = None
  gaps_filled = 0
  hb = None
  hp = None
  idx = 0
  local_crop = None
  local_pair = None
  modified_idxs = set()
  nb_idx = -1
  out = []
  part = None
  poly = None
  prim_border_union = None
  prim_geoms = [_snap_and_clean(g, grid_size) for _, g in prim_features if g is not None and not g.is_empty]
  prim_near = []
  prim_near_idxs = set()
  prim_tree = None
  ring = None
  sec_geoms = []
  sec_near = []
  sec_props = []
  sec_tree = None
  sec_union_near = None
  tree = None
  unclaimed = None

  if not prim_geoms or not sec_features:
    return sec_features, 0

  # Step 1: Collect only primary features adjacent to secondary country features
  prim_tree = STRtree(prim_geoms)
  for _, geom in sec_features:
    for idx in prim_tree.query(geom.envelope.buffer(0.25)):
      prim_near_idxs.add(int(idx))
  prim_near = [prim_geoms[idx] for idx in sorted(prim_near_idxs)]
  if not prim_near:
    return clean_planar_coverage(sec_features, grid_size, 0.05, 1e-4), 0

  prim_border_union = _union_polygons(prim_near, False)
  if prim_border_union is None or prim_border_union.is_empty:
    return clean_planar_coverage(sec_features, grid_size, 0.05, 1e-4), 0

  # Step 2: Subtract overlaps against primary border using prepared predicate
  prepare(prim_border_union)
  for props, geom in sec_features:
    if prim_border_union.intersects(geom):
      clipped = _snap_and_clean(geom.difference(prim_border_union), grid_size)
    else:
      clipped = geom
    if clipped is not None and not clipped.is_empty:
      sec_geoms.append(clipped)
      sec_props.append(props)

  if not sec_geoms:
    return out, 0

  # Step 3: Close both enclosed frontier pockets and open border cracks locally onto secondary units
  sec_tree = STRtree(sec_geoms)
  sec_near = [sec_geoms[int(idx)] for idx in sorted(set(sec_tree.query(prim_border_union.buffer(0.6, quad_segs=1))))]
  sec_union_near = _union_polygons(sec_near, False)
  if sec_union_near is not None and not sec_union_near.is_empty:
    local_pair = _union_polygons([prim_border_union, sec_union_near], False)
    if local_pair is not None and not local_pair.is_empty:
      for poly in _extract_polygons(local_pair):
        for ring in poly.interiors:
          hp = Polygon(ring)
          if hp.area <= 1e-8 or hp.area > 0.25:
            continue
          hb = hp.boundary
          if hb.intersects(prim_border_union) and hb.intersects(sec_union_near):
            unclaimed = _snap_and_clean(hp.difference(local_pair), grid_size)
            for part in _extract_polygons(unclaimed, 1e-8):
              if part.area <= 0.25:
                gap_candidates.append(part)

      frontier_band = prim_border_union.boundary.buffer(0.08, quad_segs=2).intersection(
        sec_union_near.boundary.buffer(0.08, quad_segs=2)
      )
      if frontier_band is not None and not frontier_band.is_empty:
        local_crop = local_pair.intersection(frontier_band.buffer(0.08, quad_segs=2))
        closed_band = local_crop.buffer(bridge_eps, quad_segs=2).buffer(-bridge_eps, quad_segs=2)
        bridge_gaps = _snap_and_clean(closed_band.intersection(frontier_band).difference(local_pair), grid_size)
        for part in _extract_polygons(bridge_gaps, 1e-8):
          if part.area <= 0.15 and part.boundary.intersects(sec_union_near):
            gap_candidates.append(part)

      if gap_candidates:
        gap_union = _snap_and_clean(_union_polygons(gap_candidates, False), grid_size)
        if gap_union is not None and not gap_union.is_empty:
          gap_union = _snap_and_clean(gap_union.difference(local_pair), grid_size)
          tree = STRtree(sec_geoms)
          for part in _extract_polygons(gap_union, 1e-8):
            if part.area > 0.25:
              continue
            nb_idx = _assign_part_to_neighbour(part, sec_geoms, tree)
            if nb_idx >= 0:
              sec_geoms[nb_idx] = _snap_and_clean(_union_polygons([sec_geoms[nb_idx], part], False), grid_size)
              modified_idxs.add(nb_idx)
              gaps_filled += 1

  for idx in modified_idxs:
    if prim_border_union.intersects(sec_geoms[idx]):
      clipped = _snap_and_clean(sec_geoms[idx].difference(prim_border_union), grid_size)
      if clipped is not None and not clipped.is_empty:
        sec_geoms[idx] = clipped

  out = clean_planar_coverage(list(zip(sec_props, sec_geoms)), grid_size, 0.05, 1e-4)

  # Return statement
  return out, gaps_filled


def node_planar_coverage (arg1_features, arg2_grid_size=1e-5, arg3_hole_thresh=0.05, arg4_priority_fn=None):
  """Node all ring boundaries via C-GEOS DCEL polygonization for zero overlaps and zero seam pinholes.

  @param arg1_features List of (properties_dict, shapely_geom) tuples.
  @param arg2_grid_size Precision grid spacing in degrees for global noding (e.g. 1e-5).
  @param arg3_hole_thresh Maximum uncovered enclosed face area in deg2 filled into adjacent owner.
  @param arg4_priority_fn Optional Callable(props, geom) returning comparable tuple (higher wins overlaps).
  @return Exact DCEL planar list of (properties_dict, shapely_geom) tuples.
  """
  # Convert from parameters
  features = list(arg1_features)
  grid_size = float(arg2_grid_size)
  hole_thresh = float(arg3_hole_thresh)
  priority_fn = arg4_priority_fn

  # Declare local instance variables.
  best_len, best_owner, by_owner, cands, changed = 0.0, -1, {}, [], False
  face_owner, face_tree, faces, in_geoms, in_props, in_tree = [], None, [], [], [], None
  lines, member_faces, merged, next_unassigned, noded, out, prios, unassigned = [], [], None, [], None, [], [], []

  for props, geom in features:
    g_clean = gis_helpers.clean_polygonal_geometry(geom)
    if g_clean is None or g_clean.is_empty:
      continue
    idx = len(in_geoms)
    in_geoms.append(g_clean)
    in_props.append(dict(props))
    prios.append(priority_fn(props, g_clean) if priority_fn is not None else (0, float(g_clean.area), -idx))
    for poly in _extract_polygons(g_clean):
      lines.append(LineString(poly.exterior.coords))
      for ring in poly.interiors:
        lines.append(LineString(ring.coords))

  if not in_geoms or not lines:
    return [(p, _pointwise_snap(g, grid_size)) for p, g in zip(in_props, in_geoms)]

  noded = union_all(lines, grid_size=grid_size) if grid_size > 0.0 else union_all(lines)
  faces = [fc for fc in polygonize([noded]).geoms if fc is not None and not fc.is_empty and fc.area > 0.0]
  if not faces:
    return [(p, _pointwise_snap(g, grid_size)) for p, g in zip(in_props, in_geoms)]

  in_tree = STRtree(in_geoms)
  for f_idx, fc in enumerate(faces):
    pt = fc.representative_point()
    cands = [int(c_idx) for c_idx in in_tree.query(pt) if in_geoms[int(c_idx)].contains(pt)]
    if not cands:
      cands = [int(c_idx) for c_idx in in_tree.query(pt) if in_geoms[int(c_idx)].intersects(pt)]
    if cands:
      best_owner = max(cands, key=lambda idx_val: prios[idx_val])
      face_owner.append(best_owner)
    else:
      face_owner.append(-1)
      unassigned.append(f_idx)

  if unassigned and hole_thresh > 0.0:
    face_tree = STRtree(faces)
    for _ in range(8):
      changed = False
      next_unassigned = []
      for u_idx in unassigned:
        u_face = faces[u_idx]
        if u_face.area > hole_thresh:
          continue
        best_owner = -1
        best_len = 0.0
        for nb_idx in face_tree.query(u_face):
          nb_idx = int(nb_idx)
          nb_owner = face_owner[nb_idx]
          if nb_owner < 0:
            continue
          shared_len = float(u_face.boundary.intersection(faces[nb_idx].boundary).length)
          if shared_len > best_len:
            best_len = shared_len
            best_owner = nb_owner
        if best_owner >= 0:
          face_owner[u_idx] = best_owner
          changed = True
        else:
          next_unassigned.append(u_idx)
      unassigned = next_unassigned
      if (not unassigned) or (not changed):
        break

  for f_idx, owner in enumerate(face_owner):
    if owner >= 0:
      by_owner.setdefault(owner, []).append(faces[f_idx])

  for idx in range(len(in_geoms)):
    member_faces = by_owner.get(idx)
    if not member_faces:
      continue
    if len(member_faces) == 1:
      merged = member_faces[0]
    else:
      try:
        merged = coverage_union_all(member_faces)
      except Exception:
        merged = None
      if merged is None or merged.is_empty:
        merged = _union_polygons(member_faces, False)
    merged = _pointwise_snap(gis_helpers.clean_polygonal_geometry(merged), grid_size)
    if merged is not None and not merged.is_empty:
      out.append((in_props[idx], merged))

  # Return statement
  return out


def simplify_and_clean_coverage (arg1_features, arg2_simplify_tol=0.002, arg3_grid_size=1e-5, arg4_hole_thresh=0.05, arg5_sliver_thresh=1e-4):
  """Topology-preserving coverage simplification followed by planar gap, hole and sliver cleaning.

  @param arg1_features List of (properties_dict, shapely_geom) tuples.
  @param arg2_simplify_tol Douglas-Peucker / Visvalingam coverage simplification tolerance in degrees.
  @param arg3_grid_size Precision grid size in degrees.
  @param arg4_hole_thresh Maximum enclosed hole area in sq deg to close onto adjacent features.
  @param arg5_sliver_thresh Maximum disconnected inland sliver area in sq deg to absorb.
  @return Cleaned list of (properties_dict, shapely_geom) tuples.
  """
  # Convert from parameters
  features = list(arg1_features)
  grid_size = float(arg3_grid_size)
  hole_thresh = float(arg4_hole_thresh)
  simplify_tol = float(arg2_simplify_tol)
  sliver_thresh = float(arg5_sliver_thresh)

  # Declare local instance variables.
  clean_in = []
  g_clean = None
  g_orig = None
  g_simp = None
  idx = 0
  props = None
  simp_geoms = []
  simp_pairs = []

  for props, g_orig in features:
    g_clean = gis_helpers.clean_polygonal_geometry(g_orig)
    if g_clean is not None and not g_clean.is_empty:
      clean_in.append((props, g_clean))

  if not clean_in:
    return []

  if simplify_tol > 0.0:
    try:
      simp_geoms = list(coverage_simplify([g for _, g in clean_in], simplify_tol))
    except Exception:
      simp_geoms = []
  if len(simp_geoms) == len(clean_in):
    for idx, (props, g_orig) in enumerate(clean_in):
      g_simp = gis_helpers.clean_polygonal_geometry(simp_geoms[idx])
      if g_simp is None or g_simp.is_empty:
        g_simp = g_orig
      simp_pairs.append((props, g_simp))
  else:
    simp_pairs = clean_in

  # Return statement
  return clean_planar_coverage(simp_pairs, grid_size, hole_thresh, sliver_thresh)
