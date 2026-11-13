"""Step 3 helpers for Sino-Japanese War seat-level occupation and connected-component topology."""

from collections import Counter
from shapely import STRtree
from shapely.geometry import LineString, box
from shapely.ops import unary_union
from helpers import gis_helpers


def _build_supply_root_index (arg1_builder):
  """Precompute indexed outer coastline and international border segments once per builder instance.

  @param arg1_builder AnnualAdminBuilder instance.
  @return Dict containing outer_cache dict and STRtree outer_tree over short border LineStrings.
  """
  # Convert from parameters
  builder = arg1_builder

  # Declare local instance variables.
  all_geoms = []
  cache = getattr(builder, "_supply_root_cache", None)
  outer_tree = None
  segments = []
  total_land = None

  if cache is not None:
    return cache

  for a in builder.china_atoms:
    if a.get("geom") is not None and not a["geom"].is_empty:
      all_geoms.append(a["geom"])
  for tg in builder.tusi_geoms.values():
    if tg.get("geom") is not None and not tg["geom"].is_empty:
      all_geoms.append(tg["geom"])
  for grp in (builder.mng_soums, builder.tuva_kozhuuns, builder.twn_counties):
    for item in grp:
      if item.get("geom") is not None and not item["geom"].is_empty:
        all_geoms.append(item["geom"])

  total_land = unary_union(all_geoms) if all_geoms else None
  if total_land is not None:
    polys = [total_land] if total_land.geom_type == "Polygon" else list(total_land.geoms)
    for poly in polys:
      if poly.area <= 1e-6:
        continue
      coords = list(poly.exterior.coords)
      step = 64
      for k in range(0, max(1, len(coords) - 1), step):
        seg_coords = coords[k:k + step + 1]
        if len(seg_coords) >= 2:
          segments.append(LineString(seg_coords))
  outer_tree = STRtree(segments) if segments else None
  cache = {"outer_cache": {}, "outer_tree": outer_tree}
  builder._supply_root_cache = cache

  # Return statement
  return cache


def _carve_single_enclave (arg1_builder, arg2_geom, arg3_clip, arg4_atom_id, arg5_l1, arg6_l2, arg7_ch, arg8_en, arg9_uid, arg10_gb, arg11_extra):
  """Carve an enclave geometry out of a host county polygon and append it to builder.china_atoms.

  @param arg1_builder AnnualAdminBuilder instance.
  @param arg2_geom Host Shapely polygon/multipolygon.
  @param arg3_clip Enclave clip Shapely polygon/multipolygon.
  @param arg4_atom_id Atomic ID string.
  @param arg5_l1 Parent ADM-1 name.
  @param arg6_l2 Parent ADM-2 name.
  @param arg7_ch Chinese enclave name.
  @param arg8_en English enclave name.
  @param arg9_uid Original CHGIS unit ID.
  @param arg10_gb Reference GB code string.
  @param arg11_extra Optional extra metadata dict.
  @return Remaining host Shapely geometry after subtraction.
  """
  # Convert from parameters
  atom_id = arg4_atom_id
  builder = arg1_builder
  clip = arg3_clip
  extra = dict(arg11_extra or {})
  gb = arg10_gb
  geom = arg2_geom
  l1 = arg5_l1
  l2 = arg6_l2
  name_ch = arg7_ch
  name_en = arg8_en
  uid = arg9_uid

  if clip is None or clip.is_empty or not geom.intersects(clip):
    return geom

  # Declare local instance variables.
  part = gis_helpers.clean_polygonal_geometry(geom.intersection(clip))
  rem = gis_helpers.clean_polygonal_geometry(geom.difference(clip))

  if part is not None and part.area > 0.0002:
    pg, pd = builder._cache_geom(part)
    if pg is not None:
      rp = pg.representative_point()
      extra["seat_lat"] = round(float(rp.y), builder.precision)
      extra["seat_lon"] = round(float(rp.x), builder.precision)
      builder._append_china_atom(atom_id, pd, pg, l1, l2, name_ch, name_en, uid, gb, name_ch, name_en, extra)

  # Return statement
  return rem


def _collect_node_records (arg1_classified_atoms, arg2_atom_geom_map, arg3_resolved_tusis, arg4_supply_cache):
  """Build unified node list covering mainland China atoms and mainland Feudatories.

  @param arg1_classified_atoms Mutable list of classified atom records.
  @param arg2_atom_geom_map Mapping from atom key to Shapely Polygon/MultiPolygon.
  @param arg3_resolved_tusis Mutable list of resolved Feudatory dicts.
  @param arg4_supply_cache Cached dict holding STRtree outer_tree.
  @return List of node metadata dicts indexed 0..N-1.
  """
  # Convert from parameters
  atom_geom_map = arg2_atom_geom_map
  classified_atoms = arg1_classified_atoms
  resolved_tusis = arg3_resolved_tusis
  supply_cache = arg4_supply_cache

  # Declare local instance variables.
  geoms = []
  nodes = []
  outer_hits = set()
  outer_tree = supply_cache.get("outer_tree")

  for idx, rec in enumerate(classified_atoms):
    key = rec[0]
    if not key.startswith("ch_"):
      continue
    geom = atom_geom_map.get(key)
    if geom is None or geom.is_empty:
      continue
    rp = geom.representative_point()
    geoms.append(geom)
    nodes.append({
      "adm1": rec[2],
      "area": float(geom.area),
      "country": rec[6],
      "geom": geom,
      "idx": idx,
      "kind": "atom",
      "lat": float(rp.y),
      "lon": float(rp.x),
      "occ": rec[7],
      "on_outer": False,
    })

  for idx, trec in enumerate(resolved_tusis):
    if trec["country"] in ("Bhutan", "British India", "India"):
      continue
    geom = trec["tg"].get("geom")
    if geom is None or geom.is_empty:
      continue
    rp = geom.representative_point()
    geoms.append(geom)
    nodes.append({
      "adm1": trec["adm1"],
      "area": float(geom.area),
      "country": trec["country"],
      "geom": geom,
      "idx": idx,
      "kind": "tusi",
      "lat": float(rp.y),
      "lon": float(rp.x),
      "occ": trec["occ"],
      "on_outer": False,
    })

  if outer_tree is not None and geoms:
    pairs = outer_tree.query(geoms, predicate="dwithin", distance=0.025)
    outer_hits = {int(v) for v in pairs[0]}
    for node_idx in outer_hits:
      nodes[node_idx]["on_outer"] = True

  # Return statement
  return nodes


def _is_valid_occupied_root (arg1_node, arg2_year):
  """Check whether a node borders an active Japanese maritime or overland supply root in arg2_year."""
  # Convert from parameters
  node = arg1_node
  year = int(arg2_year)

  # Declare local instance variables.
  lat = node["lat"]
  lon = node["lon"]

  if not node["on_outer"]:
    return False
  if (lon >= 107.3 and lat <= 41.8) or (lon >= 123.8 and lat >= 39.7):
    return True
  if year in (1943, 1944) and lon <= 99.2 and lat <= 26.2:
    return True
  if year == 1945 and 105.5 <= lon <= 108.8 and lat <= 23.2:
    return True

  # Return statement
  return False


def _promote_hole_component (arg1_comp, arg2_nodes, arg3_adj, arg4_classified_atoms, arg5_resolved_tusis, arg6_year):
  """Promote an enclosed interior unoccupied component to match its dominant occupied neighbour."""
  # Convert from parameters
  adj = arg3_adj
  classified_atoms = arg4_classified_atoms
  comp = arg1_comp
  nodes = arg2_nodes
  resolved_tusis = arg5_resolved_tusis
  year = int(arg6_year)

  # Declare local instance variables.
  comp_set = set(comp)
  default_occ = "Japan" if year <= 1940 else "Japan/Wang"
  dom_occ = default_occ
  occ_votes = Counter()

  for u in comp:
    for v in adj[u]:
      if v not in comp_set and nodes[v]["occ"]:
        occ_votes[nodes[v]["occ"]] += 1
  if occ_votes:
    dom_occ = occ_votes.most_common(1)[0][0]

  for u in comp:
    nd = nodes[u]
    nd["occ"] = dom_occ
    if dom_occ == "Manchukuo (Japan)":
      new_country = "Manchukuo"
    elif dom_occ == "Mengjiang (Japan)":
      new_country = "Mengjiang (Japan)"
    elif dom_occ == "Japanese Occupied Manchuria":
      new_country = "Japanese Occupied Manchuria"
    else:
      new_country = f"{nd['adm1']} (Japanese Occupied)"
    nd["country"] = new_country
    if nd["kind"] == "atom":
      rec = list(classified_atoms[nd["idx"]])
      rec[6] = new_country
      rec[7] = dom_occ
      classified_atoms[nd["idx"]] = tuple(rec)
    else:
      resolved_tusis[nd["idx"]]["country"] = new_country
      resolved_tusis[nd["idx"]]["occ"] = dom_occ


def _revert_enclave_component (arg1_comp, arg2_nodes, arg3_classified_atoms, arg4_resolved_tusis, arg5_reforms):
  """Revert a disconnected interior occupied component back to unoccupied Republic of China status."""
  # Convert from parameters
  classified_atoms = arg3_classified_atoms
  comp = arg1_comp
  nodes = arg2_nodes
  reforms = arg5_reforms
  resolved_tusis = arg4_resolved_tusis

  # Declare local instance variables.
  adm1_zh = reforms.get("adm1_zh_names", {})

  for u in comp:
    nd = nodes[u]
    nd["occ"] = ""
    nd["country"] = "Republic of China"
    if nd["kind"] == "atom":
      rec = list(classified_atoms[nd["idx"]])
      if rec[2] == "Huaihai (Japanese / Wang)":
        rec[2] = "Jiangsu"
        rec[3] = adm1_zh.get("Jiangsu", "江苏")
        rec[8] = "province"
      elif rec[2] == "Jinbei (Mengjiang)":
        rec[2] = "Shanxi"
        rec[3] = adm1_zh.get("Shanxi", "山西")
        rec[8] = "province"
      rec[6] = "Republic of China"
      rec[7] = ""
      classified_atoms[nd["idx"]] = tuple(rec)
    else:
      trec = resolved_tusis[nd["idx"]]
      trec["country"] = "Republic of China"
      trec["occ"] = ""


def build_coastal_enclave_clips (arg1_reforms, arg2_citas_list):
  """Construct clip polygons for treaty ports, foreign colonies, and split island enclaves.

  @param arg1_reforms Parsed admin_reforms_1912_1953.json5 dict.
  @param arg2_citas_list Loaded CITAS county records from _load_citas_polygons.
  @return Dict of Shapely clip geometries and deferred multi-county accumulators.
  """
  # Convert from parameters
  citas_list = arg2_citas_list
  reforms = arg1_reforms

  # Declare local instance variables.
  cfg = reforms.get("coastal_enclave_citas", {})
  gzw_gbs = tuple(cfg.get("guangzhouwan_gbs", []))
  gzw_geoms = [c["geom"] for c in citas_list if str(c.get("gb", "")).startswith(gzw_gbs)]
  hk_bbox = box(*cfg.get("hong_kong_bbox", [113.80, 22.14, 114.46, 22.562]))
  hk_gbs = tuple(cfg.get("hong_kong_gbs", []))
  hk_geoms = [c["geom"] for c in citas_list if str(c.get("gb", "")).startswith(hk_gbs)]
  mac_bbox = box(*cfg.get("macau_bbox", [113.548, 22.105, 113.605, 22.150]))
  mac_gbs = tuple(cfg.get("macau_gbs", []))
  mac_geoms = [c["geom"] for c in citas_list if str(c.get("gb", "")).startswith(mac_gbs)]
  mac_pen_bbox = box(*cfg.get("macau_peninsula_bbox", [113.520, 22.162, 113.575, 22.240]))
  wh_gbs = tuple(cfg.get("weihaiwei_gbs", []))
  wh_geoms = [c["geom"] for c in citas_list if str(c.get("gb", "")).startswith(wh_gbs)]

  hk_clip = unary_union(hk_geoms).buffer(0.015).intersection(hk_bbox) if hk_geoms else hk_bbox
  mac_pen = unary_union(mac_geoms).buffer(0.01).intersection(mac_pen_bbox) if mac_geoms else mac_pen_bbox
  mac_clip = unary_union([mac_pen, mac_bbox])
  gzw_clip = unary_union(gzw_geoms).buffer(0.008) if gzw_geoms else None
  wh_clip = unary_union(wh_geoms).buffer(0.008) if wh_geoms else None

  # Return statement
  return {
    "gzw_clip": gzw_clip,
    "gzw_parts": [],
    "hk_clip": hk_clip,
    "kinmen_dedupe_clip": box(*cfg.get("kinmen_dedupe_bbox", [118.205, 24.37, 118.49, 24.54])),
    "macau_clip": mac_clip,
    "qd_clip": box(*cfg.get("qingdao_bbox", [120.12, 35.95, 120.75, 36.28])),
    "wh_clip": wh_clip,
    "xm_clip": box(*cfg.get("xiamen_island_bbox", [118.06, 24.42, 118.20, 24.56])),
  }


def carve_coastal_enclave_atom (arg1_builder, arg2_l1, arg3_l2, arg4_uid, arg5_name_en, arg6_geom, arg7_clips):
  """Split treaty port, colonial, or island enclaves out of host CHGIS 1911 county polygons.

  @param arg1_builder AnnualAdminBuilder instance.
  @param arg2_l1 Parent ADM-1 province name.
  @param arg3_l2 Parent ADM-2 prefecture name.
  @param arg4_uid Original CHGIS unit ID.
  @param arg5_name_en Host county English name.
  @param arg6_geom Host county Shapely geometry.
  @param arg7_clips Clip dict returned by build_coastal_enclave_clips.
  @return Remaining host county geometry after carving.
  """
  # Convert from parameters
  builder = arg1_builder
  clips = arg7_clips
  geom = arg6_geom
  l1 = arg2_l1
  name_en = arg5_name_en
  uid = arg4_uid

  if l1 == "Shandong" and name_en == "Jimo Xian":
    return _carve_single_enclave(builder, geom, clips["qd_clip"], "shandong_qingdao_enclave", "Shandong", "Jiao Zhou", "青岛", "Qingdao", uid, "370201", {"enclave_key": "qingdao", "is_qingdao": True})
  if l1 == "Shandong" and name_en == "Wendeng Xian":
    return _carve_single_enclave(builder, geom, clips["wh_clip"], "shandong_weihaiwei", "Shandong", "Dengzhou Fu", "威海卫", "Weihaiwei", uid, "371001", {"enclave_key": "weihaiwei"})
  if l1 == "Guangdong" and name_en == "Xin'an Xian":
    return _carve_single_enclave(builder, geom, clips["hk_clip"], "guangdong_hong_kong", "Guangdong", "Guangzhou Fu", "香港", "Hong Kong", uid, "810000", {"enclave_key": "hong_kong"})
  if l1 == "Guangdong" and name_en == "Xiangshan Xian":
    return _carve_single_enclave(builder, geom, clips["macau_clip"], "guangdong_macau", "Guangdong", "Guangzhou Fu", "澳门", "Macau", uid, "820000", {"enclave_key": "macau"})
  if l1 == "Guangdong" and name_en in ("Suixi Xian", "Wuchuan Xian"):
    gzw_clip = clips.get("gzw_clip")
    if gzw_clip is not None and geom.intersects(gzw_clip):
      g_part = gis_helpers.clean_polygonal_geometry(geom.intersection(gzw_clip))
      if g_part is not None and g_part.area > 0.0002:
        clips["gzw_parts"].append(g_part)
      return gis_helpers.clean_polygonal_geometry(geom.difference(gzw_clip))
  if l1 == "Fujian" and name_en == "Tong'an Xian":
    rem_km = gis_helpers.clean_polygonal_geometry(geom.difference(clips["kinmen_dedupe_clip"]))
    if rem_km is None:
      return None
    return _carve_single_enclave(builder, rem_km, clips["xm_clip"], "fujian_xiamen_island", "Fujian", "Quanzhou Fu", "厦门", "Xiamen", uid, "350201", {})

  # Return statement
  return geom


def classify_china_proper_occupation (arg1_atom, arg2_year, arg3_adm1, arg4_adm2, arg5_adm3, arg6_reforms):
  """Classify 1938-1945 China Proper Japanese occupation using province-qualified prefectures and county seats.

  @param arg1_atom Atomic China unit dictionary.
  @param arg2_year Snapshot year (1938-1945).
  @param arg3_adm1 Resolved adm1 province name.
  @param arg4_adm2 Resolved adm2 name.
  @param arg5_adm3 Resolved adm3 name.
  @param arg6_reforms Parsed admin_reforms_1912_1953.json5 dict.
  @return Classification tuple (adm1, adm1_ch, adm2, adm3, country, occ, category) or None if unoccupied.
  """
  # Convert from parameters
  adm1 = arg3_adm1
  adm2 = arg4_adm2
  adm3 = arg5_adm3
  atom = arg1_atom
  reforms = arg6_reforms
  year = int(arg2_year)

  # Declare local instance variables.
  adm1_zh = reforms.get("adm1_zh_names", {})
  cfg = reforms.get("sino_japanese_occupation_1932_1945", {})
  is_occ = False
  l1 = atom["l1_1911"]
  l2 = atom["l2_1911"]
  name_en = atom["name_en"]
  occ = ""
  pref_gates = []
  cnty_gates = []

  if not (1938 <= year <= 1945):
    return None

  if year == 1945 and l2 in cfg.get("1945_huaihai_prefs", {}).get(l1, []):
    # Return statement
    return ("Huaihai (Japanese / Wang)", "淮海省", adm2, adm3, "Reorganized National Govt (Japan)", "Japan/Wang", "puppet_province")

  pref_gates = [
    (year >= 1938, "1938_prefs"),
    (year >= 1939, "1939_prefs"),
    (year >= 1940, "1940_prefs"),
    (year == 1940, "1940_only_prefs"),
    (year >= 1941, "1941_prefs"),
    (year >= 1942, "1942_prefs"),
    (year == 1945, "1945_ichigo_prefs"),
  ]
  for active, gkey in pref_gates:
    if active and l2 in cfg.get(gkey, {}).get(l1, []):
      is_occ = True
      break

  if not is_occ:
    cnty_gates = [
      (year >= 1938, "1938_counties"),
      (year >= 1939, "1939_counties"),
      (year >= 1940, "1940_counties"),
      (year == 1940, "1940_only_counties"),
      (year >= 1941, "1941_counties"),
      (year >= 1942, "1942_counties"),
      (year in (1943, 1944), "1943_1944_counties"),
      (year >= 1943, "1943_plus_counties"),
      (year >= 1944, "1944_plus_counties"),
      (year == 1945, "1945_ichigo_counties"),
    ]
    for active, gkey in cnty_gates:
      if active and name_en in cfg.get(gkey, {}).get(l1, []):
        is_occ = True
        break

  if not is_occ:
    return None

  occ = "Japan" if year <= 1940 else "Japan/Wang"
  adm1_ch = adm1_zh.get(adm1, adm1)
  cat = "province" if adm1 not in ("Shanghai", "Nanjing", "Hankou", "Guangzhou", "Qingdao", "Beiping", "Tianjin") else "municipality"

  # Return statement
  return (adm1, adm1_ch, adm2, adm3, f"{adm1} (Japanese Occupied)", occ, cat)


def classify_coastal_enclave (arg1_atom, arg2_year, arg3_country):
  """Classify carved foreign colonies, leased territories, and treaty ports for 1 January arg2_year.

  @param arg1_atom Atomic China unit dictionary.
  @param arg2_year Snapshot year (1911-1953).
  @param arg3_country Resolved base Chinese sovereignty string for unoccupied years.
  @return Classification tuple (adm1, adm1_ch, adm2, adm3, country, occ, category) or None.
  """
  # Convert from parameters
  atom = arg1_atom
  country = arg3_country
  year = int(arg2_year)

  # Declare local instance variables.
  ekey = str(atom.get("enclave_key") or "")
  occ = ""

  if not ekey:
    return None

  if ekey == "hong_kong":
    if 1942 <= year <= 1945:
      return ("Guangdong", "广东", "Hong Kong", "Hong Kong", "Hong Kong (Japanese Occupied)", "Japan", "province")
    return ("Guangdong", "广东", "Hong Kong", "Hong Kong", "United Kingdom (Hong Kong)", "", "province")
  if ekey == "macau":
    return ("Guangdong", "广东", "Macau", "Macau", "Portugal (Macau)", "", "province")
  if ekey == "guangzhouwan":
    if year <= 1943:
      return ("Guangdong", "广东", "Guangzhouwan", "Guangzhouwan", "France (Guangzhouwan)", "", "province")
    if year <= 1945:
      return ("Guangdong", "广东", "Guangzhouwan", "Guangzhouwan", "Guangzhouwan (Japanese Occupied)", "Japan", "province")
    return ("Guangdong", "广东", "Zhanjiang", "Zhanjiang Shi", country, "", "province")
  if ekey == "weihaiwei":
    if year <= 1930:
      return ("Shandong", "山东", "Weihaiwei", "Weihaiwei", "United Kingdom (Weihaiwei)", "", "province")
    if 1939 <= year <= 1945:
      occ = "Japan" if year <= 1940 else "Japan/Wang"
      return ("Shandong", "山东", "Weihaiwei", "Weihaiwei", "Shandong (Japanese Occupied)", occ, "province")
    return ("Shandong", "山东", "Weihaiwei", "Weihaiwei", country, "", "province")
  if ekey == "qingdao":
    if year <= 1914:
      return ("Shandong", "山东", "Kiautschou", "Qingdao", "German Empire (Kiautschou)", "", "province")
    if 1915 <= year <= 1922:
      return ("Qingdao (Japanese Occupied)", "青岛", "Qingdao", "Qingdao", "Empire of Japan", "Japan", "occupied_city")
    if 1939 <= year <= 1945:
      return ("Qingdao (Japanese Occupied)", "青岛", "Qingdao", "Qingdao", "Empire of Japan / North China", "Japan", "occupied_city")
    if 1929 <= year <= 1949:
      return ("Qingdao", "青岛市", "Qingdao", "Qingdao", country, "", "municipality")
    return ("Shandong", "山东", "Qingdao", "Qingdao", country, "", "province")

  # Return statement
  return None


def classify_manchuria_1932 (arg1_atom, arg2_reforms):
  """Check whether a Northeast China or Zhelimu atom belongs to the 1 January 1932 occupation corridor.

  @param arg1_atom Atomic China unit dictionary.
  @param arg2_reforms Parsed admin_reforms_1912_1953.json5 dict.
  @return True if occupied on 1 January 1932, False otherwise.
  """
  # Convert from parameters
  atom = arg1_atom
  reforms = arg2_reforms

  # Declare local instance variables.
  cfg = reforms.get("sino_japanese_occupation_1932_1945", {})
  citas_list = cfg.get("1932_manchuria_citas", [])
  gb = str(atom.get("gb") or "")
  l1 = atom.get("l1_1911", "")
  l2 = atom.get("l2_1911", "")
  pref_map = cfg.get("1932_manchuria_prefs", {})

  if gb and any(gb.startswith(pfx) for pfx in citas_list):
    return True
  if l2 in pref_map.get(l1, []):
    return True

  # Return statement
  return False


def emit_deferred_guangzhouwan (arg1_builder, arg2_clips):
  """Combine accumulated Guangzhouwan pieces from Suixi and Wuchuan into one unified enclave atom.

  @param arg1_builder AnnualAdminBuilder instance.
  @param arg2_clips Clip dict returned by build_coastal_enclave_clips.
  """
  # Convert from parameters
  builder = arg1_builder
  clips = arg2_clips

  # Declare local instance variables.
  parts = clips.get("gzw_parts", [])
  gg = None
  gd = None
  rp = None
  u = None

  if not parts:
    return

  u = gis_helpers.clean_polygonal_geometry(unary_union(parts))
  gg, gd = builder._cache_geom(u)
  if gg is None or gg.area <= 0.0005:
    return

  rp = gg.representative_point()
  builder._append_china_atom(
    "guangdong_guangzhouwan",
    gd,
    gg,
    "Guangdong",
    "Leizhou Fu",
    "广州湾",
    "Guangzhouwan",
    "guangdong_guangzhouwan",
    "440801",
    "广州湾",
    "Guangzhouwan",
    {
      "enclave_key": "guangzhouwan",
      "seat_lat": round(float(rp.y), builder.precision),
      "seat_lon": round(float(rp.x), builder.precision),
    },
  )


def enforce_occupation_topology (arg1_builder, arg2_year, arg3_classified_atoms, arg4_atom_geom_map, arg5_resolved_tusis):
  """Enforce gap-free and enclave-free Japanese occupation topology across mainland China and Feudatories.

  @param arg1_builder AnnualAdminBuilder instance.
  @param arg2_year Snapshot year (only active when 1932 <= year <= 1945).
  @param arg3_classified_atoms Mutable list of classified atom tuples.
  @param arg4_atom_geom_map Mapping from atom key to geometry.
  @param arg5_resolved_tusis Mutable list of resolved Feudatory dicts.
  @return Summary dict of hole fills and enclave reversions.
  """
  # Convert from parameters
  atom_geom_map = arg4_atom_geom_map
  builder = arg1_builder
  classified_atoms = arg3_classified_atoms
  resolved_tusis = arg5_resolved_tusis
  year = int(arg2_year)

  if not (1932 <= year <= 1945):
    return {"filled_holes": 0, "reverted_enclaves": 0}

  # Declare local instance variables.
  adj = []
  filled_cnt = 0
  geoms = []
  nodes = []
  pairs = None
  reverted_cnt = 0
  seen = []
  supply_cache = _build_supply_root_index(builder)
  tree = None

  nodes = _collect_node_records(classified_atoms, atom_geom_map, resolved_tusis, supply_cache)
  if not nodes:
    return {"filled_holes": 0, "reverted_enclaves": 0}

  geoms = [nd["geom"] for nd in nodes]
  tree = STRtree(geoms)
  adj = [[] for _ in range(len(nodes))]
  pairs = tree.query(geoms, predicate="dwithin", distance=0.018)
  for k in range(pairs.shape[1]):
    i = int(pairs[0, k])
    j = int(pairs[1, k])
    if j > i:
      adj[i].append(j)
      adj[j].append(i)

  # Pass 1: Fill completely enclosed interior unoccupied holes inside occupied plains/corridors
  seen = [False]*len(nodes)
  for start in range(len(nodes)):
    if seen[start] or nodes[start]["occ"] != "":
      continue
    comp = []
    queue = [start]
    seen[start] = True
    has_free_escape = False
    touches_occ = False
    while queue:
      u = queue.pop()
      comp.append(u)
      nd_u = nodes[u]
      is_foreign = any(tok in nd_u["country"] for tok in ("United Kingdom", "Portugal", "France", "German Empire"))
      if nd_u["on_outer"] or nd_u["lon"] < 107.5 or is_foreign:
        has_free_escape = True
      for v in adj[u]:
        if nodes[v]["occ"] != "":
          touches_occ = True
        elif not seen[v]:
          seen[v] = True
          queue.append(v)
    if (not has_free_escape) and touches_occ and len(comp) <= 2:
      _promote_hole_component(comp, nodes, adj, classified_atoms, resolved_tusis, year)
      filled_cnt += len(comp)

  # Pass 2: Revert disconnected interior occupied components lacking a valid maritime or land supply root
  seen = [False]*len(nodes)
  for start in range(len(nodes)):
    if seen[start] or nodes[start]["occ"] == "":
      continue
    comp = []
    queue = [start]
    seen[start] = True
    has_supply = False
    while queue:
      u = queue.pop()
      comp.append(u)
      if _is_valid_occupied_root(nodes[u], year):
        has_supply = True
      for v in adj[u]:
        if (not seen[v]) and nodes[v]["occ"] != "":
          seen[v] = True
          queue.append(v)
    if not has_supply:
      _revert_enclave_component(comp, nodes, classified_atoms, resolved_tusis, builder.reforms)
      reverted_cnt += len(comp)

  # Return statement
  return {"filled_holes": filled_cnt, "reverted_enclaves": reverted_cnt}
