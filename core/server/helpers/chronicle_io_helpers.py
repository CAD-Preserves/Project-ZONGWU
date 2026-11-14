"""Stateless I/O, SHA-256 verification, source registry, and GIS timeline helpers for Series A chronicles."""

from functools import lru_cache
import hashlib
import json
import os
import re
import sys

if os.path.abspath(os.path.join(os.path.dirname(__file__), "..")) not in sys.path:
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from helpers import gis_helpers, path_helpers


def _build_twn_map (arg1_edge_cases):
  """Build Traditional and Simplified Chinese Taiwan county/city name to slug map.

  @param arg1_edge_cases Parsed common/defines/local_history_edge_cases.json5 dict.
  @return Dict mapping Taiwan unit names to canonical ASCII slugs.
  """
  # Convert from parameters
  edge_cases = arg1_edge_cases or {}

  # Declare local instance variables.
  out = {}
  t2_meta = edge_cases.get("taiwan", {}).get("gadm_twn2_metadata", {})

  for gadm_key, meta in t2_meta.items():
    slug = gis_helpers.slugify_snake(meta["name_en"].replace(" County", "").replace(" City", "").replace(" (Matsu)", ""))
    n_zh = str(meta.get("name_zh") or "")
    out[n_zh] = slug
    out[n_zh.replace("臺", "台")] = slug
    out[n_zh.rstrip("縣市")] = slug
    out[n_zh.replace("臺", "台").rstrip("縣市")] = slug
    out[gadm_key] = slug
    out[meta["name_en"]] = slug

  # Return statement
  return out


def _canonical_adm3_unit_slug (arg1_props, arg2_edge_cases, arg3_twn_map):
  """Resolve canonical (division_slug, unit_slug) from an adm_3 GeoJSON feature's properties.

  @param arg1_props Feature properties dictionary from adm_3_<year>.geojson.
  @param arg2_edge_cases Parsed local_history_edge_cases.json5 dict.
  @param arg3_twn_map Mapping from _build_twn_map().
  @return Tuple (division_slug, unit_slug).
  """
  # Convert from parameters
  edge_cases = arg2_edge_cases or {}
  props = arg1_props or {}
  twn_map = arg3_twn_map or {}

  # Declare local instance variables.
  c_slug = ""
  cat = str(props.get("category") or "").strip()
  disambig = edge_cases.get("chgis_homophone_disambiguation", {})
  m_sys = None
  name_ch = str(props.get("name_ch") or "").strip()
  name_en = str(props.get("name_en") or "").strip()
  p1 = str(props.get("parent_adm1") or "").strip()
  prov_slug = gis_helpers.slugify_snake(p1)
  sys_id = ""
  uid = str(props.get("unit_id") or "").strip()

  if cat == "tusi" and uid.startswith("tusi_"):
    c_slug = gis_helpers.slugify_snake(uid[5:])
    return (c_slug, c_slug)

  if "_twn_" in uid:
    c_slug = twn_map.get(name_en) or twn_map.get(name_ch) or gis_helpers.slugify_snake(name_en)
    return (prov_slug, c_slug)

  m_sys = re.search(r"_(\d{5,7})_\d{4}$", uid)
  if m_sys:
    sys_id = m_sys.group(1)
    if sys_id in disambig:
      return (prov_slug, disambig[sys_id])

  c_slug = gis_helpers.slugify_snake(name_en)

  # Return statement
  return (prov_slug, c_slug)


@lru_cache(maxsize=2)
def _load_gis_annual_index (arg1_base_dir):
  """Load and index annual 1911-1953 adm_1/adm_3 layers and Tusi vector metadata once per workspace.

  @param arg1_base_dir Resolved workspace root path.
  @return Tuple (adm1_by_slug, adm3_by_slug, tusi_by_slug).
  """
  # Convert from parameters
  base_dir = os.path.abspath(arg1_base_dir)

  # Declare local instance variables.
  adm1_by_slug = {}
  adm3_by_slug = {}
  adm_dir = path_helpers.resolve_path("output.gis.adm_annual_dir", base_dir)
  edge_cases = gis_helpers.load_json5(path_helpers.resolve_path("common.local_history_edge_cases", base_dir)) or {}
  tusi_by_slug = {}
  tusi_path = path_helpers.resolve_path("output.gis.tusi", base_dir)
  twn_map = _build_twn_map(edge_cases)

  for yr in range(1911, 1954):
    p1 = os.path.join(adm_dir, f"adm_1_{yr}.geojson")
    if os.path.exists(p1):
      with open(p1, "r", encoding="utf-8") as fh:
        feats1 = json.load(fh).get("features", [])
      for ft in feats1:
        props = ft.get("properties", {})
        cat = str(props.get("category") or "province").strip()
        name_en = str(props.get("name_en") or "").strip()
        uid = str(props.get("unit_id") or "").strip()
        div_slug = gis_helpers.slugify_snake(uid[5:]) if (cat == "tusi" and uid.startswith("tusi_")) else gis_helpers.slugify_snake(name_en)
        if not div_slug:
          continue
        adm1_by_slug.setdefault(div_slug, []).append({
          "category": cat,
          "country": str(props.get("country") or ""),
          "name_ch": str(props.get("name_ch") or ""),
          "name_en": name_en,
          "occupied_by": str(props.get("occupied_by") or ""),
          "unit_id": uid,
          "year": yr,
        })

    p3 = os.path.join(adm_dir, f"adm_3_{yr}.geojson")
    if os.path.exists(p3):
      with open(p3, "r", encoding="utf-8") as fh:
        feats3 = json.load(fh).get("features", [])
      for ft in feats3:
        props = ft.get("properties", {})
        div_slug, u_slug = _canonical_adm3_unit_slug(props, edge_cases, twn_map)
        if not div_slug or not u_slug:
          continue
        u_map = adm3_by_slug.setdefault(div_slug, {})
        u_rec = u_map.setdefault(u_slug, {
          "adm2_names": set(),
          "name_ch": str(props.get("name_ch") or ""),
          "name_en": str(props.get("name_en") or ""),
          "timeline": [],
          "unit_ids": set(),
          "unit_slug": u_slug,
        })
        if props.get("name_ch") and not u_rec["name_ch"]:
          u_rec["name_ch"] = str(props["name_ch"])
        if props.get("parent_adm2"):
          u_rec["adm2_names"].add(str(props["parent_adm2"]))
        if props.get("unit_id"):
          u_rec["unit_ids"].add(str(props["unit_id"]))
        u_rec["timeline"].append({
          "country": str(props.get("country") or ""),
          "occupied_by": str(props.get("occupied_by") or ""),
          "parent_adm2": str(props.get("parent_adm2") or ""),
          "year": yr,
        })

  if tusi_path and os.path.exists(tusi_path):
    with open(tusi_path, "r", encoding="utf-8") as fh:
      t_feats = json.load(fh).get("features", [])
    for ft in t_feats:
      props = ft.get("properties", {})
      tid = gis_helpers.slugify_snake(props.get("tusi_id") or "")
      if tid:
        tusi_by_slug[tid] = dict(props)

  # Return statement
  return (adm1_by_slug, adm3_by_slug, tusi_by_slug)


def compute_file_sha256 (arg1_filepath):
  """Compute streamed lowercase SHA-256 hex digest of a local file in 1 MB chunks.

  @param arg1_filepath Path to target file.
  @return 64-character hex digest string, or empty string if missing.
  """
  # Convert from parameters
  filepath = str(arg1_filepath or "")

  if not filepath or not os.path.isfile(filepath):
    return ""

  # Declare local instance variables.
  chunk = b""
  digest = hashlib.sha256()

  with open(filepath, "rb") as fh:
    for _ in range(100000):
      chunk = fh.read(1048576)
      if not chunk:
        break
      digest.update(chunk)

  # Return statement
  return digest.hexdigest()


def extract_division_gis_history (arg1_slug, arg2_base_dir=None):
  """Return annual sovereignty, occupation, county roster, and Tusi boundary history for a division.

  @param arg1_slug Division or Tusi snake_case key in province_defines.json5.
  @param arg2_base_dir Optional workspace root directory.
  @return Dict containing adm1_timeline, sovereignty_transitions, units, and tusi_record.
  """
  # Convert from parameters
  base_dir = os.path.abspath(arg2_base_dir) if arg2_base_dir else path_helpers.get_project_root()
  slug = str(arg1_slug or "").strip()

  # Declare local instance variables.
  adm1_by_slug, adm3_by_slug, tusi_by_slug = _load_gis_annual_index(base_dir)
  adm1_rows = sorted(adm1_by_slug.get(slug, []), key=lambda x: x["year"])
  prev_occ = None
  prev_state = None
  raw_units = adm3_by_slug.get(slug, {})
  transitions = []
  tusi_rec = tusi_by_slug.get(slug)
  units_out = {}

  for row in adm1_rows:
    cur_state = row["country"]
    cur_occ = row["occupied_by"]
    if prev_state is not None and (cur_state != prev_state or cur_occ != prev_occ):
      transitions.append({
        "from_country": prev_state,
        "from_occupied_by": prev_occ,
        "to_country": cur_state,
        "to_occupied_by": cur_occ,
        "year": row["year"],
      })
    prev_state = cur_state
    prev_occ = cur_occ

  for u_slug, u_rec in sorted(raw_units.items()):
    tl = sorted(u_rec["timeline"], key=lambda x: x["year"])
    u_trans = []
    u_prev = None
    for item in tl:
      sig = (item["country"], item["occupied_by"], item["parent_adm2"])
      if u_prev is not None and sig != u_prev:
        u_trans.append({
          "from_country": u_prev[0],
          "from_occupied_by": u_prev[1],
          "from_parent_adm2": u_prev[2],
          "to_country": sig[0],
          "to_occupied_by": sig[1],
          "to_parent_adm2": sig[2],
          "year": item["year"],
        })
      u_prev = sig
    units_out[u_slug] = {
      "adm2_names": sorted(u_rec["adm2_names"]),
      "name_ch": u_rec["name_ch"],
      "name_en": u_rec["name_en"],
      "timeline": tl,
      "transitions": u_trans,
      "unit_ids": sorted(u_rec["unit_ids"]),
      "unit_slug": u_slug,
      "years": sorted({item["year"] for item in tl}),
    }

  # Return statement
  return {
    "adm1_timeline": adm1_rows,
    "division_slug": slug,
    "sovereignty_transitions": transitions,
    "tusi_record": dict(tusi_rec) if tusi_rec else None,
    "units": units_out,
  }


def load_source_registry (arg1_base_dir=None):
  """Load common/sources/source_registry.json5 safely, initialising schema defaults if empty.

  @param arg1_base_dir Optional workspace root directory.
  @return Parsed registry dictionary with schema_version=1 and sources dict.
  """
  # Convert from parameters
  base_dir = os.path.abspath(arg1_base_dir) if arg1_base_dir else path_helpers.get_project_root()

  # Declare local instance variables.
  reg = None
  reg_path = path_helpers.resolve_path("common.source_registry", base_dir)

  if os.path.exists(reg_path):
    reg = gis_helpers.load_json5(reg_path)
  if not isinstance(reg, dict):
    reg = {"schema_version": 1, "sources": {}}
  if "schema_version" not in reg:
    reg["schema_version"] = 1
  if not isinstance(reg.get("sources"), dict):
    reg["sources"] = {}

  # Return statement
  return reg


def resolve_division_abs_path (arg1_chronicle_path, arg2_base_dir=None):
  """Resolve a relative ./output/chronicles/... path from province_defines.json5 inside workspace root.

  @param arg1_chronicle_path Relative chronicle_path string.
  @param arg2_base_dir Optional workspace root directory.
  @return Normalised absolute path string guaranteed to stay inside output/chronicles/.
  """
  # Convert from parameters
  base_dir = os.path.abspath(arg2_base_dir) if arg2_base_dir else path_helpers.get_project_root()
  rel = str(arg1_chronicle_path or "").strip()

  # Declare local instance variables.
  abs_dir = os.path.normpath(os.path.join(base_dir, rel))
  chron_root = path_helpers.resolve_path("output.chronicles_dir", base_dir)

  if not abs_dir.startswith(chron_root):
    print(f"[ERROR] Invalid chronicle_path outside output/chronicles/: {rel}", file=sys.stderr)
    return ""

  # Return statement
  return abs_dir


def save_source_registry (arg1_registry, arg2_base_dir=None):
  """Atomically save common/sources/source_registry.json5 with 2-space indentation.

  @param arg1_registry Registry dict containing schema_version and sources.
  @param arg2_base_dir Optional workspace root directory.
  @return Absolute path written.
  """
  # Convert from parameters
  base_dir = os.path.abspath(arg2_base_dir) if arg2_base_dir else path_helpers.get_project_root()
  reg = arg1_registry if isinstance(arg1_registry, dict) else {"schema_version": 1, "sources": {}}

  # Declare local instance variables.
  reg_path = path_helpers.resolve_path("common.source_registry", base_dir)

  write_json5_atomic(
    reg_path,
    "Global deduplication registry for downloaded and OCR-processed primary sources.",
    reg,
  )

  # Return statement
  return reg_path


def upsert_registry_source (arg1_registry, arg2_source_id, arg3_entry_patch):
  """Insert or merge a primary-source entry into the source registry monotonically.

  @param arg1_registry Loaded source_registry dict modified in place.
  @param arg2_source_id Canonical source_id key.
  @param arg3_entry_patch Dict of fields to merge (kind, url, sha256, output_orig_pdf, covered_divisions, ocr_status).
  @return Updated entry dict inside registry['sources'][source_id].
  """
  # Convert from parameters
  patch = dict(arg3_entry_patch or {})
  reg = arg1_registry
  sid = str(arg2_source_id or "").strip()

  if not sid or not isinstance(reg, dict):
    print(f"[ERROR] Invalid upsert_registry_source arguments for {sid!r}", file=sys.stderr)
    return {}

  # Declare local instance variables.
  cur_rank = 0
  existing = reg.setdefault("sources", {}).get(sid, {})
  force_status = bool(patch.pop("force_status", False))
  merged_divs = set(existing.get("covered_divisions", []))
  new_divs = patch.get("covered_divisions", [])
  new_rank = 0
  rank_map = {"indexed": 1, "downloaded": 2, "done": 3}

  for d in new_divs:
    if d:
      merged_divs.add(str(d))

  out_entry = dict(existing)
  for k, v in patch.items():
    if k == "covered_divisions":
      continue
    if k == "ocr_status":
      cur_rank = rank_map.get(str(existing.get("ocr_status") or ""), 0)
      new_rank = rank_map.get(str(v or ""), 0)
      if force_status or new_rank >= cur_rank:
        out_entry["ocr_status"] = str(v)
    elif v is not None and v != "":
      out_entry[k] = v

  out_entry["covered_divisions"] = sorted(merged_divs)
  if "ocr_status" not in out_entry:
    out_entry["ocr_status"] = "indexed"

  reg["sources"][sid] = out_entry

  # Return statement
  return out_entry


def write_json5_atomic (arg1_filepath, arg2_header, arg3_payload):
  """Write formatted JSON5 atomically with a header comment via temporary file swap.

  @param arg1_filepath Destination filepath.
  @param arg2_header Comment header line without leading slashes.
  @param arg3_payload JSON-serialisable dict or list payload.
  @return Destination filepath written.
  """
  # Convert from parameters
  filepath = os.path.normpath(str(arg1_filepath))
  header = str(arg2_header or "").strip()
  payload = arg3_payload

  # Declare local instance variables.
  body = ""
  parent = os.path.dirname(filepath)
  tmp_path = f"{filepath}.tmp.{os.getpid()}"

  os.makedirs(parent, exist_ok=True)
  body = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
  with open(tmp_path, "w", encoding="utf-8") as fh:
    if header:
      fh.write(f"// {header}\n")
    fh.write(body)
    fh.write("\n")
  os.replace(tmp_path, filepath)

  # Return statement
  return filepath
