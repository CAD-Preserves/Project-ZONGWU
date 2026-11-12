"""Step 3 scanline polygon rasteriser for CHGIS/Project-ZONGWU annual GeoJSON verification."""

import hashlib
import json
import math
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gis_helpers


class ScanlineRasteriser:
  """Exact half-open even-odd scanline polygon rasteriser with span caching."""

  def __init__ (self, arg1_cfg):
    """Initialise projection canvas and span cache from data_sources.json5 config.

    @param arg1_cfg Parsed data_sources.json5 dictionary.
    """
    # Convert from parameters
    cfg = arg1_cfg

    # Declare local instance variables.
    bb = cfg["bounding_box"]
    rcfg = cfg["rasteriser"]

    self.border_cache = {}
    self.cos_lat = math.cos(math.radians(float(rcfg["aspect_cos_lat"])))
    self.height = int(rcfg["canvas_height"])
    self.max_lat = float(bb["max_lat"])
    self.max_lon = float(bb["max_lon"])
    self.min_lat = float(bb["min_lat"])
    self.min_lon = float(bb["min_lon"])
    self.span_cache = {}
    self.width = int(rcfg["canvas_width"])

    geo_h = self.max_lat - self.min_lat
    geo_w = (self.max_lon - self.min_lon)*self.cos_lat
    usable_h = self.height - 96.0
    usable_w = self.width - 40.0
    self.scale = min(usable_w / geo_w, usable_h / geo_h)
    self.offset_x = 0.5*(self.width - geo_w*self.scale)
    self.offset_y = 52.0 + 0.5*(usable_h - geo_h*self.scale)

  def _colour_for_feature (self, arg1_props):
    """Compute a deterministic high-contrast RGB fill colour from feature metadata."""
    # Convert from parameters
    props = arg1_props

    # Declare local instance variables.
    country = str(props.get("country") or "")
    digest = None
    h_val = 0.0
    key = str(props.get("unit_id") or props.get("name_en") or "unknown")
    occ = str(props.get("occupied_by") or "")
    s_val = 0.55
    unit_type = str(props.get("category") or props.get("unit_type") or "")
    v_val = 0.88

    digest = hashlib.md5(key.encode("utf-8")).digest()
    h_val = (int.from_bytes(digest[:2], "big") % 360) / 360.0

    if occ != "":
      # Distinct rose/coral/amber hue band for Japanese-occupied / puppet territories
      h_val = ((int.from_bytes(digest[:2], "big") % 48) - 18) / 360.0
      if h_val < 0.0:
        h_val += 1.0
      s_val = 0.52
      v_val = 0.88
    elif "tusi" in unit_type.lower():
      # Distinct gold-emerald range for active Tusi divisions
      h_val = (38 + (int.from_bytes(digest[:2], "big") % 42)) / 360.0
      s_val = 0.68
      v_val = 0.90
    elif "Mongol" in country or "MPR" in country:
      h_val = (175 + (int.from_bytes(digest[:2], "big") % 45)) / 360.0
      s_val = 0.45
      v_val = 0.86
    elif "Tuva" in country or "Uriankhai" in country or "USSR" in country:
      h_val = (255 + (int.from_bytes(digest[:2], "big") % 40)) / 360.0
      s_val = 0.45
      v_val = 0.86
    else:
      h_val = (85 + (int.from_bytes(digest[:2], "big") % 150)) / 360.0
      s_val = 0.40 + (digest[2] % 25) / 100.0
      v_val = 0.78 + (digest[3] % 16) / 100.0

    # HSV to RGB
    i_seg = int(h_val*6.0)
    f_frac = h_val*6.0 - i_seg
    p = v_val*(1.0 - s_val)
    q = v_val*(1.0 - f_frac*s_val)
    t = v_val*(1.0 - (1.0 - f_frac)*s_val)
    mod = i_seg % 6

    if mod == 0:
      rgb = (v_val, t, p)
    elif mod == 1:
      rgb = (q, v_val, p)
    elif mod == 2:
      rgb = (p, v_val, t)
    elif mod == 3:
      rgb = (p, q, v_val)
    elif mod == 4:
      rgb = (t, p, v_val)
    else:
      rgb = (v_val, p, q)

    # Return statement
    return (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))

  def _project_ring (self, arg1_ring):
    """Project a WGS84 ring of [lon, lat] pairs into canvas pixel coordinates."""
    # Convert from parameters
    ring = arg1_ring

    pts = []
    for c in ring:
      px = self.offset_x + (float(c[0]) - self.min_lon)*self.cos_lat*self.scale
      py = self.offset_y + (self.max_lat - float(c[1]))*self.scale
      pts.append((px, py))

    # Return statement
    return pts

  def _compute_geometry_spans (self, arg1_geom_dict):
    """Build exact even-odd scanline fill spans and border pixel coords for a GeoJSON Polygon/MultiPolygon."""
    # Convert from parameters
    geom_dict = arg1_geom_dict

    # Declare local instance variables.
    border_lines = []
    gtype = geom_dict.get("type", "")
    polys = []
    scan_x0 = []
    scan_x1 = []
    scan_y = []
    scanlines = {}

    if gtype == "Polygon":
      polys = [geom_dict.get("coordinates", [])]
    elif gtype == "MultiPolygon":
      polys = geom_dict.get("coordinates", [])
    else:
      return (np.empty(0, dtype=np.int32), np.empty(0, dtype=np.int32), np.empty(0, dtype=np.int32), [])

    for poly in polys:
      for ring in poly:
        if len(ring) < 3:
          continue
        pts = self._project_ring(ring)
        border_lines.append(pts)
        n_pts = len(pts)
        for i in range(n_pts - 1):
          x0, y0 = pts[i]
          x1, y1 = pts[i + 1]
          if y0 == y1:
            continue
          if y0 > y1:
            x0, x1 = x1, x0
            y0, y1 = y1, y0
          y_start = max(0, int(math.ceil(y0)))
          y_end = min(self.height, int(math.ceil(y1)))
          if y_start >= y_end:
            continue
          inv_slope = (x1 - x0) / (y1 - y0)
          for y in range(y_start, y_end):
            x_int = x0 + (y - y0)*inv_slope
            scanlines.setdefault(y, []).append(x_int)

    for y, xs in scanlines.items():
      xs.sort()
      pair_count = len(xs) // 2
      for i in range(pair_count):
        x_l = xs[2*i]
        x_r = xs[2*i + 1]
        x_start = max(0, int(math.ceil(x_l)))
        x_end = min(self.width, int(math.ceil(x_r)))
        if x_start < x_end:
          scan_y.append(y)
          scan_x0.append(x_start)
          scan_x1.append(x_end)

    # Return statement
    return (
      np.asarray(scan_y, dtype=np.int32),
      np.asarray(scan_x0, dtype=np.int32),
      np.asarray(scan_x1, dtype=np.int32),
      border_lines,
    )

  def _get_cached_spans (self, arg1_geom_dict):
    """Retrieve or compute cached scanline spans for a GeoJSON geometry dict."""
    # Convert from parameters
    geom_dict = arg1_geom_dict

    key_bytes = json.dumps(geom_dict, separators=(",", ":")).encode("utf-8")
    g_hash = hashlib.sha1(key_bytes).hexdigest()
    if g_hash not in self.span_cache:
      sy, sx0, sx1, blines = self._compute_geometry_spans(geom_dict)
      self.span_cache[g_hash] = (sy, sx0, sx1)
      self.border_cache[g_hash] = blines

    # Return statement
    return self.span_cache[g_hash], self.border_cache[g_hash]

  def render_geojson_to_png (self, arg1_geojson_path, arg2_png_path, arg3_year, arg4_level):
    """Rasterise a GeoJSON administrative layer to a PNG using scanline filling.

    @param arg1_geojson_path Path to input adm_<level>_<year>.geojson.
    @param arg2_png_path Destination PNG path.
    @param arg3_year Snapshot year (1 January).
    @param arg4_level Administrative level (1, 2, or 3).
    @return True on success, False on error.
    """
    # Convert from parameters
    geojson_path = arg1_geojson_path
    level = int(arg4_level)
    png_path = arg2_png_path
    year = int(arg3_year)

    if not os.path.exists(geojson_path):
      print(f"[ERROR] Missing GeoJSON for rasterisation: {geojson_path}", file=sys.stderr)
      return False

    with open(geojson_path, "r", encoding="utf-8") as fh:
      data = json.load(fh)

    features = data.get("features", [])
    # Clean pale maritime background
    fb = np.full((self.height, self.width, 3), (226, 236, 245), dtype=np.uint8)
    occ_mask = np.zeros((self.height, self.width), dtype=bool)
    all_borders = []
    tusi_borders = []

    for feat in features:
      props = feat.get("properties", {})
      geom_dict = feat.get("geometry")
      if not geom_dict:
        continue
      (sy, sx0, sx1), blines = self._get_cached_spans(geom_dict)
      col = self._colour_for_feature(props)
      is_occ = (str(props.get("occupied_by") or "") != "")
      is_tusi = ("tusi" in str(props.get("category") or props.get("unit_type") or "").lower())

      for i in range(len(sy)):
        y = int(sy[i])
        x0 = int(sx0[i])
        x1 = int(sx1[i])
        fb[y, x0:x1] = col
        if is_occ:
          occ_mask[y, x0:x1] = True

      if is_tusi:
        tusi_borders.extend(blines)
      else:
        all_borders.extend(blines)

    # Apply subtle diagonal hatch over Japanese-occupied territories for visual clarity
    if np.any(occ_mask):
      yy, xx = np.ogrid[:self.height, :self.width]
      hatch = ((xx + yy) % 8 == 0) & occ_mask
      fb[hatch] = (fb[hatch]*0.68).astype(np.uint8)

    img = Image.fromarray(fb, mode="RGB")
    draw = ImageDraw.Draw(img)

    # Crisp 1px borders
    border_col = (55, 58, 64) if level == 3 else (40, 44, 52)
    for pts in all_borders:
      if len(pts) >= 2:
        draw.line(pts, fill=border_col, width=1)
    for pts in tusi_borders:
      if len(pts) >= 2:
        draw.line(pts, fill=(140, 35, 25), width=2 if level == 1 else 1)

    # Header & Legend bars
    draw.rectangle([0, 0, self.width, 44], fill=(28, 34, 46))
    draw.rectangle([0, self.height - 34, self.width, self.height], fill=(28, 34, 46))

    font = ImageFont.load_default()
    title = f"1 January {year} (00:00 GMT+0)  |  Admin Level {level}  |  Units: {len(features)}"
    draw.text((18, 15), title, fill=(242, 245, 248), font=font)

    legend_items = [
      ((120, 175, 130), "China (ROC / PRC / Beiyang)"),
      ((115, 185, 195), "Mongolia"),
      ((165, 145, 200), "Tuva / Uriankhai"),
      ((215, 125, 115), "Japanese Occupied / Puppet (Hatched)"),
      ((210, 180, 75), "Active Tusi Polity (Crimson Outline)"),
    ]
    lx = 18
    ly = self.height - 23
    for lcol, ltxt in legend_items:
      draw.rectangle([lx, ly, lx + 14, ly + 12], fill=lcol, outline=(220, 220, 220))
      draw.text((lx + 20, ly), ltxt, fill=(230, 234, 240), font=font)
      lx += 275

    os.makedirs(os.path.dirname(png_path), exist_ok=True)
    img.save(png_path, format="PNG", optimize=False)

    # Return statement
    return True


def main ():
  """Rasterise all adm_<level>_<year>.geojson files (1911-1953) into ./tests/."""
  base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
  cfg = gis_helpers.load_json5(os.path.join(base_dir, "common", "gis", "data_sources.json5"))
  if cfg is None:
    return 1

  gis_dir = os.path.join(base_dir, "gis")
  tests_dir = os.path.join(base_dir, "tests")
  rasteriser = ScanlineRasteriser(cfg)
  rendered = 0

  for year in range(1911, 1954):
    for level in (1, 2, 3):
      in_path = os.path.join(gis_dir, f"adm_{level}_{year}.geojson")
      if not os.path.exists(in_path):
        continue
      out_path = os.path.join(tests_dir, f"CHGIS_adm_{level}_{year}.png")
      if rasteriser.render_geojson_to_png(in_path, out_path, year, level):
        rendered += 1

  print(f"[STEP 3] Scanline rasterisation complete: {rendered} PNGs rendered.")
  return 0


if __name__ == "__main__":
  sys.exit(main())
