"""Automated workspace structure, schema, AST and skill-path verification suite."""

import ast
import json
import os
import re
import sys
from shapely import STRtree
from shapely.geometry import LineString, shape
from shapely.ops import unary_union

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "server"))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from helpers import gis_helpers, path_helpers


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
      "common.province_defines",
      "common.source_registry",
      "common.tibet_reference_config",
      "common.transport_corridors",
      "common.tusi_catalog",
      "common.tusi_modelling_config",
      "input.gis.chgis_1911_adm1_base",
      "input.gis.chgis_1911_adm2_base",
      "input.gis.chgis_1911_adm3_base",
      "input.gis.chgis_dir",
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
      "output.newspapers_dir",
      "tests.outputs_dir",
    ):
      resolved = path_helpers.resolve_path(dot_key, root_dir)
      if not resolved or not os.path.exists(resolved):
        failures.append(f"Missing resolved path for {dot_key}: {resolved}")

  # 3. province_defines.json5 & output/chronicles/ hierarchy
  defines = gis_helpers.load_json5(path_helpers.resolve_path("common.province_defines", root_dir))
  provinces_map = defines.get("provinces", {}) if isinstance(defines, dict) else {}
  if len(provinces_map) != 750:
    failures.append(f"Expected 750 entries in province_defines.json5['provinces'], found {len(provinces_map)}")
  else:
    for slug, entry in provinces_map.items():
      c_path = str(entry.get("chronicle_path") or "")
      if not c_path.startswith("./output/chronicles/") or not c_path.endswith("/"):
        failures.append(f"Invalid chronicle_path for {slug}: {c_path}")
        continue
      if c_path in seen_rel_paths:
        failures.append(f"Duplicate chronicle_path: {c_path}")
      seen_rel_paths.add(c_path)
      abs_dir = os.path.normpath(os.path.join(root_dir, c_path))
      if not os.path.isdir(abs_dir):
        failures.append(f"Missing chronicle directory on disk: {abs_dir}")

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

  _check_historical_invariants(root_dir, failures)

  # Return statement
  return failures


def _check_historical_invariants (arg1_root_dir, arg2_failures):
  """Verify 1911 seat metadata, 1911 Feudatory continuity, and enclave-free 1942/1945 occupation."""
  # Convert from parameters
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
    if tusi_1911 < 620:
      failures.append(f"Expected >= 620 Feudatories in adm_3_1911.geojson, found {tusi_1911}")

  for yr in (1942, 1945):
    ypath = os.path.join(adm_annual_dir, f"adm_3_{yr}.geojson")
    if not os.path.exists(ypath):
      continue
    with open(ypath, "r", encoding="utf-8") as fh:
      yfeats = json.load(fh).get("features", [])
    all_geoms = []
    occ_items = []
    for ft in yfeats:
      p = ft.get("properties", {})
      g = shape(ft["geometry"])
      if p.get("country") not in ("Taiwan",):
        all_geoms.append(g)
      if not p.get("occupied_by") or p.get("parent_adm1") == "Taiwan":
        continue
      a1 = str(p.get("parent_adm1") or "")
      a2 = str(p.get("parent_adm2") or "")
      if a1 == "Sichuan":
        failures.append(f"Unexpected Japanese occupation in Sichuan at {yr}: {p.get('name_en')}")
      if a1 == "Anhui" and "Huizhou" in a2:
        failures.append(f"Unexpected Japanese occupation in Anhui Huizhou at {yr}: {p.get('name_en')}")
      rp = g.representative_point()
      occ_items.append((g, float(rp.x), float(rp.y)))

    if occ_items and all_geoms:
      u = unary_union(all_geoms)
      segs = []
      for poly in ([u] if u.geom_type == "Polygon" else list(u.geoms)):
        if poly.area <= 0.001:
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
          if cur in ohits and ((lon >= 107.8 and lat <= 41.8) or (lon >= 123.8 and lat >= 39.7) or (yr == 1945 and 105.5 <= lon <= 108.8 and lat <= 23.2)):
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

  print("[VERIFY OK] 7-folder layout, paths.json5, 750 chronicle targets, GeoJSON counts, server AST and 7 skills verified.")

  # Return statement
  return 0


if __name__ == "__main__":
  sys.exit(main())
