"""Pipeline Step C: Build and verify historical Tusi divisions (1912-1953)."""

import os
import sys

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from classes.TusiModeller import TusiModeller
from helpers import path_helpers


def main ():
  """Execute Step C Tusi polygon modelling, GeoJSON export, and diagnostic renders.

  @return Process exit code (0 on success).
  """
  # Declare local instance variables.
  base_dir = path_helpers.get_project_root()
  feat_count = 0
  metrics = {}
  modeller = TusiModeller(base_dir)
  out_geojson = ""
  pngs = []
  refresh_maps = "--refresh-maps" in sys.argv[1:]
  reuse_unchanged = "--reuse-unchanged" in sys.argv[1:]

  if refresh_maps:
    feat_count = modeller.load_existing_geojson()
    out_geojson, feat_count = modeller.export_geojson()
    pngs = modeller.render_diagnostic_maps()
    print(f"[STEP C REFRESH] features={feat_count} geojson={out_geojson} pngs={len(pngs)}")
  else:
    metrics = modeller.build_all_tusis(reuse_unchanged)
    out_geojson, feat_count = modeller.export_geojson()
    pngs = modeller.render_diagnostic_maps()
    print(f"[STEP C DONE] features={feat_count} (direct={metrics['chgis_direct']}, tier_b={metrics['tier_b']}, tier_c={metrics['tier_c']}) max_ov={metrics['max_overlap_deg2']:.9f} geojson={out_geojson} pngs={len(pngs)}")

  # Return statement
  return 0


if __name__ == "__main__":
  sys.exit(main())
