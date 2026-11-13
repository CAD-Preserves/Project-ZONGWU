"""Topographic and subadministrative Borderpool Graph engine for 425 Tusi polities."""

from collections import deque
import heapq
import io
import json
import math
import os
import pickle
import sys
import zipfile
import numpy as np
import shapefile
import shapely
from shapely import STRtree, make_valid, set_precision
from shapely.geometry import LineString, MultiLineString, Polygon, Point, box, shape
from shapely.ops import linemerge, polygonize, unary_union
from skimage.segmentation import watershed

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)
from helpers import gis_helpers, path_helpers, tusi_topo_helpers


class BorderpoolGraphEngine:
  """Builds watertight physical/subadministrative borderpool atoms and assigns Tusi territories via graph-cut."""

  def __init__ (self, arg1_base_dir, arg2_config, arg3_elev_builder, arg4_adm3_map, arg5_waterways, arg6_roads, arg7_towns, arg8_adm3_features=None):
    """Initialise spatial indices for CHGIS, CITAS 1990, GADM-3, HydroBASINS, HydroRIVERS, contours, and settlements.
    @param arg1_base_dir Root dir; arg2_config modelling cfg; arg3_elev_builder DEM builder; arg4_adm3_map CHGIS dict; arg5_waterways waterways; arg6_roads roads; arg7_towns towns; arg8_adm3_features CHGIS props.
    """
    # Convert from parameters
    adm3_features = arg8_adm3_features or []
    adm3_map = arg4_adm3_map
    base_dir = os.path.abspath(arg1_base_dir)
    config = arg2_config
    elev_builder = arg3_elev_builder
    roads = arg6_roads
    towns = arg7_towns
    waterways = arg5_waterways

    # Declare local instance variables.
    self.adm3_geoms = [g for g in adm3_map.values() if g is not None and not g.is_empty]
    self.adm3_map = adm3_map
    self.adm3_names = {}
    self.adm3_tree = STRtree(self.adm3_geoms) if self.adm3_geoms else None
    self.base_dir = base_dir
    self.citas_counties = []
    self.citas_tree = None
    self.config = config
    self.contour_lines = []
    self.contour_tree = None
    self.elev_builder = elev_builder
    self.gadm3_counties = []
    self.gadm3_tree = None
    self.gis_dir = path_helpers.resolve_path("output.gis.layers_dir", base_dir)
    self.hybas = {}
    self.hybas_trees = {}
    self.hydrorivers = []
    self.hydrorivers_tree = None
    self.roads = roads
    self.road_lines = [rg for _, rg in roads if rg is not None and not rg.is_empty]
    self.road_tree = STRtree(self.road_lines) if self.road_lines else None
    self.sources_dir = path_helpers.resolve_path("input.gis.priors_dir", base_dir)
    self.town_pts = towns[0] if towns else np.zeros((0, 2), dtype=np.float64)
    self.town_recs = towns[1] if towns else []
    self.waterways = waterways
    self.weights = config.get("borderpool_weights", {})

    for feat in adm3_features:
      p = feat.get("properties", {})
      uid = p.get("unit_id")
      if uid:
        self.adm3_names[uid] = (str(p.get("name_py") or p.get("name_en") or ""), str(p.get("name_ch") or ""))

    self._load_borderpool_layers()

  def _assign_atoms_topographic (self, arg1_atoms, arg2_adj, arg3_seeds, arg4_seat_atoms, arg5_k_pol, arg6_reach_scales=None):
    """Run multi-source Dijkstra, settlement-corridor backbone, and seat-connected contiguity over atoms.
    @param arg1_atoms Polygon atoms; arg2_adj graph edges; arg3_seeds seeds dict; arg4_seat_atoms seat idxs; arg5_k_pol polity count; arg6_reach_scales optional per-class step multipliers.
    @return Integer list of class labels per atom.
    """
    # Convert from parameters
    adj = arg2_adj
    atoms = arg1_atoms
    k_pol = int(arg5_k_pol)
    reach_scales = list(arg6_reach_scales) if arg6_reach_scales else []
    seat_atoms = list(arg4_seat_atoms)
    seeds = arg3_seeds

    # Declare local instance variables.
    dist = [1e18]*len(atoms)
    labels = [-1]*len(atoms)
    locked = {seat_atoms[k]: k for k in range(k_pol) if seat_atoms[k] >= 0}
    n = len(atoms)
    pq = []

    bb_claims = {}
    for k in range(k_pol):
      sa = seat_atoms[k]
      sec_targets = {a for a, c in seeds.get(k, []) if a != sa and c <= 0.05}
      if sa < 0 or not sec_targets:
        continue
      dist_b, prev_b, pq_b, rem_t = {sa: 0.0}, {}, [(0.0, sa)], set(sec_targets)
      for _ in range(n*8):
        if not pq_b or not rem_t:
          break
        db, u = heapq.heappop(pq_b)
        if db > dist_b.get(u, 1e9) + 1e-12 or db > 1.8:
          continue
        rem_t.discard(u)
        for v, w in adj[u]:
          if v in locked and locked[v] != k:
            continue
          nd = db + w
          if nd < dist_b.get(v, 1e9):
            dist_b[v], prev_b[v] = nd, u
            heapq.heappush(pq_b, (nd, v))
      for tg in sec_targets:
        cur = tg
        for _ in range(n):
          if cur == sa or cur not in prev_b:
            break
          bb_claims.setdefault(cur, set()).add(k)
          cur = prev_b[cur]

    for a_bb, kset in bb_claims.items():
      if len(kset) == 1 and a_bb not in locked:
        seeds.setdefault(next(iter(kset)), []).append((a_bb, 0.015))

    for cls_id, seed_list in seeds.items():
      for ai, c0 in seed_list:
        if ai in locked and locked[ai] != cls_id:
          continue
        if c0 < dist[ai]:
          dist[ai] = c0
          labels[ai] = cls_id
          heapq.heappush(pq, (c0, cls_id, ai))

    max_pops = max(1000, n*24)
    for _ in range(max_pops):
      if not pq:
        break
      d, cls_id, u = heapq.heappop(pq)
      if d > dist[u] + 1e-12:
        continue
      scale_cls = reach_scales[cls_id] if cls_id < len(reach_scales) else 1.0
      for v, w in adj[u]:
        if v in locked and locked[v] != cls_id:
          continue
        nd = d + w*scale_cls
        if nd < dist[v]:
          dist[v] = nd
          labels[v] = cls_id
          heapq.heappush(pq, (nd, cls_id, v))

    # Fallback for any completely disconnected island atom
    rps = [a.representative_point() for a in atoms]
    for u in range(n):
      if labels[u] >= 0:
        continue
      best_c = k_pol if k_pol in seeds else 0
      best_d = 1e9
      for v in range(n):
        if labels[v] >= 0:
          dv = math.hypot(rps[u].x - rps[v].x, rps[u].y - rps[v].y)
          if dv < best_d:
            best_d = dv
            best_c = labels[v]
      labels[u] = best_c

    # Enforce strict seat-rooted contiguity per polity k in 0..k_pol-1
    for _ in range(4):
      keep_mask = [False]*n
      for k in range(k_pol):
        sa = seat_atoms[k]
        if sa < 0:
          continue
        labels[sa] = k
        keep_mask[sa] = True
        q = deque([sa])
        for _ in range(n + 5):
          if not q:
            break
          cur = q.popleft()
          for nb, _ in adj[cur]:
            if labels[nb] == k and not keep_mask[nb]:
              keep_mask[nb] = True
              q.append(nb)

      stray_set = {u for u in range(n) if labels[u] < k_pol and not keep_mask[u]}
      if not stray_set:
        break
      spq = [(w, labels[u], v) for u in range(n) if u not in stray_set for v, w in adj[u] if v in stray_set]
      heapq.heapify(spq)
      reassigned = False
      for _ in range(len(stray_set)*12 + 20):
        if not spq or not stray_set:
          break
        cw, cls_nb, u = heapq.heappop(spq)
        if u not in stray_set:
          continue
        labels[u] = cls_nb
        stray_set.remove(u)
        reassigned = True
        for v, w in adj[u]:
          if v in stray_set:
            heapq.heappush(spq, (cw + w, cls_nb, v))
      if not reassigned:
        break

    # Return statement
    return labels

  def _build_atom_graph (self, arg1_atoms, arg2_barrier_names, arg3_seat_subs=None, arg4_disable_subadmin=False):
    """Construct weighted planar adjacency graph over borderpool atoms (relief, river, county, road).
    @param arg1_atoms Polygon atoms; arg2_barrier_names river names; arg3_seat_subs (seat_gbs, seat_gids); arg4_disable_subadmin skip modern PRC subadmin costs.
    @return List of adjacency dicts: adj[u] = [(v, edge_cost), ...].
    """
    # Convert from parameters
    atoms = arg1_atoms
    barrier_names = [b.lower() for b in (arg2_barrier_names or [])]
    disable_subadmin = bool(arg4_disable_subadmin)
    seat_gbs, seat_gids = arg3_seat_subs if arg3_seat_subs else (set(), set())

    # Declare local instance variables.
    adj = [[] for _ in range(len(atoms))]
    elev_w = float(self.weights.get("elev_diff_weight", 0.80))
    n = len(atoms)
    ridge_w = float(self.weights.get("ridge_relief_weight", 2.20))
    riv_w = float(self.weights.get("river_barrier_cost", 0.42))
    road_f = float(self.weights.get("road_corridor_factor", 0.76))
    sub_seat_w = float(self.weights.get("subadmin_seat_boundary_cost", 1.30))
    sub_w = float(self.weights.get("subadmin_boundary_cost", 0.36))

    if n <= 1:
      return adj

    rps = [a.representative_point() for a in atoms]
    rp_lons = [p.x for p in rps]
    rp_lats = [p.y for p in rps]
    atom_elevs = self.elev_builder.sample_elevation(rp_lons, rp_lats)
    subadmins = [("", "")]*len(atoms) if disable_subadmin else [self._lookup_atom_subadmin(p) for p in rps]

    dom_box = unary_union(atoms).bounds
    clip_box = box(dom_box[0] - 0.1, dom_box[1] - 0.1, dom_box[2] + 0.1, dom_box[3] + 0.1)
    major_rivs = []
    for wp, wg in self.waterways:
      nm = (str(wp.get("name_en") or "") + " " + str(wp.get("name_ch") or "")).lower()
      if wg.intersects(clip_box) and (any(bn in nm for bn in barrier_names) or "NaturalEarth" in str(wp.get("source") or "")):
        major_rivs.append(wg.intersection(clip_box))
    if self.hydrorivers_tree is not None:
      for r_idx in self.hydrorivers_tree.query(clip_box):
        ord_s, rg = self.hydrorivers[int(r_idx)]
        if ord_s >= 5 and rg.intersects(clip_box):
          major_rivs.append(rg.intersection(clip_box))
    prep_riv = shapely.prepared.prep(unary_union(major_rivs).buffer(0.0025)) if major_rivs else None

    local_roads = [self.road_lines[int(r_idx)] for r_idx in self.road_tree.query(clip_box)] if self.road_tree is not None else []
    prep_road = shapely.prepared.prep(unary_union(local_roads).buffer(0.015)) if local_roads else None

    atoms_r = [gis_helpers.round_geometry(a, 5) or a for a in atoms]
    tree = STRtree(atoms_r)
    seen_pairs = set()
    for u in range(n):
      au = atoms_r[u]
      for v_raw in tree.query(au.buffer(2e-4)):
        v = int(v_raw)
        if v <= u or (u, v) in seen_pairs:
          continue
        seen_pairs.add((u, v))
        inter = au.boundary.intersection(atoms_r[v].boundary)
        if inter.is_empty:
          continue
        lin_parts = []
        for g_part in (inter.geoms if hasattr(inter, "geoms") else [inter]):
          if g_part.geom_type in ("LineString", "LinearRing") and len(g_part.coords) >= 2:
            lin_parts.append(LineString(g_part.coords) if g_part.geom_type == "LinearRing" else g_part)
          elif g_part.geom_type == "MultiLineString":
            lin_parts.extend(ls for ls in g_part.geoms if len(ls.coords) >= 2)
        if not lin_parts or sum(float(lp.length) for lp in lin_parts) < 1.5e-4:
          continue
        lin_geom = linemerge(lin_parts) if len(lin_parts) > 1 else lin_parts[0]
        if lin_geom.is_empty or lin_geom.length <= 0.0:
          continue

        d_uv = max(0.005, math.hypot(rp_lons[u] - rp_lons[v], rp_lats[u] - rp_lats[v]))
        mid = lin_geom.interpolate(0.5, normalized=True)
        edge_pts = [lin_geom.interpolate(0.25, normalized=True), mid, lin_geom.interpolate(0.75, normalized=True)]
        edge_elev = float(np.max(self.elev_builder.sample_elevation([p.x for p in edge_pts], [p.y for p in edge_pts])))
        saddle_prom = max(0.0, edge_elev - min(float(atom_elevs[u]), float(atom_elevs[v])))
        elev_diff = abs(float(atom_elevs[u]) - float(atom_elevs[v]))

        cost = d_uv + ridge_w*(saddle_prom / 1000.0) + elev_w*(elev_diff / 1000.0)
        if not disable_subadmin:
          gb_u, gid_u = subadmins[u]
          gb_v, gid_v = subadmins[v]
          if (gb_u and gb_v and gb_u != gb_v) or (gid_u and gid_v and gid_u != gid_v):
            cost += sub_w + (sub_seat_w if (gb_u in seat_gbs or gb_v in seat_gbs or gid_u in seat_gids or gid_v in seat_gids) else 0.0)

        if prep_riv is not None and prep_riv.intersects(mid):
          cost += riv_w
        elif prep_road is not None and prep_road.intersects(mid):
          cost *= road_f

        adj[u].append((v, cost))
        adj[v].append((u, cost))

    # Return statement
    return adj

  def _chaikin_coords (self, arg1_coords, arg2_passes=2, arg3_extend_deg=0.0):
    """Apply Chaikin corner-cutting smoothing while optionally extending open endpoints slightly to cross parent bounds."""
    # Convert from parameters
    coords = list(arg1_coords)
    ext = float(arg3_extend_deg)
    passes = int(arg2_passes)

    if len(coords) < 2:
      return coords

    pts = list(coords)
    for _ in range(passes):
      if len(pts) < 3:
        break
      nxt = [pts[0]]
      for i in range(len(pts) - 1):
        p0, p1 = pts[i], pts[i + 1]
        nxt.append((0.75*p0[0] + 0.25*p1[0], 0.75*p0[1] + 0.25*p1[1]))
        nxt.append((0.25*p0[0] + 0.75*p1[0], 0.25*p0[1] + 0.75*p1[1]))
      nxt.append(pts[-1])
      pts = nxt

    if ext > 0.0 and len(pts) >= 2:
      d0 = math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1])
      if d0 > 1e-8:
        pts[0] = (pts[0][0] + ext*(pts[0][0] - pts[1][0]) / d0, pts[0][1] + ext*(pts[0][1] - pts[1][1]) / d0)
      d1 = math.hypot(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
      if d1 > 1e-8:
        pts[-1] = (pts[-1][0] + ext*(pts[-1][0] - pts[-2][0]) / d1, pts[-1][1] + ext*(pts[-1][1] - pts[-2][1]) / d1)

    # Return statement
    return pts

  def _collect_cluster_anchors (self, arg1_polities, arg2_atoms, arg3_host_domain, arg4_cluster, arg5_allow_bg, arg6_all_seats):
    """Map Tusi seats, known_settlements, namesake counties, and vetted background seeds onto atoms.
    @param arg1_polities polities; arg2_atoms atoms; arg3_host_domain host poly; arg4_cluster cfg; arg5_allow_bg bg flag; arg6_all_seats all seats.
    @return Tuple (seeds_dict, seat_atom_list, k_pol, n_anchors).
    """
    # Convert from parameters
    all_seats = arg6_all_seats
    allow_bg = bool(arg5_allow_bg)
    atoms = arg2_atoms
    cluster = arg4_cluster
    host_domain = arg3_host_domain
    polities = list(arg1_polities)

    # Declare local instance variables.
    atom_tree = STRtree(atoms)
    bg_exclude_r = float(cluster.get("bg_exclude_radius_deg") or 0.18)
    k_pol = len(polities)
    n_anchors = 0
    sec_cost = float(self.weights.get("secondary_seed_cost", 0.035))
    seat_atoms = [-1]*k_pol
    seeds = {}
    settlement_hits = {}

    def locate_atom (px, py):
      pt = Point(px, py)
      for h_idx in atom_tree.query(pt):
        if atoms[int(h_idx)].contains(pt) or atoms[int(h_idx)].distance(pt) < 1e-6:
          return int(h_idx)
      best_d, best_i = 1e9, -1
      for idx_a, atm in enumerate(atoms):
        d = atm.distance(pt)
        if d < best_d:
          best_d, best_i = d, idx_a
      return best_i if best_d < 0.03 else -1

    # 1. Mandatory seat anchors (hard-locked at init_cost=0.0)
    for k, t in enumerate(polities):
      ai = locate_atom(float(t["seat_lon"]), float(t["seat_lat"]))
      if ai >= 0:
        seat_atoms[k] = ai
        seeds.setdefault(k, []).append((ai, 0.0))
        n_anchors += 1

    seat_atom_set = {a for a in seat_atoms if a >= 0}
    pos_coords = [(float(t["seat_lon"]), float(t["seat_lat"])) for t in polities]
    disable_subadmin = bool(cluster.get("disable_modern_subadmin", False))
    seat_subs = [("", "")]*k_pol if disable_subadmin else [self._lookup_atom_subadmin(Point(px, py)) for px, py in pos_coords]
    seat_gbs = {s[0] for s in seat_subs if s[0]}
    seat_gids = {s[1] for s in seat_subs if s[1]}

    # 2. Known settlements & curated historical valley settlements (reject foreign-seated & multi-owner atoms)
    for k, t in enumerate(polities):
      sx, sy = float(t["seat_lon"]), float(t["seat_lat"])
      sgb, sgid = seat_subs[k]
      for ks in t.get("known_settlements", []):
        kx, ky = float(ks[0]), float(ks[1])
        d_own = math.hypot(kx - sx, ky - sy)
        if d_own < 1e-4:
          continue
        if not disable_subadmin:
          kgb, kgid = self._lookup_atom_subadmin(Point(kx, ky))
          if (kgb and kgb != sgb and kgb in seat_gbs) or (kgid and kgid != sgid and kgid in seat_gids):
            continue
        too_close = any(math.hypot(kx - float(ot["seat_lon"]), ky - float(ot["seat_lat"])) < min(0.16, 0.45*d_own) for ok, ot in enumerate(polities) if ok != k)
        if too_close:
          continue
        ai = locate_atom(kx, ky)
        if ai >= 0 and ai not in seat_atom_set:
          settlement_hits.setdefault(ai, set()).add(k)
          pos_coords.append((kx, ky))

    for ai, owners in settlement_hits.items():
      if len(owners) == 1:
        k_own = next(iter(owners))
        seeds.setdefault(k_own, []).append((ai, sec_cost))
        n_anchors += 1

    protected_bg_atoms = seat_atom_set | {ai for ai, owners in settlement_hits.items() if len(owners) == 1}
    gadm_nm = {c["gid"]: c["name"].lower() for c in self.gadm3_counties if c["gid"]}
    citas_nm = {c["gb"]: c["name"] for c in self.citas_counties if c["gb"]}
    skip_stems = {"shang", "zhong", "dong", "qian", "old", "new", "north", "south", "east", "west"}
    if not disable_subadmin:
      gid_matches = {}
      for k, t in enumerate(polities):
        sgb, sgid = seat_subs[k]
        stem, zh2 = t["tusi_id"].split("_")[0].lower(), str(t.get("name_zh", ""))[:2]
        if sgid and ((len(stem) >= 4 and stem not in skip_stems and gadm_nm.get(sgid, "").startswith(stem)) or (len(zh2) == 2 and citas_nm.get(sgb, "").startswith(zh2))):
          gid_matches.setdefault(sgid, []).append(k)
      nm_cost = float(self.weights.get("namesake_seed_cost", 0.28))
      for sgid, ks_match in gid_matches.items():
        if len(ks_match) != 1:
          continue
        ko = ks_match[0]
        for u, a in enumerate(atoms):
          if u in protected_bg_atoms or self._lookup_atom_subadmin(a.representative_point())[1] != sgid:
            continue
          rp = a.representative_point()
          if all(math.hypot(rp.x - float(polities[ok]["seat_lon"]), rp.y - float(polities[ok]["seat_lat"])) >= 0.16 for ok in range(k_pol) if ok != ko):
            seeds.setdefault(ko, []).append((u, nm_cost))
            protected_bg_atoms.add(u)
            n_anchors += 1

    # 3. External background class (k_pol) with strict CHGIS COUNT_PY & CITAS-county hygiene
    if allow_bg:
      citas_with_tusi_seat = set(seat_gbs)
      citas_with_explicit_bg = set()

      for bgs in cluster.get("bg_seeds", []):
        bx, by = float(bgs[0]), float(bgs[1])
        if any(math.hypot(bx - float(t["seat_lon"]), by - float(t["seat_lat"])) < 0.04 for t in polities):
          continue
        ai = locate_atom(bx, by)
        if ai >= 0 and ai not in protected_bg_atoms:
          gb, _ = self._lookup_atom_subadmin(atoms[ai].representative_point())
          if gb:
            citas_with_explicit_bg.add(gb)
          seeds.setdefault(k_pol, []).append((ai, 0.0))
          n_anchors += 1

      host_py_tokens, host_ch_tokens = set(), set()
      for uid in cluster.get("host_unit_ids", []):
        parts = uid.split("_")
        if len(parts) >= 3:
          host_py_tokens.add((parts[3] if len(parts) >= 4 and parts[1] == "fill" else parts[2]).lower())
        nm_py, nm_ch = self.adm3_names.get(uid, ("", ""))
        if nm_py:
          host_py_tokens.add(nm_py.split(" ")[0].lower())
        if len(nm_ch) >= 2:
          host_ch_tokens.add(nm_ch[:2])

      if self.town_pts.shape[0] > 0 and not bool(cluster.get("skip_town_bg", False)):
        minx, miny, maxx, maxy = host_domain.bounds
        tusi_kws = ("tusi", "tuzhou", "tufu", "tuxian", "anfusi", "xuanweisi", "xuanfusi", "zhangguansi", "土司", "土州", "土府", "土县", "长官司", "宣慰", "宣抚", "安抚")
        pos_arr = np.asarray(pos_coords, dtype=np.float64)
        for idx_t in range(self.town_pts.shape[0]):
          tx, ty = float(self.town_pts[idx_t, 0]), float(self.town_pts[idx_t, 1])
          if not (minx <= tx <= maxx and miny <= ty <= maxy):
            continue
          rec = self.town_recs[idx_t]
          meta_txt = f"{rec.get('NAME_CH', '')} {rec.get('NAME_PY', '')} {rec.get('TYPE_PY', '')} {rec.get('COUNT_PY', '')} {rec.get('COUNT_CH', '')}".lower()
          if any(kw in meta_txt for kw in tusi_kws):
            continue
          cpy, cch = str(rec.get("COUNT_PY") or "").lower().replace(" ", ""), str(rec.get("COUNT_CH") or "")
          if (cpy or cch) and (host_py_tokens or host_ch_tokens):
            if not ((cpy and any(tok in cpy for tok in host_py_tokens)) or (cch and any(tok in cch for tok in host_ch_tokens))):
              continue
          if np.min(np.hypot(all_seats[:, 0] - tx, all_seats[:, 1] - ty)) < bg_exclude_r or np.min(np.hypot(pos_arr[:, 0] - tx, pos_arr[:, 1] - ty)) < bg_exclude_r:
            continue
          ai = locate_atom(tx, ty)
          if ai >= 0 and ai not in protected_bg_atoms:
            if not disable_subadmin:
              gb, _ = self._lookup_atom_subadmin(atoms[ai].representative_point())
              if gb and gb in citas_with_tusi_seat and gb not in citas_with_explicit_bg:
                continue
            seeds.setdefault(k_pol, []).append((ai, sec_cost*1.5))
            n_anchors += 1

    # Return statement
    return seeds, seat_atoms, k_pol, n_anchors

  def _collect_poly_boundaries (self, arg1_tree, arg2_geom_list, arg3_clip_geom, arg4_lines, arg5_extract_fn=None):
    """Query spatial index inside arg3_clip_geom and append clipped boundary LineStrings to arg4_lines."""
    if arg1_tree is None:
      return
    get_g = arg5_extract_fn or (lambda item: item)
    for idx in arg1_tree.query(arg3_clip_geom):
      geom = get_g(arg2_geom_list[int(idx)])
      if geom.intersects(arg3_clip_geom):
        for b_ln in self._extract_boundaries(geom):
          if b_ln.intersects(arg3_clip_geom):
            arg4_lines.append(b_ln.intersection(arg3_clip_geom))


  def _consolidate_sliver_atoms (self, arg1_atoms, arg2_protected_idxs, arg3_disable_subadmin=False):
    """Merge tiny unseeded micro-sliver atoms into their longest-shared-edge neighbour (preferring same county).
    @param arg1_atoms Polygon atoms; arg2_protected_idxs protected indices; arg3_disable_subadmin ignore PRC subadmin when False-checking.
    @return Consolidated list of clean Shapely Polygon atoms.
    """
    # Convert from parameters
    atoms = list(arg1_atoms)
    disable_subadmin = bool(arg3_disable_subadmin)
    protected = set(arg2_protected_idxs)

    min_area = float(self.weights.get("min_sliver_area_deg2", 0.00025))
    if len(atoms) <= 1:
      return atoms

    gbs = [("", "")]*len(atoms) if disable_subadmin else [self._lookup_atom_subadmin(a.representative_point()) for a in atoms]
    alive = [True]*len(atoms)
    tree = STRtree(atoms)
    small_order = sorted([i for i, a in enumerate(atoms) if i not in protected and a.area < min_area], key=lambda i: atoms[i].area)

    for i in small_order:
      if not alive[i]:
        continue
      ai = atoms[i]
      best_j, best_score = -1, -1.0
      for j in tree.query(ai.buffer(1e-4)):
        ji = int(j)
        if ji == i or not alive[ji]:
          continue
        inter = ai.boundary.intersection(atoms[ji].boundary)
        slen = float(inter.length) if not inter.is_empty else 0.0
        if slen <= 1e-6:
          continue
        same_cnty = (gbs[i][0] != "" and gbs[i][0] == gbs[ji][0]) or (gbs[i][1] != "" and gbs[i][1] == gbs[ji][1])
        score = slen*(10.0 if same_cnty else 1.0)
        if score > best_score:
          best_score, best_j = score, ji
      if best_j >= 0:
        merged = gis_helpers.clean_polygonal_geometry(unary_union([atoms[best_j], ai]))
        if merged is not None and merged.geom_type == "Polygon":
          atoms[best_j] = merged
          alive[i] = False

    # Return statement
    return [atoms[i] for i in range(len(atoms)) if alive[i]]

  def _extract_boundaries (self, arg1_geom):
    """Extract all exterior and interior boundary LineStrings from a Polygon or MultiPolygon."""
    # Convert from parameters
    geom = arg1_geom

    # Declare local instance variables.
    out = []
    polys = [geom] if geom.geom_type == "Polygon" else (list(geom.geoms) if geom.geom_type == "MultiPolygon" else [])

    for pg in polys:
      if len(pg.exterior.coords) >= 3:
        out.append(LineString(pg.exterior.coords))
      for ring in pg.interiors:
        if len(ring.coords) >= 3:
          out.append(LineString(ring.coords))

    # Return statement
    return out

  def _load_borderpool_layers (self):
    """Load and spatially index CITAS, GADM-3, HydroBASINS 8/9/10, HydroRIVERS, and DEM contours."""
    china_bb = (71.5, 16.8, 136.5, 54.8)

    # 1. CITAS 1990 county polygons
    citas_zip = path_helpers.resolve_source_file("chgis", "v5_1990_citas_cnty_pgn_utf.zip", self.base_dir)
    if os.path.exists(citas_zip):
      for rec, geom in gis_helpers.read_zip_shapefile_wgs84(citas_zip, "utf-8", 5):
        gb = str(rec.get("GBCENMQ") or rec.get("GBCENMQ_12") or "").strip()
        if not gb or gb == "0":
          continue
        cg = gis_helpers.clean_polygonal_geometry(geom)
        if cg is not None and not cg.is_empty:
          self.citas_counties.append({"gb": gb, "geom": cg, "name": str(rec.get("NMHANZI") or rec.get("NMFULL") or gb)})
      if self.citas_counties:
        self.citas_tree = STRtree([c["geom"] for c in self.citas_counties])

    # 2. GADM 4.1 Level-3 (China + India Himalaya/NEFA)
    for gname, cc in [("gadm41_CHN_3.json.zip", "CHN"), ("gadm41_IND_3.json.zip", "IND")]:
      gpath = path_helpers.resolve_source_file("gadm", gname, self.base_dir)
      if not os.path.exists(gpath):
        continue
      with zipfile.ZipFile(gpath, "r") as zf:
        jn = next((n for n in zf.namelist() if n.lower().endswith((".json", ".geojson"))), None)
        feats = json.loads(zf.read(jn).decode("utf-8")).get("features", []) if jn else []
      for feat in feats:
        g = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
        if g is None or g.is_empty or g.bounds[2] < china_bb[0] or g.bounds[0] > china_bb[2] or g.bounds[3] < china_bb[1] or g.bounds[1] > china_bb[3]:
          continue
        p = feat.get("properties", {})
        self.gadm3_counties.append({"geom": g, "gid": str(p.get("GID_3") or ""), "name": str(p.get("NAME_3") or ""), "src": cc})
    self.gadm3_tree = STRtree([c["geom"] for c in self.gadm3_counties]) if self.gadm3_counties else None

    # 3. WWF HydroBASINS Asia levels 8, 9, 10
    for lvl in (8, 9, 10):
      hz = path_helpers.resolve_source_file("hydrosheds", f"hybas_as_lev{lvl:02d}_v1c.zip", self.base_dir)
      geoms = []
      if os.path.exists(hz):
        with zipfile.ZipFile(hz, "r") as zf:
          shp_n = next((n for n in zf.namelist() if n.lower().endswith(".shp")), None)
          if shp_n:
            for s in shapefile.Reader(shp=io.BytesIO(zf.read(shp_n)), encoding="utf-8", encodingErrors="replace").iterShapes():
              sb, pts = s.bbox, s.points
              if len(pts) < 3 or sb[2] < china_bb[0] or sb[0] > china_bb[2] or sb[3] < china_bb[1] or sb[1] > china_bb[3]:
                continue
              parts = list(s.parts) + [len(pts)]
              pg = Polygon(pts) if len(parts) == 2 else gis_helpers.clean_polygonal_geometry(Polygon([pts[parts[i]:parts[i + 1]] for i in range(len(parts) - 1) if parts[i + 1] - parts[i] >= 3][0]))
              if len(parts) > 2:
                rings = [pts[parts[i]:parts[i + 1]] for i in range(len(parts) - 1) if parts[i + 1] - parts[i] >= 3]
                pg = gis_helpers.clean_polygonal_geometry(Polygon(rings[0], rings[1:]) if rings else None)
              if pg is not None and not pg.is_empty:
                geoms.append(pg if pg.is_valid else make_valid(pg))
      self.hybas[lvl] = geoms
      self.hybas_trees[lvl] = STRtree(geoms) if geoms else None

    # 4. HydroRIVERS v10 Asia (ORD_STRA >= 3 inside China bbox, cached in pickle)
    hr_cache = path_helpers.resolve_path("input.gis.hydrorivers_cache_pkl", self.base_dir)
    hr_zip = path_helpers.resolve_source_file("hydrosheds", "HydroRIVERS_v10_as_shp.zip", self.base_dir)
    if os.path.exists(hr_cache) and os.path.getsize(hr_cache) > 0:
      with open(hr_cache, "rb") as fh:
        self.hydrorivers = [(o, LineString(pts)) for o, pts in pickle.load(fh)]
    elif os.path.exists(hr_zip):
      raw_hr = []
      with zipfile.ZipFile(hr_zip, "r") as zf:
        shp_n = next((n for n in zf.namelist() if n.lower().endswith(".shp")), None)
        dbf_n = next((n for n in zf.namelist() if n.lower().endswith(".dbf")), None)
        if shp_n and dbf_n:
          sf = shapefile.Reader(shp=io.BytesIO(zf.read(shp_n)), dbf=io.BytesIO(zf.read(dbf_n)), encoding="utf-8", encodingErrors="replace")
          ord_idx = [f[0] for f in sf.fields[1:]].index("ORD_STRA")
          for idx, s in enumerate(sf.iterShapes()):
            ord_s, sb = int(sf.record(idx)[ord_idx]), s.bbox
            if ord_s < 3 or len(s.points) < 2 or sb[2] < china_bb[0] or sb[0] > china_bb[2] or sb[3] < china_bb[1] or sb[1] > china_bb[3]:
              continue
            pts_t = [(round(float(x), 5), round(float(y), 5)) for x, y in s.points]
            raw_hr.append((ord_s, pts_t))
            self.hydrorivers.append((ord_s, LineString(pts_t)))
      if raw_hr:
        with open(hr_cache, "wb") as fh:
          pickle.dump(raw_hr, fh, protocol=pickle.HIGHEST_PROTOCOL)
    self.hydrorivers_tree = STRtree([r[1] for r in self.hydrorivers]) if self.hydrorivers else None

    # 5. DEM elevation contours from ./output/gis/layers/elevation_contours.geojson
    ec_path = path_helpers.resolve_path("output.gis.elevation_contours", self.base_dir)
    if os.path.exists(ec_path):
      with open(ec_path, "r", encoding="utf-8") as fh:
        for feat in json.load(fh).get("features", []):
          p = feat.get("properties", {})
          lvl = int(p.get("elevation_m") or 0)
          if p.get("feature_type") == "contour" and lvl >= 500:
            g = shape(feat["geometry"])
            if not g.is_empty and g.length >= 0.08:
              self.contour_lines.append((lvl, g))
      self.contour_tree = STRtree([c[1] for c in self.contour_lines]) if self.contour_lines else None

    print(
      f"[BORDERPOOL] Indexed CITAS={len(self.citas_counties)}, GADM3={len(self.gadm3_counties)}, "
      f"HyBAS8={len(self.hybas.get(8, []))}, HyBAS9={len(self.hybas.get(9, []))}, "
      f"HyBAS10={len(self.hybas.get(10, []))}, HydroRIVERS(>=3)={len(self.hydrorivers)}, Contours={len(self.contour_lines)}"
    )

  def _lookup_atom_subadmin (self, arg1_point):
    """Return (citas_gb, gadm_gid) covering a point (typically atom representative_point)."""
    # Convert from parameters
    pt = arg1_point

    # Declare local instance variables.
    citas_gb = ""
    gadm_id = ""

    if self.citas_tree is not None:
      for idx in self.citas_tree.query(pt):
        if self.citas_counties[int(idx)]["geom"].contains(pt):
          citas_gb = self.citas_counties[int(idx)]["gb"]
          break

    if self.gadm3_tree is not None:
      for idx in self.gadm3_tree.query(pt):
        if self.gadm3_counties[int(idx)]["geom"].contains(pt):
          gadm_id = self.gadm3_counties[int(idx)]["gid"]
          break

    # Return statement
    return citas_gb, gadm_id

  def _polygonise_inside (self, arg1_lines, arg2_clip_poly):
    """Node a collection of cutter LineStrings, run polygonize, and intersect cleanly inside arg2_clip_poly."""
    # Convert from parameters
    clip_poly = arg2_clip_poly
    lines = list(arg1_lines)

    if not lines or clip_poly is None or clip_poly.is_empty:
      return []

    # Declare local instance variables.
    atoms = []
    min_keep = 1e-8
    noded = None
    prep_clip = shapely.prepared.prep(clip_poly)
    valid_lines = []

    for ln in lines:
      if ln is None or ln.is_empty:
        continue
      if ln.geom_type == "LineString":
        valid_lines.append(ln)
      elif ln.geom_type in ("MultiLineString", "GeometryCollection"):
        for sub in ln.geoms:
          if sub.geom_type == "LineString":
            valid_lines.append(sub)
          elif sub.geom_type == "MultiLineString":
            valid_lines.extend(list(sub.geoms))

    if not valid_lines:
      return [clip_poly]

    try:
      noded = unary_union([set_precision(ln, 1e-5) for ln in valid_lines])
    except Exception:
      noded = unary_union(valid_lines)

    for pg in polygonize(noded):
      if pg.area <= min_keep:
        continue
      rp = pg.representative_point()
      if not prep_clip.contains(rp) and clip_poly.distance(rp) > 1e-5:
        continue
      clipped = pg if prep_clip.contains_properly(pg) else gis_helpers.clean_polygonal_geometry(pg.intersection(clip_poly))
      if clipped is None:
        continue
      polys = [clipped] if clipped.geom_type == "Polygon" else (list(clipped.geoms) if clipped.geom_type == "MultiPolygon" else [])
      atoms.extend([sub for sub in polys if sub.area > min_keep])

    if not atoms:
      return [clip_poly]

    rem = gis_helpers.clean_polygonal_geometry(clip_poly.difference(unary_union(atoms)))
    if rem is not None and rem.area > 1e-7:
      rem_polys = [rem] if rem.geom_type == "Polygon" else (list(rem.geoms) if rem.geom_type == "MultiPolygon" else [])
      atoms.extend([sub for sub in rem_polys if sub.area > 1e-8])

    # Return statement
    return atoms

  def _split_multi_seat_atom (self, arg1_atom, arg2_local_seats, arg3_host_domain):
    """Subdivide an atom holding >= 2 seats using hydrology/contours and Chaikin DEM ridge watersheds."""
    atom, local_seats = arg1_atom, list(arg2_local_seats)
    if len(local_seats) <= 1:
      return [atom]

    cuts = self._extract_boundaries(atom)
    if self.hydrorivers_tree is not None:
      cuts.extend(self.hydrorivers[int(r_idx)][1].intersection(atom.buffer(0.01)) for r_idx in self.hydrorivers_tree.query(atom) if self.hydrorivers[int(r_idx)][1].intersects(atom))
    cuts.extend(cg.intersection(atom.buffer(0.01)) for _, cg in self.elev_builder.extract_local_contours(atom.bounds, range(200, 5600, 100)) if cg.intersects(atom))

    sub_atoms = self._polygonise_inside(cuts, atom)
    if sub_atoms and not any(sum(1 for sx, sy in local_seats if sa.contains(Point(sx, sy)) or sa.distance(Point(sx, sy)) < 1e-6) >= 2 for sa in sub_atoms):
      return sub_atoms

    final_parts = []
    for pa in (sub_atoms if sub_atoms else [atom]):
      in_pa = [(sx, sy) for sx, sy in local_seats if pa.contains(Point(sx, sy)) or pa.distance(Point(sx, sy)) < 1e-5]
      if len(in_pa) <= 1:
        final_parts.append(pa)
        continue
      pb = pa.bounds
      step = max(0.0018, min(0.004, max(pb[2] - pb[0], pb[3] - pb[1]) / 90.0))
      lons, lats, elev = self.elev_builder.extract_local_dem_patch(pb, step)
      gy_e, gx_e = np.gradient(elev)
      slope = np.hypot(gx_e, gy_e)
      relief_norm = (elev - float(np.min(elev))) / max(1.0, float(np.max(elev) - np.min(elev)))
      topo_surface = 0.65*relief_norm + 0.35*(slope / max(1e-6, float(np.max(slope))))
      h, w = elev.shape
      markers = np.zeros((h, w), dtype=np.int32)
      gx_m, gy_m = np.meshgrid(lons, lats)
      inside_mask = shapely.contains_xy(pa.buffer(0.5*step), gx_m.ravel(), gy_m.ravel()).reshape(h, w)
      for s_i, (sx, sy) in enumerate(in_pa, start=1):
        ix, iy = int(np.clip(round((sx - lons[0]) / (lons[1] - lons[0])), 1, w - 2)), int(np.clip(round((sy - lats[0]) / (lats[1] - lats[0])), 1, h - 2))
        markers[iy, ix], inside_mask[iy, ix] = s_i, True
      ws_labels = watershed(topo_surface, markers=markers, mask=inside_mask, compactness=0.0)
      pair_segs = {}
      for iy, ix in np.argwhere((ws_labels[:, :-1] > 0) & (ws_labels[:, 1:] > 0) & (ws_labels[:, :-1] != ws_labels[:, 1:])):
        c0, cr, xm = int(ws_labels[iy, ix]), int(ws_labels[iy, ix + 1]), round(0.5*(lons[ix] + lons[ix + 1]), 7)
        pair_segs.setdefault((min(c0, cr), max(c0, cr)), []).append(LineString([(xm, round(lats[iy] - 0.5*step, 7)), (xm, round(lats[iy] + 0.5*step, 7))]))
      for iy, ix in np.argwhere((ws_labels[:-1, :] > 0) & (ws_labels[1:, :] > 0) & (ws_labels[:-1, :] != ws_labels[1:, :])):
        c0, cu, ym = int(ws_labels[iy, ix]), int(ws_labels[iy + 1, ix]), round(0.5*(lats[iy] + lats[iy + 1]), 7)
        pair_segs.setdefault((min(c0, cu), max(c0, cu)), []).append(LineString([(round(lons[ix] - 0.5*step, 7), ym), (round(lons[ix] + 0.5*step, 7), ym)]))
      ridge_cuts = self._extract_boundaries(pa)
      for seg_list in pair_segs.values():
        merged_lns = linemerge(seg_list)
        chains = [merged_lns] if merged_lns.geom_type == "LineString" else list(merged_lns.geoms)
        for ch in chains:
          if len(ch.coords) >= 2:
            ridge_cuts.append(LineString(self._chaikin_coords(ch.coords, 2 if len(ch.coords) >= 3 else 0, 1.4*step)))
      split_res = self._polygonise_inside(ridge_cuts, pa)
      still_bad = (not split_res) or any(sum(1 for sx, sy in in_pa if sa.contains(Point(sx, sy)) or sa.distance(Point(sx, sy)) < 1e-6) >= 2 for sa in split_res)
      if not still_bad:
        final_parts.extend(split_res)
      else:
        rem_pa = pa
        for s_i in range(1, len(in_pa)):
          coords_rc = np.argwhere(ws_labels == s_i)
          if coords_rc.shape[0] == 0:
            continue
          u_poly = unary_union([box(lons[ix] - 0.51*step, lats[iy] - 0.51*step, lons[ix] + 0.51*step, lats[iy] + 0.51*step) for iy, ix in coords_rc])
          sm = gis_helpers.clean_polygonal_geometry(u_poly.simplify(0.6*step, preserve_topology=True))
          if sm is not None and sm.geom_type == "Polygon" and len(sm.exterior.coords) >= 4:
            sm = gis_helpers.clean_polygonal_geometry(Polygon(self._chaikin_coords(sm.exterior.coords, 2, 0.0)))
          part = gis_helpers.clean_polygonal_geometry(rem_pa.intersection(sm)) if sm is not None else None
          if part is not None and not part.is_empty:
            final_parts.extend([part] if part.geom_type == "Polygon" else list(part.geoms))
            rem_pa = gis_helpers.clean_polygonal_geometry(rem_pa.difference(sm))
            if rem_pa is None or rem_pa.is_empty:
              break
        if rem_pa is not None and not rem_pa.is_empty:
          final_parts.extend([rem_pa] if rem_pa.geom_type == "Polygon" else list(rem_pa.geoms))

    # Return statement
    return [p for p in final_parts if p is not None and not p.is_empty and p.area > 1e-9]

  def _is_surveyed_admin_boundary (self, arg1_line):
    """Return True if at least 85% of arg1_line follows a surveyed CHGIS, CITAS, or GADM boundary."""
    line = arg1_line
    qbox = line.buffer(2e-4)
    refs = []
    for tree, items, getter in ((self.adm3_tree, self.adm3_geoms, lambda x: x), (self.citas_tree, self.citas_counties, lambda x: x["geom"]), (self.gadm3_tree, self.gadm3_counties, lambda x: x["geom"])):
      if tree is not None:
        refs.extend(getter(items[int(idx)]).boundary for idx in tree.query(qbox))
    if not refs:
      return False
    covered = line.intersection(unary_union(refs).buffer(2e-4))
    return float(covered.length) >= 0.85*float(line.length)

  def audit_voronoi_artefacts (self, arg1_tusi_geoms, arg2_tier_map):
    """Audit shared modelled boundaries for synthetic Voronoi chords (exempting surveyed borders)."""
    tier_map, tusi_geoms = arg2_tier_map, arg1_tusi_geoms
    checked, sin_sum, violations = 0, 0.0, []
    ids = sorted(tid for tid in tusi_geoms.keys() if tier_map.get(tid) in ("tier_b", "tier_c"))
    geoms = [tusi_geoms[tid] for tid in ids]
    tree = STRtree(geoms) if geoms else None

    if tree is not None:
      for i, tid_a in enumerate(ids):
        ga = geoms[i]
        for j_raw in tree.query(ga.buffer(1e-4)):
          j = int(j_raw)
          if j <= i:
            continue
          inter = ga.boundary.intersection(geoms[j].boundary)
          if inter.is_empty or inter.length < 0.08:
            continue
          line_parts = []
          for g_part in (inter.geoms if hasattr(inter, "geoms") else [inter]):
            if g_part.geom_type in ("LineString", "LinearRing") and len(g_part.coords) >= 2:
              line_parts.append(LineString(g_part.coords) if g_part.geom_type == "LinearRing" else g_part)
            elif g_part.geom_type == "MultiLineString":
              line_parts.extend(ls for ls in g_part.geoms if len(ls.coords) >= 2)
          if not line_parts:
            continue
          merged = linemerge(line_parts)
          chains = [merged] if merged.geom_type == "LineString" else (list(merged.geoms) if merged.geom_type == "MultiLineString" else [])
          for ch in chains:
            if ch.length < 0.08 or len(ch.coords) < 2:
              continue
            coords = list(ch.coords)
            chord = math.hypot(coords[-1][0] - coords[0][0], coords[-1][1] - coords[0][1])
            sinuosity = float(ch.length) / max(1e-4, 2.0*max(math.hypot(c[0] - coords[0][0], c[1] - coords[0][1]) for c in coords) if chord < 1e-4 else chord)
            max_seg = max(math.hypot(coords[k + 1][0] - coords[k][0], coords[k + 1][1] - coords[k][1]) for k in range(len(coords) - 1))
            checked += 1
            sin_sum += sinuosity
            if len(coords) == 2 or (len(coords) <= 3 and ch.length >= 0.08) or (ch.length >= 0.18 and sinuosity < 1.015) or (max_seg >= 0.16 and sinuosity < 1.08):
              if not self._is_surveyed_admin_boundary(ch):
                violations.append((tid_a, ids[j], round(float(ch.length), 4), round(max_seg, 4), round(sinuosity, 4), len(coords)))

    # Return statement
    return {"checked_chains": checked, "mean_sinuosity": round(sin_sum / max(1, checked), 4), "voronoi_violations": violations}

  def build_borderpool_atoms (self, arg1_host_domain, arg2_seat_pts, arg3_barrier_names, arg4_cfg=None, arg5_bg_pts=None):
    """Build watertight topographic & subadministrative borderpool atoms for a host domain."""
    barrier_names = [b.lower() for b in (arg3_barrier_names or [])]
    cfg = arg4_cfg if isinstance(arg4_cfg, dict) else {}
    host_domain, seat_pts = arg1_host_domain, list(arg2_seat_pts)
    area, buf_dom = float(host_domain.area), host_domain.buffer(0.01)
    if bool(cfg.get("disable_modern_subadmin", False)):
      lines = tusi_topo_helpers.build_pure_topographic_cutters(self, host_domain, seat_pts, arg5_bg_pts or [], barrier_names, cfg)
    else:
      lines = self._extract_boundaries(host_domain)

      self._collect_poly_boundaries(self.adm3_tree, self.adm3_geoms, buf_dom, lines)
      self._collect_poly_boundaries(self.citas_tree, self.citas_counties, buf_dom, lines, lambda r: r["geom"])
      self._collect_poly_boundaries(self.gadm3_tree, self.gadm3_counties, buf_dom, lines, lambda r: r["geom"])

      if area <= 28.0:
        self._collect_poly_boundaries(self.hybas_trees.get(10), self.hybas.get(10, []), buf_dom, lines)
      else:
        for lvl in (8, 9):
          self._collect_poly_boundaries(self.hybas_trees.get(lvl), self.hybas.get(lvl, []), buf_dom, lines)
        t10 = self.hybas_trees.get(10)
        if t10 is not None and seat_pts:
          core_zones = unary_union([Point(sx, sy).buffer(0.85) for sx, sy in seat_pts]).intersection(buf_dom)
          self._collect_poly_boundaries(t10, self.hybas.get(10, []), core_zones, lines)

      min_ord = 3 if area <= 15.0 else 4
      if self.hydrorivers_tree is not None:
        for idx in self.hydrorivers_tree.query(buf_dom):
          ord_s, rg = self.hydrorivers[int(idx)]
          if ord_s >= min_ord and rg.intersects(buf_dom):
            lines.append(rg.intersection(buf_dom))
      for wp, wg in self.waterways:
        nm = (str(wp.get("name_en") or "") + " " + str(wp.get("name_ch") or "")).lower()
        if (any(bn in nm for bn in barrier_names) or "NaturalEarth" in str(wp.get("source") or "")) and wg.intersects(buf_dom):
          lines.append(wg.intersection(buf_dom))
      if self.contour_tree is not None:
        for idx in self.contour_tree.query(buf_dom):
          lvl, cg = self.contour_lines[int(idx)]
          if lvl in (500, 1000, 1500, 2000, 3000, 4000) and cg.intersects(buf_dom):
            lines.append(cg.intersection(buf_dom))

    atoms = self._polygonise_inside(lines, host_domain)
    split_atoms = []
    for atm in atoms:
      in_atm = [(sx, sy) for sx, sy in seat_pts if atm.contains(Point(sx, sy)) or atm.distance(Point(sx, sy)) < 1e-6]
      split_atoms.extend(self._split_multi_seat_atom(atm, in_atm, host_domain) if len(in_atm) >= 2 else [atm])

    # Return statement
    return split_atoms

  def partition_cluster_borderpool (self, arg1_polities, arg2_host_domain, arg3_cfg, arg4_allow_bg, arg5_all_seats):
    """Run the full Borderpool Graph pipeline inside arg2_host_domain and return clean polygons per Tusi."""
    all_seats, allow_bg, cfg = arg5_all_seats, bool(arg4_allow_bg), arg3_cfg
    disable_subadmin = bool(cfg.get("disable_modern_subadmin", False))
    host_domain, polities = arg2_host_domain, list(arg1_polities)
    barrier_names = cfg.get("barrier_rivers", [])
    bg_pts = [(float(bgs[0]), float(bgs[1])) for bgs in cfg.get("bg_seeds", [])]
    out_geoms, prot = {}, set()
    reach_scales = tusi_topo_helpers.resolve_polity_reach_scales(polities, cfg, allow_bg)
    seat_pts = [(float(t["seat_lon"]), float(t["seat_lat"])) for t in polities]

    atoms = self.build_borderpool_atoms(host_domain, seat_pts, barrier_names, cfg, bg_pts)
    a_tree = STRtree(atoms)
    for t in polities:
      pts = [(float(t["seat_lon"]), float(t["seat_lat"]))] + [(float(k[0]), float(k[1])) for k in t.get("known_settlements", [])]
      for px, py in pts:
        pt = Point(px, py)
        for idx in a_tree.query(pt):
          if atoms[int(idx)].contains(pt) or atoms[int(idx)].distance(pt) < 1e-6:
            prot.add(int(idx))
    atoms = self._consolidate_sliver_atoms(atoms, prot, disable_subadmin)

    seeds, seat_atoms, k_pol, n_anchors = self._collect_cluster_anchors(polities, atoms, host_domain, cfg, allow_bg, all_seats)
    seat_subs_p = [("", "")]*len(seat_pts) if disable_subadmin else [self._lookup_atom_subadmin(Point(sx, sy)) for sx, sy in seat_pts]
    adj = self._build_atom_graph(atoms, barrier_names, ({s[0] for s in seat_subs_p if s[0]}, {s[1] for s in seat_subs_p if s[1]}), disable_subadmin)
    n_edges = sum(len(x) for x in adj) // 2
    labels = self._assign_atoms_topographic(atoms, adj, seeds, seat_atoms, k_pol, reach_scales)

    out_geoms = tusi_topo_helpers.assemble_and_smooth_cluster_polygons(self, atoms, labels, polities, host_domain, cfg)

    # Return statement
    return out_geoms, len(atoms), n_anchors, n_edges
