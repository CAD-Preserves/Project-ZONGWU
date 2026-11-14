"""Streaming download and reader helpers for CTAmap annual GeoPackages and MCA areacodes lineage."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import io
import json
import os
import sqlite3
import sys
import zipfile
import requests
from shapely import from_wkb, set_precision

if os.path.abspath(os.path.join(os.path.dirname(__file__), "..")) not in sys.path:
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from helpers import gis_helpers, path_helpers


def _clean_text (arg1_val):
  """Normalise attribute cell text by stripping whitespace and CR/LF artifacts.

  @param arg1_val Raw database or CSV value.
  @return Stripped UTF-8 string.
  """
  # Return statement
  return "" if arg1_val is None else str(arg1_val).strip()


def _download_zenodo_file (arg1_url, arg2_dest_path, arg3_expected_size=0, arg4_expected_md5="", arg5_retries=4):
  """Stream a remote file to disk with atomic temp-file swap and size/MD5 validation.

  @param arg1_url Remote HTTP/HTTPS URL.
  @param arg2_dest_path Destination local filepath.
  @param arg3_expected_size Optional expected byte length for cache validation.
  @param arg4_expected_md5 Optional expected lowercase MD5 hex digest.
  @param arg5_retries Maximum download attempts.
  @return True if verified file exists at destination, False otherwise.
  """
  # Convert from parameters
  dest_path = arg2_dest_path
  expected_md5 = str(arg4_expected_md5 or "").strip().lower()
  expected_size = int(arg3_expected_size or 0)
  retries = max(1, int(arg5_retries or 1))
  url = arg1_url

  # Declare local instance variables.
  attempt = 0
  buf = b""
  digest = ""
  headers = {"User-Agent": "Mozilla/5.0 (Project-ZONGWU/2.0)"}
  h_obj = None
  resp = None
  tmp_path = f"{dest_path}.tmp"

  if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
    if expected_size > 0 and os.path.getsize(dest_path) != expected_size:
      os.remove(dest_path)
    elif expected_md5:
      if _file_md5(dest_path) == expected_md5:
        return True
      os.remove(dest_path)
    else:
      return True

  os.makedirs(os.path.dirname(dest_path), exist_ok=True)
  for attempt in range(1, retries + 1):
    try:
      resp = requests.get(url, headers=headers, allow_redirects=True, stream=True, timeout=300)
      if not resp.ok:
        print(f"[WARN] HTTP {resp.status_code} on attempt {attempt}/{retries}: {url}", file=sys.stderr)
        continue
      h_obj = hashlib.md5()
      with open(tmp_path, "wb") as fh:
        for buf in resp.iter_content(chunk_size=131072):
          if buf:
            fh.write(buf)
            h_obj.update(buf)
      if expected_size > 0 and os.path.getsize(tmp_path) != expected_size:
        print(f"[WARN] Size mismatch for {os.path.basename(dest_path)} ({os.path.getsize(tmp_path)} != {expected_size})", file=sys.stderr)
        continue
      digest = h_obj.hexdigest().lower()
      if expected_md5 and digest != expected_md5:
        print(f"[WARN] MD5 mismatch for {os.path.basename(dest_path)} ({digest} != {expected_md5})", file=sys.stderr)
        continue
      os.replace(tmp_path, dest_path)
      return True
    except Exception as exc:
      print(f"[WARN] Attempt {attempt}/{retries} failed for {url}: {exc}", file=sys.stderr)
    finally:
      if os.path.exists(tmp_path):
        try:
          os.remove(tmp_path)
        except OSError:
          pass

  # Return statement
  return False


def _fetch_zenodo_manifest (arg1_record_id, arg2_cache_path):
  """Fetch and cache Zenodo file metadata (sizes and MD5 checksums) for integrity checks.

  @param arg1_record_id Zenodo numeric record identifier string.
  @param arg2_cache_path Local JSON cache file path.
  @return Dictionary mapping filename to {'md5': str, 'size': int, 'url': str}.
  """
  # Convert from parameters
  cache_path = arg2_cache_path
  record_id = str(arg1_record_id or "22179207").strip()

  # Declare local instance variables.
  api_url = f"https://zenodo.org/api/records/{record_id}"
  csum = ""
  f_entry = {}
  fname = ""
  manifest = {}
  payload = {}
  resp = None

  if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
    try:
      with open(cache_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    except Exception:
      payload = {}

  if not payload:
    try:
      resp = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0 (Project-ZONGWU/2.0)"}, timeout=60)
      if resp.ok:
        payload = resp.json()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as fh:
          json.dump(payload, fh, ensure_ascii=False, indent=2)
    except Exception as exc:
      print(f"[WARN] Failed to fetch Zenodo record manifest {api_url}: {exc}", file=sys.stderr)

  for f_entry in payload.get("files", []):
    fname = str(f_entry.get("key") or "").strip()
    if not fname:
      continue
    csum = str(f_entry.get("checksum") or "").strip()
    if csum.startswith("md5:"):
      csum = csum[4:]
    manifest[fname] = {
      "md5": csum.lower(),
      "size": int(f_entry.get("size") or 0),
      "url": str(f_entry.get("links", {}).get("self") or ""),
    }

  # Return statement
  return manifest


def _file_md5 (arg1_path):
  """Compute lowercase MD5 hex digest for a local file.

  @param arg1_path Local file path.
  @return Lowercase MD5 hex digest string.
  """
  # Convert from parameters
  filepath = arg1_path

  # Declare local instance variables.
  chunk = b""
  h_obj = hashlib.md5()

  with open(filepath, "rb") as fh:
    while True:
      chunk = fh.read(1048576)
      if not chunk:
        break
      h_obj.update(chunk)

  # Return statement
  return h_obj.hexdigest().lower()


def _parse_gpkg_envelope_len (arg1_flags):
  """Compute GeoPackage binary envelope byte length from header flags byte.

  @param arg1_flags Third byte of GeoPackage WKB header.
  @return Header offset in bytes preceding standard WKB payload.
  """
  # Convert from parameters
  flags = int(arg1_flags)

  # Declare local instance variables.
  env_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
  env_type = (flags >> 1) & 0x07

  # Return statement
  return 8 + env_sizes.get(env_type, 0)


def _split_areacode_targets (arg1_raw_targets):
  """Parse yescallop/areacodes semicolon-delimited target field with optional [YYYY] annotations.

  @param arg1_raw_targets Raw 新代码 field string.
  @return List of {'code': str, 'year': int_or_None} dicts.
  """
  # Convert from parameters
  raw_targets = _clean_text(arg1_raw_targets)

  # Declare local instance variables.
  code_part = ""
  out = []
  part = ""
  yr_part = None

  if not raw_targets:
    return out

  for part in raw_targets.split(";"):
    part = part.strip()
    if not part:
      continue
    yr_part = None
    code_part = part
    if "[" in part and part.endswith("]"):
      code_part, yr_str = part[:-1].split("[", 1)
      code_part = code_part.strip()
      if yr_str.isdigit():
        yr_part = int(yr_str)
    if code_part:
      out.append({"code": code_part, "year": yr_part})

  # Return statement
  return out


def download_ctamap_archive (arg1_cfg, arg2_base_dir=None, arg3_years=None, arg4_max_workers=3):
  """Download CTAmap tables.zip and annual T<year>_county.gpkg files into input/gis/ctamap/.

  @param arg1_cfg Parsed data_sources.json5 dictionary.
  @param arg2_base_dir Optional workspace root directory.
  @param arg3_years Optional iterable of years (defaults to configured [2000..2026]).
  @param arg4_max_workers Concurrent worker cap for Zenodo HTTP downloads.
  @return Dictionary mapping filename to local file path.
  """
  # Convert from parameters
  base_dir = os.path.abspath(arg2_base_dir) if arg2_base_dir else path_helpers.get_project_root()
  cfg = arg1_cfg or {}
  max_workers = max(1, int(arg4_max_workers or 3))
  years_arg = arg3_years

  # Declare local instance variables.
  base_url = str(cfg.get("ctamap_zenodo", {}).get("base_url") or "https://zenodo.org/api/records/22179207/files/").rstrip("/")
  ctamap_cfg = cfg.get("ctamap_zenodo", {})
  dest_dir = path_helpers.resolve_path("input.gis.ctamap_dir", base_dir)
  fut = None
  futs = {}
  job_list = []
  manifest = {}
  meta = {}
  ok = False
  paths = {}
  rec_id = str(ctamap_cfg.get("record_id") or "22179207")
  tables_fn = str(ctamap_cfg.get("tables_filename") or "tables.zip")
  yr = 0
  yr_range = ctamap_cfg.get("years", [2000, 2026])
  yr_list = []

  if not dest_dir:
    dest_dir = os.path.normpath(os.path.join(base_dir, str(ctamap_cfg.get("target_dir") or "input/gis/ctamap")))
  os.makedirs(dest_dir, exist_ok=True)

  manifest = _fetch_zenodo_manifest(rec_id, os.path.join(dest_dir, f"zenodo_record_{rec_id}.json"))
  if years_arg is not None:
    yr_list = [int(y) for y in years_arg]
  else:
    yr_list = list(range(int(yr_range[0]), int(yr_range[1]) + 1))

  job_list.append(tables_fn)
  for yr in yr_list:
    job_list.append(f"T{yr}_county.gpkg")

  with ThreadPoolExecutor(max_workers=max_workers) as pool:
    for fn in job_list:
      meta = manifest.get(fn, {})
      dl_url = meta.get("url") or f"{base_url}/{fn}/content"
      dest_p = os.path.join(dest_dir, fn)
      fut = pool.submit(_download_zenodo_file, dl_url, dest_p, meta.get("size", 0), meta.get("md5", ""))
      futs[fut] = (fn, dest_p)
    for fut in as_completed(futs):
      fn, dest_p = futs[fut]
      ok = fut.result()
      if ok:
        paths[fn] = dest_p
      else:
        print(f"[ERROR] Failed to cache CTAmap artifact: {fn}", file=sys.stderr)

  # Return statement
  return paths


def load_areacodes_lineage (arg1_result_csv_path, arg2_codes_json_path=""):
  """Parse MCA areacodes result.csv (1981-2025 Dec-31 snapshots) and optional codes.json.

  @param arg1_result_csv_path Local path to areacodes_result.csv.
  @param arg2_codes_json_path Optional local path to areacodes_codes.json.
  @return Dictionary containing parsed 'rows', 'by_code', 'forward_edges', and 'codes_tree'.
  """
  # Convert from parameters
  codes_json_path = str(arg2_codes_json_path or "").strip()
  result_csv_path = str(arg1_result_csv_path or "").strip()

  # Declare local instance variables.
  by_code = {}
  ch_yr = None
  codes_tree = {}
  en_yr = None
  forward_edges = {}
  nc_str = ""
  rec = {}
  row = {}
  rows = []
  tgt = {}

  if os.path.isfile(result_csv_path):
    with open(result_csv_path, "r", encoding="utf-8-sig", newline="") as fh:
      for row in csv.DictReader(fh):
        code = _clean_text(row.get("代码"))
        if not code:
          continue
        en_s = _clean_text(row.get("启用时间"))
        ch_s = _clean_text(row.get("变更/弃用时间"))
        en_yr = int(en_s) if en_s.isdigit() else None
        ch_yr = int(ch_s) if ch_s.isdigit() else None
        nc_str = _clean_text(row.get("新代码"))
        rec = {
          "adm1_zh": _clean_text(row.get("一级行政区")),
          "adm2_zh": _clean_text(row.get("二级行政区")),
          "change_year": ch_yr,
          "code": code,
          "enable_year": en_yr,
          "level": _clean_text(row.get("级别")),
          "name_zh": _clean_text(row.get("名称")),
          "new_targets": _split_areacode_targets(nc_str),
          "status": _clean_text(row.get("状态")),
        }
        rows.append(rec)
        by_code.setdefault(code, []).append(rec)
        for tgt in rec["new_targets"]:
          forward_edges.setdefault(code, set()).add(tgt["code"])

  if codes_json_path and os.path.isfile(codes_json_path):
    try:
      with open(codes_json_path, "r", encoding="utf-8") as fh:
        codes_tree = json.load(fh)
    except Exception as exc:
      print(f"[WARN] Could not parse areacodes_codes.json: {exc}", file=sys.stderr)

  # Return statement
  return {
    "by_code": by_code,
    "codes_tree": codes_tree,
    "forward_edges": {k: sorted(v) for k, v in forward_edges.items()},
    "rows": rows,
  }


def load_ctamap_events (arg1_tables_zip_path):
  """Load change_events_v2 and supplementary CSV tables from CTAmap tables.zip.

  @param arg1_tables_zip_path Path to CTAmap tables.zip.
  @return Dictionary mapping table stem to list of row dictionaries.
  """
  # Convert from parameters
  zip_path = str(arg1_tables_zip_path or "").strip()

  # Declare local instance variables.
  data = b""
  member = ""
  out = {}
  reader = None
  row = {}
  stem = ""
  txt = ""
  zf = None

  if not os.path.isfile(zip_path):
    return out

  with zipfile.ZipFile(zip_path, "r") as zf:
    for member in sorted(zf.namelist()):
      if not member.lower().endswith(".csv"):
        continue
      stem = os.path.splitext(os.path.basename(member))[0]
      data = zf.read(member)
      try:
        txt = data.decode("utf-8-sig")
      except UnicodeDecodeError:
        txt = data.decode("gb18030", errors="replace")
      reader = csv.DictReader(io.StringIO(txt))
      out[stem] = [{_clean_text(k): _clean_text(v) for k, v in row.items() if k is not None} for row in reader]

  # Return statement
  return out


def parse_gpkg_wkb (arg1_blob):
  """Extract standard WKB bytes from a GeoPackage geometry binary blob and decode with Shapely.

  @param arg1_blob Raw SQLite BLOB bytes from a GeoPackage geometry column.
  @return Tuple of (shapely_geometry_or_None, wkb_bytes).
  """
  # Convert from parameters
  blob = arg1_blob

  # Declare local instance variables.
  geom = None
  hdr_len = 0
  raw_bytes = b""
  wkb_bytes = b""

  if not blob:
    return None, b""

  raw_bytes = bytes(blob)
  if len(raw_bytes) < 9:
    return None, b""

  if raw_bytes[:2] == b"GP":
    if (int(raw_bytes[3]) >> 4) & 0x01:
      return None, b""
    hdr_len = _parse_gpkg_envelope_len(raw_bytes[3])
    wkb_bytes = raw_bytes[hdr_len:]
  else:
    wkb_bytes = raw_bytes

  if not wkb_bytes:
    return None, b""

  try:
    geom = from_wkb(wkb_bytes)
  except Exception:
    geom = None

  # Return statement
  return geom, wkb_bytes


def read_ctamap_county_year (arg1_gpkg_path, arg2_wkb_cache=None, arg3_precision=5):
  """Read all county-level features from a CTAmap T<year>_county.gpkg SQLite GeoPackage.

  @param arg1_gpkg_path Local path to T<year>_county.gpkg.
  @param arg2_wkb_cache Optional shared dict caching cleaned geometries by WKB hash across years.
  @param arg3_precision Coordinate decimal rounding precision.
  @return List of (properties_dict, shapely_geometry) tuples.
  """
  # Convert from parameters
  gpkg_path = os.path.abspath(arg1_gpkg_path)
  precision = int(arg3_precision)
  wkb_cache = arg2_wkb_cache if isinstance(arg2_wkb_cache, dict) else {}

  # Declare local instance variables.
  attr_cols = []
  blob = None
  cols_info = []
  conn = None
  cur = None
  features = []
  geom = None
  geom_col = "geom"
  idx = 0
  props = {}
  row = ()
  sql = ""
  tbl = ""
  wkb_bytes = b""
  wkb_key = b""

  if not os.path.isfile(gpkg_path):
    return features

  conn = sqlite3.connect(f"file:{gpkg_path}?mode=ro", uri=True)
  try:
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features' LIMIT 1")
    row = cur.fetchone()
    if row and row[0]:
      tbl = str(row[0])
    else:
      cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'T%_county' LIMIT 1")
      row = cur.fetchone()
      tbl = str(row[0]) if row else ""
    if not tbl:
      return features

    cur.execute("SELECT column_name FROM gpkg_geometry_columns WHERE table_name=? LIMIT 1", (tbl,))
    row = cur.fetchone()
    if row and row[0]:
      geom_col = str(row[0])

    cur.execute(f'PRAGMA table_info("{tbl}")')
    cols_info = [str(r[1]) for r in cur.fetchall()]
    attr_cols = [c for c in cols_info if c != geom_col]
    sql = f'SELECT "{geom_col}", ' + ", ".join(f'"{c}"' for c in attr_cols) + f' FROM "{tbl}"'
    cur.execute(sql)

    for row in cur:
      blob = row[0]
      if not blob:
        continue
      wkb_key = hashlib.blake2b(bytes(blob), digest_size=16).digest()
      if wkb_key in wkb_cache:
        geom = wkb_cache[wkb_key]
      else:
        geom, wkb_bytes = parse_gpkg_wkb(blob)
        if geom is not None and not geom.is_valid:
          geom = gis_helpers.clean_polygonal_geometry(geom)
        if geom is not None and precision > 0:
          geom = set_precision(geom, 10.0 ** (-precision))
          if not geom.is_valid:
            geom = gis_helpers.clean_polygonal_geometry(geom)
        wkb_cache[wkb_key] = geom
      if geom is None or geom.is_empty:
        continue

      props = {}
      for idx, col_name in enumerate(attr_cols):
        props[col_name] = _clean_text(row[idx + 1])
      props["_wkb_hex"] = hashlib.blake2b(geom.wkb, digest_size=16).hexdigest()
      features.append((props, geom))
  finally:
    conn.close()

  # Return statement
  return features
