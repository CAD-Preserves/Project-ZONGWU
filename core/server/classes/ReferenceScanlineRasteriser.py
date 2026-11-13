"""Scanline rasterisation verification comparing annual ADM-1 GeoJSON against 1916 reference and video frames."""

import json
import os
import sys
import cv2
import numpy as np

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)
from classes.ScanlineRasteriser import ScanlineRasteriser
from helpers import gis_helpers, path_helpers, tibet_reference_helpers


class ReferenceScanlineRasteriser (ScanlineRasteriser):
  """Scanline rasteriser projecting GeoJSON rings onto the 3840x2160 EPSG:3857+TPS video plate."""

  def __init__ (self, arg1_base_dir):
    """Initialise 4K scanline rasteriser with calibrated TPS transform and polity colour table.

    @param arg1_base_dir Project root directory.
    """
    # Convert from parameters
    base_dir = os.path.abspath(arg1_base_dir)

    # Declare local instance variables.
    cfg_path = path_helpers.resolve_path("common.tibet_reference_config", base_dir)
    pol_colors = {}
    ref_cfg = gis_helpers.load_json5(cfg_path)

    for ent in ref_cfg["polities"]:
      pol_colors[ent["tusi_id"]] = ent

    self.base_dir = base_dir
    self.canvas_x_off = int(ref_cfg.get("canvas_x_offset", 603))
    self.config = ref_cfg
    self.height = int(ref_cfg["image_size"][1])
    self.polity_colors = pol_colors
    self.span_cache = {}
    self.transform = tibet_reference_helpers._calibrate_transform(ref_cfg)
    self.width = int(ref_cfg["image_size"][0])

  def _build_evaluation_mask (self, arg1_target_rgb, arg2_render_rgb):
    """Build strict interior evaluation mask excluding borders, text anti-aliasing, lakes, and sidebar.

    @param arg1_target_rgb Reference or video target RGB frame (H, W, 3).
    @param arg2_render_rgb Scanline-rendered RGB buffer (H, W, 3) with background [255, 255, 255].
    @return Tuple (eval_mask, text_stroke_mask) of 2D boolean arrays.
    """
    # Convert from parameters
    target_rgb = arg1_target_rgb
    render_rgb = arg2_render_rgb

    # Declare local instance variables.
    dil3 = None
    ero3 = None
    eval_mask = None
    grad3 = None
    is_border_or_text = None
    is_lake = None
    is_rendered = None
    kern3 = np.ones((3, 3), dtype=np.uint8)
    lake_d = None
    lake_rgb = np.asarray([107, 134, 179], dtype=np.float32)
    max_c = None
    min_c = None

    dil3 = cv2.dilate(target_rgb, kern3)
    ero3 = cv2.erode(target_rgb, kern3)
    grad3 = np.max(dil3.astype(np.int16) - ero3.astype(np.int16), axis=2)

    # Exclude black/dark text glyphs, halo pixels, and high-gradient border strokes
    max_c = np.max(target_rgb, axis=2)
    min_c = np.min(target_rgb, axis=2)
    is_border_or_text = (grad3 > 18) | (max_c < 95) | ((max_c - min_c < 18) & (max_c < 200))

    # Exclude blue Tibetan lakes (rendered from DEM/hydro mask rather than admin GeoJSON)
    lake_d = np.linalg.norm(target_rgb.astype(np.float32) - lake_rgb, axis=2)
    is_lake = lake_d < 22.0

    # Evaluate only inside rendered Xizang + Yushu + Hor + Arunachal + W. Kham geography
    is_rendered = np.any(render_rgb != 255, axis=2)
    is_rendered[:, :self.canvas_x_off] = False
    eval_mask = is_rendered & (~is_border_or_text) & (~is_lake)

    # Return statement
    return (eval_mask, is_border_or_text)

  def _colour_for_adm1_feature (self, arg1_props, arg2_rgb_key):
    """Resolve expected display RGB colour for an exported adm_1 GeoJSON feature.

    @param arg1_props Feature properties dictionary.
    @param arg2_rgb_key Era RGB key in tibet_reference_config ('rgb_1916', 'rgb_1917', etc.).
    @return RGB tuple (r, g, b) or None to skip non-target exterior regions.
    """
    # Convert from parameters
    props = arg1_props
    rgb_key = arg2_rgb_key

    # Declare local instance variables.
    adm1_p = ""
    cat = str(props.get("category") or "")
    country = str(props.get("country") or "")
    name_en = str(props.get("name_en") or "")
    pol_colors = self.polity_colors
    rgb = None
    tid = ""
    uid = str(props.get("unit_id") or "")

    if cat == "tusi":
      tid = uid[5:] if uid.startswith("tusi_") else uid
      if tid in pol_colors:
        rgb = pol_colors[tid][rgb_key]
        return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
      adm1_p = str(props.get("parent_adm1") or "")
      if adm1_p in ("Qinghai", "Gansu"):
        return (161, 189, 173)
      return (184, 30, 22)

    if name_en == "Xizang":
      return (248, 212, 4)
    if name_en in ("Sichuan", "Chuanbian", "Xikang", "Yunnan", "Chamdo"):
      return (184, 30, 22)
    if name_en in ("Qinghai", "Gansu"):
      return (161, 189, 173)
    if name_en == "Xinjiang":
      return (216, 179, 92)
    if country == "Bhutan" or name_en == "Bhutan":
      return (254, 167, 157)
    if "India" in country or name_en == "Jammu and Kashmir":
      return (254, 167, 157)

    # Return statement
    return None

  def _draw_aligned_plate (self, arg1_geojson_path, arg2_rgb_key):
    """Scanline-rasterise an annual ADM-1 GeoJSON onto a 3840x2160 RGB array using TPS projection.

    @param arg1_geojson_path Path to output/gis/adm_annual/adm_1_<year>.geojson.
    @param arg2_rgb_key Config RGB key for the target era.
    @return RGB uint8 numpy array (2160, 3840, 3).
    """
    # Convert from parameters
    geo_path = arg1_geojson_path
    rgb_key = arg2_rgb_key

    # Declare local instance variables.
    arr = None
    bg = np.full((self.height, self.width, 3), 255, dtype=np.uint8)
    blines = []
    border_list = []
    col = None
    feats = []
    geom = None
    is_ref_tusi = False
    non_tusi = []
    props = {}
    sx0 = []
    sx1 = []
    sy = []
    tusi_feats = []

    with open(geo_path, "r", encoding="utf-8") as fh:
      feats = json.load(fh).get("features", [])

    non_tusi = [f for f in feats if f.get("properties", {}).get("category") != "tusi"]
    tusi_feats = [f for f in feats if f.get("properties", {}).get("category") == "tusi"]

    for group in (non_tusi, tusi_feats):
      for feat in group:
        props = feat.get("properties", {})
        col = self._colour_for_adm1_feature(props, rgb_key)
        if col is None:
          continue
        geom = feat.get("geometry")
        if not geom:
          continue
        sy, sx0, sx1, blines = self._compute_geometry_spans(geom)
        for i in range(len(sy)):
          bg[int(sy[i]), int(sx0[i]):int(sx1[i])] = col
        is_ref_tusi = props.get("category") == "tusi" and (props.get("unit_id", "")[5:] in self.polity_colors)
        if is_ref_tusi or props.get("name_en") in ("Xizang", "Sichuan", "Chuanbian", "Xikang", "Chamdo"):
          border_list.append(blines)

    # Draw thin dark borders matching vector topology for visual inspection
    for blines in border_list:
      for pts in blines:
        if len(pts) < 2:
          continue
        arr = np.asarray(pts, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(bg, [arr], False, (35, 35, 35), 2, lineType=cv2.LINE_AA)

    # Return statement
    return bg

  def _evaluate_plate_agreement (self, arg1_target_rgb, arg2_render_rgb, arg3_ref_mask_box, arg4_tol):
    """Compute interior pixel agreement inside the Tibetan historical domain and generate mismatch overlay.

    @param arg1_target_rgb Target frame RGB array (2160, 3840, 3).
    @param arg2_render_rgb Scanline rasterised RGB array (2160, 3840, 3).
    @param arg3_ref_mask_box Reference domain mask (boolean HxW covering Tibet/Yushu/Hor/Arunachal/W.Kham).
    @param arg4_tol Euclidean RGB distance tolerance for match.
    @return Tuple (agreement_pct, mismatch_count, eval_count, diff_vis_rgb).
    """
    # Convert from parameters
    target_rgb = arg1_target_rgb
    render_rgb = arg2_render_rgb
    dom_mask = arg3_ref_mask_box
    tol = float(arg4_tol)

    # Declare local instance variables.
    both_changtang = None
    both_china_red = None
    diff = None
    diff_vis = None
    eval_cnt = 0
    eval_mask = None
    match_mask = None
    mis_cnt = 0
    mismatch = None
    pct = 0.0
    r_dark = None

    eval_mask, _ = self._build_evaluation_mask(target_rgb, render_rgb)
    eval_mask = eval_mask & dom_mask
    # Exclude scanline anti-aliased border strokes on render buffer too
    r_dark = np.max(render_rgb, axis=2) < 90
    eval_mask = eval_mask & (~r_dark)

    diff = np.linalg.norm(render_rgb.astype(np.float32) - target_rgb.astype(np.float32), axis=2)
    # Allow darker shade variants of China Beiyang red ([125..235, <65, <45]) in SE Kham hillshade/palette
    both_china_red = (
      (render_rgb[:, :, 0] > 160) & (render_rgb[:, :, 1] < 50) & (render_rgb[:, :, 2] < 45)
      & (target_rgb[:, :, 0] > 115) & (target_rgb[:, :, 1] < 65) & (target_rgb[:, :, 2] < 45)
    )
    # Allow white uninhabited snow-cap highlands on northern Changtang / Ngolok margin
    both_changtang = (
      (render_rgb[:, :, 0] > 215) & (render_rgb[:, :, 1] > 215) & (render_rgb[:, :, 2] > 215)
      & (target_rgb[:, :, 0] > 215) & (target_rgb[:, :, 1] > 215) & (target_rgb[:, :, 2] > 215)
    )
    match_mask = (diff <= tol) | both_china_red | both_changtang
    eval_cnt = int(np.sum(eval_mask))
    mismatch = eval_mask & (~match_mask)
    mis_cnt = int(np.sum(mismatch))
    pct = 100.0*float(eval_cnt - mis_cnt) / float(max(eval_cnt, 1))

    diff_vis = render_rgb.copy()
    diff_vis[mismatch] = [255, 0, 220]

    # Return statement
    return (pct, mis_cnt, eval_cnt, diff_vis)

  def _project_ring (self, arg1_ring):
    """Project a single WGS84 coordinate ring into 3840x2160 image pixel space.

    @param arg1_ring Sequence of [lon, lat] coordinates.
    @return List of (px, py) float tuples.
    """
    # Convert from parameters
    ring = arg1_ring

    # Declare local instance variables.
    coords = np.asarray(ring, dtype=np.float64)
    lats = coords[:, 1]
    lons = coords[:, 0]
    pxs = None
    pys = None

    pxs, pys = tibet_reference_helpers.lonlat_to_px(lons, lats, self.transform)

    # Return statement
    return [(float(pxs[i]), float(pys[i])) for i in range(len(pxs))]

  def run_alignment_suite (self):
    """Run 3840x2160 TPS scanline verification across 1916 reference and 1916/1917/1922/1929 video frames.

    @return Dict mapping plate_name -> agreement percentage.
    """
    # Declare local instance variables.
    adm1_path = ""
    base_dir = self.base_dir
    plates_cfg = gis_helpers.load_json5(path_helpers.resolve_path("input.tusi.plates_config", base_dir))
    crop_box = tuple(plates_cfg["crop_box"])
    cx0 = crop_box[0]
    cx1 = crop_box[1]
    cy0 = crop_box[2]
    cy1 = crop_box[3]
    d_s = None
    dom_buf = np.zeros((self.height, self.width), dtype=np.uint8)
    dom_mask = None
    dw = None
    metrics = {}
    out_16 = os.path.join(path_helpers.resolve_path("tests.outputs_dir", base_dir), "tibet_scanline_alignment_1916.png")
    out_vid = os.path.join(path_helpers.resolve_path("tests.outputs_dir", base_dir), "tibet_scanline_alignment_video_frames.png")
    panel_16 = None
    panel_vid = None
    plates = []
    r_s = None
    ref_geo = os.path.join(base_dir, self.config["output_geojson"])
    render_cache = {}
    results_vis = []
    row = None
    rows = []
    rw = None
    sx0 = []
    sx1 = []
    sy = []
    t_s = None
    target_bgr = None
    target_rgb = None
    tid = ""
    tw = None

    # Build strict Tibet/Yushu/Hor/Arunachal/W.Kham evaluation domain mask from vectorised polities + masks
    with open(ref_geo, "r", encoding="utf-8") as fh:
      for feat in json.load(fh).get("features", []):
        tid = feat.get("properties", {}).get("tusi_id")
        if tid in ("guoluo_upper_tribes", "guoluo_lower_tribes"):
          continue
        sy, sx0, sx1, _ = self._compute_geometry_spans(feat["geometry"])
        for i in range(len(sy)):
          dom_buf[int(sy[i]), int(sx0[i]):int(sx1[i])] = 1
    # Erode 2 px around perimeter to ignore slight sub-pixel border stroke drift
    dom_mask = cv2.erode(dom_buf, np.ones((5, 5), dtype=np.uint8)) > 0

    plates = [(p["name"], int(p["year"]), p["rgb_key"], p["image_path"], float(p["tolerance"])) for p in plates_cfg["plates"]]

    for plate_item in plates:
      name = plate_item[0]
      yr = plate_item[1]
      rgb_key = plate_item[2]
      img_rel = plate_item[3]
      tol = plate_item[4]
      if (yr, rgb_key) not in render_cache:
        adm1_path = os.path.join(path_helpers.resolve_path("output.gis.adm_annual_dir", base_dir), f"adm_1_{yr}.geojson")
        render_cache[(yr, rgb_key)] = self._draw_aligned_plate(adm1_path, rgb_key)
      render_rgb = render_cache[(yr, rgb_key)]
      target_bgr = cv2.imread(os.path.join(base_dir, img_rel))
      target_rgb = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2RGB)
      pct, mis_cnt, eval_cnt, diff_vis = self._evaluate_plate_agreement(target_rgb, render_rgb, dom_mask, tol)
      metrics[name] = round(pct, 3)
      results_vis.append((name, yr, pct, target_rgb, render_rgb, diff_vis))
      print(f"[SCANLINE] {name:10s} (adm_1_{yr}): agreement={pct:6.2f}% | eval_px={eval_cnt:7d} | mismatch_px={mis_cnt:6d}")

    # Build side-by-side + overlay diagnostic plate for 1916 reference (target | scanline | magenta diff)
    p16 = results_vis[0][2]
    tgt16 = results_vis[0][3]
    rnd16 = results_vis[0][4]
    dif16 = results_vis[0][5]
    t_s = cv2.resize(tgt16[cy0:cy1, cx0:cx1], (1080, 588))
    r_s = cv2.resize(rnd16[cy0:cy1, cx0:cx1], (1080, 588))
    d_s = cv2.resize(dif16[cy0:cy1, cx0:cx1], (1080, 588))
    panel_16 = np.hstack([t_s, r_s, d_s])
    cv2.putText(panel_16, f"Target ref_1916 | Scanline adm_1_1916 | Agreement {p16:.2f}% (magenta = mismatch)", (24, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 20, 20), 2)
    cv2.imwrite(out_16, cv2.cvtColor(panel_16, cv2.COLOR_RGB2BGR))

    # Build 4-row comparison grid across all 4 video keyframes (target | scanline | diff)
    for vis_item in results_vis[1:]:
      name = vis_item[0]
      yr = vis_item[1]
      pct = vis_item[2]
      tgt = vis_item[3]
      rnd = vis_item[4]
      dif = vis_item[5]
      tw = cv2.resize(tgt[cy0:cy1, cx0:cx1], (960, 520))
      rw = cv2.resize(rnd[cy0:cy1, cx0:cx1], (960, 520))
      dw = cv2.resize(dif[cy0:cy1, cx0:cx1], (960, 520))
      row = np.hstack([tw, rw, dw])
      cv2.putText(row, f"{name} adm_1_{yr}: {pct:.2f}% match", (20, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (15, 15, 15), 2)
      rows.append(row)
    panel_vid = np.vstack(rows)
    cv2.imwrite(out_vid, cv2.cvtColor(panel_vid, cv2.COLOR_RGB2BGR))
    print(f"[SCANLINE] Wrote {out_16} and {out_vid}")

    # Return statement
    return metrics

