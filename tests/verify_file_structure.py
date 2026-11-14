"""Automated workspace structure, schema, AST and skill-path verification suite."""

import ast
import json
import os
import re
import sys
from shapely import STRtree
from shapely.geometry import LineString, Polygon, box, shape
from shapely.ops import unary_union

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "server"))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from classes.ScanlineRasteriser import ScanlineRasteriser
from helpers import gis_helpers, path_helpers, planar_topology_helpers


def _collect_failures (arg1_root_dir):
  """Run all repository invariant checks and return list of failure strings.

  @param arg1_root_dir Workspace root directory path.
  @return List of human-readable failure descriptions (empty if all checks pass).
  """
  # Convert from parameters
  root_dir = os.path.abspath(arg1_root_dir)

  # Declare local instance variables.
  adm_files = []
  classes_dir = ""
  defines = {}
  disallowed_paths = []
  expected_roots = {".agents", "common", "core", "input", "localisation", "output", "tests"}
  failures = []
  helpers_dir = ""
  layers_files = []
  modern_files = []
  paths_cfg = {}
  pipelines_dir = ""
  provinces_map = {}
  root_dirs = set()
  seen_rel_paths = set()
  skills_dir = ""

  # 1. Exact 7-folder root structure & banned directories
  root_dirs = {
    name for name in os.listdir(root_dir)
    if os.path.isdir(os.path.join(root_dir, name)) and name != ".git"
  }
  if root_dirs != expected_roots:
    failures.append(f"Root directories mismatch: expected {sorted(expected_roots)}, got {sorted(root_dirs)}")

  disallowed_paths = ["chronicles", "gis", "docs", os.path.join("input", "chronicles")]
  for rel in disallowed_paths:
    if os.path.exists(os.path.join(root_dir, rel)):
      failures.append(f"Forbidden directory exists: {rel}")

  # 2. common/paths.json5 resolution check
  paths_cfg = path_helpers.load_paths(root_dir)
  if not isinstance(paths_cfg, dict) or not paths_cfg:
    failures.append("Failed to parse common/paths.json5")
  else:
    for dot_key in (
      "common.admin_mappings",
      "common.admin_reforms",
      "common.data_sources",
      "common.local_history_edge_cases",
      "common.localisation_maps",
      "common.modern_gazetteer_crosswalk",
      "common.ocr_translation_config",
      "common.prc_admin_lineage",
      "common.prc_admin_reforms",
      "common.prc_functional_zones",
      "common.province_defines",
      "common.series_a_sources_config",
      "common.source_registry",
      "common.tibet_reference_config",
      "common.transport_corridors",
      "common.tusi_catalog",
      "common.tusi_modelling_config",
      "input.gis.chgis_1911_adm1_base",
      "input.gis.chgis_1911_adm2_base",
      "input.gis.chgis_1911_adm3_base",
      "input.gis.chgis_dir",
      "input.gis.ctamap_dir",
      "input.gis.gadm_dir",
      "input.gis.hydrosheds_dir",
      "input.gis.modern_dir",
      "input.gis.modern_reference_dir",
      "input.gis.natural_earth_dir",
      "input.gis.priors_dir",
      "input.gis.tibet_reference_polygons",
      "input.reference_maps_dir",
      "input.scrape_cache_dir",
      "input.tusi.frames_dir",
      "input.tusi.plates_config",
      "input.tusi.tibet_reference_image",
      "localisation.dir",
      "output.chronicles_dir",
      "output.gis.adm_annual_dir",
      "output.gis.layers_dir",
      "output.gis.prc_annual_dir",
      "output.newspapers_dir",
      "tests.outputs_dir",
    ):
      resolved = path_helpers.resolve_path(dot_key, root_dir)
      if not resolved or not os.path.exists(resolved):
        failures.append(f"Missing resolved path for {dot_key}: {resolved}")

  # 3. province_defines.json5 & output/chronicles/ hierarchy
  tusi_cat = gis_helpers.load_json5(path_helpers.resolve_path("common.tusi_catalog", root_dir))
  tusi_entries = tusi_cat.get("tusis", []) if isinstance(tusi_cat, dict) else []
  active_tusis = [t for t in tusi_entries if not t.get("deprecated", False)]
  active_tusi_ids = {t["tusi_id"] for t in active_tusis}
  deprecated_tusi_ids = {t["tusi_id"] for t in tusi_entries if t.get("deprecated", False)}
  deprecated_slugs = {gis_helpers.slugify_snake(tid) for tid in deprecated_tusi_ids}
  xizang_tusi_ids = {t["tusi_id"] for t in tusi_entries if t.get("parent_province") == "Xizang"}
  expected_divisions = 127 + len(active_tusi_ids)
  defines = gis_helpers.load_json5(path_helpers.resolve_path("common.province_defines", root_dir))
  provinces_map = defines.get("provinces", {}) if isinstance(defines, dict) else {}
  if len(provinces_map) != expected_divisions:
    failures.append(f"Expected {expected_divisions} entries in province_defines.json5['provinces'], found {len(provinces_map)}")
  else:
    expected_abs_dirs = set()
    for slug, entry in provinces_map.items():
      if slug in deprecated_slugs:
        failures.append(f"Deprecated Tusi present in province_defines.json5: {slug}")
      c_path = str(entry.get("chronicle_path") or "")
      if not c_path.startswith("./output/chronicles/") or not c_path.endswith("/"):
        failures.append(f"Invalid chronicle_path for {slug}: {c_path}")
        continue
      if c_path in seen_rel_paths:
        failures.append(f"Duplicate chronicle_path: {c_path}")
      seen_rel_paths.add(c_path)
      abs_dir = os.path.normpath(os.path.join(root_dir, c_path))
      expected_abs_dirs.add(abs_dir)
      if not os.path.isdir(abs_dir):
        failures.append(f"Missing chronicle directory on disk: {abs_dir}")
    chron_root = path_helpers.resolve_path("output.chronicles_dir", root_dir)
    actual_leaf_dirs = set()
    if os.path.isdir(chron_root):
      for top_d in os.listdir(chron_root):
        top_abs = os.path.join(chron_root, top_d)
        if not os.path.isdir(top_abs):
          continue
        if top_d == "tusi":
          for reg_d in os.listdir(top_abs):
            reg_abs = os.path.join(top_abs, reg_d)
            if os.path.isdir(reg_abs):
              for leaf_d in os.listdir(reg_abs):
                leaf_abs = os.path.normpath(os.path.join(reg_abs, leaf_d))
                if os.path.isdir(leaf_abs):
                  actual_leaf_dirs.add(leaf_abs)
        else:
          for leaf_d in os.listdir(top_abs):
            leaf_abs = os.path.normpath(os.path.join(top_abs, leaf_d))
            if os.path.isdir(leaf_abs):
              actual_leaf_dirs.add(leaf_abs)
    extra_chron = sorted(actual_leaf_dirs - expected_abs_dirs)
    if extra_chron:
      failures.append(f"Orphan chronicle directories on disk ({len(extra_chron)}): {extra_chron[:5]}")

  # 4. GeoJSON asset counts
  adm_files = [fn for fn in os.listdir(path_helpers.resolve_path("output.gis.adm_annual_dir", root_dir)) if fn.endswith(".geojson")]
  if len(adm_files) != 129:
    failures.append(f"Expected 129 GeoJSON files in output/gis/adm_annual/, found {len(adm_files)}")

  layers_files = [fn for fn in os.listdir(path_helpers.resolve_path("output.gis.layers_dir", root_dir)) if fn.endswith(".geojson")]
  if len(layers_files) != 5:
    failures.append(f"Expected 5 GeoJSON files in output/gis/layers/, found {len(layers_files)}")

  modern_files = [fn for fn in os.listdir(path_helpers.resolve_path("input.gis.modern_dir", root_dir)) if fn.endswith(".geojson")]
  if len(modern_files) != 10:
    failures.append(f"Expected 10 GeoJSON files in input/gis/modern/, found {len(modern_files)}")

  prc_annual_dir = path_helpers.resolve_path("output.gis.prc_annual_dir", root_dir)
  if os.path.isdir(prc_annual_dir):
    prc_ann_files = [fn for fn in os.listdir(prc_annual_dir) if fn.endswith(".geojson")]
    if len(prc_ann_files) != 219:
      failures.append(f"Expected 219 GeoJSON files in output/gis/prc_annual_1954_2026/, found {len(prc_ann_files)}")

  # 5. core/server AST, naming & line-limit checks
  classes_dir = os.path.join(root_dir, "core", "server", "classes")
  helpers_dir = os.path.join(root_dir, "core", "server", "helpers")
  pipelines_dir = os.path.join(root_dir, "core", "server", "pipelines")

  server_entries = {fn for fn in os.listdir(os.path.join(root_dir, "core", "server")) if fn != "__pycache__"}
  if server_entries != {"classes", "helpers", "pipelines"}:
    failures.append(f"Unexpected entries in core/server/: {sorted(server_entries)}")

  for pkg_dir, kind in ((classes_dir, "class"), (helpers_dir, "helper"), (pipelines_dir, "pipeline")):
    if os.path.exists(os.path.join(pkg_dir, "__init__.py")) and kind in ("class", "pipeline"):
      failures.append(f"Forbidden __init__.py in {pkg_dir}")
    for fn in sorted(os.listdir(pkg_dir)):
      if fn == "__pycache__":
        continue
      if not fn.endswith(".py"):
        failures.append(f"Non-Python file in {pkg_dir}: {fn}")
        continue
      stem = fn[:-3]
      fpath = os.path.join(pkg_dir, fn)
      with open(fpath, "r", encoding="utf-8") as fh:
        src = fh.read()
      line_count = len(src.splitlines())
      if line_count >= 1000:
        failures.append(f"Line limit exceeded (>=1000) in {fpath}: {line_count}")
      tree = ast.parse(src, filename=fpath)
      class_defs = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
      if hasattr(ast, "Match") and any(isinstance(n, ast.Match) for n in ast.walk(tree)):
        failures.append(f"Forbidden match statement in {fpath}")
      if kind == "class":
        if not re.match(r"^[A-Z][A-Za-z0-9]+$", stem):
          failures.append(f"Class filename must be CamelCase: {fn}")
        if class_defs != [stem]:
          failures.append(f"Expected single class [{stem}] in {fn}, found {class_defs}")
      elif kind == "helper":
        if not re.match(r"^[a-z][a-z0-9_]+$", stem):
          failures.append(f"Helper filename must be snake_case: {fn}")
        if class_defs:
          failures.append(f"Helper module must declare 0 classes ({fn}): found {class_defs}")
      elif kind == "pipeline":
        if not re.match(r"^[A-Z]_[a-z0-9_]+$", stem):
          failures.append(f"Pipeline filename must be <Letter>_<snake_case>.py: {fn}")
        if class_defs:
          failures.append(f"Pipeline runner must declare 0 classes ({fn}): found {class_defs}")

  # 6. .agents rules, references & skills sanity check
  skills_dir = os.path.join(root_dir, ".agents", "skills")
  expected_skills = {
    "1.build-chgis-admin",
    "2.build-prc-crosswalk",
    "3.orchestrate-chronicles",
    "4.index-province",
    "5.scrape-province",
    "6.ocr-translate-province",
    "7.chronology-province",
    "series-a-workflow",
  }
  if not os.path.isfile(os.path.join(root_dir, ".agents", "rules", "project_architecture.md")):
    failures.append("Missing .agents/rules/project_architecture.md")
  if not os.path.isfile(os.path.join(root_dir, ".agents", "references", "taxonomy_and_schemas.md")):
    failures.append("Missing .agents/references/taxonomy_and_schemas.md")
  actual_skills = {d for d in os.listdir(skills_dir) if os.path.isdir(os.path.join(skills_dir, d))}
  if actual_skills != expected_skills:
    failures.append(f"Skill directories mismatch: expected {sorted(expected_skills)}, got {sorted(actual_skills)}")

  stale_patterns = (
    "./chronicles/",
    "chronicles/source_registry.json5",
    "./gis/",
    "gis/sources",
    "1.download-CHGIS",
    "1.download-PRC",
    "1.download-all-provinces",
    "F_download_and_crosswalk_modern_gis.py",
  )
  for r, _, files in os.walk(os.path.join(root_dir, ".agents")):
    for fn in sorted(files):
      if not fn.endswith(".md"):
        continue
      md_path = os.path.join(r, fn)
      with open(md_path, "r", encoding="utf-8") as fh:
        content = fh.read()
      for pat in stale_patterns:
        if pat in content:
          failures.append(f"Stale reference '{pat}' in {md_path}")

  _check_historical_invariants(root_dir, failures, active_tusis, deprecated_tusi_ids)
  _check_prc_1954_2026_invariants(root_dir, failures)
  _check_topology_invariants(root_dir, failures, active_tusis, deprecated_tusi_ids, xizang_tusi_ids)
  _check_series_a_invariants(root_dir, failures)

  # Return statement
  return failures


def _check_prc_1954_2026_invariants (arg1_root_dir, arg2_failures):
  """Verify 1953 seat propagation, 1954-2026 PRC GeoJSON/PNG coverage, Hotan/XPCC additions, lineage, and schema v2 crosswalk."""
  # Convert from parameters
  failures = arg2_failures
  root_dir = os.path.abspath(arg1_root_dir)

  # Declare local instance variables.
  adm_annual_dir = path_helpers.resolve_path("output.gis.adm_annual_dir", root_dir)
  cw_path = path_helpers.resolve_path("common.modern_gazetteer_crosswalk", root_dir)
  inland_bbox = (94.0, 32.0, 105.0, 40.0)
  lin_path = path_helpers.resolve_path("common.prc_admin_lineage", root_dir)
  modern_dir = path_helpers.resolve_path("input.gis.modern_dir", root_dir)
  prc_annual_dir = path_helpers.resolve_path("output.gis.prc_annual_dir", root_dir)
  rasteriser = ScanlineRasteriser(gis_helpers.load_json5(path_helpers.resolve_path("common.data_sources", root_dir)))
  reforms_cfg = gis_helpers.load_json5(path_helpers.resolve_path("common.prc_admin_reforms", root_dir)) or {}
  req_gbs = {"653228", "653229"} | {f"6590{i:02d}" for i in range(1, 13)}
  tests_outputs_dir = path_helpers.resolve_path("tests.outputs_dir", root_dir)

  # 1. Verify adm_{1,2,3}_1953.geojson hand-off seats
  for lvl in (1, 2, 3):
    p53 = os.path.join(adm_annual_dir, f"adm_{lvl}_1953.geojson")
    if os.path.exists(p53):
      with open(p53, "r", encoding="utf-8") as fh:
        f53 = json.load(fh).get("features", [])
      miss = sum(1 for ft in f53 if ft.get("properties", {}).get("seat_lon") is None or ft.get("properties", {}).get("seat_lat") is None)
      if miss > 0:
        failures.append(f"adm_{lvl}_1953.geojson has {miss} features missing seat_lon/seat_lat")

  # 2. Verify PRC_modern_adm_{1,2,3}.png & all 219 PRC_adm_{1,2,3}_{1954..2026}.png existence and freshness
  for lvl in (1, 2, 3):
    m_geo = os.path.join(modern_dir, f"prc_adm_{lvl}.geojson")
    m_png = os.path.join(tests_outputs_dir, f"PRC_modern_adm_{lvl}.png")
    if not os.path.isfile(m_png):
      failures.append(f"Missing modern verification PNG: {m_png}")
    elif os.path.exists(m_geo) and os.path.getmtime(m_png) < os.path.getmtime(m_geo) - 5.0:
      failures.append(f"Stale modern PNG older than GeoJSON: {os.path.basename(m_png)}")

  for yr in range(1954, 2027):
    for lvl in (1, 2, 3):
      g_p = os.path.join(prc_annual_dir, f"prc_adm_{lvl}_{yr}.geojson")
      p_p = os.path.join(tests_outputs_dir, f"PRC_adm_{lvl}_{yr}.png")
      if not os.path.isfile(p_p):
        failures.append(f"Missing 1954-2026 verification PNG: {os.path.basename(p_p)}")
      elif os.path.exists(g_p) and os.path.getmtime(p_p) < os.path.getmtime(g_p) - 5.0:
        failures.append(f"Stale 1954-2026 PNG older than GeoJSON: {os.path.basename(p_p)}")

  # 3. Verify 2024 Hotan counties and XPCC shi cities in modern & 2026 layers + modern planar topology audit
  for mf in (
    "prc_adm_1.geojson",
    "prc_adm_2.geojson",
    "prc_adm_3.geojson",
    "twn_adm_1.geojson",
    "twn_adm_2.geojson",
    "twn_adm_3.geojson",
    "mng_adm_1.geojson",
    "mng_adm_2.geojson",
    "tuva_adm_1.geojson",
    "tuva_adm_2.geojson",
  ):
    mfp = os.path.join(modern_dir, mf)
    if os.path.exists(mfp):
      with open(mfp, "r", encoding="utf-8") as fh:
        m_feats = [(ft.get("properties") or {}, shape(ft["geometry"])) for ft in json.load(fh).get("features", []) if ft.get("geometry")]
      m_rep = planar_topology_helpers.audit_planar_layer(m_feats, 1e-9, 1e-8)
      if m_rep["invalid_count"] > 0 or m_rep["overlap_count"] > 0 or m_rep["hole_count"] > 0:
        failures.append(f"Planar topology violation in modern {mf}: {m_rep}")
      m_sl = rasteriser.audit_geojson_scanline(mfp)
      if m_sl["double_painted_pixels"] != 0:
        failures.append(f"Scanline overlap in modern {mf}: {m_sl}")

  for clbl, cfiles in (
    ("modern_combined_adm1", ("prc_adm_1.geojson", "twn_adm_1.geojson", "mng_adm_1.geojson", "tuva_adm_1.geojson")),
    ("modern_combined_adm2", ("prc_adm_2.geojson", "twn_adm_2.geojson", "mng_adm_2.geojson", "tuva_adm_2.geojson")),
    ("modern_combined_adm3", ("prc_adm_3.geojson", "twn_adm_3.geojson", "mng_adm_2.geojson", "tuva_adm_2.geojson")),
  ):
    c_feats = []
    for cf in cfiles:
      cfp = os.path.join(modern_dir, cf)
      if os.path.exists(cfp):
        with open(cfp, "r", encoding="utf-8") as fh:
          c_feats.extend([(ft.get("properties") or {}, shape(ft["geometry"])) for ft in json.load(fh).get("features", []) if ft.get("geometry")])
    if c_feats:
      c_rep = planar_topology_helpers.audit_planar_layer(c_feats, 1e-9, 1e-8)
      if c_rep["invalid_count"] > 0 or c_rep["overlap_count"] > 0 or c_rep["hole_count"] > 0:
        failures.append(f"Planar topology violation in {clbl}: {c_rep}")

  for lbl, gpath in (("prc_adm_3.geojson", os.path.join(modern_dir, "prc_adm_3.geojson")), ("prc_adm_3_2026.geojson", os.path.join(prc_annual_dir, "prc_adm_3_2026.geojson"))):
    if os.path.exists(gpath):
      with open(gpath, "r", encoding="utf-8") as fh:
        f3 = json.load(fh).get("features", [])
      by_gb3 = {str(ft.get("properties", {}).get("gb_code") or ""): ft.get("properties", {}) for ft in f3}
      missing_gb = sorted(req_gbs - set(by_gb3))
      if missing_gb:
        failures.append(f"{lbl} missing expected 2026 GB codes: {missing_gb}")
      name_k = "name_zh" if lbl == "prc_adm_3.geojson" else "name_ch"
      for hgb, hname in (("653228", "和康县"), ("653229", "和安县")):
        if hgb in by_gb3 and str(by_gb3[hgb].get(name_k) or "") != hname:
          failures.append(f"{lbl} expected {hgb}=={hname}, found {by_gb3[hgb].get(name_k)}")

  # 4. Landmark snapshot assertions & multi-level planar topology + scanline audit
  for yr in (1954, 1955, 1956, 1957, 1958, 1959, 1966, 1970, 1980, 1989, 1998, 2000, 2001, 2003, 2011, 2025, 2026):
    for lvl in (1, 2, 3):
      pl = os.path.join(prc_annual_dir, f"prc_adm_{lvl}_{yr}.geojson")
      if not os.path.exists(pl):
        continue
      with open(pl, "r", encoding="utf-8") as fh:
        fl = json.load(fh).get("features", [])
      l_feats = [(ft.get("properties") or {}, shape(ft["geometry"])) for ft in fl if ft.get("geometry")]
      l_rep = planar_topology_helpers.audit_planar_layer(l_feats, 1e-9, 1e-8)
      if l_rep["invalid_count"] > 0 or l_rep["overlap_count"] > 0 or l_rep["hole_count"] > 0:
        failures.append(f"Planar topology violation in prc_adm_{lvl}_{yr}.geojson: {l_rep}")
      sl_full = rasteriser.audit_geojson_scanline(pl)
      sl_inland = rasteriser.audit_geojson_scanline(pl, inland_bbox)
      if sl_full["double_painted_pixels"] != 0 or sl_inland["double_painted_pixels"] != 0 or sl_inland["interior_void_pixels"] != 0:
        failures.append(f"Scanline topology violation in prc_adm_{lvl}_{yr}.geojson: full={sl_full}, inland={sl_inland}")
      if lvl != 1:
        continue
      names1 = {str(ft.get("properties", {}).get("name_en") or "") for ft in fl}
      countries1 = {str(ft.get("properties", {}).get("country") or "") for ft in fl}
      if yr >= 1959:
        tusi_cnt = sum(1 for ft in fl if ft.get("properties", {}).get("category") == "tusi")
        if tusi_cnt > 0:
          failures.append(f"Unexpected post-1958 Tusi remaining in prc_adm_1_{yr}.geojson: {tusi_cnt}")
      if yr in (1998, 2000, 2026) and ("Chongqing" not in names1 or "Hong Kong SAR" not in names1):
        failures.append(f"prc_adm_1_{yr}.geojson missing Chongqing or Hong Kong SAR")
      if yr in (2000, 2026) and "Macau SAR" not in names1:
        failures.append(f"prc_adm_1_{yr}.geojson missing Macau SAR")
      if yr == 2026:
        if "Taoyuan" not in names1 or "Mongolia" not in countries1 or "Russian Federation" not in countries1:
          failures.append(f"prc_adm_1_2026.geojson missing expected 2026 entities (names={sorted(names1)[:10]}, countries={sorted(countries1)})")

  # 5. Lineage & crosswalk schema v2 checks
  lin_doc = gis_helpers.load_json5(lin_path)
  if not isinstance(lin_doc, dict) or lin_doc.get("schema_version") != 1 or lin_doc.get("coverage_years") != [1954, 2026]:
    failures.append(f"Invalid prc_admin_lineage_1954_2026 schema in {lin_path}")
  elif "fz_xiongan_xinqu" not in lin_doc.get("units_by_id", {}):
    failures.append("prc_admin_lineage_1954_2026 missing fz_xiongan_xinqu functional zone")
  else:
    lin_by_gb = {str(v.get("gb_code_2026") or ""): str(v.get("name_zh_2026") or "") for v in lin_doc.get("units_by_id", {}).values()}
    for hgb, hname in (("653228", "和康县"), ("653229", "和安县")):
      if lin_by_gb.get(hgb) != hname:
        failures.append(f"prc_admin_lineage_1954_2026 expected {hgb}=={hname}, found {lin_by_gb.get(hgb)}")

  cw_doc = gis_helpers.load_json5(cw_path)
  banned_pre1949 = set(reforms_cfg.get("epoch_1_1954_1979", {}).get("pre_1949_imperial_republican_names_banned_in_mainland_xinzhi", []))
  if not isinstance(cw_doc, dict) or cw_doc.get("schema_version") != 2:
    failures.append(f"Expected schema_version == 2 in {cw_path}")
  else:
    if not isinstance(cw_doc.get("functional_zone_redirects"), dict) or "fz_xiongan_xinqu" not in cw_doc.get("functional_zone_redirects", {}):
      failures.append("modern_gazetteer_crosswalk missing functional_zone_redirects")
    bad_qs = []
    missing_plan = 0
    for uid, rec in cw_doc.get("by_modern_unit", {}).items():
      if rec.get("region") != "mainland_prc":
        continue
      plan = rec.get("chronicle_search_plan")
      if not isinstance(plan, dict) or "rung_1_1990s_exact" not in plan:
        missing_plan += 1
      for q in rec.get("search_queries", []):
        if "ctext.org" in str(q) or str(q) in banned_pre1949 or str(q).rstrip("志") in banned_pre1949:
          bad_qs.append((uid, q))
    if missing_plan > 0:
      failures.append(f"modern_gazetteer_crosswalk has {missing_plan} mainland_prc units missing chronicle_search_plan")
    if bad_qs:
      failures.append(f"Mainland query hygiene violation in crosswalk: {bad_qs[:5]}")


def _check_series_a_invariants (arg1_root_dir, arg2_failures):
  """Verify Series A input/output separation, source_registry schema, and index_manifest linkage.

  @param arg1_root_dir Workspace root directory path.
  @param arg2_failures Failure list updated in place.
  """
  # Convert from parameters
  failures = arg2_failures
  root_dir = os.path.abspath(arg1_root_dir)

  # Declare local instance variables.
  chronicles_dir = path_helpers.resolve_path("output.chronicles_dir", root_dir)
  input_dir = os.path.join(root_dir, "input")
  leaked_suffixes = ("_orig.pdf", "_zh.pdf", "_en.pdf", "_zh_raw.md", "_en_raw.md")
  manifest = None
  reg = None
  reg_path = path_helpers.resolve_path("common.source_registry", root_dir)
  reg_sources = {}

  for r, _, files in os.walk(input_dir):
    for fn in files:
      if fn.endswith(leaked_suffixes) or (fn.startswith("chronology_") and fn.endswith(".md")):
        failures.append(f"Generated Series A artefact leaked into input/: {os.path.join(r, fn)}")

  reg = gis_helpers.load_json5(reg_path)
  if not isinstance(reg, dict) or reg.get("schema_version") != 1 or not isinstance(reg.get("sources"), dict):
    failures.append(f"Invalid source_registry schema in {reg_path}")
    return
  reg_sources = reg.get("sources", {})

  if os.path.isdir(chronicles_dir):
    for r, _, files in os.walk(chronicles_dir):
      for fn in files:
        if fn != "index_manifest.json5":
          continue
        mpath = os.path.join(r, fn)
        try:
          manifest = gis_helpers.load_json5(mpath)
        except Exception as exc:
          failures.append(f"Failed to parse {mpath}: {exc}")
          continue
        if not isinstance(manifest, dict):
          failures.append(f"Non-dict manifest in {mpath}")
          continue
        for unit in manifest.get("units_indexed", []):
          for src in unit.get("sources", []):
            sid = str(src.get("source_id") or "")
            if not sid or sid not in reg_sources:
              failures.append(f"Unregistered source_id '{sid}' in {mpath}")


def _check_year_name_rules (arg1_yr, arg2_occ_by_key, arg3_failures):
  """Verify key historical occupation and neutrality assertions on 1 January arg1_yr."""
  # Convert from parameters
  failures = arg3_failures
  occ_by_key = arg2_occ_by_key
  yr = int(arg1_yr)

  # Declare local instance variables.
  expected_occ = []
  expected_unocc = []

  if yr == 1938:
    expected_occ = [("Henan", "Anyang Xian"), ("Zhejiang", "Shengxi Xian"), ("Fujian", "Kinmen Xian")]
    expected_unocc = [("Henan", "Xinxiang Xian"), ("Henan", "Ji Xian"), ("Henan", "Henei Xian"), ("Hebei", "Changyuan Xian"), ("Hebei", "Kai Zhou"), ("Qingdao", "Qingdao")]
  elif yr == 1939:
    expected_occ = [("Henan", "Xinxiang Xian"), ("Qingdao (Japanese Occupied)", "Qingdao"), ("Shandong", "Weihaiwei"), ("Fujian", "Xiamen")]
    expected_unocc = [("Fujian", "Tong'an Xian"), ("Guangdong", "Hong Kong"), ("Guangdong", "Macau")]
  elif yr == 1942:
    expected_occ = [("Guangdong", "Hong Kong")]
    expected_unocc = [("Guangdong", "Macau"), ("Guangdong", "Guangzhouwan")]
  elif yr == 1944:
    expected_occ = [("Guangdong", "Guangzhouwan"), ("Guangdong", "Xuwen Xian")]
    expected_unocc = [("Guangdong", "Macau")]
  elif yr == 1945:
    expected_occ = [
      ("Hunan", "Changsha Xian"), ("Hunan", "Hengyang Xian"), ("Hunan", "Lingling Xian"),
      ("Guangxi", "Lingui Xian"), ("Guangxi", "Longzhou Ting"), ("Guangdong", "Qin Zhou"),
      ("Guangdong", "Hepu Xian"), ("Guangdong", "Xinning Xian"),
    ]
    expected_unocc = [
      ("Hunan", "Chen Zhou"), ("Hunan", "Guiyang Zhou"), ("Hunan", "Dao Zhou"),
      ("Hunan", "Ningyuan Xian"), ("Hunan", "Xintian Xian"), ("Hunan", "Jianghua Xian"),
      ("Hunan", "Xinhua Xian"), ("Guangdong", "Qujiang Xian"), ("Guangxi", "Hechi Zhou"),
      ("Guangxi", "Dayao Shan Yao Autonomous Region (Shipai Polity)"), ("Guangxi", "He Xian"),
      ("Guangdong", "Macau"),
    ]

  for k in expected_occ:
    if not occ_by_key.get(k):
      failures.append(f"Expected Japanese occupation at {yr} for {k}, got {occ_by_key.get(k)!r}")
  for k in expected_unocc:
    if k not in occ_by_key:
      failures.append(f"Missing expected unit at {yr}: {k}")
    elif occ_by_key[k]:
      failures.append(f"Unexpected Japanese occupation at {yr} for {k}: {occ_by_key[k]!r}")


def _check_topology_invariants (arg1_root_dir, arg2_failures, arg3_active_tusis, arg4_deprecated_ids, arg5_xizang_tusi_ids):
  """Verify Pamir clip, PNG freshness, post-1951 Tibet/Golok constraints, deprecated Tusi exclusion, and PRC hole removal."""
  # Convert from parameters
  active_tusis = list(arg3_active_tusis or [])
  deprecated_ids = set(arg4_deprecated_ids or set())
  failures = arg2_failures
  root_dir = arg1_root_dir
  xizang_tusi_ids = set(arg5_xizang_tusi_ids or set())

  # Declare local instance variables.
  adm_annual_dir = path_helpers.resolve_path("output.gis.adm_annual_dir", root_dir)
  base1_path = path_helpers.resolve_path("input.gis.chgis_1911_adm1_base", root_dir)
  modern_dir = path_helpers.resolve_path("input.gis.modern_dir", root_dir)
  nefa_box = box(91.6, 26.5, 97.4, 27.55)
  qinghai_box = box(89.0, 31.5, 103.0, 39.0)
  tests_outputs_dir = path_helpers.resolve_path("tests.outputs_dir", root_dir)
  tusi_geo_path = path_helpers.resolve_path("output.gis.tusi", root_dir)

  if os.path.exists(base1_path):
    with open(base1_path, "r", encoding="utf-8") as fh:
      b_feats = json.load(fh).get("features", [])
    min_lon = min((shape(ft["geometry"]).bounds[0] for ft in b_feats if ft.get("geometry")), default=999.0)
    if min_lon < 73.45:
      failures.append(f"East Tajikistan remains in {base1_path}: min_lon={min_lon:.4f}")

  if os.path.exists(tusi_geo_path):
    with open(tusi_geo_path, "r", encoding="utf-8") as fh:
      t_feats = json.load(fh).get("features", [])
    if len(t_feats) != len(active_tusis):
      failures.append(f"Expected {len(active_tusis)} active features in tusi_1912_1953.geojson, found {len(t_feats)}")
    found_dep = [ft.get("properties", {}).get("tusi_id") for ft in t_feats if ft.get("properties", {}).get("tusi_id") in deprecated_ids]
    if found_dep:
      failures.append(f"Deprecated Tusis present in tusi_1912_1953.geojson: {found_dep[:10]}")
    min_t_lon = min((shape(ft["geometry"]).bounds[0] for ft in t_feats if ft.get("geometry")), default=999.0)
    if min_t_lon < 73.45:
      failures.append(f"East Tajikistan remains in tusi_1912_1953.geojson: min_lon={min_t_lon:.4f}")

  for yr in range(1911, 1954):
    a1_path = os.path.join(adm_annual_dir, f"adm_1_{yr}.geojson")
    if os.path.exists(a1_path):
      with open(a1_path, "r", encoding="utf-8") as fh:
        a1_feats = json.load(fh).get("features", [])
      yr_min_lon = min((shape(ft["geometry"]).bounds[0] for ft in a1_feats if ft.get("geometry")), default=999.0)
      if yr_min_lon < 73.45:
        failures.append(f"East Badakhshan/Tajikistan remains in adm_1_{yr}.geojson: min_lon={yr_min_lon:.4f}")
      if yr in (1952, 1953):
        xz_t = [
          ft.get("properties", {}).get("unit_id")
          for ft in a1_feats
          if ft.get("properties", {}).get("category") == "tusi"
          and (
            str(ft.get("properties", {}).get("unit_id") or "")[5:] in xizang_tusi_ids
            or ft.get("properties", {}).get("parent_adm1") == "Xizang"
          )
        ]
        if xz_t:
          failures.append(f"Unexpected post-1951 Xizang Tusi in adm_1_{yr}.geojson: {xz_t[:5]}")
        geoms_yr = []
        for ft in a1_feats:
          g = shape(ft["geometry"])
          geoms_yr.append(g)
          p = ft.get("properties", {})
          ctry = str(p.get("country") or "").lower()
          if ("china" in ctry or "qing" in ctry) and g.intersects(nefa_box) and g.intersection(nefa_box).area > 0.02:
            failures.append(f"Unexpected post-1951 Chinese coverage south of 27.55N in adm_1_{yr}.geojson: {p.get('unit_id')}")
          if "china" in ctry:
            parts = [g] if g.geom_type == "Polygon" else list(g.geoms)
            for part in parts:
              if 0.0002 <= part.area < 0.05 and 90.0 <= part.centroid.x <= 97.5 and part.centroid.y < 27.9:
                failures.append(f"Detached South Tibet sliver south of McMahon Line in adm_1_{yr}.geojson: {p.get('unit_id')} area={part.area:.5f} at {part.centroid.coords[0]}")
        if geoms_yr:
          u_yr = unary_union(geoms_yr)
          for poly in ([u_yr] if u_yr.geom_type == "Polygon" else list(u_yr.geoms)):
            for r in poly.interiors:
              hp = Polygon(r)
              if hp.area > 0.05 and qinghai_box.contains(hp.centroid):
                unclaimed_area = hp.difference(u_yr).area
                if unclaimed_area > 0.05:
                  failures.append(f"Unclaimed Golok/Qinghai hole in adm_1_{yr}.geojson: area={unclaimed_area:.4f} at {hp.centroid.coords[0]}")

    for lvl in (1, 2, 3):
      geo_p = os.path.join(adm_annual_dir, f"adm_{lvl}_{yr}.geojson")
      png_p = os.path.join(tests_outputs_dir, f"CHGIS_adm_{lvl}_{yr}.png")
      if not os.path.isfile(png_p):
        failures.append(f"Missing verification raster PNG: {png_p}")
      elif os.path.exists(geo_p) and os.path.getmtime(png_p) < os.path.getmtime(geo_p) - 5.0:
        failures.append(f"Stale verification PNG older than GeoJSON: {os.path.basename(png_p)}")

  for lvl in (1, 2):
    m_path = os.path.join(modern_dir, f"prc_adm_{lvl}.geojson")
    if os.path.exists(m_path):
      with open(m_path, "r", encoding="utf-8") as fh:
        m_feats = json.load(fh).get("features", [])
      u_m = unary_union([shape(ft["geometry"]) for ft in m_feats if ft.get("geometry")])
      large_holes = [Polygon(r).difference(u_m).area for poly in ([u_m] if u_m.geom_type == "Polygon" else list(u_m.geoms)) for r in poly.interiors if Polygon(r).difference(u_m).area > 0.001]
      if large_holes:
        failures.append(f"prc_adm_{lvl}.geojson retains {len(large_holes)} unclaimed interior holes >0.001 deg2 (max={max(large_holes):.5f})")
      if lvl == 2:
        seen_pref = set()
        dup_pref = []
        for ft in m_feats:
          p = ft.get("properties", {})
          pk = (str(p.get("parent_adm1") or ""), str(p.get("name_en") or ""))
          if pk in seen_pref:
            dup_pref.append(pk)
          seen_pref.add(pk)
        if dup_pref:
          failures.append(f"prc_adm_2.geojson has duplicate (parent_adm1, name_en) pairs: {dup_pref[:5]}")


def _check_historical_invariants (arg1_root_dir, arg2_failures, arg3_active_tusis, arg4_deprecated_ids):
  """Verify 1911 seat metadata, 1911 Feudatory continuity, enclave-free occupation, and historical frontline assertions."""
  # Convert from parameters
  active_tusis = list(arg3_active_tusis or [])
  deprecated_ids = set(arg4_deprecated_ids or set())
  failures = arg2_failures
  root_dir = arg1_root_dir

  # Declare local instance variables.
  adm3_base_path = path_helpers.resolve_path("input.gis.chgis_1911_adm3_base", root_dir)
  adm_annual_dir = path_helpers.resolve_path("output.gis.adm_annual_dir", root_dir)

  if os.path.exists(adm3_base_path):
    with open(adm3_base_path, "r", encoding="utf-8") as fh:
      b_feats = json.load(fh).get("features", [])
    missing_seats = sum(1 for ft in b_feats if "seat_lon" not in ft.get("properties", {}) or "seat_lat" not in ft.get("properties", {}))
    if missing_seats > 0:
      failures.append(f"{adm3_base_path} has {missing_seats} features missing seat_lon/seat_lat")

  p_1911 = os.path.join(adm_annual_dir, "adm_3_1911.geojson")
  if os.path.exists(p_1911):
    with open(p_1911, "r", encoding="utf-8") as fh:
      f_1911 = json.load(fh).get("features", [])
    tusi_1911 = sum(1 for ft in f_1911 if ft.get("properties", {}).get("category") == "tusi")
    expected_1911 = sum(1 for t in active_tusis if int(t.get("de_facto_start_year", 1911)) <= 1911 <= int(t.get("de_facto_end_year", 1953)))
    if tusi_1911 < expected_1911 - 2:
      failures.append(f"Expected >= {expected_1911 - 2} active Feudatories in adm_3_1911.geojson, found {tusi_1911}")
    dep_1911 = [ft.get("properties", {}).get("unit_id") for ft in f_1911 if ft.get("properties", {}).get("category") == "tusi" and str(ft.get("properties", {}).get("unit_id") or "")[5:] in deprecated_ids]
    if dep_1911:
      failures.append(f"Deprecated Tusis present in adm_3_1911.geojson: {dep_1911[:5]}")

  for yr in (1938, 1939, 1940, 1942, 1944, 1945):
    ypath = os.path.join(adm_annual_dir, f"adm_3_{yr}.geojson")
    if not os.path.exists(ypath):
      continue
    with open(ypath, "r", encoding="utf-8") as fh:
      yfeats = json.load(fh).get("features", [])
    all_geoms = []
    occ_by_key = {}
    occ_items = []
    for ft in yfeats:
      p = ft.get("properties", {})
      g = shape(ft["geometry"])
      a1 = str(p.get("parent_adm1") or "")
      a2 = str(p.get("parent_adm2") or "")
      n_en = str(p.get("name_en") or "")
      occ_val = str(p.get("occupied_by") or "")
      occ_by_key[(a1, n_en)] = occ_val
      if p.get("country") not in ("Taiwan",):
        all_geoms.append(g)
      if not occ_val or a1 == "Taiwan":
        continue
      if a1 == "Sichuan":
        failures.append(f"Unexpected Japanese occupation in Sichuan at {yr}: {n_en}")
      if a1 == "Anhui" and "Huizhou" in a2:
        failures.append(f"Unexpected Japanese occupation in Anhui Huizhou at {yr}: {n_en}")
      rp = g.representative_point()
      occ_items.append((g, float(rp.x), float(rp.y)))

    _check_year_name_rules(yr, occ_by_key, failures)

    if occ_items and all_geoms and yr in (1938, 1940, 1942, 1944, 1945):
      u = unary_union(all_geoms)
      segs = []
      for poly in ([u] if u.geom_type == "Polygon" else list(u.geoms)):
        if poly.area <= 1e-6:
          continue
        coords = list(poly.exterior.coords)
        for k in range(0, max(1, len(coords) - 1), 64):
          sc = coords[k:k + 65]
          if len(sc) >= 2:
            segs.append(LineString(sc))
      outer_tree = STRtree(segs)
      og = [it[0] for it in occ_items]
      ohits = {int(v) for v in outer_tree.query(og, predicate="dwithin", distance=0.025)[0]}
      otree = STRtree(og)
      pairs = otree.query(og, predicate="dwithin", distance=0.018)
      adj = [[] for _ in range(len(occ_items))]
      for k in range(pairs.shape[1]):
        i, j = int(pairs[0, k]), int(pairs[1, k])
        if i != j:
          adj[i].append(j)
      seen = [False]*len(occ_items)
      for start in range(len(occ_items)):
        if seen[start]:
          continue
        comp, q, seen[start], ok = [], [start], True, False
        while q:
          cur = q.pop()
          comp.append(cur)
          _, lon, lat = occ_items[cur]
          if cur in ohits and (
            (lon >= 107.3 and lat <= 41.8)
            or (lon >= 123.8 and lat >= 39.7)
            or (yr in (1943, 1944) and lon <= 99.2 and lat <= 26.2)
            or (yr == 1945 and 105.5 <= lon <= 108.8 and lat <= 23.2)
          ):
            ok = True
          for nb in adj[cur]:
            if not seen[nb]:
              seen[nb] = True
              q.append(nb)
        if not ok:
          failures.append(f"Disconnected interior occupied component at {yr} ({len(comp)} units)")


def main ():
  """Execute workspace structure verification CLI.

  @return Exit code 0 if all checks pass, 1 otherwise.
  """
  # Declare local instance variables.
  failures = []
  root_dir = path_helpers.get_project_root()

  failures = _collect_failures(root_dir)
  if failures:
    for item in failures:
      print(f"[FAIL] {item}", file=sys.stderr)
    print(f"[VERIFY FAIL] {len(failures)} check(s) failed.", file=sys.stderr)
    return 1

  tusi_cat = gis_helpers.load_json5(path_helpers.resolve_path("common.tusi_catalog", root_dir))
  active_cnt = sum(1 for t in tusi_cat.get("tusis", []) if not t.get("deprecated", False))
  print(f"[VERIFY OK] 7-folder layout, paths.json5, {127 + active_cnt} chronicle targets, GeoJSON/PNG topology & freshness, server AST and 7 skills verified.")

  # Return statement
  return 0


if __name__ == "__main__":
  sys.exit(main())
