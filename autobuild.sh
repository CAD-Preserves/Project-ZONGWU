#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 core/server/pipelines/A_download_and_reproject_gis.py
python3 core/server/pipelines/B_build_tibet_reference.py
python3 core/server/pipelines/C_build_tusi_divisions.py
python3 core/server/pipelines/D_build_annual_admin_series.py
python3 core/server/pipelines/B_build_tibet_reference.py --scanline-only
python3 core/server/pipelines/E_scanline_rasterise_adm.py --years 1911,1912,1936,1948
python3 core/server/pipelines/F_export_chronicles_and_defines.py
python3 core/server/pipelines/G_download_and_crosswalk_modern_gis.py
python3 tests/verify_file_structure.py
