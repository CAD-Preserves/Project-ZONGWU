"""Shared GIS, JSON5, reprojection, and geometry helpers for Project-ZONGWU."""

from functools import lru_cache
import hashlib
import io
import json
import os
import sys
import zipfile
import numpy as np
import requests
import shapefile
from scipy import ndimage
from shapely import make_valid
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.ops import polygonize, unary_union

if os.path.abspath(os.path.join(os.path.dirname(__file__), "..")) not in sys.path:
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@lru_cache(maxsize=1)
def _load_lev1_ch_to_py ():
  """Lazy-load Chinese level-1 name to canonical pinyin lookup map from common/gis/admin_mappings.json5.

  @return Dict mapping Chinese level-1 name to canonical pinyin string.
  """
  # Declare local instance variables.
  from helpers import path_helpers
  map_path = path_helpers.resolve_path("common.admin_mappings")
  payload = load_json5(map_path) if map_path and os.path.exists(map_path) else {}

  # Return statement
  return dict(payload.get("lev1_ch_to_py", {}))


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

  # Declare local instance variables.
  lev1_map = _load_lev1_ch_to_py()

  if raw_ch in lev1_map:
    return lev1_map[raw_ch]
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


def _chaikin_smooth_chain (arg1_pts, arg2_is_loop, arg3_passes=2):
  """Smooth a polyline chain with Chaikin corner-cutting while fixing open-chain endpoints.

  @param arg1_pts List of (x, y) coordinate tuples.
  @param arg2_is_loop True when the chain forms a closed ring without degree-3+ junctions.
  @param arg3_passes Number of smoothing iterations.
  @return List of smoothed (x, y) tuples.
  """
  # Convert from parameters
  is_loop = bool(arg2_is_loop)
  passes = int(arg3_passes)
  pts = list(arg1_pts)

  if len(pts) < 3 or passes <= 0:
    return pts

  # Declare local instance variables.
  cur = pts
  nxt = []

  for _ in range(passes):
    n_pts = len(cur)
    if n_pts < 3:
      break
    nxt = []
    if is_loop:
      ring = cur[:-1] if cur[0] == cur[-1] else cur
      m = len(ring)
      if m < 3:
        break
      for i in range(m):
        p0 = ring[i]
        p1 = ring[(i + 1) % m]
        nxt.append((0.75*p0[0] + 0.25*p1[0], 0.75*p0[1] + 0.25*p1[1]))
        nxt.append((0.25*p0[0] + 0.75*p1[0], 0.25*p0[1] + 0.75*p1[1]))
      nxt.append(nxt[0])
    else:
      nxt.append(cur[0])
      for i in range(n_pts - 1):
        p0 = cur[i]
        p1 = cur[i + 1]
        if i > 0:
          nxt.append((0.75*p0[0] + 0.25*p1[0], 0.75*p0[1] + 0.25*p1[1]))
        if i + 1 < n_pts - 1:
          nxt.append((0.25*p0[0] + 0.75*p1[0], 0.25*p0[1] + 0.75*p1[1]))
      nxt.append(cur[-1])
    cur = nxt

  # Return statement
  return cur


def extract_seat_connected_partition (arg1_labels, arg2_in_domain, arg3_seat_rc, arg4_n_polities, arg5_allow_background):
  """Enforce a single seat-seeded 4-connected component per polity and fill interior pockets.

  @param arg1_labels 2D int32 label array (-1 outside, 0..K-1 polities, K background).
  @param arg2_in_domain 2D boolean mask of valid domain cells.
  @param arg3_seat_rc List of (row, col) locked seat indices.
  @param arg4_n_polities Number of competing polities K.
  @param arg5_allow_background Whether label K represents external background.
  @return Cleaned 2D int32 label array with zero detached polity islands or interior pockets.
  """
  # Convert from parameters
  allow_bg = bool(arg5_allow_background)
  in_dom = arg2_in_domain
  labels = np.array(arg1_labels, dtype=np.int32, copy=True)
  n_pol = int(arg4_n_polities)
  seat_rc = list(arg3_seat_rc)

  # Declare local instance variables.
  bg_id = n_pol
  comp = None
  h, w = labels.shape
  keep_id = 0
  padded = None
  struct4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.int32)

  for i in range(n_pol):
    sr, sc = seat_rc[i]
    labels[sr, sc] = i
    comp, n_comp = ndimage.label(labels == i, structure=struct4)
    if n_comp > 1:
      keep_id = int(comp[sr, sc])
      labels[(labels == i) & (comp != keep_id)] = -2

  if allow_bg:
    comp, n_comp = ndimage.label(labels == bg_id, structure=struct4)
    if n_comp > 0:
      ext_mask = np.zeros_like(in_dom)
      ext_mask[0, :] |= (labels[0, :] == bg_id)
      ext_mask[-1, :] |= (labels[-1, :] == bg_id)
      ext_mask[:, 0] |= (labels[:, 0] == bg_id)
      ext_mask[:, -1] |= (labels[:, -1] == bg_id)
      ext_mask[1:, :] |= ((labels[1:, :] == bg_id) & (labels[:-1, :] == -1))
      ext_mask[:-1, :] |= ((labels[:-1, :] == bg_id) & (labels[1:, :] == -1))
      ext_mask[:, 1:] |= ((labels[:, 1:] == bg_id) & (labels[:, :-1] == -1))
      ext_mask[:, :-1] |= ((labels[:, :-1] == bg_id) & (labels[:, 1:] == -1))
      touch_ids = set(int(v) for v in np.unique(comp[ext_mask]) if v > 0)
      for cid in range(1, n_comp + 1):
        if cid not in touch_ids:
          labels[comp == cid] = -2

  # Reassign detached -2 pixels to adjacent 4-neighbours in bounded for passes
  for _ in range(h + w + 4):
    un_mask = (labels == -2) & in_dom
    if not np.any(un_mask):
      break
    padded = np.pad(labels, 1, mode="constant", constant_values=-1)
    n_up = padded[:-2, 1:-1]
    n_dn = padded[2:, 1:-1]
    n_lt = padded[1:-1, :-2]
    n_rt = padded[1:-1, 2:]
    cand_stack = np.stack([n_up, n_dn, n_lt, n_rt], axis=0)
    best_lbl = np.full((h, w), -2, dtype=np.int32)
    best_cnt = np.zeros((h, w), dtype=np.int32)
    for lbl in range(n_pol + (1 if allow_bg else 0)):
      cnt = np.sum(cand_stack == lbl, axis=0)
      win = un_mask & (cnt > best_cnt)
      best_lbl[win] = lbl
      best_cnt[win] = cnt[win]
    upd = un_mask & (best_lbl >= 0)
    if not np.any(upd):
      break
    labels[upd] = best_lbl[upd]

  if np.any((labels == -2) & in_dom):
    if allow_bg:
      labels[(labels == -2) & in_dom] = bg_id
    else:
      rem_r, rem_c = np.where((labels == -2) & in_dom)
      seats_arr = np.asarray(seat_rc, dtype=np.float64)
      for idx in range(len(rem_r)):
        d2 = (seats_arr[:, 0] - rem_r[idx])**2 + (seats_arr[:, 1] - rem_c[idx])**2
        labels[rem_r[idx], rem_c[idx]] = int(np.argmin(d2))

  for i in range(n_pol):
    sr, sc = seat_rc[i]
    labels[sr, sc] = i

  # Return statement
  return labels


def polygonize_smoothed_partition (arg1_labels, arg2_grid_meta, arg3_domain_poly, arg4_seat_pts, arg5_n_polities, arg6_allow_background):
  """Convert a discrete 2D partition into watertight polygons via topological shared-chain smoothing.

  @param arg1_labels 2D int32 label array (-1 outside, 0..K-1 polities, K background).
  @param arg2_grid_meta Dict with x0, y0, step grid spacing parameters.
  @param arg3_domain_poly Clipping Shapely polygon for the cluster domain.
  @param arg4_seat_pts List of (lon, lat) seat tuples for 0..K-1.
  @param arg5_n_polities Number of polities K.
  @param arg6_allow_background True if label K represents background.
  @return Dict mapping polity index i -> clean valid Shapely Polygon inside arg3_domain_poly.
  """
  # Convert from parameters
  allow_bg = bool(arg6_allow_background)
  domain_poly = arg3_domain_poly
  grid_meta = arg2_grid_meta
  labels = arg1_labels
  n_pol = int(arg5_n_polities)
  seat_pts = list(arg4_seat_pts)

  # Declare local instance variables.
  adj = {}
  chains = []
  h, w = labels.shape
  pad = np.full((h + 2, w + 2), -1, dtype=np.int32)
  reg_sets = {}
  seat_pin_verts = set()
  step = float(grid_meta["step"])
  x0 = float(grid_meta["x0"])
  y0 = float(grid_meta["y0"])

  pad[1:-1, 1:-1] = labels
  for i in range(n_pol):
    sx, sy = seat_pts[i]
    sc = int(np.floor((sx - (x0 - 0.5*step)) / step))
    sr = int(np.floor((sy - (y0 - 0.5*step)) / step))
    for dr, dc in ((0, 0), (0, 1), (1, 0), (1, 1)):
      seat_pin_verts.add((sr + dr, sc + dc))

  def add_edge (u, v, a, b):
    pair = (a, b) if a < b else (b, a)
    adj.setdefault(u, []).append((v, pair))
    adj.setdefault(v, []).append((u, pair))
    for pt in (u, v):
      pr, pc = pt
      reg_sets.setdefault(pt, set()).update((int(pad[pr, pc]), int(pad[pr, pc + 1]), int(pad[pr + 1, pc]), int(pad[pr + 1, pc + 1])))

  hr, hc = np.where(pad[:-1, 1:-1] != pad[1:, 1:-1])
  for idx in range(len(hr)):
    vr, vc = int(hr[idx]), int(hc[idx])
    a, b = int(pad[vr, vc + 1]), int(pad[vr + 1, vc + 1])
    if a >= 0 or b >= 0:
      add_edge((vr, vc), (vr, vc + 1), a, b)

  vr_a, vc_a = np.where(pad[1:-1, :-1] != pad[1:-1, 1:])
  for idx in range(len(vr_a)):
    vr, vc = int(vr_a[idx]), int(vc_a[idx])
    a, b = int(pad[vr + 1, vc]), int(pad[vr + 1, vc + 1])
    if a >= 0 or b >= 0:
      add_edge((vr, vc), (vr + 1, vc), a, b)

  junctions = {u for u, nbs in adj.items() if len(nbs) != 2 or len(reg_sets.get(u, set())) >= 3 or u in seat_pin_verts}
  visited = set()
  max_walk = max(4, sum(len(v) for v in adj.values()) + 2)

  for is_loop_pass in (False, True):
    start_nodes = sorted(junctions) if not is_loop_pass else sorted(adj.keys())
    for u0 in start_nodes:
      for v0, pair0 in adj.get(u0, []):
        ek0 = (u0, v0) if u0 < v0 else (v0, u0)
        if ek0 in visited:
          continue
        visited.add(ek0)
        verts = [u0, v0]
        prev_u, cur_v = u0, v0
        for _ in range(max_walk):
          if (not is_loop_pass and cur_v in junctions) or (is_loop_pass and cur_v == u0):
            break
          nxt_item = next((cv for cv, cp in adj.get(cur_v, []) if cv != prev_u and cp == pair0), None)
          if nxt_item is None:
            break
          ek_n = (cur_v, nxt_item) if cur_v < nxt_item else (nxt_item, cur_v)
          if ek_n in visited:
            verts.append(nxt_item)
            break
          visited.add(ek_n)
          verts.append(nxt_item)
          prev_u, cur_v = cur_v, nxt_item
        pts = [(x0 + (vc - 0.5)*step, y0 + (vr - 0.5)*step) for vr, vc in verts]
        is_closed = (len(verts) >= 4 and verts[0] == verts[-1] and u0 not in junctions)
        sm_pts = _chaikin_smooth_chain(pts, is_closed, 2) if (pair0[0] >= 0 and pair0[1] >= 0) else pts
        chains.append((pair0, LineString(sm_pts)))

  all_seat_objs = [Point(seat_pts[j][0], seat_pts[j][1]) for j in range(n_pol)]
  out_polys = {}
  for i in range(n_pol):
    lines_sm = [sm_ln for pair, sm_ln in chains if i in pair]
    polys = [clean_polygonal_geometry(p) for p in polygonize(lines_sm)]
    polys = [p for p in polys if p is not None and not p.is_empty and not any(p.contains(all_seat_objs[j]) for j in range(n_pol) if j != i)]
    geom = clean_polygonal_geometry(unary_union(polys).intersection(domain_poly)) if polys else None
    spt = all_seat_objs[i]
    if geom is not None:
      if geom.geom_type == "MultiPolygon":
        geom = next((sub for sub in geom.geoms if sub.contains(spt) or sub.distance(spt) < 1e-9), max(geom.geoms, key=lambda g: g.area))
      if len(geom.interiors) > 0:
        kept_holes = [ring for ring in geom.interiors if any(Polygon(ring).contains(all_seat_objs[j]) for j in range(n_pol) if j != i)]
        geom = Polygon(geom.exterior, kept_holes)
      out_polys[i] = geom

  if not allow_bg and len(out_polys) == n_pol:
    rem = clean_polygonal_geometry(domain_poly.difference(unary_union(list(out_polys.values()))))
    if rem is not None and not rem.is_empty:
      for frag in ([rem] if rem.geom_type == "Polygon" else list(rem.geoms)):
        if frag.area <= 1e-11:
          continue
        best_i = max(out_polys.keys(), key=lambda idx: (frag.intersection(out_polys[idx]).length, -frag.distance(out_polys[idx])))
        merged = clean_polygonal_geometry(unary_union([out_polys[best_i], frag]))
        if merged is not None and merged.geom_type == "Polygon":
          if len(merged.interiors) > 0:
            merged = Polygon(merged.exterior, [r for r in merged.interiors if any(Polygon(r).contains(all_seat_objs[j]) for j in range(n_pol) if j != best_i)])
          out_polys[best_i] = merged

  # Return statement
  return out_polys


def smooth_discrete_partition (arg1_labels, arg2_in_domain, arg3_seat_rc, arg4_n_polities, arg5_allow_background, arg6_passes=3):
  """Apply seat-locked 3x3 majority smoothing passes on a discrete 2D raster partition.

  @param arg1_labels 2D int32 label array (-1 outside, 0..K-1 polities, K background).
  @param arg2_in_domain 2D boolean mask of valid domain pixels.
  @param arg3_seat_rc List of (row, col) locked seat indices.
  @param arg4_n_polities Number of competing polities K.
  @param arg5_allow_background True if label K represents background.
  @param arg6_passes Number of smoothing passes.
  @return Smoothed 2D int32 label array.
  """
  # Convert from parameters
  allow_bg = bool(arg5_allow_background)
  in_dom = arg2_in_domain
  labels = np.array(arg1_labels, dtype=np.int32, copy=True)
  n_pol = int(arg4_n_polities)
  passes = int(arg6_passes)
  seat_rc = list(arg3_seat_rc)

  # Declare local instance variables.
  h, w = labels.shape
  n_cls = n_pol + (1 if allow_bg else 0)
  seat_mask = np.zeros((h, w), dtype=bool)
  for sr, sc in seat_rc:
    seat_mask[sr, sc] = True

  for _ in range(passes):
    padded = np.pad(labels, 1, mode="constant", constant_values=-1)
    best_lbl = np.array(labels, dtype=np.int32, copy=True)
    best_cnt = np.zeros((h, w), dtype=np.int32)
    cur_cnt = sum((padded[dr:dr + h, dc:dc + w] == labels) for dr in range(3) for dc in range(3))
    for lbl in range(n_cls):
      cnt = sum((padded[dr:dr + h, dc:dc + w] == lbl) for dr in range(3) for dc in range(3))
      win = in_dom & (~seat_mask) & (cnt >= 5) & (cnt > cur_cnt + 1) & (cnt > best_cnt)
      best_lbl[win] = lbl
      best_cnt[win] = cnt[win]
    labels = best_lbl
    for i in range(n_pol):
      sr, sc = seat_rc[i]
      labels[sr, sc] = i

  # Return statement
  return labels
