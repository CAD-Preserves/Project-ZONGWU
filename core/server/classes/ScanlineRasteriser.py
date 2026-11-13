"""Step 3 scanline polygon rasteriser for CHGIS/Project-ZONGWU annual GeoJSON verification."""

import hashlib
import json
import math
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)
from helpers import gis_helpers


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
    self.palette = rcfg.get("palette", {})
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
    """Compute a deterministic historical-atlas RGB fill colour grouped by province and sovereign status."""
    # Convert from parameters
    props = arg1_props

    # Declare local instance variables.
    base_rgb = (224, 204, 158)
    country = str(props.get("country") or "")
    delta = 0
    digest = None
    fallback_china = self.palette.get("fallback_china_rgbs", [[226, 204, 156]])
    key = str(props.get("unit_id") or props.get("name_en") or "unknown")
    occ = str(props.get("occupied_by") or "")
    prov_key = str(props.get("parent_adm1") or props.get("name_en") or "unknown")
    prov_map = self.palette.get("china_provincial_rgbs", {})
    unit_type = str(props.get("category") or props.get("unit_type") or "")

    digest = hashlib.md5(key.encode("utf-8")).digest()
    delta = (digest[0] % 21) - 10

    if occ != "":
      base_rgb = tuple(self.palette.get("occupied_base_rgb", [216, 116, 108]))
      delta = (digest[1] % 19) - 9
    elif "tusi" in unit_type.lower():
      base_rgb = tuple(self.palette.get("feudatory_base_rgb", [224, 188, 86]))
      delta = (digest[1] % 19) - 9
    elif "Mongol" in country or "MPR" in country:
      base_rgb = tuple(self.palette.get("mongolia_base_rgb", [118, 176, 214]))
      delta = (digest[1] % 21) - 10
    elif "Tuva" in country or "Uriankhai" in country or "USSR" in country or "Tyva" in prov_key:
      base_rgb = tuple(self.palette.get("tuva_base_rgb", [168, 146, 204]))
      delta = (digest[1] % 19) - 9
    elif country in (
      "Bhutan",
      "British India",
      "France (Guangzhouwan)",
      "German Empire (Kiautschou)",
      "India",
      "Portugal (Macau)",
      "United Kingdom (Hong Kong)",
      "United Kingdom (Weihaiwei)",
    ):
      base_rgb = tuple(self.palette.get("foreign_stone_rgb", [204, 198, 188]))
      delta = (digest[1] % 13) - 6
    else:
      if prov_key in prov_map:
        base_rgb = tuple(prov_map[prov_key])
      else:
        p_digest = hashlib.md5(prov_key.encode("utf-8")).digest()
        base_rgb = tuple(fallback_china[int.from_bytes(p_digest[:2], "big") % len(fallback_china)])

    # Return statement
    return (
      max(0, min(255, int(base_rgb[0]) + delta)),
      max(0, min(255, int(base_rgb[1]) + delta)),
      max(0, min(255, int(base_rgb[2]) + delta)),
    )

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

  def draw_provincial_boundaries (self, arg1_fb, arg2_prov_buf, arg3_border_rgb=None):
    """Draw crisp 2px provincial/national boundaries wherever adjacent pixels differ in prov_buf.

    @param arg1_fb Target RGB image NumPy array of shape (H, W, 3).
    @param arg2_prov_buf Integer province ID raster of shape (H, W).
    @param arg3_border_rgb Optional 3-element RGB colour override.
    @return Modified RGB NumPy array.
    """
    # Convert from parameters
    border_col = tuple(arg3_border_rgb or self.palette.get("province_border_rgb", [36, 33, 30]))
    fb = arg1_fb
    prov_buf = arg2_prov_buf

    # Declare local instance variables.
    horiz = None
    mask = np.zeros(prov_buf.shape, dtype=bool)
    vert = None

    horiz = prov_buf[:, 1:] != prov_buf[:, :-1]
    vert = prov_buf[1:, :] != prov_buf[:-1, :]
    mask[:, 1:] |= horiz
    mask[:, :-1] |= horiz
    mask[1:, :] |= vert
    mask[:-1, :] |= vert
    fb[mask] = border_col

    # Return statement
    return fb

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
    ocean_rgb = tuple(self.palette.get("ocean_rgb", [224, 235, 245]))
    fb = np.full((self.height, self.width, 3), ocean_rgb, dtype=np.uint8)
    occ_mask = np.zeros((self.height, self.width), dtype=bool)
    prov_buf = np.zeros((self.height, self.width), dtype=np.int32)
    prov_ids = {}
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
      prov_key = str(props.get("parent_adm1") or props.get("name_en") or "unknown")
      pkey = (str(props.get("country") or ""), prov_key, is_occ, is_tusi)
      if pkey not in prov_ids:
        prov_ids[pkey] = len(prov_ids) + 1
      pid = prov_ids[pkey]

      for i in range(len(sy)):
        y = int(sy[i])
        x0 = int(sx0[i])
        x1 = int(sx1[i])
        fb[y, x0:x1] = col
        prov_buf[y, x0:x1] = pid
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

    # Layer 1: Thin county/prefecture borders
    border_col = tuple(self.palette.get("county_border_rgb" if level == 3 else "admin_border_rgb", [96, 88, 78] if level == 3 else [52, 48, 44]))
    for pts in all_borders:
      if len(pts) >= 2:
        draw.line(pts, fill=border_col, width=1)

    # Layer 2: Crisp 2px provincial/national boundaries above county edges
    fb = self.draw_provincial_boundaries(np.asarray(img, dtype=np.uint8).copy(), prov_buf)
    img = Image.fromarray(fb, mode="RGB")
    draw = ImageDraw.Draw(img)

    # Layer 3: Feudatory crimson outlines on top
    feud_border = tuple(self.palette.get("feudatory_border_rgb", [150, 32, 24]))
    for pts in tusi_borders:
      if len(pts) >= 2:
        draw.line(pts, fill=feud_border, width=2 if level == 1 else 1)

    # Header & Legend bars
    draw.rectangle([0, 0, self.width, 44], fill=(28, 34, 46))
    draw.rectangle([0, self.height - 34, self.width, self.height], fill=(28, 34, 46))

    font = ImageFont.load_default()
    title = f"1 January {year} (00:00 GMT+0)  |  Admin Level {level}  |  Units: {len(features)}"
    draw.text((18, 15), title, fill=(242, 245, 248), font=font)

    legend_items = [
      ((226, 204, 156), "China (Qing / ROC / PRC)"),
      (tuple(self.palette.get("mongolia_base_rgb", [118, 176, 214])), "Mongolia"),
      (tuple(self.palette.get("tuva_base_rgb", [168, 146, 204])), "Tuva / Uriankhai"),
      (tuple(self.palette.get("occupied_base_rgb", [216, 116, 108])), "Japanese Occupied / Puppet (Hatched)"),
      (tuple(self.palette.get("feudatory_base_rgb", [224, 188, 86])), "Feudatories (Crimson Outline)"),
    ]
    lx = 18
    ly = self.height - 23
    for lcol, ltxt in legend_items:
      draw.rectangle([lx, ly, lx + 14, ly + 12], fill=lcol, outline=(220, 220, 220))
      draw.text((lx + 20, ly), ltxt, fill=(230, 234, 240), font=font)
      lx += 285

    os.makedirs(os.path.dirname(png_path), exist_ok=True)
    img.save(png_path, format="PNG", optimize=False)

    # Return statement
    return True
