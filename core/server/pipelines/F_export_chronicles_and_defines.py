"""Pipeline Step F: Export output/chronicles/ hierarchy, province_defines.json5, and localisation."""

import os
import sys

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)

from classes.ChroniclesDefinesExporter import ChroniclesDefinesExporter
from helpers import path_helpers


def main ():
  """Execute Step F chronicle directory, defines, and localisation export.

  @return Process exit code (0 on success).
  """
  # Declare local instance variables.
  base_dir = path_helpers.get_project_root()
  exporter = ChroniclesDefinesExporter(base_dir)
  summary = {}

  summary = exporter.export_all()
  print("[STEP F DONE]", summary)

  # Return statement
  return 0


if __name__ == "__main__":
  sys.exit(main())
