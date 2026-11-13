@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

python core\server\pipelines\A_download_and_reproject_gis.py || exit /b 1
python core\server\pipelines\B_build_tibet_reference.py || exit /b 1
python core\server\pipelines\C_build_tusi_divisions.py || exit /b 1
python core\server\pipelines\D_build_annual_admin_series.py || exit /b 1
python core\server\pipelines\B_build_tibet_reference.py --scanline-only || exit /b 1
python core\server\pipelines\E_scanline_rasterise_adm.py --years 1911,1912,1936,1948 || exit /b 1
python core\server\pipelines\F_export_chronicles_and_defines.py || exit /b 1
python core\server\pipelines\G_download_and_crosswalk_modern_gis.py || exit /b 1
python tests\verify_file_structure.py || exit /b 1
