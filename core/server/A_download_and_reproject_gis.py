"""Step 1 pipeline: download CHGIS/GADM/Natural Earth sources, reproject to WGS84, clean, and export 1911 baseline + transport."""

import io
import json
import os
import sys
import zipfile
from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, Polygon, box, shape
from shapely.ops import unary_union
from shapely.prepared import prep

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elevation_helpers
import gis_helpers


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


def _map_taiwan_cho_1911 (arg1_name_2):
  """Map GADM TWN_2 county/city name to 1911-1920 Japanese Taiwan 12 Cho."""
  # Convert from parameters
  name = str(arg1_name_2 or "").strip()

  mapping_table = {
    "Keelung": ("Taihoku Cho", "台北厅"),
    "NewTaipei": ("Taihoku Cho", "台北厅"),
    "Taipei": ("Taihoku Cho", "台北厅"),
    "Yilan": ("Giran Cho", "宜兰厅"),
    "Taoyuan": ("Toen Cho", "桃园厅"),
    "Hsinchu": ("Shinchiku Cho", "新竹厅"),
    "HsinchuCounty": ("Shinchiku Cho", "新竹厅"),
    "HsinchuCity": ("Shinchiku Cho", "新竹厅"),
    "Miaoli": ("Shinchiku Cho", "新竹厅"),
    "Taichung": ("Taichu Cho", "台中厅"),
    "Changhua": ("Taichu Cho", "台中厅"),
    "Nantou": ("Nanto Cho", "南投厅"),
    "Yunlin": ("Kagi Cho", "嘉义厅"),
    "Yulin": ("Kagi Cho", "嘉义厅"),
    "Chiayi": ("Kagi Cho", "嘉义厅"),
    "ChiayiCounty": ("Kagi Cho", "嘉义厅"),
    "ChiayiCity": ("Kagi Cho", "嘉义厅"),
    "Tainan": ("Tainan Cho", "台南厅"),
    "Kaohsiung": ("Tainan Cho", "台南厅"),
    "Pingtung": ("Ako Cho", "阿缑厅"),
    "Taitung": ("Taito Cho", "台东厅"),
    "Hualien": ("Karenko Cho", "花莲港厅"),
    "Penghu": ("Hoko Cho", "澎湖厅"),
  }

  # Return statement
  return mapping_table.get(name, ("Taihoku Cho", "台北厅"))


def A_download_all_sources (arg1_cfg, arg2_sources_dir):
  """Download and cache all Dataverse, GADM, and Natural Earth source files.

  @param arg1_cfg Parsed data_sources.json5 configuration dictionary.
  @param arg2_sources_dir Local cache directory ./gis/sources/.
  @return Dictionary mapping logical source keys to local filepaths.
  """
  # Convert from parameters
  cfg = arg1_cfg
  sources_dir = arg2_sources_dir

  # Declare local instance variables.
  base_url = cfg["chgis_dataverse"]["base_url"]
  local_paths = {}

  for key, meta in cfg["chgis_dataverse"]["files"].items():
    dest = os.path.join(sources_dir, meta["filename"])
    url = f"{base_url}{meta['file_id']}"
    ok = gis_helpers.download_with_cache(url, dest)
    if ok:
      local_paths[key] = dest

  for key, meta in cfg["gadm"]["files"].items():
    dest = os.path.join(sources_dir, meta["filename"])
    ok = gis_helpers.download_with_cache(meta["url"], dest)
    if ok:
      local_paths[key] = dest

  for key, meta in cfg["natural_earth"]["files"].items():
    dest = os.path.join(sources_dir, meta["filename"])
    ok = gis_helpers.download_with_cache(meta["url"], dest)
    if ok:
      local_paths[key] = dest

  for key, meta in cfg.get("hydrosheds", {}).get("files", {}).items():
    dest = os.path.join(sources_dir, meta["filename"])
    ok = gis_helpers.download_with_cache(meta["url"], dest)
    if ok:
      local_paths[key] = dest

  # Return statement
  return local_paths


def B_build_1911_baseline (arg1_paths, arg2_cfg, arg3_gis_dir):
  """Reproject, clean, and export adm_1_1911.geojson, adm_2_1911.geojson, and adm_3_1911.geojson.

  @param arg1_paths Dictionary of local source filepaths.
  @param arg2_cfg Parsed data_sources.json5 configuration dictionary.
  @param arg3_gis_dir Output ./gis/ directory.
  @return Summary dictionary of exported feature counts.
  """
  # Convert from parameters
  cfg = arg2_cfg
  gis_dir = arg3_gis_dir
  paths = arg1_paths

  # Declare local instance variables.
  adm1_features = []
  adm2_features = []
  adm3_features = []
  precision = int(cfg.get("coordinate_precision", 5))
  raw_cnty = gis_helpers.read_zip_shapefile_wgs84(paths["chgis_1911_cnty"], "utf-8", precision)
  raw_pref = gis_helpers.read_zip_shapefile_wgs84(paths["chgis_1911_pref"], "utf-8", precision)
  raw_prov = gis_helpers.read_zip_shapefile_wgs84(paths["chgis_1911_prov"], "utf-8", precision)
  twn_gadm = _load_gadm_geojson_from_path(paths["gadm_twn_2"])

  # 1. Level-1 (Provinces & Frontier Regions)
  for rec, geom in raw_prov:
    name_py = gis_helpers.normalise_lev1_name(rec.get("NAME_PY"), rec.get("NAME_CH"))
    name_ch = str(rec.get("NAME_CH") or "").strip()
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
  cnty_geoms_by_l1 = {}
  for item in cnty_items:
    rec = item["rec"]
    l1 = item["lev1_py"]
    l2 = str(rec.get("LEV2_PY") or "").strip()
    cnty_geoms_by_l1.setdefault(l1, []).append(item["geom"])
    props = {
      "adm_level": 3,
      "country": "Qing Empire",
      "name_ch": item["name_ch"],
      "name_en": item["name_py"],
      "occupied_by": "",
      "parent_adm1": l1,
      "parent_adm2": l2,
      "sys_id": str(rec.get("SYS_ID") or ""),
      "type_py": str(rec.get("TYPE_PY") or ""),
      "unit_id": f"cnty_{gis_helpers.slugify_snake(l1)}_{gis_helpers.slugify_snake(item['name_py'])}_{rec.get('SYS_ID','')}",
      "year": 1911,
    }
    adm3_features.append((props, item["geom"]))

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
      adm3_features.append((
        {
          "adm_level": 3,
          "country": "Qing Empire",
          "name_ch": f"{props2['name_ch']}直辖",
          "name_en": f"{props2['name_en']} Direct",
          "occupied_by": "",
          "parent_adm1": l1,
          "parent_adm2": props2["name_en"],
          "sys_id": f"FILL_{props2['sys_id']}",
          "type_py": "Zhixiadi",
          "unit_id": f"cnty_fill_{gis_helpers.slugify_snake(l1)}_{gis_helpers.slugify_snake(props2['name_en'])}",
          "year": 1911,
        },
        diff,
      ))

  c1 = gis_helpers.write_geojson(os.path.join(gis_dir, "adm_1_1911.geojson"), adm1_features, precision)
  c2 = gis_helpers.write_geojson(os.path.join(gis_dir, "adm_2_1911.geojson"), adm2_features, precision)
  c3 = gis_helpers.write_geojson(os.path.join(gis_dir, "adm_3_1911.geojson"), adm3_features, precision)

  # Return statement
  return {"adm_1_1911": c1, "adm_2_1911": c2, "adm_3_1911": c3}


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
  @param arg4_gis_dir Output ./gis/ directory.
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

  cw = gis_helpers.write_geojson(os.path.join(gis_dir, "waterways_1912_1953.geojson"), water_features, precision)
  cr = gis_helpers.write_geojson(os.path.join(gis_dir, "railways_1912_1953.geojson"), rail_features, precision)
  cd = gis_helpers.write_geojson(os.path.join(gis_dir, "roads_1912_1953.geojson"), road_features, precision)

  # Return statement
  return {"railways": cr, "roads": cd, "waterways": cw}


def main ():
  """Execute Step 1 download, reprojection, cleaning, baseline, transport, and elevation export."""
  base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
  common_gis = os.path.join(base_dir, "common", "gis")
  elev_only = "--elevation-only" in sys.argv[1:]
  gis_dir = os.path.join(base_dir, "gis")
  sources_dir = os.path.join(gis_dir, "sources")

  cfg = gis_helpers.load_json5(os.path.join(common_gis, "data_sources.json5"))
  corridors = gis_helpers.load_json5(os.path.join(common_gis, "transport_corridors.json5"))
  if cfg is None or corridors is None:
    return 1

  paths = A_download_all_sources(cfg, sources_dir)
  print("[STEP 1A] Sources ready:", len(paths))
  if not elev_only:
    adm_summary = B_build_1911_baseline(paths, cfg, gis_dir)
    print("[STEP 1B] 1911 baseline:", adm_summary)
    tr_summary = C_build_transport_layers(paths, cfg, corridors, gis_dir)
    print("[STEP 1C] Transport layers:", tr_summary)
  elev_builder = elevation_helpers.ElevationContourBuilder(cfg, sources_dir, gis_dir)
  elev_summary = elev_builder.build_elevation_contours(paths)
  print("[STEP 1D] Elevation contours & relief:", elev_summary)
  return 0


if __name__ == "__main__":
  sys.exit(main())
