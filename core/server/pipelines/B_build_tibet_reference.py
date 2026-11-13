"""Pipeline Step B: Generate Tibet/Yushu reference polygons and verify video/plate scanlines."""

import os
import sys

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from classes.ReferenceScanlineRasteriser import ReferenceScanlineRasteriser
from helpers import path_helpers, tibet_reference_helpers


def main ():
  """Execute Step B reference polygon extraction and optional scanline verification.

  @return Process exit code (0 on success, 1 on threshold failure).
  """
  # Declare local instance variables.
  args = sys.argv[1:]
  base_dir = path_helpers.get_project_root()
  failed = []
  metrics = {}
  rasteriser = None
  run_build = "--scanline-only" not in args
  run_scanline = ("--scanline-only" in args) or ("--verify-scanline" in args)

  if run_build:
    tibet_reference_helpers.build_reference_polygons(base_dir)
    print("[STEP B] Reference polygons built.")

  if run_scanline:
    rasteriser = ReferenceScanlineRasteriser(base_dir)
    metrics = rasteriser.run_alignment_suite()
    failed = [k for k, v in metrics.items() if v < 95.0]
    if failed:
      print(f"[SCANLINE FAIL] Below 95,0% threshold: {failed}", file=sys.stderr)
      return 1

  # Return statement
  return 0


if __name__ == "__main__":
  sys.exit(main())
