"""Builds continuous 1954-2026 annual adm_1/adm_2/adm_3 GeoJSON snapshots for PRC, Taiwan, Mongolia, and Tuva."""

import os
import sys

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from shapely.ops import unary_union
from shapely.strtree import STRtree

from helpers import gis_helpers, path_helpers, prc_annual_helpers


class PrcAnnualAdminBuilder:
  """Constructs 219 watertight annual administrative GeoJSONs covering 1954-2026 into output/gis/prc_annual_1954_2026/."""

  def __init__ (self, arg1_cfg, arg2_base_dir=None):
    """Initialise annual builder configuration, file paths, and union geometry caches.

    @param arg1_cfg Loaded data_sources.json5 dict.
    @param arg2_base_dir Optional workspace root directory.
    """
    # Convert from parameters
    base_dir = str(arg2_base_dir or (arg1_cfg or {}).get("_base_dir") or path_helpers.get_project_root())
    cfg = arg1_cfg

    # Declare local instance variables.
    self.adm_annual_dir = path_helpers.resolve_path("output.gis.adm_annual_dir", base_dir)
    self.base_dir = base_dir
    self.cfg = cfg
    self.china_1953_atoms = []
    self.layers_loaded = False
    self.mng_atoms = []
    self.out_dir = path_helpers.resolve_path("output.gis.prc_annual_dir", self.base_dir)
    self.prc_2026_atoms = []
    self.precision = int(cfg.get("coordinate_precision", 5))
    self.reforms_cfg = gis_helpers.load_json5(path_helpers.resolve_path("common.prc_admin_reforms", self.base_dir)) or {}
    self.tuva_atoms = []
    self.twn_atoms = []
    self.union_cache = {}
    os.makedirs(self.out_dir, exist_ok=True)

  def _annotate_1953_atoms (self, arg1_feats_1953, arg2_prc_feats):
    """Tag 1953 Mainland/Tusi/HK/Macau atoms with overlapping 1990 and 2026 GB/T 2260 codes.

    @param arg1_feats_1953 Features loaded from adm_3_1953.geojson.
    @param arg2_prc_feats Features loaded from prc_adm_3.geojson.
    @return List of annotated 1953 atom dicts with geom and identity keys.
    """
    # Convert from parameters
    feats_1953 = list(arg1_feats_1953 or [])
    prc_feats = list(arg2_prc_feats or [])

    # Declare local instance variables.
    atoms = []
    prc_geoms = [g for _, g in prc_feats]
    prc_props = [p for p, _ in prc_feats]
    tree = STRtree(prc_geoms) if prc_geoms else None

    for idx, (props, geom) in enumerate(feats_1953):
      c_str = str(props.get("country") or "")
      if c_str == "Republic of China" or "Mongol" in c_str or "Tuva" in c_str or "USSR" in c_str:
        continue
      gb26 = ""
      gb90 = ""
      if tree is not None:
        rp = geom.representative_point()
        hits = tree.query(rp)
        best_i = None
        for h in hits:
          if prc_geoms[int(h)].contains(rp):
            best_i = int(h)
            break
        if best_i is None:
          best_area = 0.0
          for h in tree.query(geom):
            cand = prc_geoms[int(h)]
            if cand.intersects(geom):
              area = cand.intersection(geom).area
              if area > best_area:
                best_area = area
                best_i = int(h)
        if best_i is not None:
          mp = prc_props[best_i]
          gb26 = str(mp.get("gb_code") or "")
          snap90 = mp.get("unit_1990s_snapshot") or {}
          gb90 = str(snap90.get("gb_1990") or snap90.get("gb_code") or gb26)

      uid = str(props.get("unit_id") or f"c53_{idx}")
      rp = geom.representative_point()
      atoms.append({
        "atom_key": f"c53_{idx}_{uid}",
        "category": str(props.get("category") or "province"),
        "country": c_str,
        "gb_1990": gb90,
        "gb_2026": gb26,
        "geom": geom,
        "name_ch": str(props.get("name_ch") or ""),
        "name_en": str(props.get("name_en") or ""),
        "parent_adm1": str(props.get("parent_adm1") or ""),
        "parent_adm2": str(props.get("parent_adm2") or ""),
        "seat_lat": props.get("seat_lat") if props.get("seat_lat") is not None else round(float(rp.y), self.precision),
        "seat_lon": props.get("seat_lon") if props.get("seat_lon") is not None else round(float(rp.x), self.precision),
        "unit_id": uid,
      })

    # Return statement
    return atoms

  def _assemble_layer_from_buckets (self, arg1_buckets, arg2_geom_map, arg3_adm_level, arg4_year):
    """Union bucket atom keys via cache and construct clean feature tuples for one layer.

    @param arg1_buckets Ordered dict key_tuple -> {"props": dict, "keys": list[str]}.
    @param arg2_geom_map Mapping atom_key -> Shapely geometry.
    @param arg3_adm_level Administrative level (1, 2, or 3).
    @param arg4_year Integer snapshot year.
    @return List of (props_dict, Shapely_geometry) tuples.
    """
    # Convert from parameters
    adm_lvl = int(arg3_adm_level)
    buckets = dict(arg1_buckets or {})
    geom_map = arg2_geom_map
    yr = int(arg4_year)

    # Declare local instance variables.
    out_feats = []

    for _, bucket in sorted(buckets.items(), key=lambda x: str(x[0])):
      k_list = bucket["keys"]
      if not k_list:
        continue
      u_geom = self._cached_union(k_list, geom_map) if len(k_list) > 1 else geom_map.get(k_list[0])
      if u_geom is None or u_geom.is_empty:
        continue
      out_props = dict(bucket["props"])
      out_props["adm_level"] = adm_lvl
      out_props["year"] = yr
      out_feats.append((out_props, u_geom))

    # Return statement
    return out_feats

  def _build_epoch1_1954_1979 (self, arg1_year, arg2_adm1_b, arg3_adm2_b, arg4_adm3_b, arg5_geom_map):
    """Classify and bucket 1953 China/HK/Macau/Tusi atoms for a year in 1954..1979.

    @param arg1_year Snapshot year in 1954..1979.
    @param arg2_adm1_b Mutable adm_1 bucket dict.
    @param arg3_adm2_b Mutable adm_2 bucket dict.
    @param arg4_adm3_b Mutable adm_3 bucket dict.
    @param arg5_geom_map Mutable atom_key -> Shapely geom map.
    """
    # Convert from parameters
    adm1_b = arg2_adm1_b
    adm2_b = arg3_adm2_b
    adm3_b = arg4_adm3_b
    geom_map = arg5_geom_map
    yr = int(arg1_year)

    for atom in self.china_1953_atoms:
      ak = atom["atom_key"]
      geom_map[ak] = atom["geom"]
      cp = prc_annual_helpers.classify_1954_1979_china_atom(atom, yr, self.reforms_cfg)
      adm3_b[("c", ak)] = {"keys": [ak], "props": cp}

      is_tusi = cp["category"] == "tusi"
      if is_tusi:
        p1_key = ("c_tusi", cp["country"], atom["unit_id"])
        p1_props = {
          "category": "tusi",
          "country": cp["country"],
          "gb_code": cp["gb_code"],
          "name_ch": cp["name_ch"],
          "name_en": cp["name_en"],
          "occupied_by": "",
          "parent_adm1": cp["parent_adm1"],
          "parent_adm2": cp["parent_adm2"],
          "unit_id": cp["unit_id"],
          "unit_type": "tusi",
        }
      else:
        p1_meta = prc_annual_helpers.build_1954_1979_prov_meta(cp["parent_adm1"], yr, self.reforms_cfg)
        p1_key = ("c_adm1", cp["country"], cp["parent_adm1"])
        p1_props = {
          "category": p1_meta["category"],
          "country": cp["country"],
          "gb_code": cp["gb_code"][:2] + "0000" if len(cp["gb_code"]) == 6 else "",
          "name_ch": cp["parent_adm1_zh"] or cp["parent_adm1"],
          "name_en": cp["parent_adm1"],
          "occupied_by": "",
          "parent_adm1": cp["parent_adm1"],
          "parent_adm2": "",
          "unit_id": f"prc_{yr}_adm1_{gis_helpers.slugify_snake(cp['parent_adm1'])}",
          "unit_type": "province_level_unit" if p1_meta["category"] != "colony" else "colony",
        }
      adm1_b.setdefault(p1_key, {"keys": [], "props": p1_props})["keys"].append(ak)

      p2_key = ("c_tusi2", atom["unit_id"]) if is_tusi else ("c_adm2", cp["country"], cp["parent_adm1"], cp["parent_adm2"])
      p2_props = {
        "category": cp["category"],
        "country": cp["country"],
        "gb_code": cp["gb_code"][:4] + "00" if (not is_tusi and len(cp["gb_code"]) == 6) else cp["gb_code"],
        "name_ch": cp["name_ch"] if is_tusi else (cp["parent_adm2"] or cp["parent_adm1"]),
        "name_en": cp["name_en"] if is_tusi else (cp["parent_adm2"] or cp["parent_adm1"]),
        "occupied_by": "",
        "parent_adm1": cp["parent_adm1"],
        "parent_adm2": cp["parent_adm2"],
        "unit_id": cp["unit_id"] if is_tusi else f"prc_{yr}_adm2_{gis_helpers.slugify_snake(cp['parent_adm1'] + '_' + cp['parent_adm2'])}",
        "unit_type": "tusi" if is_tusi else "prefecture_level_unit",
      }
      adm2_b.setdefault(p2_key, {"keys": [], "props": p2_props})["keys"].append(ak)

  def _build_epoch23_1980_2026 (self, arg1_year, arg2_adm1_b, arg3_adm2_b, arg4_adm3_b, arg5_geom_map):
    """Classify and bucket modern PRC atoms for a year in 1980..2026 including pre-carving merges.

    @param arg1_year Snapshot year in 1980..2026.
    @param arg2_adm1_b Mutable adm_1 bucket dict.
    @param arg3_adm2_b Mutable adm_2 bucket dict.
    @param arg4_adm3_b Mutable adm_3 bucket dict.
    @param arg5_geom_map Mutable atom_key -> Shapely geom map.
    """
    # Convert from parameters
    adm1_b = arg2_adm1_b
    adm2_b = arg3_adm2_b
    adm3_b = arg4_adm3_b
    geom_map = arg5_geom_map
    yr = int(arg1_year)

    # Declare local instance variables.
    gb_to_atom = {a["gb_code"]: a for a in self.prc_2026_atoms if a.get("gb_code")}
    gb_to_atom_key = {a["gb_code"]: a["atom_key"] for a in self.prc_2026_atoms if a.get("gb_code")}

    for atom in self.prc_2026_atoms:
      ak = atom["atom_key"]
      geom_map[ak] = atom["geom"]
      cp = prc_annual_helpers.classify_1980_2026_prc_atom(atom, yr, self.reforms_cfg)
      m_gb = cp.get("merge_gb") or ""
      target_ak = gb_to_atom_key.get(m_gb, ak) if m_gb else ak

      if target_ak not in adm3_b:
        adm3_b[target_ak] = {"keys": [], "props": {k: v for k, v in cp.items() if k != "merge_gb"}}
      elif target_ak == ak:
        # Host unit properties win over merged carved child
        adm3_b[target_ak]["props"] = {k: v for k, v in cp.items() if k != "merge_gb"}
      adm3_b[target_ak]["keys"].append(ak)

      grp_cp = prc_annual_helpers.classify_1980_2026_prc_atom(gb_to_atom[m_gb], yr, self.reforms_cfg) if (m_gb and m_gb in gb_to_atom) else cp
      p1_key = ("c_adm1", grp_cp["country"], grp_cp["parent_adm1"])
      if p1_key not in adm1_b:
        adm1_b[p1_key] = {
          "keys": [],
          "props": {
            "category": grp_cp["category"],
            "country": grp_cp["country"],
            "gb_code": grp_cp["gb_code"][:2] + "0000" if len(grp_cp["gb_code"]) == 6 else "",
            "name_ch": grp_cp["parent_adm1_zh"] or grp_cp["parent_adm1"],
            "name_en": grp_cp["parent_adm1"],
            "occupied_by": "",
            "parent_adm1": grp_cp["parent_adm1"],
            "parent_adm2": "",
            "unit_id": f"prc_{yr}_adm1_{gis_helpers.slugify_snake(grp_cp['parent_adm1'])}",
            "unit_type": "province_level_unit" if grp_cp["category"] != "colony" else "colony",
          },
        }
      adm1_b[p1_key]["keys"].append(ak)

      p2_key = ("c_adm2", grp_cp["country"], grp_cp["parent_adm1"], grp_cp["parent_adm2"])
      if p2_key not in adm2_b:
        adm2_b[p2_key] = {
          "keys": [],
          "props": {
            "category": grp_cp["category"],
            "country": grp_cp["country"],
            "gb_code": grp_cp["gb_code"][:4] + "00" if len(grp_cp["gb_code"]) == 6 else "",
            "name_ch": grp_cp["parent_adm2_zh"] or grp_cp["parent_adm2"],
            "name_en": grp_cp["parent_adm2"],
            "occupied_by": "",
            "parent_adm1": grp_cp["parent_adm1"],
            "parent_adm2": grp_cp["parent_adm2"],
            "unit_id": f"prc_{yr}_adm2_{gis_helpers.slugify_snake(grp_cp['parent_adm1'] + '_' + grp_cp['parent_adm2'])}",
            "unit_type": "prefecture_level_unit",
          },
        }
      adm2_b[p2_key]["keys"].append(ak)

  def _build_outer_1954_2026 (self, arg1_year, arg2_adm1_b, arg3_adm2_b, arg4_adm3_b, arg5_geom_map):
    """Classify and bucket Taiwan, Mongolia, and Tuva atoms across 1954..2026.

    @param arg1_year Snapshot year in 1954..2026.
    @param arg2_adm1_b Mutable adm_1 bucket dict.
    @param arg3_adm2_b Mutable adm_2 bucket dict.
    @param arg4_adm3_b Mutable adm_3 bucket dict.
    @param arg5_geom_map Mutable atom_key -> Shapely geom map.
    """
    # Convert from parameters
    adm1_b = arg2_adm1_b
    adm2_b = arg3_adm2_b
    adm3_b = arg4_adm3_b
    geom_map = arg5_geom_map
    yr = int(arg1_year)

    # Declare local instance variables.
    region_groups = [("taiwan", self.twn_atoms), ("mongolia", self.mng_atoms), ("tuva_republic", self.tuva_atoms)]

    for region_key, atoms in region_groups:
      by_name = {a["name_en"]: a["atom_key"] for a in atoms}
      for atom in atoms:
        ak = atom["atom_key"]
        geom_map[ak] = atom["geom"]
        cp = prc_annual_helpers.classify_1954_2026_outer_atom(region_key, atom, yr, self.reforms_cfg)
        m_name = cp.get("merge_target_name") or ""
        t_ak = by_name.get(m_name, ak) if m_name else ak

        if t_ak not in adm3_b:
          adm3_b[t_ak] = {"keys": [], "props": {k: v for k, v in cp.items() if k != "merge_target_name"}}
        elif t_ak == ak:
          adm3_b[t_ak]["props"] = {k: v for k, v in cp.items() if k != "merge_target_name"}
        adm3_b[t_ak]["keys"].append(ak)

        p1_key = ("o_adm1", region_key, cp["country"], cp["parent_adm1"])
        if p1_key not in adm1_b:
          adm1_b[p1_key] = {
            "keys": [],
            "props": {
              "category": cp["category"],
              "country": cp["country"],
              "gb_code": "",
              "name_ch": cp["parent_adm1_zh"] or cp["parent_adm1"],
              "name_en": cp["parent_adm1"],
              "occupied_by": "",
              "parent_adm1": cp["parent_adm1"],
              "parent_adm2": "",
              "unit_id": f"{region_key}_{yr}_adm1_{gis_helpers.slugify_snake(cp['parent_adm1'])}",
              "unit_type": cp["category"],
            },
          }
        adm1_b[p1_key]["keys"].append(ak)

        p2_key = ("o_adm2", region_key, cp["country"], cp["parent_adm1"], cp["parent_adm2"])
        if p2_key not in adm2_b:
          adm2_b[p2_key] = {
            "keys": [],
            "props": {
              "category": cp["category"],
              "country": cp["country"],
              "gb_code": "",
              "name_ch": cp["parent_adm2"],
              "name_en": cp["parent_adm2"],
              "occupied_by": "",
              "parent_adm1": cp["parent_adm1"],
              "parent_adm2": cp["parent_adm2"],
              "unit_id": f"{region_key}_{yr}_adm2_{gis_helpers.slugify_snake(cp['parent_adm1'] + '_' + cp['parent_adm2'])}",
              "unit_type": "county" if region_key == "taiwan" else cp["unit_type"],
            },
          }
        adm2_b[p2_key]["keys"].append(ak)

  def _cached_union (self, arg1_keys, arg2_geom_map):
    """Compute and memoise a clean unary_union keyed by an immutable frozenset of atom keys.

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
    merged = gis_helpers.clean_polygonal_geometry(unary_union(geoms)) if geoms else None
    self.union_cache[keys] = merged

    # Return statement
    return merged

  def _load_static_layers (self):
    """Load 1953 Mainland atoms and modern PRC, Taiwan, Mongolia, and Tuva layers once."""
    if self.layers_loaded:
      return

    # Declare local instance variables.
    modern_dir = path_helpers.resolve_path("input.gis.modern_dir", self.base_dir)
    feats_1953 = prc_annual_helpers.load_geojson_features(os.path.join(self.adm_annual_dir, "adm_3_1953.geojson"))
    prc_raw = prc_annual_helpers.load_geojson_features(os.path.join(modern_dir, "prc_adm_3.geojson"))

    self.china_1953_atoms = self._annotate_1953_atoms(feats_1953, prc_raw)

    self.prc_2026_atoms = []
    for idx, (props, geom) in enumerate(prc_raw):
      row = dict(props)
      row["atom_key"] = f"p26_{idx}_{props.get('modern_unit_id') or props.get('gb_code') or idx}"
      row["geom"] = geom
      self.prc_2026_atoms.append(row)

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

    self.layers_loaded = True

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

    self._load_static_layers()
    for yr in range(start_yr, end_yr + 1):
      res = self.build_year(yr)
      files_written += 3
      if yr in (1954, 1966, 1970, 1980, 1998, 2015, 2026):
        print(f"  [prc-annual] {yr}: adm_1={res['adm1']}, adm_2={res['adm2']}, adm_3={res['adm3']}")

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
    adm1_b = {}
    adm2_b = {}
    adm3_b = {}
    geom_map = {}

    if yr <= 1979:
      self._build_epoch1_1954_1979(yr, adm1_b, adm2_b, adm3_b, geom_map)
    else:
      self._build_epoch23_1980_2026(yr, adm1_b, adm2_b, adm3_b, geom_map)
    self._build_outer_1954_2026(yr, adm1_b, adm2_b, adm3_b, geom_map)

    f1 = self._assemble_layer_from_buckets(adm1_b, geom_map, 1, yr)
    f2 = self._assemble_layer_from_buckets(adm2_b, geom_map, 2, yr)
    f3 = self._assemble_layer_from_buckets(adm3_b, geom_map, 3, yr)

    c1_feats, c2_feats, c3_feats = prc_annual_helpers.clean_and_populate_year_layers(f1, f2, f3, self.precision)
    n1 = gis_helpers.write_geojson(os.path.join(self.out_dir, f"prc_adm_1_{yr}.geojson"), c1_feats, self.precision)
    n2 = gis_helpers.write_geojson(os.path.join(self.out_dir, f"prc_adm_2_{yr}.geojson"), c2_feats, self.precision)
    n3 = gis_helpers.write_geojson(os.path.join(self.out_dir, f"prc_adm_3_{yr}.geojson"), c3_feats, self.precision)

    # Return statement
    return {"adm1": n1, "adm2": n2, "adm3": n3, "year": yr}
