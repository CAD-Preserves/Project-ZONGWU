"""Canonical workspace path resolution helpers reading ./common/paths.json5."""

from functools import lru_cache
import os
import sys

if os.path.abspath(os.path.join(os.path.dirname(__file__), "..")) not in sys.path:
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from helpers import gis_helpers


def get_project_root ():
  """Return the absolute workspace root directory (three levels above core/server/helpers/).

  @return Absolute path string to Project-ZONGWU root.
  """
  # Return statement
  return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


@lru_cache(maxsize=4)
def load_paths (arg1_base_dir=None):
  """Load and cache common/paths.json5 for a given workspace root.

  @param arg1_base_dir Optional workspace root directory.
  @return Parsed paths dictionary from common/paths.json5.
  """
  # Convert from parameters
  base_dir = os.path.abspath(arg1_base_dir) if arg1_base_dir else get_project_root()

  # Declare local instance variables.
  paths_file = os.path.join(base_dir, "common", "paths.json5")

  # Return statement
  return gis_helpers.load_json5(paths_file)


def resolve_chronicle_relpath (arg1_slug, arg2_category, arg3_tusi_region="", arg4_loc_maps=None):
  """Resolve canonical ./output/chronicles/ relative directory path for a division or Tusi.

  @param arg1_slug Division or Tusi snake_case slug.
  @param arg2_category Primary category key from province_defines.
  @param arg3_tusi_region Regional bucket inside tusi_catalog.json5 when category is 'tusi'.
  @param arg4_loc_maps Optional parsed common/defines/localisation_maps.json5 dictionary.
  @return Relative path string such as './output/chronicles/provinces/sichuan/'.
  """
  # Convert from parameters
  category = str(arg2_category or "province").strip()
  loc_maps = arg4_loc_maps or {}
  slug = str(arg1_slug or "").strip()
  tusi_region = str(arg3_tusi_region or "").strip()

  # Declare local instance variables.
  branch_map = loc_maps.get("chronicle_category_branches", {})
  branch = branch_map.get(category)

  if not branch:
    if category == "tusi":
      branch = "tusi"
    elif category == "municipality":
      branch = "municipalities"
    elif category in ("special_region", "autonomous_region", "autonomous_oblast"):
      branch = "autonomous_and_special"
    elif category in ("puppet_province", "occupied_province", "occupied_city", "leased_territory", "colony"):
      branch = "occupied_and_leased"
    elif category in ("aimag", "frontier_polity", "republic"):
      branch = "frontier_and_outer"
    else:
      branch = "provinces"

  if branch == "tusi":
    if tusi_region:
      return f"./output/chronicles/tusi/{tusi_region}/{slug}/"
    return f"./output/chronicles/tusi/{slug}/"

  # Return statement
  return f"./output/chronicles/{branch}/{slug}/"


def resolve_path (arg1_dot_key, arg2_base_dir=None):
  """Resolve a dotted key from common/paths.json5 into an absolute workspace path.

  @param arg1_dot_key Dotted key string (e.g. 'output.gis.adm_annual_dir').
  @param arg2_base_dir Optional workspace root directory.
  @return Resolved absolute path string.
  """
  # Convert from parameters
  base_dir = os.path.abspath(arg2_base_dir) if arg2_base_dir else get_project_root()
  dot_key = str(arg1_dot_key or "").strip()

  # Declare local instance variables.
  cursor = load_paths(base_dir)
  parts = dot_key.split(".")

  for part in parts:
    if isinstance(cursor, dict) and part in cursor:
      cursor = cursor[part]
    else:
      print(f"[ERROR] Missing path key in common/paths.json5: {dot_key}", file=sys.stderr)
      return ""

  if not isinstance(cursor, str):
    print(f"[ERROR] Path key does not resolve to string: {dot_key}", file=sys.stderr)
    return ""

  # Return statement
  return os.path.normpath(os.path.join(base_dir, cursor))


def resolve_provider_file (arg1_cfg, arg2_section, arg3_file_key, arg4_base_dir=None):
  """Resolve local filepath for a configured data_sources.json5 provider entry.

  @param arg1_cfg Parsed data_sources.json5 dictionary.
  @param arg2_section Top-level provider key (e.g. 'chgis_dataverse' or 'gadm').
  @param arg3_file_key Entry key inside section['files'].
  @param arg4_base_dir Optional workspace root directory.
  @return Resolved absolute path string inside input/gis/.
  """
  # Convert from parameters
  base_dir = os.path.abspath(arg4_base_dir) if arg4_base_dir else get_project_root()
  cfg = arg1_cfg or {}
  file_key = str(arg3_file_key or "").strip()
  section = str(arg2_section or "").strip()

  # Declare local instance variables.
  sec_obj = cfg.get(section, {})
  files_map = sec_obj.get("files", {})
  fname = str(files_map.get(file_key, {}).get("filename") or "").strip()
  target_dir = str(sec_obj.get("target_dir") or "").strip()

  if not fname or not target_dir:
    print(f"[ERROR] Incomplete data_sources entry: {section}.{file_key}", file=sys.stderr)
    return ""

  # Return statement
  return os.path.normpath(os.path.join(base_dir, target_dir, fname))


def resolve_source_file (arg1_provider, arg2_filename, arg3_base_dir=None):
  """Resolve a filename inside one of the canonical input/gis/<provider> subdirectories.

  @param arg1_provider Provider key ('chgis', 'gadm', 'hydrosheds', 'modern', 'modern_reference', 'natural_earth', 'priors').
  @param arg2_filename Target file or cache name inside the provider directory.
  @param arg3_base_dir Optional workspace root directory.
  @return Resolved absolute path string.
  """
  # Convert from parameters
  base_dir = os.path.abspath(arg3_base_dir) if arg3_base_dir else get_project_root()
  filename = str(arg2_filename or "").strip()
  provider = str(arg1_provider or "").strip()

  # Declare local instance variables.
  provider_keys = {
    "chgis": "input.gis.chgis_dir",
    "gadm": "input.gis.gadm_dir",
    "hydrosheds": "input.gis.hydrosheds_dir",
    "modern": "input.gis.modern_dir",
    "modern_reference": "input.gis.modern_reference_dir",
    "natural_earth": "input.gis.natural_earth_dir",
    "priors": "input.gis.priors_dir",
  }
  path_key = provider_keys.get(provider)

  if not path_key:
    print(f"[ERROR] Unknown input/gis provider key: {provider}", file=sys.stderr)
    return ""

  # Return statement
  return os.path.normpath(os.path.join(resolve_path(path_key, base_dir), filename))
