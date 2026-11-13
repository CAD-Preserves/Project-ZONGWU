@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

python core\server\pipelines\F_export_chronicles_and_defines.py || exit /b 1
python core\server\pipelines\E_scanline_rasterise_adm.py --years 1912,1936,1948 || exit /b 1
python core\server\pipelines\B_build_tibet_reference.py --scanline-only || exit /b 1
python tests\verify_file_structure.py || exit /b 1
