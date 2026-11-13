"""AWS Terrarium DEM loader, WGS84 contour generator, and relief query helper."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
import math
import os
import sys
import zipfile
import contourpy
import numpy as np
from PIL import Image
import requests
from scipy import ndimage
import shapefile
from shapely.geometry import LineString, Point, box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gis_helpers


class ElevationContourBuilder:
  """Downloads AWS Mapzen Terrarium DEM tiles, exports elevation contours, and serves DEM relief queries."""

  def __init__ (self, arg1_cfg, arg2_sources_dir, arg3_gis_dir):
    """Initialise DEM tile grid parameters and cache paths.

    @param arg1_cfg Parsed data_sources.json5 dictionary.
    @param arg2_sources_dir Path to ./gis/sources/.
    @param arg3_gis_dir Path to ./gis/.
    """
    # Convert from parameters
    cfg = arg1_cfg
    gis_dir = arg3_gis_dir
    sources_dir = arg2_sources_dir

    # Declare local instance variables.
    ecfg = cfg.get("elevation", {})
    self.bbox = cfg["bounding_box"]
    self.cache_path = os.path.join(sources_dir, str(ecfg.get("cache_npz") or "terrarium_dem_z7_z8.npz"))
    self.cfg = cfg
    self.ecfg = ecfg
    self.fr_bbox = ecfg.get("frontier_bbox", self.bbox)
    self.fr_dem = None
    self.fr_lats = None
    self.fr_lons = None
    self.gis_dir = gis_dir
    self.ov_dem = None
    self.ov_lats = None
    self.ov_lons = None
    self.precision = int(cfg.get("coordinate_precision", 5))
    self.sources_dir = sources_dir
    self.tile_cache_dir = os.path.join(sources_dir, "terrarium_tiles")

  def _deg_to_tile (self, arg1_lon, arg2_lat, arg3_zoom):
    """Convert WGS84 lon/lat to Slippy Map tile indices (xtile, ytile) at arg3_zoom.

    @param arg1_lon Longitude in degrees.
    @param arg2_lat Latitude in degrees.
    @param arg3_zoom Web Mercator zoom level.
    @return Tuple (xtile, ytile).
    """
    # Convert from parameters
    lat = float(arg2_lat)
    lon = float(arg1_lon)
    zoom = int(arg3_zoom)

    lat_rad = math.radians(max(-85.0, min(85.0, lat)))
    n = float(1 << zoom)
    xt = int((lon + 180.0) / 360.0*n)
    yt = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi)*0.5*n)

    # Return statement
    return max(0, min(int(n) - 1, xt)), max(0, min(int(n) - 1, yt))

  def _fetch_single_tile (self, arg1_zoom, arg2_x, arg3_y, arg4_url_tpl):
    """Download or load from disk cache a single 256x256 Terrarium PNG tile and decode elevations in metres.

    @param arg1_zoom Web Mercator zoom level.
    @param arg2_x Tile X index.
    @param arg3_y Tile Y index.
    @param arg4_url_tpl URL template containing {z}, {x}, {y}.
    @return Tuple (x, y, float32_256x256_array).
    """
    # Convert from parameters
    tx = int(arg2_x)
    ty = int(arg3_y)
    url_tpl = str(arg4_url_tpl)
    zoom = int(arg1_zoom)

    # Declare local instance variables.
    raw_bytes = None
    tpath = os.path.join(self.tile_cache_dir, f"z{zoom}", f"{tx}_{ty}.png")

    if os.path.exists(tpath) and os.path.getsize(tpath) > 0:
      with open(tpath, "rb") as fh:
        raw_bytes = fh.read()
    else:
      url = url_tpl.format(z=zoom, x=tx, y=ty)
      for _ in range(3):
        try:
          resp = requests.get(url, headers={"User-Agent": "Project-ZONGWU/1.0"}, timeout=30)
          if resp.ok and len(resp.content) > 100:
            raw_bytes = resp.content
            os.makedirs(os.path.dirname(tpath), exist_ok=True)
            with open(tpath, "wb") as fh:
              fh.write(raw_bytes)
            break
        except Exception:
          pass

    if raw_bytes is None:
      return tx, ty, np.zeros((256, 256), dtype=np.float32)

    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    arr = np.asarray(img, dtype=np.float32)
    elev = (arr[:, :, 0]*256.0 + arr[:, :, 1] + arr[:, :, 2]/256.0) - 32768.0

    # Return statement
    return tx, ty, elev

  def _fetch_zoom_grid (self, arg1_bbox, arg2_zoom, arg3_step_deg):
    """Assemble and resample Terrarium DEM tiles at arg2_zoom onto a regular WGS84 grid.

    @param arg1_bbox Bounding box dict with min_lon, max_lon, min_lat, max_lat.
    @param arg2_zoom Web Mercator zoom level.
    @param arg3_step_deg Output regular WGS84 degree spacing.
    @return Tuple (lons_1d, lats_1d, elev_2d_float32).
    """
    # Convert from parameters
    bb = arg1_bbox
    step = float(arg3_step_deg)
    zoom = int(arg2_zoom)

    # Declare local instance variables.
    max_lat = float(bb["max_lat"]) + 0.5
    max_lon = float(bb["max_lon"]) + 0.5
    min_lat = float(bb["min_lat"]) - 0.5
    min_lon = float(bb["min_lon"]) - 0.5
    n_world = float(1 << zoom)
    url_tpl = str(self.ecfg.get("terrarium_tile_url") or "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png")

    x0, y0 = self._deg_to_tile(min_lon, max_lat, zoom)
    x1, y1 = self._deg_to_tile(max_lon, min_lat, zoom)
    nx = x1 - x0 + 1
    ny = y1 - y0 + 1
    mosaic = np.zeros((ny*256, nx*256), dtype=np.float32)
    jobs = [(tx, ty) for ty in range(y0, y1 + 1) for tx in range(x0, x1 + 1)]

    with ThreadPoolExecutor(max_workers=16) as pool:
      futs = [pool.submit(self._fetch_single_tile, zoom, tx, ty, url_tpl) for tx, ty in jobs]
      for fut in as_completed(futs):
        tx, ty, tile = fut.result()
        rx = (tx - x0)*256
        ry = (ty - y0)*256
        mosaic[ry:ry + 256, rx:rx + 256] = tile

    lons = np.arange(float(bb["min_lon"]) - 0.15, float(bb["max_lon"]) + 0.15 + 0.5*step, step, dtype=np.float64)
    lats = np.arange(float(bb["min_lat"]) - 0.15, float(bb["max_lat"]) + 0.15 + 0.5*step, step, dtype=np.float64)
    px_x = ((lons + 180.0)/360.0*n_world - float(x0))*256.0
    lat_r = np.deg2rad(lats)
    px_y = ((1.0 - np.arcsinh(np.tan(lat_r))/math.pi)*0.5*n_world - float(y0))*256.0
    gx, gy = np.meshgrid(px_x, px_y)
    elev = ndimage.map_coordinates(mosaic, [gy, gx], order=1, mode="nearest").astype(np.float32)

    # Return statement
    return lons, lats, elev

  def ensure_dem_loaded (self):
    """Ensure overview (z=7) and frontier (z=8) DEM grids are loaded from compressed cache or built from tiles."""
    if self.ov_dem is not None and self.fr_dem is not None:
      return

    if os.path.exists(self.cache_path) and os.path.getsize(self.cache_path) > 0:
      npz = np.load(self.cache_path)
      self.ov_lons = npz["ov_lons"]
      self.ov_lats = npz["ov_lats"]
      self.ov_dem = npz["ov_dem"]
      self.fr_lons = npz["fr_lons"]
      self.fr_lats = npz["fr_lats"]
      self.fr_dem = npz["fr_dem"]
      return

    z_ov = int(self.ecfg.get("dem_zoom_overview", 7))
    z_fr = int(self.ecfg.get("dem_zoom_frontier", 8))
    step_ov = float(self.ecfg.get("grid_step_deg", 0.015))
    step_fr = float(self.ecfg.get("frontier_grid_step_deg", 0.006))

    print(f"[ELEV] Fetching Terrarium z={z_ov} overview & z={z_fr} frontier DEM grids...")
    self.ov_lons, self.ov_lats, self.ov_dem = self._fetch_zoom_grid(self.bbox, z_ov, step_ov)
    self.fr_lons, self.fr_lats, self.fr_dem = self._fetch_zoom_grid(self.fr_bbox, z_fr, step_fr)
    os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
    np.savez_compressed(
      self.cache_path,
      ov_lons=self.ov_lons, ov_lats=self.ov_lats, ov_dem=self.ov_dem,
      fr_lons=self.fr_lons, fr_lats=self.fr_lats, fr_dem=self.fr_dem,
    )
    print(f"[ELEV] Saved DEM cache {self.cache_path} ({os.path.getsize(self.cache_path)//1024} KB)")

  def sample_elevation (self, arg1_lons, arg2_lats):
    """Bilinearly sample terrain elevation (m) at arbitrary WGS84 coordinates, using high-res frontier DEM where covered.

    @param arg1_lons 1D sequence/array of longitudes.
    @param arg2_lats 1D sequence/array of latitudes.
    @return Float64 NumPy array of elevations in metres.
    """
    # Convert from parameters
    lats = np.asarray(arg2_lats, dtype=np.float64)
    lons = np.asarray(arg1_lons, dtype=np.float64)

    self.ensure_dem_loaded()
    out = np.zeros(lons.shape[0], dtype=np.float64)
    if lons.shape[0] == 0:
      return out

    # Sample overview z=7 everywhere first
    ix_o = (lons - self.ov_lons[0]) / (self.ov_lons[1] - self.ov_lons[0])
    iy_o = (lats - self.ov_lats[0]) / (self.ov_lats[1] - self.ov_lats[0])
    out = ndimage.map_coordinates(self.ov_dem, [iy_o, ix_o], order=1, mode="nearest").astype(np.float64)

    # Override with higher-resolution z=8 frontier DEM inside frontier_bbox
    in_fr = (
      (lons >= self.fr_lons[0]) & (lons <= self.fr_lons[-1])
      & (lats >= self.fr_lats[0]) & (lats <= self.fr_lats[-1])
    )
    if np.any(in_fr):
      ix_f = (lons[in_fr] - self.fr_lons[0]) / (self.fr_lons[1] - self.fr_lons[0])
      iy_f = (lats[in_fr] - self.fr_lats[0]) / (self.fr_lats[1] - self.fr_lats[0])
      out[in_fr] = ndimage.map_coordinates(self.fr_dem, [iy_f, ix_f], order=1, mode="nearest")

    # Return statement
    return out

  def extract_local_contours (self, arg1_bbox, arg2_intervals_m):
    """Extract local topographic contour LineStrings inside a sub-bbox from the highest-res available DEM.

    @param arg1_bbox Tuple (minx, miny, maxx, maxy).
    @param arg2_intervals_m Sequence of elevation levels in metres.
    @return List of (elev_m, LineString) tuples.
    """
    # Convert from parameters
    intervals = [float(v) for v in arg2_intervals_m]
    minx, miny, maxx, maxy = [float(v) for v in arg1_bbox]

    self.ensure_dem_loaded()
    pad = 0.05
    use_fr = (
      minx >= self.fr_lons[0] and maxx <= self.fr_lons[-1]
      and miny >= self.fr_lats[0] and maxy <= self.fr_lats[-1]
    )
    src_lons = self.fr_lons if use_fr else self.ov_lons
    src_lats = self.fr_lats if use_fr else self.ov_lats
    src_dem = self.fr_dem if use_fr else self.ov_dem

    ix0 = max(0, int(np.searchsorted(src_lons, minx - pad)) - 1)
    ix1 = min(len(src_lons), int(np.searchsorted(src_lons, maxx + pad)) + 2)
    iy0 = max(0, int(np.searchsorted(src_lats, miny - pad)) - 1)
    iy1 = min(len(src_lats), int(np.searchsorted(src_lats, maxy + pad)) + 2)
    if ix1 - ix0 < 3 or iy1 - iy0 < 3:
      return []

    sub_lons = src_lons[ix0:ix1]
    sub_lats = src_lats[iy0:iy1]
    sub_z = ndimage.gaussian_filter(src_dem[iy0:iy1, ix0:ix1].astype(np.float64), sigma=0.7)
    z_min, z_max = float(np.min(sub_z)), float(np.max(sub_z))
    cg = contourpy.contour_generator(x=sub_lons, y=sub_lats, z=sub_z)
    out = []

    for lvl in intervals:
      if lvl <= z_min or lvl >= z_max:
        continue
      for pts in cg.lines(lvl):
        if pts.shape[0] < 3:
          continue
        ln = LineString(pts)
        if ln.length >= 0.015:
          out.append((int(lvl), ln))

    # Return statement
    return out

  def extract_local_dem_patch (self, arg1_bbox, arg2_step_deg=0.003):
    """Build a smoothly interpolated local DEM grid over arg1_bbox for microscopic valley-divide splitting.

    @param arg1_bbox Tuple (minx, miny, maxx, maxy).
    @param arg2_step_deg Grid spacing in degrees.
    @return Tuple (lons_1d, lats_1d, elev_2d).
    """
    # Convert from parameters
    minx, miny, maxx, maxy = [float(v) for v in arg1_bbox]
    step = float(arg2_step_deg)

    pad = max(0.02, 4.0*step)
    lons = np.arange(minx - pad, maxx + pad + 0.5*step, step, dtype=np.float64)
    lats = np.arange(miny - pad, maxy + pad + 0.5*step, step, dtype=np.float64)
    gx, gy = np.meshgrid(lons, lats)
    z_flat = self.sample_elevation(gx.ravel(), gy.ravel())
    elev = z_flat.reshape(len(lats), len(lons))

    # Return statement
    return lons, lats, elev

  def _collect_peaks_and_passes (self, arg1_paths, arg2_bbox_geom):
    """Gather named mountain peaks and passes from Natural Earth and GNS gazetteers.

    @param arg1_paths Dictionary of downloaded source filepaths.
    @param arg2_bbox_geom Shapely bounding box Polygon.
    @return List of (props_dict, Point) tuples.
    """
    # Convert from parameters
    bbox_geom = arg2_bbox_geom
    paths = arg1_paths

    # Declare local instance variables.
    min_d = 0.04
    pts_seen = []
    out = []

    ne_ep = paths.get("ne_elevation_points")
    if ne_ep and os.path.exists(ne_ep):
      with open(ne_ep, "r", encoding="utf-8") as fh:
        data = json.load(fh)
      for feat in data.get("features", []):
        g = feat.get("geometry")
        if not g or g.get("type") != "Point":
          continue
        lon, lat = float(g["coordinates"][0]), float(g["coordinates"][1])
        pt = Point(lon, lat)
        if not bbox_geom.contains(pt):
          continue
        p = feat.get("properties", {})
        elev = p.get("elevation")
        pts_seen.append((lon, lat))
        out.append((
          {
            "elevation_m": int(round(float(elev))) if elev is not None else int(round(float(self.sample_elevation([lon], [lat])[0]))),
            "feature_type": str(p.get("featurecla") or "peak").lower(),
            "name_ch": "",
            "name_en": str(p.get("name") or "Peak"),
            "source": "NaturalEarth_elevation_points",
          },
          pt,
        ))

    gns_keys = [k for k in sorted(paths.keys()) if k.startswith("gns_")]
    cand_rows = []
    for k in gns_keys:
      zp = paths[k]
      if not zp or not os.path.exists(zp):
        continue
      with zipfile.ZipFile(zp, "r") as zf:
        shp_n = next((n for n in zf.namelist() if n.lower().endswith(".shp")), None)
        dbf_n = next((n for n in zf.namelist() if n.lower().endswith(".dbf")), None)
        if not shp_n or not dbf_n:
          continue
        sf = shapefile.Reader(shp=io.BytesIO(zf.read(shp_n)), dbf=io.BytesIO(zf.read(dbf_n)), encoding="gb18030", encodingErrors="replace")
        fnames = [f[0] for f in sf.fields[1:]]
        for sr in sf.iterShapeRecords():
          rec = dict(zip(fnames, sr.record))
          dsg = str(rec.get("DSG") or "").strip().upper()
          if dsg not in ("PASS", "PK", "MT"):
            continue
          if not sr.shape.points:
            continue
          lon, lat = float(sr.shape.points[0][0]), float(sr.shape.points[0][1])
          if abs(lon) > 360.0 or abs(lat) > 90.0:
            lon, lat = gis_helpers.gk19_array_to_lonlat([[lon, lat]])[0]
          if str(rec.get("NT") or "").strip().upper() not in ("N", "C"):
            continue
          cand_rows.append((dsg, str(rec.get("NAME") or "").strip(), str(rec.get("CNTY_CH") or ""), lon, lat))

    if cand_rows:
      elevs = self.sample_elevation([r[3] for r in cand_rows], [r[4] for r in cand_rows])
      order = sorted(range(len(cand_rows)), key=lambda i: (-1 if cand_rows[i][0] == "PASS" else 0, -float(elevs[i])))
      for i in order:
        dsg, nm, cnty, lon, lat = cand_rows[i]
        pt = Point(lon, lat)
        if not bbox_geom.contains(pt):
          continue
        if any(math.hypot(lon - sx, lat - sy) < min_d for sx, sy in pts_seen):
          continue
        pts_seen.append((lon, lat))
        ftype = "pass" if dsg == "PASS" else ("peak" if dsg == "PK" else "mountain")
        out.append((
          {
            "elevation_m": int(round(float(elevs[i]))),
            "feature_type": ftype,
            "name_ch": cnty,
            "name_en": nm,
            "source": "GNS_topography",
          },
          pt,
        ))
        if len(out) >= 2400:
          break

    # Return statement
    return out

  def build_elevation_contours (self, arg1_paths):
    """Build and export ./gis/elevation_contours.geojson with intervals 200-4000 m plus peaks and passes.

    @param arg1_paths Dictionary of downloaded source filepaths.
    @return Summary dictionary with feature counts per layer.
    """
    # Convert from parameters
    paths = arg1_paths

    # Declare local instance variables.
    bb = self.bbox
    bbox_geom = box(float(bb["min_lon"]), float(bb["min_lat"]), float(bb["max_lon"]), float(bb["max_lat"]))
    features = []
    intervals = [int(v) for v in self.ecfg.get("contour_intervals_m", [200, 500, 1000, 2000, 3000, 4000])]
    min_len = float(self.ecfg.get("min_contour_length_deg", 0.12))
    out_path = os.path.join(self.gis_dir, "elevation_contours.geojson")
    simp_tol = float(self.ecfg.get("simplify_tolerance_deg", 0.003))

    self.ensure_dem_loaded()
    smooth_dem = ndimage.gaussian_filter(self.ov_dem.astype(np.float64), sigma=1.0)
    cg = contourpy.contour_generator(x=self.ov_lons, y=self.ov_lats, z=smooth_dem)
    counts = {}

    for lvl in intervals:
      cnt = 0
      for pts in cg.lines(float(lvl)):
        if pts.shape[0] < 4:
          continue
        ln = LineString(pts).simplify(simp_tol, preserve_topology=False)
        if ln.is_empty or ln.length < min_len:
          continue
        clipped = ln.intersection(bbox_geom)
        if clipped.is_empty or clipped.length < min_len:
          continue
        features.append((
          {
            "elevation_m": lvl,
            "feature_type": "contour",
            "length_deg": round(float(clipped.length), 3),
            "source": "AWS_Terrarium_DEM_z7",
          },
          clipped,
        ))
        cnt += 1
      counts[f"contour_{lvl}m"] = cnt

    pts_features = self._collect_peaks_and_passes(paths, bbox_geom)
    features.extend(pts_features)
    counts["peaks_and_passes"] = len(pts_features)

    total = gis_helpers.write_geojson(out_path, features, self.precision)
    counts["total_features"] = total

    # Return statement
    return counts
