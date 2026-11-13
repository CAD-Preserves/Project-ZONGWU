#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 core/server/pipelines/F_export_chronicles_and_defines.py
python3 core/server/pipelines/E_scanline_rasterise_adm.py --years 1912,1936,1948
python3 core/server/pipelines/B_build_tibet_reference.py --scanline-only
python3 tests/verify_file_structure.py
