"""Pipeline Step G: Build modern administrative reference layers and gazetteer crosswalk."""

import os
import sys

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from classes.ModernGisCrosswalkBuilder import ModernGisCrosswalkBuilder
from helpers import path_helpers


def main ():
  """Execute Step G modern GIS crosswalk and verification raster export.

  @return Process exit code (0 on success).
  """
  # Declare local instance variables.
  base_dir = path_helpers.get_project_root()
  builder = ModernGisCrosswalkBuilder(base_dir)
  summary = {}

  summary = builder.build_crosswalk_and_rasters()
  print("[STEP G DONE]", summary)

  # Return statement
  return 0


if __name__ == "__main__":
  sys.exit(main())
