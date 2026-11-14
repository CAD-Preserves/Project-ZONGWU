"""Step 3 annual Xizang watershed subdivision and dynamic Tusi parent-province hierarchy helpers."""

import json
import os
import sys
import zipfile
from shapely import STRtree
from shapely.geometry import Point, Polygon, shape
from shapely.ops import unary_union

if os.path.abspath(os.path.join(os.path.dirname(__file__), "..")) not in sys.path:
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from helpers import gis_helpers, path_helpers


def _load_gadm_subset_union (arg1_builder, arg2_file_key, arg3_name1_filter):
  """Load and union GADM polygons whose NAME_1 contains arg3_name1_filter.

  @param arg1_builder AnnualAdminBuilder instance with cfg and base_dir.
  @param arg2_file_key Key under cfg['gadm']['files'] (e.g. 'gadm_ind_3').
  @param arg3_name1_filter Case-insensitive substring matched against NAME_1.
  @return Cleaned Shapely union geometry, or None if unavailable.
  """
  # Convert from parameters
  builder = arg1_builder
  file_key = str(arg2_file_key)
  name_filter = str(arg3_name1_filter).lower()

  # Declare local instance variables.
  data = {}
  feats = []
  g = None
  gadm_path = path_helpers.resolve_provider_file(builder.cfg, "gadm", file_key, builder.base_dir)
  geoms = []
  jname = None

  if not os.path.exists(gadm_path):
    return None

  if gadm_path.lower().endswith(".zip"):
    with zipfile.ZipFile(gadm_path, "r") as zf:
      jname = next((n for n in zf.namelist() if n.lower().endswith((".json", ".geojson"))), None)
      if jname:
        data = json.loads(zf.read(jname).decode("utf-8"))
  else:
    with open(gadm_path, "r", encoding="utf-8") as fh:
      data = json.load(fh)

  feats = data.get("features", [])
  for feat in feats:
    n1 = str(feat.get("properties", {}).get("NAME_1") or "").lower()
    if name_filter not in n1:
      continue
    g = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
    if g is not None and not g.is_empty:
      geoms.append(g)

  # Return statement
  return gis_helpers.clean_polygonal_geometry(unary_union(geoms)) if geoms else None


def append_xizang_watershed_atoms (arg1_builder, arg2_feat, arg3_geom):
  """Subdivide historical Xizang exclusively with HydroBASINS level-8 watersheds (never PRC modern adm3).

  @param arg1_builder AnnualAdminBuilder instance receiving atoms.
  @param arg2_feat Source 1911 CHGIS Xizang feature dictionary.
  @param arg3_geom Cleaned Shapely geometry of 1911 CHGIS Xizang.
  @return Count of watershed atoms appended.
  """
  # Convert from parameters
  builder = arg1_builder
  feat = arg2_feat
  geom = arg3_geom

  # Declare local instance variables.
  appended = 0
  covered = []
  hy_cfg = builder.cfg["hydrosheds"]["files"]["hybas_as_lev08"]
  hy_path = path_helpers.resolve_source_file("hydrosheds", hy_cfg["filename"], builder.base_dir)
  props = feat["properties"]
  raw_basins = gis_helpers.read_zip_shapefile_wgs84(hy_path, "utf-8", builder.precision)
  uid = props["unit_id"]

  for rec, b_geom in raw_basins:
    if b_geom is None or b_geom.is_empty or not geom.intersects(b_geom):
      continue
    inter = gis_helpers.clean_polygonal_geometry(geom.intersection(b_geom))
    if inter is None or inter.area <= 0.002:
      continue
    ig, idict = builder._cache_geom(inter)
    if ig is None:
      continue
    hid = str(rec.get("HYBAS_ID") or len(builder.china_atoms))
    rp = ig.representative_point()
    l2_name = "Chamdo" if (rp.x >= 96.2 and rp.y >= 29.5) else "U-Tsang & Changtang"
    builder._append_china_atom(
      f"{uid}_hybas_{hid}_{len(builder.china_atoms)}",
      idict,
      ig,
      "Xizang",
      l2_name,
      f"西藏流域 {hid}",
      f"Xizang Watershed {hid}",
      uid,
      "",
      "",
      "",
    )
    covered.append(inter)
    appended += 1

  if covered:
    rem = gis_helpers.clean_polygonal_geometry(geom.difference(unary_union(covered)))
    if rem is not None and rem.area > 0.01:
      rg, rdict = builder._cache_geom(rem)
      if rg is not None:
        rp = rg.representative_point()
        l2_name = "Chamdo" if (rp.x >= 96.2 and rp.y >= 29.5) else "U-Tsang & Changtang"
        builder._append_china_atom(f"{uid}_hybas_rem", rdict, rg, "Xizang", l2_name, props["name_ch"], props["name_en"], uid)
        appended += 1
  else:
    rg, rdict = builder._cache_geom(geom)
    if rg is not None:
      builder._append_china_atom(uid, rdict, rg, "Xizang", "U-Tsang & Changtang", props["name_ch"], props["name_en"], uid)
      appended += 1

  # Return statement
  return appended


def apply_reference_frontline_masks (arg1_builder):
  """Split Xizang/Sichuan atoms along 1916 Beiyang vs 1919-1950 Dalai Lama frontline masks and backfill Powo.

  @param arg1_builder AnnualAdminBuilder instance whose china_atoms are refined in-place.
  @return Count of frontline split or backfilled atoms created.
  """
  # Convert from parameters
  builder = arg1_builder

  # Declare local instance variables.
  created = 0
  mask_map = {}
  new_atoms = []
  ref_path = path_helpers.resolve_path("input.gis.tibet_reference_polygons", builder.base_dir)

  if not os.path.exists(ref_path):
    return 0

  with open(ref_path, "r", encoding="utf-8") as fh:
    for feat in json.load(fh).get("features", []):
      tid = feat.get("properties", {}).get("tusi_id")
      if tid in ("__mask_dalai_lama_1916__", "__mask_beiyang_1916__", "__mask_dalai_lama_post1918__", "powo_kingdom", "gyirong_nyalam_joint_monastic"):
        mask_map[tid] = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))

  gyirong_g = mask_map.get("gyirong_nyalam_joint_monastic")
  m_dl16 = mask_map.get("__mask_dalai_lama_1916__")
  m_by16 = mask_map.get("__mask_beiyang_1916__")
  m_dl18 = mask_map.get("__mask_dalai_lama_post1918__")
  powo_g = mask_map.get("powo_kingdom")
  if m_dl16 is None or m_by16 is None or m_dl18 is None:
    return 0

  zone_dl16 = gis_helpers.clean_polygonal_geometry(m_dl16.union(powo_g)) if powo_g is not None else m_dl16
  zone_post18 = gis_helpers.clean_polygonal_geometry(m_dl18.difference(zone_dl16))
  zone_by_stay = gis_helpers.clean_polygonal_geometry(m_by16.difference(m_dl18).difference(zone_dl16))
  zone_parts = [(z, tag) for z, tag in ((zone_dl16, "dalai_1916"), (zone_post18, "dalai_post1918"), (zone_by_stay, "beiyang_only")) if z is not None and not z.is_empty]
  front_union = gis_helpers.clean_polygonal_geometry(unary_union([z for z, _ in zone_parts]))
  xz_sc_geoms = []

  def _clone_atom (arg1_base, arg2_suffix, arg3_geom, arg4_dict, arg5_tag):
    rec = dict(arg1_base)
    rec["atom_id"] = f"{arg1_base['atom_id']}_{arg2_suffix}"
    rec["dict"] = arg4_dict
    rec["geom"] = arg3_geom
    if arg5_tag:
      rec["ref_frontline"] = arg5_tag
    return rec

  for atom in builder.china_atoms:
    if atom["l1_1911"] not in ("Xizang", "Sichuan") or not atom["geom"].intersects(front_union):
      new_atoms.append(atom)
      continue
    g = atom["geom"]
    split_hit = False
    for z_geom, tag in zone_parts:
      if not g.intersects(z_geom):
        continue
      inter = gis_helpers.clean_polygonal_geometry(g.intersection(z_geom))
      if inter is not None and inter.area > 0.0003:
        cg, cd = builder._cache_geom(inter)
        if cg is not None:
          new_atoms.append(_clone_atom(atom, f"fr_{tag}", cg, cd, tag))
          xz_sc_geoms.append(cg)
          split_hit = True
          created += 1
    rem = gis_helpers.clean_polygonal_geometry(g.difference(front_union))
    if rem is not None and rem.area > 0.0003:
      rg, rd = builder._cache_geom(rem)
      if rg is not None:
        new_atoms.append(_clone_atom(atom, "fr_rem" if split_hit else "keep", rg, rd, ""))
        xz_sc_geoms.append(rg)

  # Ensure Powo Kingdom, post-1918 Chamdo salient, and western Ngari PRC margin have seamless China background
  cov_union = gis_helpers.clean_polygonal_geometry(unary_union(xz_sc_geoms)) if xz_sc_geoms else None
  gadm_arunachal = _load_gadm_subset_union(builder, "gadm_ind_3", "arunachal")
  gadm_prc_xizang = _load_gadm_subset_union(builder, "gadm_chn_3", "xizang")
  loss_parts = []
  mcmahon_ids = set(builder.tusi_modelling_cfg.get("mcmahon_southern_ids", []))
  tusi_geoms = getattr(builder, "tusi_geoms", {})
  if gadm_arunachal is not None:
    loss_parts.append(gadm_arunachal)
  for bh_id in ("merak_brokpa_estate", "sakteng_brokpa_estate"):
    if bh_id in tusi_geoms:
      loss_parts.append(tusi_geoms[bh_id]["geom"])
  for m_id in mcmahon_ids:
    if m_id in ("merak_brokpa_estate", "sakteng_brokpa_estate") or m_id not in tusi_geoms:
      continue
    mg = tusi_geoms[m_id]["geom"]
    if gadm_prc_xizang is not None:
      mg = gis_helpers.clean_polygonal_geometry(mg.difference(gadm_prc_xizang))
    if mg is not None and not mg.is_empty:
      loss_parts.append(mg)
  builder.south_tibet_post1951_loss_union = gis_helpers.clean_polygonal_geometry(unary_union(loss_parts)) if loss_parts else None
  builder.post1951_south_cache = {}

  backfill_specs = [(powo_g, "dalai_1916", "U-Tsang & Changtang"), (gyirong_g, "dalai_1916", "U-Tsang & Changtang"), (zone_post18, "dalai_post1918", "Chamdo")]
  if m_dl16 is not None and gadm_prc_xizang is not None:
    m_dl16_prc = gis_helpers.clean_polygonal_geometry(m_dl16.intersection(gadm_prc_xizang))
    if m_dl16_prc is not None and not m_dl16_prc.is_empty:
      backfill_specs.append((m_dl16_prc, "dalai_1916", "U-Tsang & Changtang"))

  for z_geom, tag, l2_fallback in backfill_specs:
    if z_geom is None or z_geom.is_empty:
      continue
    fill_g = z_geom if cov_union is None else gis_helpers.clean_polygonal_geometry(z_geom.difference(cov_union))
    if fill_g is not None and fill_g.area > 0.0003:
      fg, fd = builder._cache_geom(fill_g)
      if fg is not None:
        new_atoms.append({
          "atom_id": f"ref_backfill_{tag}_{len(new_atoms)}",
          "citas_ch": "",
          "citas_en": "",
          "dict": fd,
          "gb": "542100" if l2_fallback == "Chamdo" else "",
          "geom": fg,
          "l1_1911": "Xizang",
          "l2_1911": l2_fallback,
          "name_ch": l2_fallback,
          "name_en": l2_fallback,
          "orig_uid": f"ref_backfill_{tag}",
          "ref_frontline": tag,
        })
        cov_union = gis_helpers.clean_polygonal_geometry(cov_union.union(fg)) if cov_union is not None else fg
        created += 1

  builder.china_atoms = new_atoms
  print(f"[STEP 3] Frontline mask split: {created} sub-atoms | total china_atoms={len(new_atoms)}")

  # Return statement
  return created


def clip_post_annexation_south_tibet (arg1_builder, arg2_atom, arg3_year, arg4_geom, arg5_dict):
  """Remove Arunachal Pradesh (NEFA) and eastern Bhutan Merak-Sakteng from Xizang/Chamdo post-1951.

  @param arg1_builder AnnualAdminBuilder instance.
  @param arg2_atom Atomic China unit dictionary.
  @param arg3_year Snapshot year evaluated on 1 January GMT+0.
  @param arg4_geom Current Shapely geometry after active Tusi subtraction.
  @param arg5_dict GeoJSON geometry dict corresponding to arg4_geom.
  @return Tuple (clipped_geom, clipped_dict), or (None, None) when completely removed.
  """
  # Convert from parameters
  atom = arg2_atom
  builder = arg1_builder
  geom = arg4_geom
  geom_dict = arg5_dict
  year = int(arg3_year)

  # Declare local instance variables.
  cache_key = None
  loss_union = getattr(builder, "south_tibet_post1951_loss_union", None)
  rem = None

  if year < 1952 or atom.get("l1_1911") not in ("Xizang", "Sichuan"):
    return geom, geom_dict
  if loss_union is None or geom is None or geom.is_empty or not geom.intersects(loss_union):
    return geom, geom_dict

  if geom is atom.get("geom"):
    cache_key = atom["atom_id"]
    if cache_key in builder.post1951_south_cache:
      # Return statement
      return builder.post1951_south_cache[cache_key]

  rem = gis_helpers.clean_polygonal_geometry(geom.difference(loss_union))
  if rem is None or rem.area <= 0.0005:
    if cache_key is not None:
      builder.post1951_south_cache[cache_key] = (None, None)
    # Return statement
    return None, None

  cg, cd = builder._cache_geom(rem)
  if cache_key is not None:
    builder.post1951_south_cache[cache_key] = (cg, cd)

  # Return statement
  return cg, cd


def classify_frontline_atom (arg1_atom, arg2_year, arg3_country):
  """Classify a frontline-split Xizang/Kham atom using the 1916 Beiyang vs 1918 truce lines.

  @param arg1_atom Atomic China dict with optional extra['ref_frontline'].
  @param arg2_year Target snapshot year.
  @param arg3_country Resolved Chinese state sovereignty string.
  @return Classification tuple matching _classify_china_atom, or None to fall through.
  """
  # Convert from parameters
  atom = arg1_atom
  country = arg3_country
  year = int(arg2_year)

  # Declare local instance variables.
  tag = atom.get("ref_frontline")
  adm2 = atom["l2_1911"]
  adm3 = atom["name_en"]
  gb = atom["gb"]

  if not tag:
    return None

  if tag == "dalai_1916":
    if (gb.startswith("5421") or adm2 == "Chamdo") and year >= 1951:
      return ("Chamdo", "昌都", "Chamdo", adm3, country, "", "special_region")
    return ("Xizang", "西藏", adm2, adm3, country, "", "province")

  if tag == "dalai_post1918":
    if year >= 1951:
      return ("Chamdo", "昌都", "Chamdo", adm3, country, "", "special_region")
    if year >= 1919:
      return ("Xizang", "西藏", "Chamdo", adm3, country, "", "province")
    adm1_cn = "Chuanbian" if year >= 1915 else "Sichuan"
    return (adm1_cn, adm1_cn, adm2, adm3, country, "", "province")

  if tag == "beiyang_only":
    adm1_cn = "Xikang" if year >= 1929 else ("Chuanbian" if year >= 1915 else "Sichuan")
    return (adm1_cn, adm1_cn, adm2, adm3, country, "", "province")

  # Return statement
  return None


def emit_annual_tusis (arg1_builder, arg2_year, arg3_active_tusis, arg4_tg_map, arg5_adm1_features, arg6_adm2_features, arg7_adm3_features):
  """Emit active de facto Feudatories/Tusis across adm_1, adm_2, and adm_3 using dynamic host-atom hierarchy.

  @param arg1_builder AnnualAdminBuilder instance.
  @param arg2_year Target snapshot year.
  @param arg3_active_tusis List of active Tusi metadata dicts for arg2_year.
  @param arg4_tg_map Geometry lookup mapping tusi_id -> {dict, geom, props}.
  @param arg5_adm1_features Output list for ADM-1 GeoJSON features.
  @param arg6_adm2_features Output list for ADM-2 GeoJSON features.
  @param arg7_adm3_features Output list for ADM-3 GeoJSON features.
  """
  # Convert from parameters
  adm1_features = arg5_adm1_features
  adm2_features = arg6_adm2_features
  adm3_features = arg7_adm3_features
  year = int(arg2_year)

  # Declare local instance variables.
  resolved = resolve_annual_tusis(arg1_builder, year, arg3_active_tusis, arg4_tg_map)

  emit_resolved_tusis(year, resolved, adm1_features, adm2_features, adm3_features)


def emit_resolved_tusis (arg1_year, arg2_resolved_tusis, arg3_adm1_features, arg4_adm2_features, arg5_adm3_features):
  """Append pre-resolved Feudatory records across adm_1, adm_2, and adm_3 GeoJSON feature lists.

  @param arg1_year Target snapshot year.
  @param arg2_resolved_tusis List of resolved Feudatory dicts from resolve_annual_tusis.
  @param arg3_adm1_features Output list for ADM-1 GeoJSON features.
  @param arg4_adm2_features Output list for ADM-2 GeoJSON features.
  @param arg5_adm3_features Output list for ADM-3 GeoJSON features.
  """
  # Convert from parameters
  adm1_features = arg3_adm1_features
  adm2_features = arg4_adm2_features
  adm3_features = arg5_adm3_features
  resolved = arg2_resolved_tusis
  year = int(arg1_year)

  for rec in resolved:
    t = rec["t"]
    tid = rec["tid"]
    tg = rec["tg"]
    t_adm1 = rec["adm1"]
    t_country = rec["country"]
    t_occ = rec["occ"]
    ptype = rec["ptype"]
    for lvl, feats_out in ((1, adm1_features), (2, adm2_features), (3, adm3_features)):
      feats_out.append({
        "type": "Feature",
        "properties": {
          "abolition_note": t.get("abolition_note", ""),
          "adm_level": lvl,
          "category": "tusi",
          "country": t_country,
          "de_facto_end_year": int(t.get("de_facto_end_year", t.get("end_year", 1953))),
          "de_facto_start_year": int(t.get("de_facto_start_year", t.get("start_year", 1911))),
          "de_jure_gaituguiliu_year": t.get("de_jure_gaituguiliu_year"),
          "name_ch": t["name_zh"],
          "name_en": t["name_en"],
          "occupied_by": t_occ,
          "parent_adm1": t_adm1 if lvl > 1 else "",
          "parent_adm2": t["name_en"] if lvl == 3 else "",
          "polity_type": ptype or "tusi",
          "rank_title": t.get("rank_title", "Tusi"),
          "start_year": int(t.get("start_year", 1911)),
          "tusi_status": t.get("tusi_status", "de_jure_and_de_facto"),
          "unit_id": f"tusi_{tid}",
          "unit_type": "tusi",
          "year": year,
        },
        "geometry": tg["dict"],
      })


def resolve_annual_tusis (arg1_builder, arg2_year, arg3_active_tusis, arg4_tg_map):
  """Resolve dynamic host hierarchy and wartime occupation status for active Feudatories in arg2_year.

  @param arg1_builder AnnualAdminBuilder instance.
  @param arg2_year Target snapshot year.
  @param arg3_active_tusis List of active Tusi metadata dicts for arg2_year.
  @param arg4_tg_map Geometry lookup mapping tusi_id -> {dict, geom, props}.
  @return List of mutable resolved Feudatory dicts.
  """
  # Convert from parameters
  active_tusis = arg3_active_tusis
  builder = arg1_builder
  tg_map = arg4_tg_map
  year = int(arg2_year)

  # Declare local instance variables.
  default_country = "Qing Empire" if year == 1911 else ("People's Republic of China" if year >= 1950 else ("Republic of China (Beiyang)" if year <= 1928 else "Republic of China"))
  dehong_occ_tokens = builder.reforms.get("dehong_west_salween_1943_1944_tokens", [])
  host_map = getattr(builder, "tusi_host_atoms", {})
  mcmahon_ids = set(builder.tusi_modelling_cfg.get("mcmahon_southern_ids", []))
  resolved = []

  for t in active_tusis:
    tid = t["tusi_id"]
    tg = tg_map[tid]
    host_atom = host_map.get(tid)
    t_adm1 = t.get("parent_province", "")
    t_country = default_country
    t_occ = ""
    if host_atom is not None:
      h_adm1, _, _, _, h_country, h_occ, _ = builder._classify_china_atom(host_atom, year)
      if h_adm1:
        t_adm1 = h_adm1
      if h_country:
        t_country = h_country
      if h_occ:
        t_occ = h_occ
    ptype = str(t.get("polity_type") or "")
    bhutan_ids = {
      "darchen_bhutan_monastic_enclave",
      "gartok_bhutan_enclave",
      "merak_brokpa_estate",
      "sakteng_brokpa_estate",
    }
    is_nefa = (tid in mcmahon_ids) and (tid not in bhutan_ids)
    if tid in bhutan_ids:
      t_adm1 = "Bhutan"
      t_country = "Bhutan"
      t_occ = ""
    elif tid == "minsar_ladakh_enclave":
      t_adm1 = "Jammu and Kashmir"
      t_country = "British India" if year < 1947 else "India"
      t_occ = ""
    elif tid in ("choling_dorje_estate", "jomda_upper_naduo_anfusi", "dege_xuanweisi", "lincong_anfusi"):
      if 1919 <= year <= 1950:
        t_adm1 = "Xizang"
      elif year <= 1918:
        t_adm1 = "Chuanbian" if year >= 1915 else "Sichuan"
      else:
        t_adm1 = "Xikang"
    elif tid == "chamdo_phagpalha_estate" and year <= 1918:
      t_adm1 = "Chuanbian" if year >= 1915 else "Sichuan"
    elif year >= 1952 and is_nefa:
      t_adm1 = "North-East Frontier Agency"
      t_country = "India"
      t_occ = ""
    elif year in (1943, 1944) and any(tok in tid.lower() or tok in str(t.get("name_en", "")).lower() for tok in dehong_occ_tokens):
      t_occ = "Japan"
      t_country = "Yunnan (Japanese Occupied)"
    resolved.append({
      "adm1": t_adm1,
      "country": t_country,
      "occ": t_occ,
      "ptype": ptype,
      "t": t,
      "tg": tg,
      "tid": tid,
    })

  # Return statement
  return resolved


def index_tusi_host_atoms (arg1_tusi_catalog, arg2_china_atoms, arg3_china_perm_union):
  """Map each Tusi seat coordinate to its containing or nearest China atom for dynamic year-aware classification.

  @param arg1_tusi_catalog List of Tusi metadata dictionaries.
  @param arg2_china_atoms List of atomic China polygon records.
  @param arg3_china_perm_union Permanent China union geometry (unused fallback guard).
  @return Dict mapping tusi_id -> host china_atom dict.
  """
  # Convert from parameters
  china_atoms = list(arg2_china_atoms or [])
  china_perm_union = arg3_china_perm_union
  tusi_catalog = list(arg1_tusi_catalog or [])

  # Declare local instance variables.
  geoms = [a["geom"] for a in china_atoms]
  host_map = {}
  tree = STRtree(geoms) if geoms else None

  if tree is None:
    return host_map

  for t in tusi_catalog:
    tid = t["tusi_id"]
    sp = Point(float(t["seat_lon"]), float(t["seat_lat"]))
    hit = None
    for idx in tree.query(sp):
      cand = china_atoms[int(idx)]
      if cand["geom"].contains(sp) or cand["geom"].distance(sp) < 1e-6:
        hit = cand
        break
    if hit is None and (china_perm_union is None or china_perm_union.distance(sp) < 0.25):
      n_idx = int(tree.nearest(sp))
      if geoms[n_idx].distance(sp) < 0.25:
        hit = china_atoms[n_idx]
    if hit is not None:
      host_map[tid] = hit

  # Return statement
  return host_map


def strip_unclaimed_micro_holes (arg1_features, arg2_max_hole_area_deg2=0.002):
  """Remove unclaimed micro-sliver interior rings from dissolved administrative features.

  @param arg1_features Mutable list of GeoJSON Feature dicts (after Tusi emission).
  @param arg2_max_hole_area_deg2 Maximum interior-ring area in deg2 eligible for micro-sliver stripping.
  @return Total number of interior sliver rings stripped.
  """
  # Convert from parameters
  features = arg1_features
  max_area = float(arg2_max_hole_area_deg2)

  # Declare local instance variables.
  candidates = []
  geoms = []
  stripped = 0
  tree = None

  for idx, feat in enumerate(features):
    geom_dict = feat.get("geometry") or {}
    g_type = geom_dict.get("type")
    coords = geom_dict.get("coordinates") or []
    has_holes = (g_type == "Polygon" and len(coords) > 1) or (g_type == "MultiPolygon" and any(len(part) > 1 for part in coords))
    g = shape(geom_dict) if geom_dict else None
    geoms.append(g)
    if has_holes:
      candidates.append(idx)

  if not candidates:
    # Return statement
    return 0

  valid_pairs = [(i, g) for i, g in enumerate(geoms) if g is not None and not g.is_empty]
  if not valid_pairs:
    # Return statement
    return 0
  valid_idxs = [p[0] for p in valid_pairs]
  tree = STRtree([p[1] for p in valid_pairs])

  def filter_poly_rings (arg1_rings, arg2_owner_idx):
    nonlocal stripped
    if len(arg1_rings) <= 1:
      return arg1_rings
    kept = [arg1_rings[0]]
    for ring in arg1_rings[1:]:
      hp = Polygon(ring)
      if not hp.is_valid:
        hp = gis_helpers.clean_polygonal_geometry(hp)
      if hp is None or hp.is_empty or hp.area > max_area:
        kept.append(ring)
        continue
      rp = hp.representative_point()
      claimed = False
      for hit in tree.query(hp):
        other_idx = valid_idxs[int(hit)]
        if other_idx == arg2_owner_idx:
          continue
        og = geoms[other_idx]
        if og.contains(rp) or og.intersection(hp).area > 0.5*hp.area:
          claimed = True
          break
      if claimed:
        kept.append(ring)
      else:
        stripped += 1
    return kept

  for idx in candidates:
    geom_dict = features[idx]["geometry"]
    if geom_dict["type"] == "Polygon":
      geom_dict["coordinates"] = filter_poly_rings(geom_dict["coordinates"], idx)
    elif geom_dict["type"] == "MultiPolygon":
      geom_dict["coordinates"] = [filter_poly_rings(part, idx) for part in geom_dict["coordinates"]]

  # Return statement
  return stripped
