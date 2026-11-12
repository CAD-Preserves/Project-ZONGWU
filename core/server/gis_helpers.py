"""Shared GIS, JSON5, reprojection, and geometry helpers for Project-ZONGWU."""

import hashlib
import io
import json
import os
import sys
import zipfile
import numpy as np
import requests
import shapefile
from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.ops import unary_union


# Normalisation map from Chinese level-1 name to canonical pinyin key
LEV1_CH_TO_PY = {
  "安徽": "Anhui",
  "奉天": "Fengtian",
  "福建": "Fujian",
  "甘肃": "Gansu",
  "广东": "Guangdong",
  "广西": "Guangxi",
  "贵州": "Guizhou",
  "黑龙江": "Heilongjiang",
  "河南": "Henan",
  "湖北": "Hubei",
  "湖南": "Hunan",
  "江苏": "Jiangsu",
  "江西": "Jiangxi",
  "吉林": "Jilin",
  "内蒙古": "Neimenggu",
  "青海": "Qinghai",
  "山东": "Shandong",
  "山西": "Shanxi",
  "陕西": "Shaanxi",
  "四川": "Sichuan",
  "台湾(日本占领)": "Taiwan",
  "台湾": "Taiwan",
  "乌里雅苏台": "Wuliyasutai",
  "新疆": "Xinjiang",
  "西藏": "Xizang",
  "云南": "Yunnan",
  "浙江": "Zhejiang",
  "直隶": "Zhili",
}


def clean_polygonal_geometry (arg1_geom):
  """Validate and extract only Polygon or MultiPolygon components from a Shapely geometry.

  @param arg1_geom Input Shapely geometry object.
  @return Clean polygonal Shapely geometry, or None when empty.
  """
  # Convert from parameters
  geom = arg1_geom

  if geom is None or geom.is_empty:
    return None

  if not geom.is_valid:
    geom = make_valid(geom)

  # Declare local instance variables.
  parts = []

  if geom.geom_type == "Polygon":
    if geom.area > 0.0:
      parts.append(geom)
  elif geom.geom_type == "MultiPolygon":
    for poly in geom.geoms:
      if poly.area > 0.0:
        parts.append(poly)
  elif geom.geom_type == "GeometryCollection":
    for sub in geom.geoms:
      if sub.geom_type == "Polygon" and sub.area > 0.0:
        parts.append(sub)
      elif sub.geom_type == "MultiPolygon":
        for poly in sub.geoms:
          if poly.area > 0.0:
            parts.append(poly)

  # Return statement
  if not parts:
    return None
  if len(parts) == 1:
    return parts[0]
  return MultiPolygon(parts)


def download_with_cache (arg1_url, arg2_dest_path):
  """Download a remote file to disk if not already cached.

  @param arg1_url Remote HTTP/HTTPS URL.
  @param arg2_dest_path Destination local filepath.
  @return True if available locally after call, False on failure.
  """
  # Convert from parameters
  dest_path = arg2_dest_path
  url = arg1_url

  if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
    return True

  os.makedirs(os.path.dirname(dest_path), exist_ok=True)
  headers = {"User-Agent": "Mozilla/5.0 (Project-ZONGWU/1.0)"}

  try:
    resp = requests.get(url, headers=headers, allow_redirects=True, timeout=180)
    if not resp.ok:
      print(f"[ERROR] HTTP {resp.status_code} downloading {url}", file=sys.stderr)
      return False
    with open(dest_path, "wb") as fh:
      fh.write(resp.content)
  except Exception as exc:
    print(f"[ERROR] Exception downloading {url}: {exc}", file=sys.stderr)
    return False

  # Return statement
  return True


def gk19_array_to_lonlat (arg1_coords):
  """Convert Xian 1980 Gauss-Kruger Zone 19 (eastings/northings in metres) to WGS84 lon/lat degrees.

  Uses the 8th-order Kruger inverse expansion matching CHGIS V6 WGS84 outputs to < 1e-7 degrees.
  @param arg1_coords Sequence or (N, 2) NumPy array of [x, y] coordinates.
  @return List of [lon, lat] pairs.
  """
  # Convert from parameters
  coords = np.asarray(arg1_coords, dtype=np.float64)

  if coords.size == 0:
    return []

  # Declare local instance variables.
  a = 6378140.0
  c1 = None
  cosp = None
  d = None
  dx = coords[:, 0] - 19500000.0
  e1 = None
  e2 = None
  ep2 = None
  f = 1.0 / 298.257
  lat = None
  lon = None
  lon0 = np.deg2rad(111.0)
  m = coords[:, 1]
  mu = None
  n1 = None
  phi1 = None
  r1 = None
  sinp = None
  t1 = None
  tanp = None

  e2 = 2.0*f - f*f
  ep2 = e2 / (1.0 - e2)
  e1 = (1.0 - np.sqrt(1.0 - e2)) / (1.0 + np.sqrt(1.0 - e2))
  mu = m / (a*(1.0 - e2/4.0 - 3.0*(e2**2)/64.0 - 5.0*(e2**3)/256.0))
  phi1 = (
    mu
    + (3.0*e1/2.0 - 27.0*(e1**3)/32.0)*np.sin(2.0*mu)
    + (21.0*(e1**2)/16.0 - 55.0*(e1**4)/32.0)*np.sin(4.0*mu)
    + (151.0*(e1**3)/96.0)*np.sin(6.0*mu)
    + (1097.0*(e1**4)/512.0)*np.sin(8.0*mu)
  )
  sinp = np.sin(phi1)
  cosp = np.cos(phi1)
  tanp = np.tan(phi1)
  n1 = a / np.sqrt(1.0 - e2*(sinp**2))
  t1 = tanp**2
  c1 = ep2*(cosp**2)
  r1 = a*(1.0 - e2) / ((1.0 - e2*(sinp**2))**1.5)
  d = dx / n1

  lat = phi1 - (n1*tanp/r1)*(
    (d**2)/2.0
    - (5.0 + 3.0*t1 + 10.0*c1 - 4.0*(c1**2) - 9.0*ep2)*(d**4)/24.0
    + (61.0 + 90.0*t1 + 298.0*c1 + 45.0*(t1**2) - 252.0*ep2 - 3.0*(c1**2))*(d**6)/720.0
    - (1385.0 + 3633.0*t1 + 4095.0*(t1**2) + 1575.0*(t1**3))*(d**8)/40320.0
  )
  lon = lon0 + (
    d
    - (1.0 + 2.0*t1 + c1)*(d**3)/6.0
    + (5.0 - 2.0*c1 + 28.0*t1 - 3.0*(c1**2) + 8.0*ep2 + 24.0*(t1**2))*(d**5)/120.0
    - (61.0 + 662.0*t1 + 1320.0*(t1**2) + 720.0*(t1**3))*(d**7)/5040.0
  ) / cosp

  # Return statement
  return np.column_stack([np.rad2deg(lon), np.rad2deg(lat)]).tolist()


def load_json5 (arg1_filepath):
  """Load a JSON5 file supporting // line comments, /* */ block comments, and trailing commas.

  @param arg1_filepath Path to JSON5 file.
  @return Parsed Python object, or None on error.
  """
  # Convert from parameters
  filepath = arg1_filepath

  if not os.path.exists(filepath):
    print(f"[ERROR] JSON5 file not found: {filepath}", file=sys.stderr)
    return None

  with open(filepath, "r", encoding="utf-8") as fh:
    raw = fh.read()

  # Strip comments while respecting quoted strings
  chars = []
  in_block = False
  in_line = False
  in_string = False
  n = len(raw)
  skip_next = False
  string_char = ""

  for i in range(n):
    if skip_next:
      skip_next = False
      continue
    ch = raw[i]
    nxt = raw[i + 1] if i + 1 < n else ""

    if in_line:
      if ch == "\n":
        in_line = False
        chars.append(ch)
      continue
    if in_block:
      if ch == "*" and nxt == "/":
        in_block = False
        skip_next = True
      continue
    if in_string:
      chars.append(ch)
      if ch == "\\" and nxt != "":
        chars.append(nxt)
        skip_next = True
      elif ch == string_char:
        in_string = False
      continue

    if ch in ('"', "'"):
      in_string = True
      string_char = ch
      chars.append(ch)
    elif ch == "/" and nxt == "/":
      in_line = True
      skip_next = True
    elif ch == "/" and nxt == "*":
      in_block = True
      skip_next = True
    else:
      chars.append(ch)

  cleaned = "".join(chars)
  # Strip trailing commas outside strings before } or ]
  out = []
  in_string = False
  m = len(cleaned)
  skip_next = False

  for i in range(m):
    if skip_next:
      skip_next = False
      continue
    ch = cleaned[i]
    if in_string:
      out.append(ch)
      if ch == "\\" and i + 1 < m:
        out.append(cleaned[i + 1])
        skip_next = True
      elif ch == string_char:
        in_string = False
      continue
    if ch in ('"', "'"):
      in_string = True
      string_char = ch
      out.append(ch)
      continue
    if ch == ",":
      # Look ahead past whitespace for ] or }
      is_trailing = False
      for x in range(i + 1, m):
        c2 = cleaned[x]
        if c2 in (" ", "\t", "\r", "\n"):
          continue
        if c2 in ("]", "}"):
          is_trailing = True
        break
      if not is_trailing:
        out.append(ch)
      continue
    out.append(ch)

  # Return statement
  return json.loads("".join(out))


def normalise_lev1_name (arg1_raw_py, arg2_raw_ch):
  """Resolve canonical level-1 pinyin name from Chinese name to correct CHGIS typos.

  @param arg1_raw_py Raw LEV1_PY or NAME_PY string.
  @param arg2_raw_ch Raw LEV1_CH or NAME_CH string.
  @return Canonical level-1 pinyin string.
  """
  # Convert from parameters
  raw_ch = str(arg2_raw_ch or "").strip()
  raw_py = str(arg1_raw_py or "").strip()

  if raw_ch in LEV1_CH_TO_PY:
    return LEV1_CH_TO_PY[raw_ch]
  if raw_py == "Taiwan(Japan Occupied)":
    return "Taiwan"
  if raw_py == "Meimenggu":
    return "Neimenggu"
  if raw_py == "Shangdong":
    return "Shandong"
  if raw_py == "Wliyasutai":
    return "Wuliyasutai"

  # Return statement
  return raw_py


def read_zip_shapefile_wgs84 (arg1_zip_path, arg2_encoding="utf-8", arg3_precision=5):
  """Read a zipped ESRI Shapefile and convert its geometries to clean WGS84 Shapely geometries.

  @param arg1_zip_path Path to local .zip shapefile archive.
  @param arg2_encoding DBF text encoding (e.g. 'utf-8' or 'gb18030').
  @param arg3_precision Coordinate rounding precision in decimal degrees.
  @return List of (properties_dict, shapely_geometry) tuples.
  """
  # Convert from parameters
  encoding = arg2_encoding
  precision = arg3_precision
  zip_path = arg1_zip_path

  if not os.path.exists(zip_path):
    print(f"[ERROR] Shapefile zip missing: {zip_path}", file=sys.stderr)
    return []

  # Declare local instance variables.
  dbf_bytes = None
  features = []
  fields = None
  is_projected = False
  prj_text = ""
  sf = None
  shp_bytes = None

  with zipfile.ZipFile(zip_path, "r") as zf:
    names = zf.namelist()
    shp_names = [n for n in names if n.lower().endswith(".shp")]
    dbf_names = [n for n in names if n.lower().endswith(".dbf")]
    prj_names = [n for n in names if n.lower().endswith(".prj")]

    if not shp_names or not dbf_names:
      print(f"[ERROR] Missing .shp or .dbf in {zip_path}", file=sys.stderr)
      return []

    shp_bytes = zf.read(shp_names[0])
    dbf_bytes = zf.read(dbf_names[0])
    if prj_names:
      prj_text = zf.read(prj_names[0]).decode("utf-8", errors="replace")

  is_projected = ("PROJCS" in prj_text) or ("Gauss_Kruger" in prj_text) or ("Transverse_Mercator" in prj_text)
  sf = shapefile.Reader(shp=io.BytesIO(shp_bytes), dbf=io.BytesIO(dbf_bytes), encoding=encoding, encodingErrors="replace")
  fields = [f[0] for f in sf.fields[1:]]

  if not is_projected and len(sf) > 0:
    bbox = sf.bbox
    if abs(bbox[0]) > 360.0 or abs(bbox[2]) > 360.0:
      is_projected = True

  for i in range(len(sf)):
    rec = dict(zip(fields, sf.record(i)))
    shp_obj = sf.shape(i)
    if shp_obj.shapeType == shapefile.NULL or not shp_obj.points:
      continue
    geom_dict = shp_obj.__geo_interface__
    if is_projected:
      geom_dict = _reproject_geo_interface(geom_dict, precision)
    else:
      geom_dict = _round_geo_interface(geom_dict, precision)

    if geom_dict is None:
      continue
    geom = shape(geom_dict)
    gtype = geom.geom_type
    if "Polygon" in gtype:
      geom = clean_polygonal_geometry(geom)
    if geom is not None and not geom.is_empty:
      features.append((rec, geom))

  # Return statement
  return features


def _reproject_geo_interface (arg1_geom_dict, arg2_precision):
  """Reproject a GeoJSON geometry dict from Xian 1980 GK19 to WGS84 with rounding."""
  # Convert from parameters
  geom_dict = arg1_geom_dict
  precision = arg2_precision

  gtype = geom_dict.get("type", "")
  coords = geom_dict.get("coordinates")
  if coords is None:
    return None

  if gtype == "Point":
    if len(coords) < 2:
      return None
    ll = gk19_array_to_lonlat([coords[:2]])[0]
    new_coords = [round(ll[0], precision), round(ll[1], precision)]
  elif gtype in ("MultiPoint", "LineString"):
    pts = gk19_array_to_lonlat([c[:2] for c in coords])
    new_coords = [[round(p[0], precision), round(p[1], precision)] for p in pts]
  elif gtype in ("MultiLineString", "Polygon"):
    new_coords = []
    for ring in coords:
      pts = gk19_array_to_lonlat([c[:2] for c in ring])
      new_coords.append([[round(p[0], precision), round(p[1], precision)] for p in pts])
  elif gtype == "MultiPolygon":
    new_coords = []
    for poly in coords:
      new_poly = []
      for ring in poly:
        pts = gk19_array_to_lonlat([c[:2] for c in ring])
        new_poly.append([[round(p[0], precision), round(p[1], precision)] for p in pts])
      new_coords.append(new_poly)
  else:
    return None

  # Return statement
  return {"type": gtype, "coordinates": new_coords}


def _round_geo_interface (arg1_geom_dict, arg2_precision):
  """Round coordinates of a WGS84 GeoJSON geometry dict."""
  # Convert from parameters
  geom_dict = arg1_geom_dict
  precision = arg2_precision

  gtype = geom_dict.get("type", "")
  coords = geom_dict.get("coordinates")
  if coords is None:
    return None

  if gtype == "Point":
    new_coords = [round(float(coords[0]), precision), round(float(coords[1]), precision)]
  elif gtype in ("MultiPoint", "LineString"):
    new_coords = [[round(float(c[0]), precision), round(float(c[1]), precision)] for c in coords]
  elif gtype in ("MultiLineString", "Polygon"):
    new_coords = [[[round(float(c[0]), precision), round(float(c[1]), precision)] for c in ring] for ring in coords]
  elif gtype == "MultiPolygon":
    new_coords = [
      [[[round(float(c[0]), precision), round(float(c[1]), precision)] for c in ring] for ring in poly]
      for poly in coords
    ]
  elif gtype == "GeometryCollection":
    geoms = []
    for sub in geom_dict.get("geometries", []):
      sub_r = _round_geo_interface(sub, precision)
      if sub_r is not None:
        geoms.append(sub_r)
    return {"type": "GeometryCollection", "geometries": geoms} if geoms else None
  else:
    return None

  # Return statement
  return {"type": gtype, "coordinates": new_coords}


def round_geometry (arg1_geom, arg2_precision=5):
  """Round coordinates of any Shapely geometry to the specified decimal precision.

  @param arg1_geom Shapely geometry.
  @param arg2_precision Decimal places for WGS84 degrees.
  @return Rounded Shapely geometry.
  """
  # Convert from parameters
  geom = arg1_geom
  precision = arg2_precision

  if geom is None or geom.is_empty:
    return geom

  rounded_dict = _round_geo_interface(mapping(geom), precision)
  out_geom = shape(rounded_dict)
  if "Polygon" in out_geom.geom_type:
    out_geom = clean_polygonal_geometry(out_geom)

  # Return statement
  return out_geom


def slugify_snake (arg1_text):
  """Convert a placename into a clean ASCII snake_case identifier.

  @param arg1_text Input string.
  @return snake_case string.
  """
  # Convert from parameters
  text = str(arg1_text or "").strip().lower()

  replacements = [
    ("ü", "u"), ("ö", "o"), ("ä", "a"), ("é", "e"), ("è", "e"), ("á", "a"), ("í", "i"), ("ó", "o"), ("ú", "u"),
    ("'", ""), ("’", ""), ("-", "_"), ("/", "_"), ("(", "_"), (")", "_"), (" ", "_"), (".", "_"), (",", "_"),
  ]
  for old, new in replacements:
    text = text.replace(old, new)

  chars = []
  prev_us = False
  for ch in text:
    if ch.isalnum():
      chars.append(ch)
      prev_us = False
    elif ch == "_" and not prev_us and chars:
      chars.append("_")
      prev_us = True

  res = "".join(chars).strip("_")
  # Return statement
  return res if res else "unknown_unit"


def split_stacked_banners (arg1_items):
  """Partition overlapping/stacked nomadic banner polygons via clipped Voronoi cells.

  @param arg1_items List of dicts containing 'geom', 'lon', 'lat', and metadata.
  @return Updated list with non-overlapping partitioned 'geom' values.
  """
  # Convert from parameters
  items = arg1_items

  # Declare local instance variables.
  groups = []
  n = len(items)
  visited = [False]*n

  for i in range(n):
    if visited[i]:
      continue
    g_i = items[i]["geom"]
    if g_i is None or g_i.is_empty or g_i.area <= 0.0:
      continue
    cluster = [i]
    for x in range(i + 1, n):
      if visited[x]:
        continue
      g_x = items[x]["geom"]
      if g_x is None or g_x.is_empty:
        continue
      if not g_i.bounds[0] > g_x.bounds[2] and not g_x.bounds[0] > g_i.bounds[2]:
        inter_a = g_i.intersection(g_x).area
        union_a = g_i.area + g_x.area - inter_a
        if union_a > 0.0 and (inter_a / union_a) > 0.85:
          cluster.append(x)
    for idx in cluster:
      visited[idx] = True
    if len(cluster) > 1:
      groups.append(cluster)

  for cluster in groups:
    domain = clean_polygonal_geometry(unary_union([items[idx]["geom"] for idx in cluster]))
    if domain is None or domain.is_empty:
      continue
    seeds = []
    minx, miny, maxx, maxy = domain.bounds
    for k, idx in enumerate(cluster):
      sx = float(items[idx].get("lon") or 0.0)
      sy = float(items[idx].get("lat") or 0.0)
      if not (minx <= sx <= maxx and miny <= sy <= maxy):
        # Deterministic jittered fallback inside domain
        angle = 2.0*np.pi*(k / float(len(cluster)))
        c = domain.representative_point()
        sx = c.x + 0.08*np.cos(angle)
        sy = c.y + 0.08*np.sin(angle)
      # Disambiguate identical seed coordinates slightly
      for prev_sx, prev_sy in seeds:
        if abs(sx - prev_sx) < 1e-4 and abs(sy - prev_sy) < 1e-4:
          sx += 0.015*(k + 1)
          sy += 0.012*((k % 3) - 1)
      seeds.append((sx, sy))

    # Build exact half-plane clipped Voronoi cell for each seed
    pad = max(maxx - minx, maxy - miny) + 2.0
    for a, idx in enumerate(cluster):
      sx, sy = seeds[a]
      cell = box(minx - pad, miny - pad, maxx + pad, maxy + pad)
      for b in range(len(cluster)):
        if a == b:
          continue
        ox, oy = seeds[b]
        dx = ox - sx
        dy = oy - sy
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
          continue
        mx = 0.5*(sx + ox)
        my = 0.5*(sy + oy)
        # Half-plane where (p - m) . (o - s) <= 0
        norm = np.hypot(dx, dy)
        nx = dx / norm
        ny = dy / norm
        tx = -ny
        ty = nx
        ext = pad*4.0
        hp = Polygon([
          (mx - tx*ext, my - ty*ext),
          (mx + tx*ext, my + ty*ext),
          (mx + tx*ext - nx*ext, my + ty*ext - ny*ext),
          (mx - tx*ext - nx*ext, my - ty*ext - ny*ext),
        ])
        cell = cell.intersection(hp)
      clipped = clean_polygonal_geometry(domain.intersection(cell))
      if clipped is not None and not clipped.is_empty:
        items[idx]["geom"] = clipped

  # Return statement
  return items


def write_geojson (arg1_filepath, arg2_features, arg3_precision=5):
  """Write a list of (properties, shapely_geometry) pairs to an RFC 7946 GeoJSON FeatureCollection.

  @param arg1_filepath Destination .geojson path.
  @param arg2_features Iterable of (props_dict, shapely_geom) tuples.
  @param arg3_precision Decimal rounding precision.
  @return Number of features written.
  """
  # Convert from parameters
  features = arg2_features
  filepath = arg1_filepath
  precision = arg3_precision

  os.makedirs(os.path.dirname(filepath), exist_ok=True)
  fc_features = []

  for props, geom in features:
    if geom is None or geom.is_empty:
      continue
    g_out = round_geometry(geom, precision)
    if g_out is None or g_out.is_empty:
      continue
    fc_features.append({
      "type": "Feature",
      "properties": props,
      "geometry": mapping(g_out),
    })

  payload = {
    "type": "FeatureCollection",
    "features": fc_features,
  }
  with open(filepath, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))

  # Return statement
  return len(fc_features)
