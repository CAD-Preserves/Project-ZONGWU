"""Pipeline Step E: Rasterise annual adm_1, adm_2, and adm_3 snapshots to verification PNGs."""

import os
import sys

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from classes.ScanlineRasteriser import ScanlineRasteriser
from helpers import gis_helpers, path_helpers


def _parse_years_flag (arg1_argv):
  """Parse optional --all, --prc-all, --years, or --prc-years list/range from CLI arguments.

  @param arg1_argv CLI argument sequence excluding program name.
  @return Tuple (is_prc_mode, list_of_years).
  """
  # Convert from parameters
  argv = list(arg1_argv or [])

  # Declare local instance variables.
  is_prc = "--prc-all" in argv or any(a.startswith("--prc-years") for a in argv)
  raw = ""
  years = list(range(1954, 2027)) if "--prc-all" in argv else [1911, 1912, 1936, 1948]

  if "--all" in argv:
    return False, list(range(1911, 1954))
  if "--prc-all" in argv:
    return True, list(range(1954, 2027))

  for i in range(len(argv)):
    if argv[i] in ("--years", "--prc-years") and i + 1 < len(argv):
      raw = argv[i + 1]
    elif argv[i].startswith("--years=") or argv[i].startswith("--prc-years="):
      raw = argv[i].split("=", 1)[1]

  if raw:
    years = []
    for tok in raw.split(","):
      tok_s = tok.strip()
      if not tok_s:
        continue
      if "-" in tok_s:
        a, b = tok_s.split("-", 1)
        years.extend(range(int(a.strip()), int(b.strip()) + 1))
      else:
        years.append(int(tok_s))

  # Return statement
  return is_prc, years


def main ():
  """Execute Step E scanline verification rasterisation to tests/outputs/.

  @return Process exit code (0 on success, 1 on missing configuration).
  """
  # Declare local instance variables.
  base_dir = path_helpers.get_project_root()
  cfg = None
  in_path = ""
  is_prc, years = _parse_years_flag(sys.argv[1:])
  out_path = ""
  rasteriser = None
  src_dir = ""
  tests_outputs_dir = ""

  cfg = gis_helpers.load_json5(path_helpers.resolve_path("common.data_sources", base_dir))
  if cfg is None:
    return 1

  src_dir = path_helpers.resolve_path("output.gis.prc_annual_dir" if is_prc else "output.gis.adm_annual_dir", base_dir)
  tests_outputs_dir = path_helpers.resolve_path("tests.outputs_dir", base_dir)
  os.makedirs(tests_outputs_dir, exist_ok=True)
  rasteriser = ScanlineRasteriser(cfg)

  for yr in years:
    for lvl in (1, 2, 3):
      in_name = f"prc_adm_{lvl}_{yr}.geojson" if is_prc else f"adm_{lvl}_{yr}.geojson"
      out_name = f"PRC_adm_{lvl}_{yr}.png" if is_prc else f"CHGIS_adm_{lvl}_{yr}.png"
      in_path = os.path.join(src_dir, in_name)
      if not os.path.exists(in_path):
        print(f"[WARN] Missing snapshot GeoJSON: {in_path}", file=sys.stderr)
        continue
      out_path = os.path.join(tests_outputs_dir, out_name)
      rasteriser.render_geojson_to_png(in_path, out_path, yr, lvl)

  # Return statement
  return 0


if __name__ == "__main__":
  sys.exit(main())
