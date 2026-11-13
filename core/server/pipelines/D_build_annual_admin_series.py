"""Pipeline Step D: Construct annual CHGIS/Feudatory adm_1, adm_2, and adm_3 snapshots (1911-1953)."""

import os
import sys

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from classes.AnnualAdminBuilder import AnnualAdminBuilder
from helpers import path_helpers


def main ():
  """Execute Step D annual 1911-1953 GeoJSON generation.

  @return Process exit code (0 on success).
  """
  # Declare local instance variables.
  argv = sys.argv[1:]
  base_dir = path_helpers.get_project_root()
  builder = AnnualAdminBuilder(base_dir)
  end_year = 1953
  results = []
  start_year = 1911

  for i in range(len(argv)):
    if argv[i] == "--start-year" and i + 1 < len(argv):
      start_year = int(argv[i + 1])
    elif argv[i].startswith("--start-year="):
      start_year = int(argv[i].split("=", 1)[1])
    elif argv[i] == "--end-year" and i + 1 < len(argv):
      end_year = int(argv[i + 1])
    elif argv[i].startswith("--end-year="):
      end_year = int(argv[i].split("=", 1)[1])

  os.makedirs(builder.adm_annual_dir, exist_ok=True)
  results = builder.build_all_years(start_year, end_year)
  print(f"[STEP D DONE] Built {len(results)} annual admin snapshot sets ({start_year}-{end_year}).")

  # Return statement
  return 0


if __name__ == "__main__":
  sys.exit(main())
