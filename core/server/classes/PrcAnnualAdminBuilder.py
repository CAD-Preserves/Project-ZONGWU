"""Builds 219 watertight 1954-2026 annual adm_1/adm_2/adm_3 GeoJSONs from genuinely scraped sources."""

import hashlib
import os
import sys

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from shapely import STRtree, prepare
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from helpers import ctamap_io_helpers, gis_helpers, path_helpers, planar_topology_helpers, prc_annual_helpers


class PrcAnnualAdminBuilder:
  """Constructs 219 watertight annual administrative GeoJSONs covering 1954-2026 into output/gis/prc_annual_1954_2026/."""

  def __init__ (self, arg1_cfg, arg2_base_dir=None):
    """Initialise annual builder configuration, file paths, and planar topology caches.

    @param arg1_cfg Loaded data_sources.json5 dict.
    @param arg2_base_dir Optional workspace root directory.
    """
    # Convert from parameters
    base_dir = str(arg2_base_dir or (arg1_cfg or {}).get("_base_dir") or path_helpers.get_project_root())
    cfg = arg1_cfg

    # Declare local instance variables.
    self.ac_index = {}
    self.agg_cache = {}
    self.base_1980_clean = []
    self.base_2000_clean = []
    self.base_dir = base_dir
    self.cfg = cfg
    self.ctamap_clean_by_year = {}
    self.ctamap_dcel_by_sig = {}
    self.ctamap_dir = path_helpers.resolve_path("input.gis.ctamap_dir", self.base_dir)
    self.layers_loaded = False
    self.mng_atoms = []
    self.northern_seam_cache = {}
    self.out_dir = path_helpers.resolve_path("output.gis.prc_annual_dir", self.base_dir)
    self.precision = int(cfg.get("coordinate_precision", 5))
    self.grid_size = 10.0 ** (-self.precision)
    self.prov_epoch1_cache = {}
    self.raw_wkb_cache = {}
    self.reforms_cfg = gis_helpers.load_json5(path_helpers.resolve_path("common.prc_admin_reforms", self.base_dir)) or {}
    self.roc_fujian_mask = None
    self.tuva_atoms = []
    self.tusi_carved_cache = {}
    self.tusi_cohorts = {}
    self.twn_atoms = []
    self.union_cache = {}
    self.year_outer_dcel = {}
    os.makedirs(self.out_dir, exist_ok=True)

  def _aggregate_region_cached (self, arg1_region_tag, arg2_level, arg3_unit_feats, arg4_key_fn, arg5_meta_fn):
    """Aggregate region features via aggregate_coverage_by_key, caching geometry partitions across identical years.

    @param arg1_region_tag String label ('prc', 'twn', 'mng', 'tuva').
    @param arg2_level Administrative level (1 or 2).
    @param arg3_unit_feats List of (props_dict, shapely_geom) tuples.
    @param arg4_key_fn Callable mapping props_dict -> immutable grouping tuple.
    @param arg5_meta_fn Callable (group_key, member_props_list) -> output props_dict.
    @return List of (aggregated_props, shapely_geom) tuples.
    """
    # Convert from parameters
    key_fn = arg4_key_fn
    level = int(arg2_level)
    meta_fn = arg5_meta_fn
    region_tag = str(arg1_region_tag)
    unit_feats = list(arg3_unit_feats or [])

    # Declare local instance variables.
    cached_geoms = {}
    geom = None
    g_key = None
    grouped_props = {}
    idx = 0
    out_feats = []
    props = {}
    props_out = {}
    rp = None
    sig_items = []

    if not unit_feats:
      return []

    for idx, (props, geom) in enumerate(unit_feats):
      g_key = key_fn(props)
      grouped_props.setdefault(g_key, []).append(props)
      sig_items.append((g_key, hashlib.blake2b(geom.wkb, digest_size=12).digest()))

    sig = (region_tag, level, tuple(sorted(sig_items, key=lambda x: str(x[0]))))
    if sig not in self.agg_cache:
      agg_pairs = planar_topology_helpers.aggregate_coverage_by_key(
        unit_feats,
        key_fn,
        lambda k, ms: {"_gk": k},
        self.grid_size,
        0.05,
      )
      self.agg_cache[sig] = {p["_gk"]: g for p, g in agg_pairs}

    cached_geoms = self.agg_cache[sig]
    for g_key in sorted(grouped_props.keys(), key=str):
      geom = cached_geoms.get(g_key)
      if geom is None or geom.is_empty:
        continue
      props_out = meta_fn(g_key, grouped_props[g_key])
      rp = geom.representative_point()
      props_out["adm_level"] = level
      props_out["seat_lat"] = round(float(rp.y), self.precision)
      props_out["seat_lon"] = round(float(rp.x), self.precision)
      out_feats.append((props_out, geom))

    # Return statement
    return out_feats

  def _build_mainland_1954_1979 (self, arg1_year):
    """Build watertight Mainland/HK/Macau + active 1954-1958 Tusi adm_3 features for 1954..1979.

    @param arg1_year Snapshot integer year (1954..1979).
    @return List of (props_dict, shapely_geom) tuples.
    """
    # Convert from parameters
    yr = int(arg1_year)

    # Declare local instance variables.
    active_tusis, ak, by_uid, carved, c_key, c_sig, cp = [], "", {}, [], (), None, {}
    carved_prc, ch_by_op, geom_items, hit_idxs, kept_parts, k_poly = [], {}, [], set(), [], None
    mainland_geoms, mainland_union, max_cohort, nb_idx = [], None, 0, -1
    mng_2000, mng_dcel_map, orig_parts, p_adm1, p_it, prc_colonies, prc_main = [], {}, [], "", {}, [], []
    prio_map, prov_meta, prov_sig, raw_items, rem_adds, remnant_parts = {"colony": 3, "mng": 1, "prc": 2, "tusi": 3, "tuva": 0}, {}, None, [], {}, []
    sub_parts, surv_area, target_feats, target_geoms, target_tree = [], 0.0, [], [], None
    t_cleaned, t_clip, t_clipped, t_dict, t_poly, t_tree, t_union = [], None, [], {}, None, None, None
    tuva_2000, tuva_dcel_map, untouched_prc, u_props, zh_by_adm1 = [], {}, [], {}, {}

    for ak, u_props, locked_geom in self.base_1980_clean:
      cp = prc_annual_helpers.classify_1954_1979_mainland_unit(u_props, yr, self.reforms_cfg)
      cp["_ak"] = ak
      raw_items.append((cp, locked_geom))
      zh_by_adm1[cp["parent_adm1"]] = (cp["parent_adm1_zh"], cp["category"])

    prov_sig = tuple((cp["_ak"], cp["parent_adm1"], cp["country"]) for cp, _ in raw_items)
    if prov_sig not in self.prov_epoch1_cache:
      prc_only = [(p, g) for p, g in raw_items if p["country"] == "People's Republic of China"]
      col_only = [(p, g) for p, g in raw_items if p["country"] != "People's Republic of China"]
      contig_prc, _ = planar_topology_helpers.enforce_adm1_contiguity(prc_only, "parent_adm1", 0.005, self.grid_size, {"tusi", "colony"})
      self.prov_epoch1_cache[prov_sig] = (
        {p["_ak"]: (p["parent_adm1"], g) for p, g in contig_prc + col_only},
        {},
      )

    adm1_geom_map, _ = self.prov_epoch1_cache[prov_sig]
    for cp, _ in raw_items:
      ak = cp["_ak"]
      p_adm1, geom = adm1_geom_map[ak]
      if p_adm1 != cp["parent_adm1"]:
        cp["parent_adm1"] = p_adm1
        if p_adm1 in zh_by_adm1:
          cp["parent_adm1_zh"], cp["category"] = zh_by_adm1[p_adm1]
        else:
          prov_meta = self.reforms_cfg.get("adm1_zh_names", {})
          cp["parent_adm1_zh"] = str(prov_meta.get(p_adm1) or "")
      by_uid[ak] = cp

    if yr <= 1954:
      max_cohort = 1954
      active_tusis = self.tusi_cohorts.get(1954, []) + self.tusi_cohorts.get(1956, []) + self.tusi_cohorts.get(1958, [])
    elif yr <= 1956:
      max_cohort = 1956
      active_tusis = self.tusi_cohorts.get(1956, []) + self.tusi_cohorts.get(1958, [])
    elif yr <= 1958:
      max_cohort = 1958
      active_tusis = self.tusi_cohorts.get(1958, [])
    else:
      max_cohort = 0
      active_tusis = []

    c_sig = (prov_sig, max_cohort)
    if c_sig not in self.tusi_carved_cache:
      base_pairs = [(by_uid[ak], adm1_geom_map[ak][1]) for ak in [cp["_ak"] for cp, _ in raw_items]]
      if not active_tusis:
        self.tusi_carved_cache[c_sig] = ([(p["_ak"], None, g) for p, g in base_pairs], None, None)
      else:
        prc_main = [(p, g) for p, g in base_pairs if p["country"] == "People's Republic of China"]
        prc_colonies = [(p, g) for p, g in base_pairs if p["country"] != "People's Republic of China"]
        mainland_geoms = [g for _, g in prc_main]
        mainland_union = planar_topology_helpers._union_polygons(mainland_geoms, True)
        prepare(mainland_union)
        for t_dict in active_tusis:
          if mainland_union.intersects(t_dict["geom"]):
            t_clip = gis_helpers.clean_polygonal_geometry(t_dict["geom"].intersection(mainland_union))
            if t_clip is not None and not t_clip.is_empty:
              t_clipped.append((dict(t_dict), t_clip))
        t_cleaned = planar_topology_helpers.node_planar_coverage(t_clipped, self.grid_size, 0.05)
        t_union = planar_topology_helpers._union_polygons([g for _, g in t_cleaned], False)
        if t_union is not None and not t_union.is_empty:
          prepare(t_union)
          t_tree = STRtree(mainland_geoms)
          for t_poly in planar_topology_helpers._extract_polygons(t_union):
            for i in t_tree.query(t_poly):
              if t_union.intersects(mainland_geoms[int(i)]):
                hit_idxs.add(int(i))
          for i, (p, g) in enumerate(prc_main):
            if i not in hit_idxs:
              untouched_prc.append((p, g))
              continue
            orig_parts = planar_topology_helpers._extract_polygons(g)
            g_sub = gis_helpers.clean_polygonal_geometry(g.difference(t_union))
            if g_sub is None or g_sub.is_empty:
              continue
            sub_parts = planar_topology_helpers._extract_polygons(g_sub)
            ch_by_op = {}
            for sp in sub_parts:
              rp_sp = sp.representative_point()
              op_idx = next((oi for oi, op in enumerate(orig_parts) if op.contains(rp_sp)), None)
              if op_idx is None:
                op_idx = max(range(len(orig_parts)), key=lambda oi: sp.intersection(orig_parts[oi]).area)
              ch_by_op.setdefault(op_idx, []).append(sp)
            kept_parts = []
            for op_idx, children in ch_by_op.items():
              orig_p = orig_parts[op_idx]
              if not t_union.intersects(orig_p):
                kept_parts.extend(children)
                continue
              surv_area = sum(c.area for c in children)
              max_child = max(children, key=lambda c: c.area)
              if orig_p.area > 0.02 and surv_area < 0.20*orig_p.area and max_child.area < 0.03:
                remnant_parts.extend(children)
              else:
                kept_parts.append(max_child)
                for c in children:
                  if c is max_child:
                    continue
                  if c.area < 0.025 and float(c.distance(t_union)) < 0.002:
                    remnant_parts.append(c)
                  else:
                    kept_parts.append(c)
            if kept_parts:
              k_poly = kept_parts[0] if len(kept_parts) == 1 else MultiPolygon(kept_parts)
              carved_prc.append((p, k_poly))

          target_feats = untouched_prc + carved_prc + t_cleaned
          if remnant_parts and target_feats:
            target_geoms = [g for _, g in target_feats]
            target_tree = STRtree(target_geoms)
            for rem_poly in remnant_parts:
              nb_idx = planar_topology_helpers._assign_part_to_neighbour(rem_poly, target_geoms, target_tree)
              if nb_idx >= 0:
                rem_adds.setdefault(nb_idx, []).append(rem_poly)
            for nb_idx, adds in rem_adds.items():
              merged_target = gis_helpers.clean_polygonal_geometry(unary_union([target_geoms[nb_idx]] + adds))
              if merged_target is not None and not merged_target.is_empty:
                target_geoms[nb_idx] = merged_target
            target_feats = [(tp, tg) for (tp, _), tg in zip(target_feats, target_geoms)]

          contig_all, _ = planar_topology_helpers.enforce_adm1_contiguity(
            target_feats + prc_colonies,
            "parent_adm1",
            0.015,
            self.grid_size,
            {"tusi", "colony"},
          )
          mng_2000, tuva_2000 = self.year_outer_dcel[2000]
          dcel_in = []
          for p_item, g_item in contig_all:
            cp_d = dict(p_item)
            cp_d["_src"] = "tusi" if p_item.get("category") == "tusi" else ("colony" if p_item.get("country") != "People's Republic of China" else "prc")
            dcel_in.append((cp_d, g_item))
          for ak_m, gm_m in mng_2000.items():
            dcel_in.append(({"_src": "mng", "_oak": ak_m}, gm_m))
          for ak_t, gm_t in tuva_2000.items():
            dcel_in.append(({"_src": "tuva", "_oak": ak_t}, gm_t))

          noded_cohort = planar_topology_helpers.node_planar_coverage(
            dcel_in,
            self.grid_size,
            0.05,
            lambda p, g: (prio_map.get(p.get("_src"), 0), float(g.area)),
          )
          mng_dcel_map, tuva_dcel_map = dict(mng_2000), dict(tuva_2000)
          geom_items = []
          for p_item, g_item in noded_cohort:
            src_k = p_item.pop("_src", "")
            if src_k == "mng":
              mng_dcel_map[p_item["_oak"]] = g_item
            elif src_k == "tuva":
              tuva_dcel_map[p_item["_oak"]] = g_item
            elif src_k == "tusi":
              geom_items.append((None, p_item, g_item))
            else:
              geom_items.append((p_item["_ak"], None, g_item))
          self.tusi_carved_cache[c_sig] = (geom_items, mng_dcel_map, tuva_dcel_map)
        else:
          self.tusi_carved_cache[c_sig] = ([(p["_ak"], None, g) for p, g in base_pairs], None, None)

    cached_rows, cached_mng, cached_tuva = self.tusi_carved_cache[c_sig]
    if cached_mng is not None and cached_tuva is not None:
      self.year_outer_dcel[yr] = (cached_mng, cached_tuva)
    for c_key, t_props, geom in cached_rows:
      if c_key is not None:
        cp = {k: v for k, v in by_uid[c_key].items() if not k.startswith("_") and k not in ("gb_1980", "gb_2000")}
        rp = geom.representative_point()
        cp["seat_lat"] = round(float(rp.y), self.precision)
        cp["seat_lon"] = round(float(rp.x), self.precision)
        carved.append((cp, geom))
      else:
        cp = {k: v for k, v in t_props.items() if k not in ("abolition_year", "geom", "grid_size")}
        if cp.get("parent_adm1") == "Xikang" and yr >= 1956:
          cp["parent_adm1"] = "Sichuan"
          cp["parent_adm1_zh"] = "四川省"
        rp = geom.representative_point()
        cp["seat_lat"] = round(float(rp.y), self.precision)
        cp["seat_lon"] = round(float(rp.x), self.precision)
        carved.append((cp, geom))

    # Return statement
    return carved

  def _build_mainland_1980_1999 (self, arg1_year):
    """Build watertight Mainland/HK/Macau adm_3 features for 1980..1999 from base_2000_clean + areacodes.

    @param arg1_year Snapshot integer year (1980..1999).
    @return List of (props_dict, shapely_geom) tuples.
    """
    # Convert from parameters
    yr = int(arg1_year)

    # Declare local instance variables.
    active_2000 = {p["gb_code"] for p, _ in self.base_2000_clean if p.get("gb_code")}
    buckets = {}
    cp = {}
    gb_to_ak = {}
    geom = None
    geom_map = {}
    host_props = {}
    idx = 0
    m_gb = ""
    out = []
    props = {}
    rp = None
    row_ak = ""
    t_ak = ""

    for idx, (props, geom) in enumerate(self.base_2000_clean):
      row_ak = f"b00_{idx}"
      geom_map[row_ak] = geom
      if props.get("gb_code"):
        gb_to_ak[props["gb_code"]] = row_ak

    for idx, (props, _) in enumerate(self.base_2000_clean):
      row_ak = f"b00_{idx}"
      cp = prc_annual_helpers.classify_1980_1999_mainland_unit(props, yr, self.ac_index, self.reforms_cfg, active_2000)
      m_gb = str(cp.get("merge_gb") or "")
      t_ak = gb_to_ak.get(m_gb, row_ak) if m_gb else row_ak
      if t_ak not in buckets:
        buckets[t_ak] = {"keys": [], "props": cp}
      elif t_ak == row_ak:
        buckets[t_ak]["props"] = cp
      buckets[t_ak]["keys"].append(row_ak)

    for t_ak in sorted(buckets.keys()):
      k_list = buckets[t_ak]["keys"]
      geom = geom_map[k_list[0]] if len(k_list) == 1 else self._cached_union(k_list, geom_map)
      if geom is None or geom.is_empty:
        continue
      host_props = {k: v for k, v in buckets[t_ak]["props"].items() if k not in ("gb_1980", "gb_2000", "merge_gb")}
      rp = geom.representative_point()
      host_props["seat_lat"] = round(float(rp.y), self.precision)
      host_props["seat_lon"] = round(float(rp.x), self.precision)
      out.append((host_props, geom))

    # Return statement
    return out

  def _build_outer_layers (self, arg1_year, arg2_prc_adm3):
    """Build harmonised Taiwan, Mongolia, and Tuva adm_3 features for any year in 1954..2026.

    @param arg1_year Snapshot integer year (1954..2026).
    @param arg2_prc_adm3 Watertight Mainland/HK/Macau/(Tusi) adm_3 features for arg1_year.
    @return Tuple (twn_feats, mng_feats, tuva_feats).
    """
    # Convert from parameters
    prc_adm3 = list(arg2_prc_adm3 or [])
    yr = int(arg1_year)

    # Declare local instance variables.
    atom = {}
    cp = {}
    geom = None
    mng_by_id = {}
    mng_harm = []
    mng_out = []
    m_name = ""
    prc_north = []
    rp = None
    seam_sig = None
    tuva_buckets = {}
    tuva_by_id = {}
    tuva_geom_map = {}
    tuva_harm = []
    tuva_out = []
    tuva_raw_by_name = {}
    twn_out = []

    if yr in self.year_outer_dcel:
      mng_by_id, tuva_by_id = self.year_outer_dcel[yr]
    elif 2000 in self.year_outer_dcel:
      mng_by_id, tuva_by_id = self.year_outer_dcel[2000]
    else:
      for props, geom in prc_adm3:
        if geom.bounds[3] >= 40.5:
          prc_north.append((props, geom))
      seam_sig = tuple(sorted((str(p.get("unit_id") or ""), hashlib.blake2b(g.wkb, digest_size=10).digest()) for p, g in prc_north))
      if seam_sig not in self.northern_seam_cache:
        mng_raw = [({"_ak": a["atom_key"]}, a["geom"]) for a in self.mng_atoms]
        tuva_raw = [({"_ak": a["atom_key"]}, a["geom"]) for a in self.tuva_atoms]
        mng_harm, _ = planar_topology_helpers.harmonise_international_seams(prc_north, mng_raw, self.grid_size, 0.03)
        tuva_harm, _ = planar_topology_helpers.harmonise_international_seams(prc_north + mng_harm, tuva_raw, self.grid_size, 0.03)
        self.northern_seam_cache[seam_sig] = (
          {p["_ak"]: g for p, g in mng_harm},
          {p["_ak"]: g for p, g in tuva_harm},
        )
      mng_by_id, tuva_by_id = self.northern_seam_cache[seam_sig]

    for atom in self.twn_atoms:
      cp = prc_annual_helpers.classify_1954_2026_outer_atom("taiwan", atom, yr, self.reforms_cfg)
      cp.pop("merge_target_name", None)
      twn_out.append((cp, atom["geom"]))

    for atom in self.mng_atoms:
      geom = mng_by_id.get(atom["atom_key"]) or atom["geom"]
      cp = prc_annual_helpers.classify_1954_2026_outer_atom("mongolia", atom, yr, self.reforms_cfg)
      cp.pop("merge_target_name", None)
      rp = geom.representative_point()
      cp["seat_lat"] = round(float(rp.y), self.precision)
      cp["seat_lon"] = round(float(rp.x), self.precision)
      mng_out.append((cp, geom))

    for atom in self.tuva_atoms:
      tuva_geom_map[atom["atom_key"]] = tuva_by_id.get(atom["atom_key"]) or atom["geom"]
      tuva_raw_by_name[atom["name_en"]] = atom["atom_key"]

    for atom in self.tuva_atoms:
      cp = prc_annual_helpers.classify_1954_2026_outer_atom("tuva_republic", atom, yr, self.reforms_cfg)
      m_name = str(cp.pop("merge_target_name", "") or "")
      t_ak = tuva_raw_by_name.get(m_name, atom["atom_key"]) if m_name else atom["atom_key"]
      if t_ak not in tuva_buckets:
        tuva_buckets[t_ak] = {"keys": [], "props": cp}
      elif t_ak == atom["atom_key"]:
        tuva_buckets[t_ak]["props"] = cp
      tuva_buckets[t_ak]["keys"].append(atom["atom_key"])

    for t_ak in sorted(tuva_buckets.keys()):
      k_list = tuva_buckets[t_ak]["keys"]
      geom = tuva_geom_map[k_list[0]] if len(k_list) == 1 else self._cached_union(k_list, tuva_geom_map)
      if geom is None or geom.is_empty:
        continue
      cp = dict(tuva_buckets[t_ak]["props"])
      rp = geom.representative_point()
      cp["seat_lat"] = round(float(rp.y), self.precision)
      cp["seat_lon"] = round(float(rp.x), self.precision)
      tuva_out.append((cp, geom))

    # Return statement
    return twn_out, mng_out, tuva_out

  def _cached_union (self, arg1_keys, arg2_geom_map):
    """Compute and memoise a disjoint/planar union keyed by an immutable frozenset of atom keys.

    @param arg1_keys Sequence of atom key strings.
    @param arg2_geom_map Mapping atom_key -> Shapely geometry.
    @return Clean Shapely polygonal geometry or None.
    """
    # Convert from parameters
    geom_map = arg2_geom_map
    keys = frozenset(arg1_keys or [])

    if not keys:
      return None
    if keys in self.union_cache:
      return self.union_cache[keys]

    # Declare local instance variables.
    geoms = [geom_map[k] for k in sorted(keys) if k in geom_map and geom_map[k] is not None]
    merged = planar_topology_helpers._pointwise_snap(
      planar_topology_helpers._union_polygons(geoms, True),
      self.grid_size,
    ) if geoms else None
    self.union_cache[keys] = merged

    # Return statement
    return merged

  def _clean_ctamap_year (self, arg1_year):
    """Load, coverage-simplify, and globally DCEL-node CTAmap + northern outer borders across 2000..2026.

    @param arg1_year Snapshot integer year (2000..2026).
    @return List of (props_dict, cleaned_shapely_geom) tuples.
    """
    # Convert from parameters
    yr = int(arg1_year)

    if yr in self.ctamap_clean_by_year:
      return self.ctamap_clean_by_year[yr]

    # Declare local instance variables.
    base_clean = []
    combined = []
    combined_dcel = []
    contig_pairs = []
    dcel_in = []
    fmt_rows = []
    geom = None
    geom_sig = None
    gpkg_path = ""
    idx = 0
    mng_by_id = {}
    mng_dcel_map = {}
    mng_harm = []
    mng_raw = []
    modern_dir = path_helpers.resolve_path("input.gis.modern_dir", self.base_dir)
    noded = []
    p = {}
    prc_geom_by_uidx = {}
    prc_north = []
    prio_map = {"mng": 1, "prc": 2, "tuva": 0}
    props = {}
    raw_rows = []
    rp = None
    seam_sig = None
    simp_pairs = []
    tagged_fmt = []
    tuva_by_id = {}
    tuva_dcel_map = {}
    tuva_harm = []
    tuva_raw = []

    if yr == 2026:
      raw_rows = prc_annual_helpers.load_geojson_features(os.path.join(modern_dir, "prc_adm_3.geojson"))
      for props, geom in raw_rows:
        p = {
          "category": "sar" if str(props.get("gb_code") or "").startswith(("81", "82")) else (
            "municipality" if str(props.get("parent_adm1_gb") or "") in ("110000", "120000", "310000", "500000") else (
              "autonomous_region" if "Autonomous" in str(props.get("parent_adm1") or "") else "province"
            )
          ),
          "country": "People's Republic of China",
          "gb_code": str(props.get("gb_code") or ""),
          "name_ch": str(props.get("name_zh") or props.get("name_ch") or ""),
          "name_en": str(props.get("name_en") or ""),
          "occupied_by": "",
          "parent_adm1": str(props.get("parent_adm1") or ""),
          "parent_adm1_gb": str(props.get("parent_adm1_gb") or ""),
          "parent_adm1_zh": str(props.get("parent_adm1_zh") or ""),
          "parent_adm2": str(props.get("parent_adm2") or ""),
          "parent_adm2_gb": str(props.get("parent_adm2_gb") or ""),
          "parent_adm2_zh": str(props.get("parent_adm2_zh") or ""),
          "seat_lat": props.get("seat_lat"),
          "seat_lon": props.get("seat_lon"),
          "unit_id": str(props.get("modern_unit_id") or props.get("unit_id") or ""),
          "unit_type": str(props.get("unit_type") or "county"),
        }
        base_clean.append((p, geom))
      base_clean = self._strip_roc_fujian_islands(base_clean)
      self.year_outer_dcel[2026] = (
        {a["atom_key"]: a["geom"] for a in self.mng_atoms},
        {a["atom_key"]: a["geom"] for a in self.tuva_atoms},
      )
      self.ctamap_clean_by_year[2026] = base_clean
      return base_clean

    gpkg_path = os.path.join(self.ctamap_dir, f"T{yr}_county.gpkg")
    raw_rows = ctamap_io_helpers.read_ctamap_county_year(gpkg_path, self.raw_wkb_cache, self.precision)
    fmt_rows = self._strip_roc_fujian_islands(prc_annual_helpers.format_ctamap_year_units(raw_rows, yr, self.reforms_cfg))
    geom_sig = tuple((p.get("_wkb_hex"), p.get("parent_adm1")) for p, _ in fmt_rows)

    if geom_sig not in self.ctamap_dcel_by_sig:
      for idx, (props, geom) in enumerate(fmt_rows):
        p = dict(props)
        p["_uidx"] = idx
        tagged_fmt.append((p, geom))
      simp_pairs = planar_topology_helpers.simplify_and_clean_coverage(tagged_fmt, 0.002, self.grid_size, 0.05, 1e-4)
      contig_pairs, _ = planar_topology_helpers.enforce_adm1_contiguity(simp_pairs, "parent_adm1", 0.005, self.grid_size)

      prc_north = [(p, g) for p, g in contig_pairs if g.bounds[3] >= 40.5]
      seam_sig = tuple(sorted((str(p.get("gb_code") or ""), hashlib.blake2b(g.wkb, digest_size=10).digest()) for p, g in prc_north))
      if seam_sig not in self.northern_seam_cache:
        mng_raw = [({"_ak": a["atom_key"]}, a["geom"]) for a in self.mng_atoms]
        tuva_raw = [({"_ak": a["atom_key"]}, a["geom"]) for a in self.tuva_atoms]
        mng_harm, _ = planar_topology_helpers.harmonise_international_seams(prc_north, mng_raw, self.grid_size, 0.03)
        tuva_harm, _ = planar_topology_helpers.harmonise_international_seams(prc_north + mng_harm, tuva_raw, self.grid_size, 0.03)
        self.northern_seam_cache[seam_sig] = (
          {p["_ak"]: g for p, g in mng_harm},
          {p["_ak"]: g for p, g in tuva_harm},
        )
      mng_by_id, tuva_by_id = self.northern_seam_cache[seam_sig]

      dcel_in = []
      for p, g in contig_pairs:
        p["_src"] = "prc"
        dcel_in.append((p, g))
      for ak_m, gm_m in mng_by_id.items():
        dcel_in.append(({"_src": "mng", "_ak": ak_m}, gm_m))
      for ak_t, gm_t in tuva_by_id.items():
        dcel_in.append(({"_src": "tuva", "_ak": ak_t}, gm_t))

      noded = planar_topology_helpers.node_planar_coverage(
        dcel_in,
        self.grid_size,
        0.05,
        lambda p_it, g_it: (prio_map.get(p_it.get("_src"), 0), float(g_it.area)),
      )
      for p_it, g_it in noded:
        src_k = p_it.get("_src")
        if src_k == "prc":
          prc_geom_by_uidx[p_it["_uidx"]] = g_it
        elif src_k == "mng":
          mng_dcel_map[p_it["_ak"]] = g_it
        elif src_k == "tuva":
          tuva_dcel_map[p_it["_ak"]] = g_it
      self.ctamap_dcel_by_sig[geom_sig] = (prc_geom_by_uidx, mng_dcel_map, tuva_dcel_map)

    prc_geom_by_uidx, mng_dcel_map, tuva_dcel_map = self.ctamap_dcel_by_sig[geom_sig]
    self.year_outer_dcel[yr] = (mng_dcel_map, tuva_dcel_map)
    for idx, (props, _) in enumerate(fmt_rows):
      geom = prc_geom_by_uidx.get(idx)
      if geom is None or geom.is_empty:
        continue
      p = dict(props)
      rp = geom.representative_point()
      p["seat_lat"] = round(float(rp.y), self.precision)
      p["seat_lon"] = round(float(rp.x), self.precision)
      combined.append((p, geom))
    self.ctamap_clean_by_year[yr] = combined

    # Return statement
    return combined

  def _load_static_layers (self):
    """Load areacodes, T2000/1980 PRC bases, 1954-1958 Tusi cohorts, and modern Taiwan/Mongolia/Tuva atoms once."""
    if self.layers_loaded:
      return

    # Declare local instance variables.
    ac_res = path_helpers.resolve_provider_file(self.cfg, "modern_reference", "areacodes_result", self.base_dir)
    ac_json = path_helpers.resolve_provider_file(self.cfg, "modern_reference", "areacodes_codes", self.base_dir)
    ac_doc = ctamap_io_helpers.load_areacodes_lineage(ac_res, ac_json)
    active_2000 = set()
    attr_name = ""
    b80_buckets = {}
    cp = {}
    fname = ""
    gb_to_ak = {}
    geom = None
    geom_map = {}
    idx = 0
    modern_dir = path_helpers.resolve_path("input.gis.modern_dir", self.base_dir)
    offshore_geoms = []
    prefix = ""
    props = {}
    raw = []
    row_ak = ""
    target_list = []
    tusi_path = path_helpers.resolve_path("output.gis.tusi", self.base_dir)

    self.ac_index = prc_annual_helpers.build_areacodes_year_index(ac_doc)
    self.tusi_cohorts = prc_annual_helpers.load_active_tusi_cohorts(tusi_path, self.reforms_cfg, self.grid_size)

    for attr_name, fname, prefix in [
      ("twn_atoms", "twn_adm_3.geojson", "twn"),
      ("mng_atoms", "mng_adm_2.geojson", "mng"),
      ("tuva_atoms", "tuva_adm_2.geojson", "tuv"),
    ]:
      raw = prc_annual_helpers.load_geojson_features(os.path.join(modern_dir, fname))
      target_list = []
      for idx, (props, geom) in enumerate(raw):
        row = dict(props)
        row["atom_key"] = f"{prefix}_{idx}_{props.get('modern_unit_id') or idx}"
        row["geom"] = geom
        target_list.append(row)
      setattr(self, attr_name, target_list)

    offshore_geoms = []
    for atom in self.twn_atoms:
      if atom.get("roc_fujian_offshore"):
        offshore_geoms.append(atom["geom"])
      else:
        for pt in planar_topology_helpers._extract_polygons(atom["geom"]):
          if pt.centroid.x < 117.5 and pt.centroid.y < 21.5:
            offshore_geoms.append(pt)
    if offshore_geoms:
      self.roc_fujian_mask = unary_union(offshore_geoms).buffer(0.015)

    self.base_2000_clean = self._clean_ctamap_year(2000)
    active_2000 = {p["gb_code"] for p, _ in self.base_2000_clean if p.get("gb_code")}
    for idx, (props, geom) in enumerate(self.base_2000_clean):
      row_ak = f"b80_{idx}"
      geom_map[row_ak] = geom
      if props.get("gb_code"):
        gb_to_ak[props["gb_code"]] = row_ak

    for idx, (props, _) in enumerate(self.base_2000_clean):
      row_ak = f"b80_{idx}"
      cp = prc_annual_helpers.classify_1980_1999_mainland_unit(props, 1980, self.ac_index, self.reforms_cfg, active_2000)
      m_gb = str(cp.get("merge_gb") or "")
      t_ak = gb_to_ak.get(m_gb, row_ak) if m_gb else row_ak
      if t_ak not in b80_buckets:
        b80_buckets[t_ak] = {"keys": [], "props": cp}
      elif t_ak == row_ak:
        b80_buckets[t_ak]["props"] = cp
      b80_buckets[t_ak]["keys"].append(row_ak)

    self.base_1980_clean = []
    for t_ak in sorted(b80_buckets.keys()):
      k_list = b80_buckets[t_ak]["keys"]
      geom = geom_map[k_list[0]] if len(k_list) == 1 else self._cached_union(k_list, geom_map)
      if geom is not None and not geom.is_empty:
        self.base_1980_clean.append((t_ak, b80_buckets[t_ak]["props"], geom))

    self.layers_loaded = True

  def _normalise_adm3_props (self, arg1_feats, arg2_year):
    """Strip private keys and populate required adm_level and year fields for exported adm_3 features.

    @param arg1_feats List of (props_dict, geom) tuples.
    @param arg2_year Snapshot integer year.
    @return Clean list of (props_dict, geom) tuples.
    """
    # Convert from parameters
    feats = list(arg1_feats or [])
    yr = int(arg2_year)

    # Declare local instance variables.
    geom = None
    out = []
    props = {}
    p_out = {}

    for props, geom in feats:
      p_out = {
        "adm_level": 3,
        "category": str(props.get("category") or "province"),
        "country": str(props.get("country") or "People's Republic of China"),
        "gb_code": str(props.get("gb_code") or ""),
        "name_ch": str(props.get("name_ch") or props.get("name_zh") or ""),
        "name_en": str(props.get("name_en") or ""),
        "occupied_by": str(props.get("occupied_by") or ""),
        "parent_adm1": str(props.get("parent_adm1") or ""),
        "parent_adm1_zh": str(props.get("parent_adm1_zh") or ""),
        "parent_adm2": str(props.get("parent_adm2") or ""),
        "seat_lat": props.get("seat_lat"),
        "seat_lon": props.get("seat_lon"),
        "unit_id": str(props.get("unit_id") or props.get("modern_unit_id") or ""),
        "unit_type": str(props.get("unit_type") or "county"),
        "year": yr,
      }
      out.append((p_out, geom))

    # Return statement
    return out

  def _strip_roc_fujian_islands (self, arg1_rows):
    """Drop PRC nominal Kinmen claims and Matsu/Juguang/Wuqiu offshore islets duplicated by ROC Fujian layers.

    @param arg1_rows List of (props_dict, shapely_geom) tuples.
    @return Filtered list of (props_dict, shapely_geom) tuples.
    """
    # Convert from parameters
    rows = list(arg1_rows or [])

    # Declare local instance variables.
    cp = {}
    gb_code = ""
    geom = None
    kept_parts = []
    name_zh = ""
    out = []
    parts = []
    props = {}

    for props, geom in rows:
      if geom is None or geom.is_empty:
        continue
      gb_code = str(props.get("gb_code") or "").strip()
      name_zh = str(props.get("name_ch") or props.get("name_zh") or "").strip()
      if gb_code in ("350527", "352427") or name_zh == "金门县":
        continue
      if self.roc_fujian_mask is not None and (gb_code[:2] in ("35", "44") or str(props.get("parent_adm1_gb") or "") in ("350000", "440000") or str(props.get("parent_adm1") or "") in ("Fujian", "Guangdong")):
        if geom.intersects(self.roc_fujian_mask):
          parts = planar_topology_helpers._extract_polygons(geom)
          kept_parts = [pt for pt in parts if not (pt.area < 0.05 and pt.intersects(self.roc_fujian_mask))]
          if not kept_parts:
            continue
          if len(kept_parts) != len(parts):
            geom = kept_parts[0] if len(kept_parts) == 1 else MultiPolygon(kept_parts)
            cp = dict(props)
            cp["_wkb_hex"] = hashlib.blake2b(geom.wkb, digest_size=16).hexdigest()
            props = cp
      out.append((props, geom))

    # Return statement
    return out

  def build_all_years (self, arg1_start_year=1954, arg2_end_year=2026):
    """Generate and export all 219 annual PRC/modern GeoJSON snapshots across 1954..2026.

    @param arg1_start_year Inclusive start year (default 1954).
    @param arg2_end_year Inclusive end year (default 2026).
    @return Summary dict with file counts and built year span.
    """
    # Convert from parameters
    end_yr = int(arg2_end_year)
    start_yr = int(arg1_start_year)

    # Declare local instance variables.
    files_written = 0
    res = {}
    yr = 1954

    self._load_static_layers()
    for yr in range(start_yr, end_yr + 1):
      res = self.build_year(yr)
      files_written += 3
      if yr in (1954, 1959, 1966, 1970, 1980, 1998, 2000, 2011, 2025, 2026):
        print(f"  [prc-annual] {yr}: adm_1={res['adm1']}, adm_2={res['adm2']}, adm_3={res['adm3']}", flush=True)

    # Return statement
    return {"end_year": end_yr, "files_written": files_written, "out_dir": self.out_dir, "start_year": start_yr}

  def build_year (self, arg1_year):
    """Build and export prc_adm_1_<year>, prc_adm_2_<year>, and prc_adm_3_<year> GeoJSONs.

    @param arg1_year Snapshot year in 1954..2026.
    @return Dict with feature counts for each exported level.
    """
    # Convert from parameters
    yr = int(arg1_year)

    self._load_static_layers()

    # Declare local instance variables.
    adm1_all = []
    adm2_all = []
    adm3_all = []
    mng_adm1 = []
    mng_adm2 = []
    mng_adm3 = []
    n1 = 0
    n2 = 0
    n3 = 0
    outer_meta = None
    prc_adm1 = []
    prc_adm2 = []
    prc_adm3 = []
    prc_raw = []
    tuva_adm1 = []
    tuva_adm2 = []
    tuva_adm3 = []
    twn_adm1 = []
    twn_adm2 = []
    twn_adm3 = []

    if yr <= 1979:
      prc_raw = self._build_mainland_1954_1979(yr)
    elif yr <= 1999:
      prc_raw = self._build_mainland_1980_1999(yr)
    else:
      prc_raw = self._clean_ctamap_year(yr)

    prc_adm3 = self._normalise_adm3_props(prc_raw, yr)
    twn_adm3, mng_adm3, tuva_adm3 = self._build_outer_layers(yr, prc_adm3)
    twn_adm3 = self._normalise_adm3_props(twn_adm3, yr)
    mng_adm3 = self._normalise_adm3_props(mng_adm3, yr)
    tuva_adm3 = self._normalise_adm3_props(tuva_adm3, yr)

    prc_adm2 = self._aggregate_region_cached(
      "prc", 2, prc_adm3,
      lambda p: ("tusi", p["unit_id"]) if p["category"] == "tusi" else ("p2", p["country"], p["parent_adm1"], p["parent_adm2"]),
      lambda k, ms: {
        "category": ms[0]["category"], "country": ms[0]["country"],
        "gb_code": ms[0]["gb_code"][:4] + "00" if (k[0] != "tusi" and len(ms[0]["gb_code"]) == 6) else ms[0]["gb_code"],
        "name_ch": ms[0]["name_ch"] if k[0] == "tusi" else (ms[0]["parent_adm2"] or ms[0]["parent_adm1"]),
        "name_en": ms[0]["name_en"] if k[0] == "tusi" else (ms[0]["parent_adm2"] or ms[0]["parent_adm1"]),
        "occupied_by": "", "parent_adm1": ms[0]["parent_adm1"], "parent_adm1_zh": ms[0]["parent_adm1_zh"], "parent_adm2": ms[0]["parent_adm2"],
        "unit_id": ms[0]["unit_id"] if k[0] == "tusi" else f"prc_{yr}_adm2_{gis_helpers.slugify_snake(ms[0]['parent_adm1'] + '_' + ms[0]['parent_adm2'])}",
        "unit_type": "tusi" if k[0] == "tusi" else "prefecture_level_unit", "year": yr,
      },
    )
    prc_adm1 = self._aggregate_region_cached(
      "prc", 1, prc_adm3,
      lambda p: ("tusi", p["country"], p["unit_id"]) if p["category"] == "tusi" else ("p1", p["country"], p["parent_adm1"]),
      lambda k, ms: {
        "category": ms[0]["category"], "country": ms[0]["country"],
        "gb_code": ms[0]["gb_code"] if k[0] == "tusi" else (ms[0]["gb_code"][:2] + "0000" if len(ms[0]["gb_code"]) == 6 else ""),
        "name_ch": ms[0]["name_ch"] if k[0] == "tusi" else (ms[0]["parent_adm1_zh"] or ms[0]["parent_adm1"]),
        "name_en": ms[0]["name_en"] if k[0] == "tusi" else ms[0]["parent_adm1"],
        "occupied_by": "", "parent_adm1": ms[0]["parent_adm1"], "parent_adm1_zh": ms[0]["parent_adm1_zh"], "parent_adm2": ms[0]["parent_adm2"] if k[0] == "tusi" else "",
        "unit_id": ms[0]["unit_id"] if k[0] == "tusi" else f"prc_{yr}_adm1_{gis_helpers.slugify_snake(ms[0]['parent_adm1'])}",
        "unit_type": "tusi" if k[0] == "tusi" else ("colony" if ms[0]["category"] == "colony" else "province_level_unit"), "year": yr,
      },
    )

    outer_meta = lambda r_uid, lvl, feats_in, r_tag, zh_fn, ut_fn: self._aggregate_region_cached(
      r_tag, lvl, feats_in,
      lambda p: (p["country"], p["parent_adm1"], p["parent_adm2"]) if lvl == 2 else (p["country"], p["parent_adm1"]),
      lambda k, ms: {
        "category": ms[0]["category"], "country": ms[0]["country"], "gb_code": "",
        "name_ch": ms[0]["parent_adm2"] if lvl == 2 else zh_fn(ms[0]),
        "name_en": ms[0]["parent_adm2"] if lvl == 2 else ms[0]["parent_adm1"],
        "occupied_by": "", "parent_adm1": ms[0]["parent_adm1"],
        "parent_adm1_zh": "" if r_tag == "mongolia" else ms[0]["parent_adm1_zh"],
        "parent_adm2": ms[0]["parent_adm2"] if lvl == 2 else "",
        "unit_id": f"{r_uid}_{yr}_adm{lvl}_{gis_helpers.slugify_snake((ms[0]['parent_adm1'] + '_' + ms[0]['parent_adm2']) if lvl == 2 else ms[0]['parent_adm1'])}",
        "unit_type": ut_fn(ms[0]) if lvl == 2 else ms[0]["category"], "year": yr,
      },
    )
    twn_adm2 = outer_meta("taiwan", 2, twn_adm3, "taiwan", lambda m: m["parent_adm1_zh"] or m["parent_adm1"], lambda m: "county")
    twn_adm1 = outer_meta("taiwan", 1, twn_adm3, "taiwan", lambda m: m["parent_adm1_zh"] or m["parent_adm1"], lambda m: "county")
    mng_adm2 = outer_meta("mongolia", 2, mng_adm3, "mongolia", lambda m: m["parent_adm1"], lambda m: m["unit_type"])
    mng_adm1 = outer_meta("mongolia", 1, mng_adm3, "mongolia", lambda m: m["parent_adm1"], lambda m: m["unit_type"])
    tuva_adm2 = [({**p, "adm_level": 2}, g) for p, g in tuva_adm3]
    tuva_adm1 = outer_meta("tuva_republic", 1, tuva_adm3, "tuva", lambda m: m["parent_adm1_zh"] or m["parent_adm1"], lambda m: m["category"])

    adm1_all = prc_adm1 + twn_adm1 + mng_adm1 + tuva_adm1
    adm2_all = prc_adm2 + twn_adm2 + mng_adm2 + tuva_adm2
    adm3_all = prc_adm3 + twn_adm3 + mng_adm3 + tuva_adm3

    n1 = gis_helpers.write_geojson(os.path.join(self.out_dir, f"prc_adm_1_{yr}.geojson"), adm1_all, self.precision)
    n2 = gis_helpers.write_geojson(os.path.join(self.out_dir, f"prc_adm_2_{yr}.geojson"), adm2_all, self.precision)
    n3 = gis_helpers.write_geojson(os.path.join(self.out_dir, f"prc_adm_3_{yr}.geojson"), adm3_all, self.precision)

    # Return statement
    return {"adm1": n1, "adm2": n2, "adm3": n3, "year": yr}
