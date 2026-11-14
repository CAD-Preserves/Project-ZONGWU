"""Step 1 pipeline: download CHGIS/GADM/Natural Earth sources, reproject to WGS84, clean, and export 1911 baseline + transport."""

from collections import Counter
import io
import json
import math
import os
import sys
import zipfile
from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box, shape
from shapely.ops import unary_union
from shapely.prepared import prep

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)
from classes.ElevationContourBuilder import ElevationContourBuilder
from helpers import gis_helpers, path_helpers


def _clip_linear_geom (arg1_geom, arg2_bbox):
  """Clip a linear or polygonal geometry to the target bounding box."""
  # Convert from parameters
  bbox = arg2_bbox
  geom = arg1_geom

  if geom is None or geom.is_empty:
    return None
  if not geom.intersects(bbox):
    return None
  clipped = geom.intersection(bbox)
  if clipped is None or clipped.is_empty:
    return None

  # Return statement
  return clipped


def _clip_pamir_east_tajikistan (arg1_geom, arg2_pamir_box, arg3_prc_xj_union, arg4_min_lobe_area):
  """Remove undemarcated East Tajikistan Pamir lobes west of the Sarikol Range from CHGIS 1911 Xinjiang priors.

  @param arg1_geom Input CHGIS Shapely geometry.
  @param arg2_pamir_box Bounding box covering the Pamir border region.
  @param arg3_prc_xj_union Modern GADM Xinjiang union inside arg2_pamir_box.
  @param arg4_min_lobe_area Minimum exterior lobe area in deg2 to strip.
  @return Clipped polygonal Shapely geometry.
  """
  # Convert from parameters
  geom = arg1_geom
  min_lobe = float(arg4_min_lobe_area)
  pamir_box = arg2_pamir_box
  prc_xj_union = arg3_prc_xj_union

  # Declare local instance variables.
  lobes = []
  outside = None
  parts = []
  trimmed = None

  if geom is None or geom.is_empty or pamir_box is None or prc_xj_union is None:
    return geom
  if not geom.intersects(pamir_box):
    return geom

  outside = gis_helpers.clean_polygonal_geometry(geom.intersection(pamir_box).difference(prc_xj_union))
  if outside is None or outside.is_empty:
    return geom

  parts = [outside] if outside.geom_type == "Polygon" else list(outside.geoms)
  lobes = [p for p in parts if p.area >= min_lobe]
  if not lobes:
    return geom

  trimmed = gis_helpers.clean_polygonal_geometry(geom.difference(unary_union(lobes)))
  if trimmed is None or trimmed.is_empty:
    return geom

  # Return statement
  return trimmed


def _load_gadm_geojson_from_path (arg1_path):
  """Load a GADM GeoJSON file either directly or from a .json.zip archive."""
  # Convert from parameters
  path = arg1_path

  if not os.path.exists(path):
    print(f"[ERROR] Missing GADM file: {path}", file=sys.stderr)
    return []

  if path.lower().endswith(".zip"):
    with zipfile.ZipFile(path, "r") as zf:
      json_names = [n for n in zf.namelist() if n.lower().endswith(".json") or n.lower().endswith(".geojson")]
      if not json_names:
        return []
      data = json.loads(zf.read(json_names[0]).decode("utf-8"))
  else:
    with open(path, "r", encoding="utf-8") as fh:
      data = json.load(fh)

  features = []
  for feat in data.get("features", []):
    geom = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
    if geom is not None and not geom.is_empty:
      features.append((feat.get("properties", {}), geom))

  # Return statement
  return features


_TAIWAN_CHO_CACHE = None


def _map_taiwan_cho_1911 (arg1_name_2):
  """Map GADM TWN_2 county/city name to 1911-1920 Japanese Taiwan 12 Cho."""
  # Convert from parameters
  name = str(arg1_name_2 or "").strip()

  # Declare local instance variables.
  global _TAIWAN_CHO_CACHE
  default_pair = ("Taihoku Cho", "台北厅")
  mappings = {}
  pair = None

  if _TAIWAN_CHO_CACHE is None:
    _TAIWAN_CHO_CACHE = gis_helpers.load_json5(path_helpers.resolve_path("common.admin_mappings"))["taiwan_cho_1911"]
  default_pair = tuple(_TAIWAN_CHO_CACHE.get("default", default_pair))
  mappings = _TAIWAN_CHO_CACHE.get("mappings", {})
  pair = mappings.get(name)

  # Return statement
  return tuple(pair) if pair else default_pair


def A_download_all_sources (arg1_cfg, arg2_base_dir):
  """Download and cache all Dataverse, GADM, Natural Earth, and HydroSHEDS source files.

  @param arg1_cfg Parsed data_sources.json5 configuration dictionary.
  @param arg2_base_dir Workspace root directory (or fallback cache dir).
  @return Dictionary mapping logical source keys to local filepaths.
  """
  # Convert from parameters
  base_dir = arg2_base_dir
  cfg = arg1_cfg

  # Declare local instance variables.
  base_url = cfg["chgis_dataverse"]["base_url"]
  dest = ""
  local_paths = {}
  ok = False
  section_cfg = {}
  url = ""

  for section in ("chgis_dataverse", "gadm", "natural_earth", "hydrosheds"):
    section_cfg = cfg.get(section, {})
    for key, meta in section_cfg.get("files", {}).items():
      dest = path_helpers.resolve_provider_file(cfg, section, key, base_dir)
      os.makedirs(os.path.dirname(dest), exist_ok=True)
      url = f"{base_url}{meta['file_id']}" if section == "chgis_dataverse" else meta["url"]
      ok = gis_helpers.download_with_cache(url, dest)
      if ok:
        local_paths[key] = dest

  # Return statement
  return local_paths


def B_build_1911_baseline (arg1_paths, arg2_cfg, arg3_base_dir):
  """Reproject, clean, and export raw CHGIS 1911 prior GeoJSON baselines to input/gis/priors/.

  @param arg1_paths Dictionary of local source filepaths.
  @param arg2_cfg Parsed data_sources.json5 configuration dictionary.
  @param arg3_base_dir Project root directory for resolving prior output paths.
  @return Summary dictionary of exported feature counts.
  """
  # Convert from parameters
  base_dir = arg3_base_dir
  cfg = arg2_cfg
  paths = arg1_paths

  # Declare local instance variables.
  admin_map_cfg = gis_helpers.load_json5(path_helpers.resolve_path("common.admin_mappings", base_dir))
  adm1_features = []
  adm1_out = path_helpers.resolve_path("input.gis.chgis_1911_adm1_base", base_dir)
  adm2_features = []
  adm2_out = path_helpers.resolve_path("input.gis.chgis_1911_adm2_base", base_dir)
  adm3_features = []
  adm3_out = path_helpers.resolve_path("input.gis.chgis_1911_adm3_base", base_dir)
  pamir_cfg = admin_map_cfg.get("pamir_east_tajikistan_clip", {}) if isinstance(admin_map_cfg, dict) else {}
  pamir_bbox = pamir_cfg.get("bbox")
  pamir_box = box(float(pamir_bbox[0]), float(pamir_bbox[1]), float(pamir_bbox[2]), float(pamir_bbox[3])) if pamir_bbox and len(pamir_bbox) == 4 else None
  min_pamir_lobe = float(pamir_cfg.get("min_exterior_lobe_deg2", 0.02))
  chn_gadm = _load_gadm_geojson_from_path(paths["gadm_chn_3"]) if (pamir_box is not None and "gadm_chn_3" in paths) else []
  xj_pamir_geoms = [
    g for r, g in chn_gadm
    if "xinjiang" in str(r.get("NAME_1") or "").lower() and pamir_box is not None and g.intersects(pamir_box)
  ]
  prc_xj_pamir_union = gis_helpers.clean_polygonal_geometry(unary_union(xj_pamir_geoms)) if xj_pamir_geoms else None
  precision = int(cfg.get("coordinate_precision", 5))
  raw_cnty = gis_helpers.read_zip_shapefile_wgs84(paths["chgis_1911_cnty"], "utf-8", precision)
  raw_pref = gis_helpers.read_zip_shapefile_wgs84(paths["chgis_1911_pref"], "utf-8", precision)
  raw_prov = gis_helpers.read_zip_shapefile_wgs84(paths["chgis_1911_prov"], "utf-8", precision)
  twn_gadm = _load_gadm_geojson_from_path(paths["gadm_twn_2"])

  # 1. Level-1 (Provinces & Frontier Regions)
  for rec, geom in raw_prov:
    name_py = gis_helpers.normalise_lev1_name(rec.get("NAME_PY"), rec.get("NAME_CH"))
    name_ch = str(rec.get("NAME_CH") or "").strip()
    if name_py == "Xinjiang":
      geom = _clip_pamir_east_tajikistan(geom, pamir_box, prc_xj_pamir_union, min_pamir_lobe)
    is_jp = (name_py == "Taiwan")
    props = {
      "adm_level": 1,
      "category": "colony" if is_jp else "province",
      "country": "Empire of Japan" if is_jp else "Qing Empire",
      "name_ch": "台湾" if is_jp else name_ch,
      "name_en": name_py,
      "occupied_by": "Japan" if is_jp else "",
      "parent_adm1": "",
      "sys_id": str(rec.get("SYS_ID") or ""),
      "type_py": str(rec.get("TYPE_PY") or ""),
      "unit_id": f"prov_{gis_helpers.slugify_snake(name_py)}",
      "year": 1911,
    }
    adm1_features.append((props, geom))

  # 2. Level-2 (Prefectures, Leagues, Aimags, Uriankhai, Kobdo + Taiwan 12 Cho)
  pref_items = []
  for rec, geom in raw_pref:
    lev1_py = gis_helpers.normalise_lev1_name(rec.get("LEV1_PY"), rec.get("LEV1_CH"))
    name_py = str(rec.get("NAME_PY") or "").strip()
    name_ch = str(rec.get("NAME_CH") or "").strip()
    if name_py == "Xuzhou Fu" and lev1_py == "Anhui":
      lev1_py = "Jiangsu"
    if lev1_py == "Xinjiang":
      geom = _clip_pamir_east_tajikistan(geom, pamir_box, prc_xj_pamir_union, min_pamir_lobe)
    lon = None
    lat = None
    if rec.get("X_COORD") not in (None, "", 0) and rec.get("Y_COORD") not in (None, "", 0):
      xc = float(rec["X_COORD"])
      yc = float(rec["Y_COORD"])
      if abs(xc) > 360.0:
        lon, lat = gis_helpers.gk19_array_to_lonlat([[xc, yc]])[0]
      else:
        lon, lat = xc, yc
    pref_items.append({
      "geom": geom,
      "lat": lat,
      "lev1_py": lev1_py,
      "lon": lon,
      "name_ch": name_ch,
      "name_py": name_py,
      "rec": rec,
    })

  pref_items = gis_helpers.split_stacked_banners(pref_items)
  for item in pref_items:
    rec = item["rec"]
    props = {
      "adm_level": 2,
      "country": "Qing Empire",
      "name_ch": item["name_ch"],
      "name_en": item["name_py"],
      "occupied_by": "",
      "parent_adm1": item["lev1_py"],
      "sys_id": str(rec.get("SYS_ID") or ""),
      "type_py": str(rec.get("TYPE_PY") or ""),
      "unit_id": f"pref_{gis_helpers.slugify_snake(item['lev1_py'])}_{gis_helpers.slugify_snake(item['name_py'])}_{rec.get('SYS_ID','')}",
      "year": 1911,
    }
    adm2_features.append((props, item["geom"]))

  # Add Taiwan 12 Cho to adm_2 and Taiwan counties/cities to adm_3 (excluding Kinmen/Matsu in Fujian)
  cho_groups = {}
  for rec, geom in twn_gadm:
    n1 = str(rec.get("NAME_1") or "").strip()
    n2 = str(rec.get("NAME_2") or "").strip()
    if n1 == "Fujian" or n2 in ("Kinmen", "Lienkiang"):
      continue
    cho_en, cho_ch = _map_taiwan_cho_1911(n2)
    cho_groups.setdefault((cho_en, cho_ch), []).append(geom)
    adm3_features.append((
      {
        "adm_level": 3,
        "country": "Empire of Japan",
        "name_ch": str(rec.get("NL_NAME_2") or n2),
        "name_en": n2,
        "occupied_by": "Japan",
        "parent_adm1": "Taiwan",
        "parent_adm2": cho_en,
        "sys_id": str(rec.get("GID_2") or ""),
        "type_py": "Subprefecture",
        "unit_id": f"twn_{gis_helpers.slugify_snake(n2)}",
        "year": 1911,
      },
      geom,
    ))

  for (cho_en, cho_ch), geoms in sorted(cho_groups.items()):
    merged = gis_helpers.clean_polygonal_geometry(unary_union(geoms))
    if merged is not None:
      adm2_features.append((
        {
          "adm_level": 2,
          "country": "Empire of Japan",
          "name_ch": cho_ch,
          "name_en": cho_en,
          "occupied_by": "Japan",
          "parent_adm1": "Taiwan",
          "sys_id": f"TWN_{gis_helpers.slugify_snake(cho_en)}",
          "type_py": "Cho",
          "unit_id": f"pref_taiwan_{gis_helpers.slugify_snake(cho_en)}",
          "year": 1911,
        },
        merged,
      ))

  # 3. Level-3 (Counties, Banners, Tusis + unstacked Kebuduo/Qinghai banners + frontier gap fill)
  cnty_items = []
  for rec, geom in raw_cnty:
    lev1_py = gis_helpers.normalise_lev1_name(rec.get("LEV1_PY"), rec.get("LEV1_CH"))
    name_py = str(rec.get("NAME_PY") or "").strip()
    name_ch = str(rec.get("NAME_CH") or "").strip()
    if lev1_py == "Xinjiang":
      geom = _clip_pamir_east_tajikistan(geom, pamir_box, prc_xj_pamir_union, min_pamir_lobe)
    lon = None
    lat = None
    if rec.get("X_COORD") not in (None, "", 0) and rec.get("Y_COORD") not in (None, "", 0):
      xc = float(rec["X_COORD"])
      yc = float(rec["Y_COORD"])
      if abs(xc) > 360.0:
        lon, lat = gis_helpers.gk19_array_to_lonlat([[xc, yc]])[0]
      else:
        lon, lat = xc, yc
    cnty_items.append({
      "geom": geom,
      "lat": lat,
      "lev1_py": lev1_py,
      "lon": lon,
      "name_ch": name_ch,
      "name_py": name_py,
      "rec": rec,
    })

  cnty_items = gis_helpers.split_stacked_banners(cnty_items)
  sid_counts = Counter(str(it["rec"].get("SYS_ID") or "").strip() for it in cnty_items)
  cnty_geoms_by_l1 = {}
  for item in cnty_items:
    rec = item["rec"]
    l1 = item["lev1_py"]
    l2 = str(rec.get("LEV2_PY") or "").strip()
    sid = str(rec.get("SYS_ID") or "").strip()
    geom_c = item["geom"]
    s_lon = item.get("lon")
    s_lat = item.get("lat")
    use_seat = False
    if s_lon is not None and s_lat is not None:
      if sid_counts[sid] <= 1:
        use_seat = True
      elif geom_c.distance(Point(float(s_lon), float(s_lat))) < 0.05:
        use_seat = True
    if not use_seat:
      rp = geom_c.representative_point()
      s_lon, s_lat = rp.x, rp.y
    cnty_geoms_by_l1.setdefault(l1, []).append(geom_c)
    props = {
      "adm_level": 3,
      "country": "Qing Empire",
      "name_ch": item["name_ch"],
      "name_en": item["name_py"],
      "occupied_by": "",
      "parent_adm1": l1,
      "parent_adm2": l2,
      "seat_lat": round(float(s_lat), precision),
      "seat_lon": round(float(s_lon), precision),
      "sys_id": sid,
      "type_py": str(rec.get("TYPE_PY") or ""),
      "unit_id": f"cnty_{gis_helpers.slugify_snake(l1)}_{gis_helpers.slugify_snake(item['name_py'])}_{rec.get('SYS_ID','')}",
      "year": 1911,
    }
    adm3_features.append((props, geom_c))

  # Fill direct-administered frontier prefectures missing from v6_1911_cnty using global spatial index
  all_cnty_geoms = [item["geom"] for item in cnty_items]
  cnty_tree = STRtree(all_cnty_geoms)
  for props2, geom2 in adm2_features:
    l1 = props2["parent_adm1"]
    if l1 == "Taiwan":
      continue
    hits = [all_cnty_geoms[idx] for idx in cnty_tree.query(geom2)]
    existing = unary_union(hits) if hits else None
    diff = geom2 if existing is None else geom2.difference(existing)
    diff = gis_helpers.clean_polygonal_geometry(diff)
    # Keep significant direct-administered territories (> 0.005 deg^2, ~50 km^2)
    if diff is not None and diff.area > 0.005:
      rp_d = diff.representative_point()
      adm3_features.append((
        {
          "adm_level": 3,
          "country": "Qing Empire",
          "name_ch": f"{props2['name_ch']}直辖",
          "name_en": f"{props2['name_en']} Direct",
          "occupied_by": "",
          "parent_adm1": l1,
          "parent_adm2": props2["name_en"],
          "seat_lat": round(float(rp_d.y), precision),
          "seat_lon": round(float(rp_d.x), precision),
          "sys_id": f"FILL_{props2['sys_id']}",
          "type_py": "Zhixiadi",
          "unit_id": f"cnty_fill_{gis_helpers.slugify_snake(l1)}_{gis_helpers.slugify_snake(props2['name_en'])}",
          "year": 1911,
        },
        diff,
      ))

  for out_fp in (adm1_out, adm2_out, adm3_out):
    os.makedirs(os.path.dirname(out_fp), exist_ok=True)
  c1 = gis_helpers.write_geojson(adm1_out, adm1_features, precision)
  c2 = gis_helpers.write_geojson(adm2_out, adm2_features, precision)
  c3 = gis_helpers.write_geojson(adm3_out, adm3_features, precision)

  # Return statement
  return {"chgis_1911_adm1_base": c1, "chgis_1911_adm2_base": c2, "chgis_1911_adm3_base": c3}


def _feature_touches_bbox (arg1_geom_dict, arg2_minx, arg3_miny, arg4_maxx, arg5_maxy):
  """Fast check whether any coordinate of a GeoJSON geometry dict falls near the bounding box."""
  # Convert from parameters
  geom_dict = arg1_geom_dict
  maxx = arg4_maxx
  maxy = arg5_maxy
  minx = arg2_minx
  miny = arg3_miny

  coords = geom_dict.get("coordinates")
  if not coords:
    return False
  stack = [coords]
  for _ in range(100000):
    if not stack:
      break
    cur = stack.pop()
    if isinstance(cur, (list, tuple)) and cur:
      if isinstance(cur[0], (int, float)):
        if minx - 1.0 <= cur[0] <= maxx + 1.0 and miny - 1.0 <= cur[1] <= maxy + 1.0:
          return True
      else:
        stack.extend(cur)

  # Return statement
  return False


def C_build_transport_layers (arg1_paths, arg2_cfg, arg3_corridors, arg4_gis_dir):
  """Export clipped waterways, historical railways (1912-1953), and roads (1912-1953) GeoJSON layers.

  @param arg1_paths Dictionary of local source filepaths.
  @param arg2_cfg Parsed data_sources.json5 dictionary.
  @param arg3_corridors Parsed transport_corridors.json5 dictionary.
  @param arg4_gis_dir Output ./output/gis/layers/ directory.
  @return Dictionary of feature counts per transport layer.
  """
  # Convert from parameters
  cfg = arg2_cfg
  corridors = arg3_corridors
  gis_dir = arg4_gis_dir
  paths = arg1_paths

  # Declare local instance variables.
  bb_cfg = cfg["bounding_box"]
  bbox = box(bb_cfg["min_lon"], bb_cfg["min_lat"], bb_cfg["max_lon"], bb_cfg["max_lat"])
  precision = int(cfg.get("coordinate_precision", 5))
  rail_features = []
  road_features = []
  water_features = []

  # 1. Waterways (CHGIS rivers + lakes + Natural Earth 10m rivers)
  for rec, geom in gis_helpers.read_zip_shapefile_wgs84(paths["chgis_1820_rivers"], "utf-8", precision):
    clipped = _clip_linear_geom(geom, bbox)
    if clipped is not None:
      water_features.append((
        {
          "name_ch": str(rec.get("NAME_CH") or rec.get("HYD_NAME") or ""),
          "name_en": str(rec.get("NAME_PY") or rec.get("HYD_PY") or "River"),
          "source": "CHGIS_v6_rivers",
          "water_type": "river",
        },
        clipped,
      ))

  for rec, geom in gis_helpers.read_zip_shapefile_wgs84(paths["chgis_1820_lakes"], "utf-8", precision):
    clipped = _clip_linear_geom(geom, bbox)
    if clipped is not None:
      water_features.append((
        {
          "name_ch": str(rec.get("NAME_CH") or ""),
          "name_en": str(rec.get("NAME_PY") or "Lake"),
          "source": "CHGIS_v6_lakes",
          "water_type": "lake",
        },
        clipped,
      ))

  with open(paths["ne_rivers"], "r", encoding="utf-8") as fh:
    ne_riv = json.load(fh)
  for feat in ne_riv.get("features", []):
    if not _feature_touches_bbox(feat["geometry"], bb_cfg["min_lon"], bb_cfg["min_lat"], bb_cfg["max_lon"], bb_cfg["max_lat"]):
      continue
    geom = shape(feat["geometry"])
    clipped = _clip_linear_geom(geom, bbox)
    if clipped is not None:
      p = feat.get("properties", {})
      water_features.append((
        {
          "name_ch": "",
          "name_en": str(p.get("name_en") or p.get("name") or "River"),
          "source": "NaturalEarth_10m_rivers",
          "water_type": "river",
        },
        clipped,
      ))

  # 2. Historical Railways (1912-1953)
  # Include corridor trunk lines with exact historical opening years + nearby NE rail segments
  rail_corridor_buffers = []
  for cor in corridors["railways"]:
    line = LineString(cor["waypoints"])
    buf = line.buffer(0.45)
    rail_corridor_buffers.append((cor, buf, prep(buf)))
    rail_features.append((
      {
        "corridor_id": cor["corridor_id"],
        "line_name": cor["line_name"],
        "open_year": int(cor["open_year"]),
        "operator": cor["operator"],
        "source": "Historical_Rail_Corridor_1912_1953",
      },
      line,
    ))

  with open(paths["ne_railroads"], "r", encoding="utf-8") as fh:
    ne_rail = json.load(fh)
  for feat in ne_rail.get("features", []):
    if not _feature_touches_bbox(feat["geometry"], bb_cfg["min_lon"], bb_cfg["min_lat"], bb_cfg["max_lon"], bb_cfg["max_lat"]):
      continue
    geom = shape(feat["geometry"])
    clipped = _clip_linear_geom(geom, bbox)
    if clipped is None:
      continue
    matched_cor = None
    for cor, buf, pbuf in rail_corridor_buffers:
      if pbuf.intersects(clipped):
        inter_len = clipped.intersection(buf).length
        if clipped.length > 0.0 and (inter_len / clipped.length) >= 0.35:
          matched_cor = cor
          break
    if matched_cor is not None:
      rail_features.append((
        {
          "corridor_id": matched_cor["corridor_id"],
          "line_name": matched_cor["line_name"],
          "open_year": int(matched_cor["open_year"]),
          "operator": matched_cor["operator"],
          "source": "NaturalEarth_10m_filtered_pre1953",
        },
        clipped,
      ))

  # 3. Historical Roads & Caravan/Courier Routes (1912-1953)
  for key, label in [
    ("ming_courier_routes", "Imperial_Courier_Trunk"),
    ("teahorse_major_routes", "TeaHorse_Major_Caravan"),
    ("teahorse_minor_routes", "TeaHorse_Minor_Caravan"),
  ]:
    for rec, geom in gis_helpers.read_zip_shapefile_wgs84(paths[key], "utf-8", precision):
      clipped = _clip_linear_geom(geom, bbox)
      if clipped is not None:
        road_features.append((
          {
            "corridor_id": key,
            "open_year": 1912,
            "road_name": str(rec.get("NAME") or rec.get("Route") or label),
            "road_type": "caravan_courier",
            "source": key,
          },
          clipped,
        ))

  road_corridor_buffers = []
  for cor in corridors["trunk_roads"]:
    line = LineString(cor["waypoints"])
    road_corridor_buffers.append((cor, prep(line.buffer(0.55))))
    road_features.append((
      {
        "corridor_id": cor["corridor_id"],
        "open_year": int(cor["open_year"]),
        "road_name": cor["road_name"],
        "road_type": "trunk_highway",
        "source": "Historical_Trunk_Highway_1912_1953",
      },
      line,
    ))

  with open(paths["ne_roads"], "r", encoding="utf-8") as fh:
    ne_roads = json.load(fh)
  for feat in ne_roads.get("features", []):
    if not _feature_touches_bbox(feat["geometry"], bb_cfg["min_lon"], bb_cfg["min_lat"], bb_cfg["max_lon"], bb_cfg["max_lat"]):
      continue
    p = feat.get("properties", {})
    ftype = str(p.get("type") or "")
    if ftype not in ("Major Highway", "Secondary Highway", "Road", "Ferry Route"):
      continue
    geom = shape(feat["geometry"])
    clipped = _clip_linear_geom(geom, bbox)
    if clipped is None:
      continue
    open_yr = 1938
    for cor, pbuf in road_corridor_buffers:
      if pbuf.intersects(clipped):
        open_yr = int(cor["open_year"])
        break
    road_features.append((
      {
        "corridor_id": f"ne_road_{p.get('gid', '')}",
        "open_year": open_yr,
        "road_name": str(p.get("name") or ftype),
        "road_type": ftype,
        "source": "NaturalEarth_10m_roads",
      },
      clipped,
    ))

  filter_cfg = cfg.get("transport_straight_link_filter", {})
  rail_features = D_filter_straight_transport_links(rail_features, filter_cfg)
  road_features = D_filter_straight_transport_links(road_features, filter_cfg)

  cw = gis_helpers.write_geojson(os.path.join(gis_dir, "waterways_1912_1953.geojson"), water_features, precision)
  cr = gis_helpers.write_geojson(os.path.join(gis_dir, "railways_1912_1953.geojson"), rail_features, precision)
  cd = gis_helpers.write_geojson(os.path.join(gis_dir, "roads_1912_1953.geojson"), road_features, precision)

  # Return statement
  return {"railways": cr, "roads": cd, "waterways": cw}


def _is_straight_line_part (arg1_line, arg2_filter_cfg):
  """Detect coarse straight-chord LineString artefacts using vertex spacing and length thresholds.

  Args:
    arg1_line: Shapely LineString geometry to inspect.
    arg2_filter_cfg: Dict of straight-link filter thresholds from data_sources.json5.

  Returns:
    True when the line segment pattern indicates an un-digitised straight chord.
  """
  # Convert from parameters
  filter_cfg = arg2_filter_cfg if arg2_filter_cfg is not None else {}
  line_geom = arg1_line

  # Declare local instance variables.
  coarse_len = float(filter_cfg.get("coarse_min_length_deg", 0.20))
  coarse_mean = float(filter_cfg.get("coarse_mean_segment_deg", 0.15))
  coords = list(line_geom.coords) if line_geom is not None else []
  dx = 0.0
  dy = 0.0
  i = 0
  is_straight = False
  max_seg = 0.0
  max_seg_limit = float(filter_cfg.get("max_segment_deg", 0.28))
  mean_seg = 0.0
  n_pts = len(coords)
  seg_len = 0.0
  total_len = 0.0
  two_pt_len = float(filter_cfg.get("two_point_min_length_deg", 0.18))

  if n_pts < 2:
    return False

  for i in range(n_pts - 1):
    dx = coords[i + 1][0] - coords[i][0]
    dy = coords[i + 1][1] - coords[i][1]
    seg_len = math.hypot(dx, dy)
    total_len += seg_len
    if seg_len > max_seg:
      max_seg = seg_len
  mean_seg = total_len / float(n_pts - 1)
  is_straight = (
    (max_seg >= max_seg_limit) or
    (mean_seg >= coarse_mean and total_len >= coarse_len) or
    (n_pts == 2 and total_len >= two_pt_len)
  )

  # Return statement
  return is_straight


def _is_straight_transport_geom (arg1_geom, arg2_filter_cfg):
  """Evaluate whether a linear feature geometry contains any straight-chord part.

  Args:
    arg1_geom: Shapely LineString or MultiLineString geometry.
    arg2_filter_cfg: Dict of straight-link filter thresholds.

  Returns:
    True if any linear component triggers the straight-chord detector.
  """
  # Convert from parameters
  filter_cfg = arg2_filter_cfg if arg2_filter_cfg is not None else {}
  geom = arg1_geom

  # Declare local instance variables.
  has_straight = False
  part = None
  parts = []

  if geom is None or geom.is_empty:
    return False

  parts = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
  for part in parts:
    if isinstance(part, LineString) and _is_straight_line_part(part, filter_cfg):
      has_straight = True

  # Return statement
  return has_straight


def D_filter_straight_transport_links (arg1_features, arg2_filter_cfg):
  """Remove straight-chord anomalies and schematic graph-edge sources from transport features.

  Args:
    arg1_features: List of (properties_dict, shapely_geometry) tuples.
    arg2_filter_cfg: Dict of straight-link filter thresholds from data_sources.json5.

  Returns:
    Filtered list of (properties_dict, shapely_geometry) tuples.
  """
  # Convert from parameters
  features = arg1_features
  filter_cfg = arg2_filter_cfg if arg2_filter_cfg is not None else {}

  # Declare local instance variables.
  bad_sources = set()
  cleaned_features = []
  feat_flagged = []
  flag_val = False
  geom = None
  props = None
  ratio = 0.0
  ratio_limit = float(filter_cfg.get("source_schematic_ratio", 0.65))
  src = ""
  src_flagged = {}
  src_total = {}

  if not features:
    return []

  for props, geom in features:
    flag_val = _is_straight_transport_geom(geom, filter_cfg)
    feat_flagged.append((props, geom, flag_val))
    src = str((props or {}).get("source", ""))
    src_total[src] = src_total.get(src, 0) + 1
    if flag_val:
      src_flagged[src] = src_flagged.get(src, 0) + 1

  for src in src_total:
    ratio = float(src_flagged.get(src, 0)) / float(src_total[src])
    if ratio >= ratio_limit:
      bad_sources.add(src)

  for props, geom, flag_val in feat_flagged:
    src = str((props or {}).get("source", ""))
    if not flag_val and src not in bad_sources:
      cleaned_features.append((props, geom))

  # Return statement
  return cleaned_features


def E_clean_existing_transport_geojsons (arg1_cfg, arg2_gis_dir):
  """Clean existing railways and roads GeoJSON exports of straight-chord anomalies in place.

  Args:
    arg1_cfg: Parsed data_sources.json5 configuration dict.
    arg2_gis_dir: Path to the output gis directory.

  Returns:
    Dict mapping layer names to before/after feature counts.
  """
  # Convert from parameters
  cfg = arg1_cfg if arg1_cfg is not None else {}
  gis_dir = arg2_gis_dir

  # Declare local instance variables.
  after_count = 0
  before_count = 0
  cleaned = []
  data = None
  feat = None
  features = []
  file_name = ""
  file_path = ""
  filter_cfg = cfg.get("transport_straight_link_filter", {})
  geom = None
  layer_names = ("railways", "roads")
  precision = int(cfg.get("coordinate_precision", 5))
  props = None
  summary = {}

  for file_name in layer_names:
    file_path = os.path.join(gis_dir, "{0}_1912_1953.geojson".format(file_name))
    if not os.path.exists(file_path):
      continue
    with open(file_path, "r", encoding="utf-8") as handle:
      data = json.load(handle)
    features = []
    for feat in data.get("features", []):
      geom = shape(feat.get("geometry")) if feat.get("geometry") else None
      props = feat.get("properties") or {}
      if geom is not None and not geom.is_empty:
        features.append((props, geom))
    before_count = len(features)
    cleaned = D_filter_straight_transport_links(features, filter_cfg)
    after_count = gis_helpers.write_geojson(file_path, cleaned, precision)
    summary[file_name] = {
      "after": after_count,
      "before": before_count,
      "removed": before_count - after_count,
    }

  # Return statement
  return summary


def main ():
  """Execute Step 1 download, reprojection, cleaning, baseline, transport, and elevation export."""
  # Declare local instance variables.
  adm_annual_dir = ""
  base_dir = path_helpers.get_project_root()
  clean_only = "--clean-transport-only" in sys.argv[1:]
  elev_only = "--elevation-only" in sys.argv[1:]
  layers_dir = ""
  priors_dir = ""

  adm_annual_dir = path_helpers.resolve_path("output.gis.adm_annual_dir", base_dir)
  cfg = gis_helpers.load_json5(path_helpers.resolve_path("common.data_sources", base_dir))
  corridors = gis_helpers.load_json5(path_helpers.resolve_path("common.transport_corridors", base_dir))
  layers_dir = path_helpers.resolve_path("output.gis.layers_dir", base_dir)
  if cfg is None or corridors is None:
    return 1
  priors_dir = os.path.normpath(os.path.join(base_dir, str(cfg.get("elevation", {}).get("priors_dir") or "input/gis/priors")))
  os.makedirs(adm_annual_dir, exist_ok=True)
  os.makedirs(layers_dir, exist_ok=True)
  os.makedirs(priors_dir, exist_ok=True)

  if clean_only:
    clean_summary = E_clean_existing_transport_geojsons(cfg, layers_dir)
    print("[STEP 1E] Transport straight-link clean:", clean_summary)
    return 0

  paths = A_download_all_sources(cfg, base_dir)
  print("[STEP 1A] Sources ready:", len(paths))
  if not elev_only:
    adm_summary = B_build_1911_baseline(paths, cfg, base_dir)
    print("[STEP 1B] 1911 baseline:", adm_summary)
    tr_summary = C_build_transport_layers(paths, cfg, corridors, layers_dir)
    print("[STEP 1C] Transport layers:", tr_summary)
  elev_builder = ElevationContourBuilder(cfg, priors_dir, layers_dir)
  elev_summary = elev_builder.build_elevation_contours(paths)
  print("[STEP 1D] Elevation contours & relief:", elev_summary)
  return 0


if __name__ == "__main__":
  sys.exit(main())
