"""Modern GIS layer prefecture harmonisation and unclaimed interior hole patching helpers."""

from shapely import STRtree
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from helpers import gis_helpers


def _merge_hole_additions (arg1_geoms, arg2_additions):
  """Union accumulated hole polygons into their assigned owner geometries.

  @param arg1_geoms List of Shapely geometries aligned with arg2_additions keys.
  @param arg2_additions Dict mapping unit index to list of interior hole Polygons.
  @return Updated list of Shapely geometries.
  """
  # Convert from parameters
  additions = arg2_additions
  geoms = list(arg1_geoms)

  # Declare local instance variables.
  merged = None

  for idx, holes in additions.items():
    if not holes:
      continue
    merged = gis_helpers.clean_polygonal_geometry(unary_union([geoms[idx]] + holes))
    if merged is not None and not merged.is_empty:
      geoms[idx] = merged

  # Return statement
  return geoms


def _pick_best_neighbour (arg1_hole_poly, arg2_geoms, arg3_tree, arg4_allowed_set=None):
  """Select the unit geometry sharing the longest boundary with an unclaimed interior hole.

  @param arg1_hole_poly Shapely Polygon of the unclaimed interior hole.
  @param arg2_geoms List of candidate unit geometries.
  @param arg3_tree STRtree built over arg2_geoms.
  @param arg4_allowed_set Optional set of allowed indices in arg2_geoms.
  @return Best matching index in arg2_geoms, or None if no valid candidate exists.
  """
  # Convert from parameters
  allowed = arg4_allowed_set
  geoms = arg2_geoms
  hole_poly = arg1_hole_poly
  tree = arg3_tree

  # Declare local instance variables.
  best_dist = 1e12
  best_idx = None
  best_shared = -1.0
  cand_ids = []
  hole_b = hole_poly.boundary

  cand_ids = [int(i) for i in tree.query(hole_poly.buffer(1e-4))]
  if allowed is not None:
    cand_ids = [i for i in cand_ids if i in allowed]
  if not cand_ids and allowed:
    cand_ids = list(allowed)

  for i in cand_ids:
    g = geoms[i]
    shared = g.boundary.intersection(hole_b).length
    dist = g.distance(hole_poly)
    if (shared > best_shared + 1e-9) or (abs(shared - best_shared) <= 1e-9 and dist < best_dist):
      best_shared = shared
      best_dist = dist
      best_idx = i

  if best_idx is None:
    best_idx = int(tree.nearest(hole_poly))

  # Return statement
  return best_idx


def _strip_poly_unclaimed_holes (arg1_idx, arg2_geom, arg3_geoms, arg4_tree, arg5_max_hole_area):
  """Strip unclaimed small interior rings directly inside a single unit geometry.

  @param arg1_idx Index of arg2_geom inside arg3_geoms.
  @param arg2_geom Input Shapely Polygon or MultiPolygon.
  @param arg3_geoms List of all layer geometries.
  @param arg4_tree STRtree over arg3_geoms.
  @param arg5_max_hole_area Maximum hole area in deg2 eligible for stripping.
  @return Cleaned Shapely geometry with unclaimed small holes removed.
  """
  # Convert from parameters
  geom = arg2_geom
  geoms = arg3_geoms
  idx = int(arg1_idx)
  max_area = float(arg5_max_hole_area)
  tree = arg4_tree

  # Declare local instance variables.
  changed = False
  cov = 0.0
  hp = None
  kept_rings = []
  new_polys = []
  polys = []

  if geom is None or geom.is_empty:
    return geom

  polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
  for poly in polys:
    if len(poly.interiors) == 0:
      new_polys.append(poly)
      continue
    kept_rings = []
    for ring in poly.interiors:
      hp = Polygon(ring)
      if hp.area > max_area:
        kept_rings.append(ring)
        continue
      cov = 0.0
      for cand_i in tree.query(hp):
        ci = int(cand_i)
        if ci != idx and geoms[ci].intersects(hp):
          cov += geoms[ci].intersection(hp).area
          if cov >= 0.5*hp.area:
            break
      if cov >= 0.5*hp.area:
        kept_rings.append(ring)
      else:
        changed = True
    new_polys.append(Polygon(poly.exterior, kept_rings))

  if not changed:
    return geom

  # Return statement
  return gis_helpers.clean_polygonal_geometry(new_polys[0] if len(new_polys) == 1 else MultiPolygon(new_polys))


def harmonise_prc_units (arg1_units, arg2_gb_lookup):
  """Unify split PRC municipalities and prefecture-level GB/T 2260 assignments across GADM adm_2 groups.

  @param arg1_units List of PRC adm_3 unit dictionaries.
  @param arg2_gb_lookup Lookup dict built by ModernLayerAssembler._load_gb2260_lookup.
  @return Updated arg1_units with consistent parent_adm2_gb and parent_adm2_zh values.
  """
  # Convert from parameters
  gb_lookup = arg2_gb_lookup
  units = list(arg1_units or [])

  # Declare local instance variables.
  areas = gb_lookup.get("areas", {})
  by_stem = gb_lookup.get("by_prov_stem", {})
  cities = gb_lookup.get("cities", {})
  muni_map = {
    "Beijing": ("110100", "北京市"),
    "Chongqing": ("500100", "重庆市"),
    "Hong Kong": ("810000", "香港特别行政区"),
    "Macau": ("820000", "澳门特别行政区"),
    "Shanghai": ("310100", "上海市"),
    "Tianjin": ("120100", "天津市"),
  }
  pref_groups = {}

  for u in units:
    p1 = u["parent_adm1"]
    if p1 in muni_map:
      m_gb, m_zh = muni_map[p1]
      u["parent_adm2"] = p1
      u["parent_adm2_gb"] = m_gb
      u["parent_adm2_zh"] = m_zh
      if p1 == "Chongqing" and u["gb_code"].startswith("51"):
        for r in by_stem.get(("50", u["name_zh"]), []):
          u["gb_code"] = r["code"]
          u["name_zh"] = r["name"]
          break
      continue
    if p1 == "Hainan" and u["parent_adm2"] == "Hainan" and u["gb_code"] == "460400":
      u["parent_adm2"] = "Danzhou"
      u["parent_adm2_gb"] = "460400"
      u["parent_adm2_zh"] = "儋州市"
      continue
    if p1 == "Hainan" and u["parent_adm2"] == "Hainan":
      u["parent_adm2_gb"] = "469000"
      u["parent_adm2_zh"] = "海南省直辖"
      continue
    pref_groups.setdefault((p1, u["parent_adm2"]), []).append(u)

  for (_, _), grp in pref_groups.items():
    distinct = {(u["parent_adm2_gb"], u["parent_adm2_zh"]) for u in grp}
    if len(distinct) <= 1:
      continue
    scores = {}
    for u in grp:
      p2_key = (u["parent_adm2_gb"], u["parent_adm2_zh"])
      if p2_key not in scores:
        c4 = u["parent_adm2_gb"][:4]
        crow = cities.get(c4, {})
        c_zh = str(crow.get("name") or "")
        is_modern_city = int(bool(crow) and c_zh not in ("市辖区", "省直辖县级行政区划", "自治区直辖县级行政区划"))
        scores[p2_key] = [is_modern_city, 0, 0.0, u["parent_adm2_zh"].endswith(("市", "州", "盟"))]
      scores[p2_key][1] += 1
      scores[p2_key][2] += float(u["geom"].area)
    best_gb, best_zh = max(scores.keys(), key=lambda k: tuple(scores[k]))
    if not best_zh.endswith(("市", "州", "盟", "地区")) and best_gb[:4] in cities:
      best_zh = str(cities[best_gb[:4]].get("name") or best_zh)
    best_c4 = best_gb[:4]
    prov2 = grp[0]["parent_adm1_gb"][:2]
    for u in grp:
      u["parent_adm2_gb"] = best_gb
      u["parent_adm2_zh"] = best_zh
      if u["gb_code"][:4] != best_c4:
        cands = by_stem.get((prov2, u["name_zh"]), [])
        matched = next((r for r in cands if r.get("cityCode") == best_c4), None)
        if matched is not None and matched.get("code") in areas:
          u["gb_code"] = matched["code"]
          u["name_zh"] = matched["name"]

  # Return statement
  return units


def patch_unclaimed_holes_in_units (arg1_units, arg2_max_hole_area=0.05):
  """Patch all unclaimed interior county-boundary gaps/slivers into adjacent adm_3 units.

  @param arg1_units List of PRC adm_3 unit dicts with 'geom' and 'parent_adm1'.
  @param arg2_max_hole_area Maximum interior hole area in deg2 to fill.
  @return Updated arg1_units with watertight gap-free polygons.
  """
  # Convert from parameters
  max_area = float(arg2_max_hole_area)
  units = list(arg1_units or [])

  if not units:
    return units

  # Declare local instance variables.
  additions = {}
  by_prov = {}
  geoms = [u["geom"] for u in units]
  nat_adds = {}
  nat_u = None
  prov_unions = []
  tree = STRtree(geoms)

  for i in range(len(geoms)):
    geoms[i] = _strip_poly_unclaimed_holes(i, geoms[i], geoms, tree, max_area)
    by_prov.setdefault(units[i]["parent_adm1"], []).append(i)

  tree = STRtree(geoms)
  for _, idxs in by_prov.items():
    idx_set = set(idxs)
    pu = gis_helpers.clean_polygonal_geometry(unary_union([geoms[i] for i in idxs]))
    if pu is None:
      continue
    pu_polys = [pu] if pu.geom_type == "Polygon" else list(pu.geoms)
    for poly in pu_polys:
      for ring in poly.interiors:
        hp = Polygon(ring)
        if hp.area <= 0.0 or hp.area > max_area:
          continue
        ext_cov = sum(geoms[int(j)].intersection(hp).area for j in tree.query(hp) if int(j) not in idx_set and geoms[int(j)].intersects(hp))
        if ext_cov >= 0.5*hp.area:
          continue
        best_i = _pick_best_neighbour(hp, geoms, tree, idx_set)
        if best_i is not None:
          additions.setdefault(best_i, []).append(hp)

  geoms = _merge_hole_additions(geoms, additions)
  for _, idxs in by_prov.items():
    pu = gis_helpers.clean_polygonal_geometry(unary_union([geoms[i] for i in idxs]))
    if pu is not None:
      prov_unions.append(pu)

  nat_u = gis_helpers.clean_polygonal_geometry(unary_union(prov_unions)) if prov_unions else None
  if nat_u is not None:
    tree = STRtree(geoms)
    nat_polys = [nat_u] if nat_u.geom_type == "Polygon" else list(nat_u.geoms)
    for poly in nat_polys:
      for ring in poly.interiors:
        hp = Polygon(ring)
        if hp.area <= 0.0 or hp.area > max_area:
          continue
        best_i = _pick_best_neighbour(hp, geoms, tree, None)
        if best_i is not None:
          nat_adds.setdefault(best_i, []).append(hp)
    geoms = _merge_hole_additions(geoms, nat_adds)

  for i in range(len(units)):
    units[i]["geom"] = geoms[i]

  # Return statement
  return units


def strip_unclaimed_holes_in_features (arg1_feats, arg2_max_hole_area=0.05):
  """Strip unclaimed small interior rings from exported (props, geom) GeoJSON feature tuples.

  @param arg1_feats List of (properties_dict, Shapely_geometry) tuples.
  @param arg2_max_hole_area Maximum interior hole area in deg2 to strip if unclaimed.
  @return Cleaned list of (properties_dict, Shapely_geometry) tuples.
  """
  # Convert from parameters
  feats = list(arg1_feats or [])
  max_area = float(arg2_max_hole_area)

  if not feats:
    return feats

  # Declare local instance variables.
  geoms = [g for _, g in feats]
  out_feats = []
  tree = STRtree(geoms)

  for i, (props, g) in enumerate(feats):
    cleaned = _strip_poly_unclaimed_holes(i, g, geoms, tree, max_area)
    if cleaned is not None and not cleaned.is_empty:
      out_feats.append((props, cleaned))

  # Return statement
  return out_feats
