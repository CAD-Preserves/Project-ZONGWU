"""Step 3 annual 1 January (00:00 GMT+0) administrative GeoJSON builder for 1911-1953."""

import io
import json
import os
import sys
import time
import zipfile
import shapefile
from shapely import STRtree
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
  sys.path.insert(0, SERVER_DIR)
from helpers import annual_occupation_helpers, annual_tusi_helpers, gis_helpers, path_helpers


class AnnualAdminBuilder:
  """Constructs watertight 1911-1953 adm_1/adm_2/adm_3 GeoJSON snapshots with geometry caching."""

  def __init__ (self, arg1_base_dir):
    """Load configuration, atomic geometries, GADM layers, and Tusi catalog.

    @param arg1_base_dir Project root directory.
    """
    # Convert from parameters
    base_dir = os.path.abspath(arg1_base_dir)

    # Declare local instance variables.
    self.base_dir = base_dir
    self.adm_annual_dir = path_helpers.resolve_path("output.gis.adm_annual_dir", base_dir)
    self.cfg = gis_helpers.load_json5(path_helpers.resolve_path("common.data_sources", base_dir))
    self.china_atoms = []
    self.diff_cache = {}
    self.layers_dir = path_helpers.resolve_path("output.gis.layers_dir", base_dir)
    self.mng_soums = []
    self.mng_union = None
    self.precision = int(self.cfg.get("coordinate_precision", 5))
    self.reforms = gis_helpers.load_json5(path_helpers.resolve_path("common.admin_reforms", base_dir))
    self.tusi_modelling_cfg = gis_helpers.load_json5(path_helpers.resolve_path("common.tusi_modelling_config", base_dir))
    self.tusi_by_id = {}
    self.tusi_catalog = []
    self.tusi_chgis_unit_ids = set()
    self.tusi_geoms = {}
    self.tusi_geoms_post1931 = {}
    self.tusi_host_atoms = {}
    self.tuva_kozhuuns = []
    self.twn_counties = []
    self.union_cache = {}

    self._load_all_sources()

  def _cache_geom (self, arg1_geom):
    """Round and clean a geometry and return (shapely_geom, geojson_mapping_dict)."""
    # Convert from parameters
    geom = arg1_geom

    cleaned = gis_helpers.round_geometry(geom, self.precision)
    if cleaned is None or cleaned.is_empty:
      return None, None

    # Return statement
    return cleaned, mapping(cleaned)

  def _load_citas_polygons (self):
    """Load 1990 CITAS county polygons in WGS84 for subdividing 1911 frontier prefectures."""
    citas_path = path_helpers.resolve_provider_file(self.cfg, "chgis_dataverse", "chgis_1990_citas_cnty", self.base_dir)
    raw = gis_helpers.read_zip_shapefile_wgs84(citas_path, "utf-8", self.precision)
    citas_list = []
    for rec, geom in raw:
      gb = str(rec.get("GBCENMQ") or "").strip()
      if len(gb) < 4:
        continue
      citas_list.append({
        "gb": gb,
        "geom": geom,
        "name_ch": str(rec.get("NMHANZI") or "").strip(),
        "name_en": str(rec.get("NMFULL") or "").strip(),
      })

    # Return statement
    return citas_list

  def _load_gadm_zip (self, arg1_filename):
    """Load features from a GADM JSON or JSON.zip archive."""
    # Convert from parameters
    path = path_helpers.resolve_source_file("gadm", arg1_filename, self.base_dir)

    if path.lower().endswith(".zip"):
      with zipfile.ZipFile(path, "r") as zf:
        jname = [n for n in zf.namelist() if n.lower().endswith(".json")][0]
        data = json.loads(zf.read(jname).decode("utf-8"))
    else:
      with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    out = []
    for feat in data.get("features", []):
      geom = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
      if geom is not None and not geom.is_empty:
        g_round, g_dict = self._cache_geom(geom)
        if g_round is not None:
          out.append({"props": feat.get("properties", {}), "geom": g_round, "dict": g_dict})

    # Return statement
    return out

  def _append_china_atom (self, arg1_atom_id, arg2_dict, arg3_geom, arg4_l1, arg5_l2, arg6_name_ch, arg7_name_en, arg8_orig_uid, arg9_gb="", arg10_citas_ch="", arg11_citas_en="", arg12_extra=None):
    """Append a normalised atomic subdivision dict to self.china_atoms."""
    # Convert from parameters
    rec = {
      "atom_id": arg1_atom_id,
      "citas_ch": arg10_citas_ch or arg6_name_ch,
      "citas_en": arg11_citas_en or arg7_name_en,
      "dict": arg2_dict,
      "gb": arg9_gb,
      "geom": arg3_geom,
      "l1_1911": arg4_l1,
      "l2_1911": arg5_l2,
      "name_ch": arg6_name_ch,
      "name_en": arg7_name_en,
      "orig_uid": arg8_orig_uid,
    }
    if arg12_extra:
      rec.update(arg12_extra)
    self.china_atoms.append(rec)

  def _load_all_sources (self):
    """Build atomic China, Taiwan, Mongolia, Tuva, and Feudatory geometry tables."""
    # 1. Load 1911 CHGIS base prior and subdivide huge frontier units via CITAS
    with open(path_helpers.resolve_path("input.gis.chgis_1911_adm3_base", self.base_dir), "r", encoding="utf-8") as fh:
      a3 = json.load(fh)["features"]

    citas_list = self._load_citas_polygons()
    citas_geoms = [c["geom"] for c in citas_list]
    citas_tree = STRtree(citas_geoms)
    prefixes = self.reforms["citas_subdivide_unit_prefixes"]

    # Load GADM Taiwan, Mongolia, and Tuva
    twn_raw = self._load_gadm_zip(self.cfg["gadm"]["files"]["gadm_twn_2"]["filename"])
    for item in twn_raw:
      n1 = str(item["props"].get("NAME_1") or "").strip()
      n2 = str(item["props"].get("NAME_2") or "").strip()
      if n1 == "Fujian" or n2 in ("Kinmen", "Lienkiang"):
        # Kinmen & Lienkiang (Matsu) remain Fujian ROC counties
        n2_ch = str(item["props"].get("NL_NAME_2") or n2)
        gb_code = "350527" if n2 == "Kinmen" else "350128"
        l2_par = "Fuzhou Fu" if n2 == "Lienkiang" else "Quanzhou Fu"
        self._append_china_atom(f"fjn_{gis_helpers.slugify_snake(n2)}", item["dict"], item["geom"], "Fujian", l2_par, n2_ch, f"{n2} Xian", f"fjn_{gis_helpers.slugify_snake(n2)}", gb_code, n2_ch, n2, {"is_roc_offshore": True})
      else:
        self.twn_counties.append(item)

    self.mng_soums = self._load_gadm_zip(self.cfg["gadm"]["files"]["gadm_mng_2"]["filename"])
    rus_raw = self._load_gadm_zip(self.cfg["gadm"]["files"]["gadm_rus_2"]["filename"])
    for item in rus_raw:
      n1 = str(item["props"].get("NAME_1") or "").lower()
      if "tuva" in n1 or "tyva" in n1:
        self.tuva_kozhuuns.append(item)

    tuva_union = unary_union([t["geom"] for t in self.tuva_kozhuuns]) if self.tuva_kozhuuns else None
    enclave_clips = annual_occupation_helpers.build_coastal_enclave_clips(self.reforms, citas_list)

    for feat in a3:
      p = feat["properties"]
      uid = p["unit_id"]
      l1 = p["parent_adm1"]
      l2 = p["parent_adm2"]
      # Taiwan handled cleanly via GADM TWN_2
      if l1 == "Taiwan":
        continue
      geom = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
      if geom is None or geom.is_empty:
        continue

      # Handle Tangnuwulianghai: exclude Tuva proper (handled by tuva_kozhuuns for continuity)
      if l1 == "Wuliyasutai" and l2 == "Tangnuwulianghai" and tuva_union is not None:
        if "kusuguer" not in uid:
          rem = gis_helpers.clean_polygonal_geometry(geom.difference(tuva_union))
          if rem is None or rem.area <= 0.01:
            continue
          geom = rem

      # Split treaty port, colonial, and island enclaves out of host 1911 county units
      geom = annual_occupation_helpers.carve_coastal_enclave_atom(self, l1, l2, uid, p["name_en"], geom, enclave_clips)
      if geom is None or geom.area <= 0.0005:
        continue

      if uid == "cnty_xizang_xizanggedifang_9999_2":
        annual_tusi_helpers.append_xizang_watershed_atoms(self, feat, geom)
        continue

      should_sub = any(uid.startswith(pref) for pref in prefixes)
      if should_sub:
        sub_pieces = []
        covered = []
        for idx in citas_tree.query(geom):
          cg = citas_geoms[idx]
          if not geom.intersects(cg):
            continue
          inter = gis_helpers.clean_polygonal_geometry(geom.intersection(cg))
          if inter is not None and inter.area > 0.003:
            c_meta = citas_list[idx]
            ig, idict = self._cache_geom(inter)
            if ig is not None:
              sub_pieces.append((c_meta, ig, idict))
              covered.append(inter)
        if sub_pieces:
          for c_meta, ig, idict in sub_pieces:
            rp_sub = ig.representative_point()
            self._append_china_atom(f"{uid}_c_{c_meta['gb']}_{len(self.china_atoms)}", idict, ig, l1, l2, c_meta["name_ch"] or p["name_ch"], c_meta["name_en"] or p["name_en"], uid, c_meta["gb"], c_meta["name_ch"], c_meta["name_en"], {"seat_lat": round(float(rp_sub.y), self.precision), "seat_lon": round(float(rp_sub.x), self.precision)})
          rem = gis_helpers.clean_polygonal_geometry(geom.difference(unary_union(covered)))
          if rem is not None and rem.area > 0.015:
            rg, rdict = self._cache_geom(rem)
            if rg is not None:
              rp_rem = rg.representative_point()
              self._append_china_atom(f"{uid}_rem", rdict, rg, l1, l2, p["name_ch"], p["name_en"], uid, "", "", "", {"seat_lat": round(float(rp_rem.y), self.precision), "seat_lon": round(float(rp_rem.x), self.precision)})
          continue

      ag, adict = self._cache_geom(geom)
      if ag is not None:
        rp_fallback = ag.representative_point()
        s_lon = p.get("seat_lon", round(float(rp_fallback.x), self.precision))
        s_lat = p.get("seat_lat", round(float(rp_fallback.y), self.precision))
        self._append_china_atom(uid, adict, ag, l1, l2, p["name_ch"], p["name_en"], uid, "", "", "", {"seat_lat": s_lat, "seat_lon": s_lon})

    annual_occupation_helpers.emit_deferred_guangzhouwan(self, enclave_clips)

    # 2. Load Tusi catalog and geometries
    tusi_cat_path = path_helpers.resolve_path("common.tusi_catalog", self.base_dir)
    tusi_geo_path = path_helpers.resolve_path("output.gis.tusi", self.base_dir)
    if os.path.exists(tusi_cat_path) and os.path.exists(tusi_geo_path):
      cat_obj = gis_helpers.load_json5(tusi_cat_path)
      self.tusi_catalog = cat_obj.get("tusis", []) if isinstance(cat_obj, dict) else []
      for t in self.tusi_catalog:
        self.tusi_by_id[t["tusi_id"]] = t
        for cuid in t.get("chgis_unit_ids", []):
          self.tusi_chgis_unit_ids.add(cuid)
      with open(tusi_geo_path, "r", encoding="utf-8") as fh:
        tg = json.load(fh)
      for feat in tg.get("features", []):
        tid = feat["properties"].get("tusi_id")
        g = gis_helpers.clean_polygonal_geometry(shape(feat["geometry"]))
        cg, cd = self._cache_geom(g)
        if tid and cg is not None:
          self.tusi_geoms[tid] = {"dict": cd, "geom": cg, "props": feat["properties"]}

    # 3. Clip GADM Mongolia soums & post-1931 overlapping Tusis cleanly against permanent China atoms
    perm_china = [a["geom"] for a in self.china_atoms if a["l1_1911"] != "Wuliyasutai" or a["gb"].startswith("65")]
    china_perm_union = gis_helpers.clean_polygonal_geometry(unary_union(perm_china)) if perm_china else None
    if china_perm_union is not None:
      clipped_soums = []
      for item in self.mng_soums:
        if item["geom"].intersects(china_perm_union):
          rem = gis_helpers.clean_polygonal_geometry(item["geom"].difference(china_perm_union))
          if rem is None or rem.area <= 1e-5:
            continue
          rg, rd = self._cache_geom(rem)
          if rg is None:
            continue
          item["geom"], item["dict"] = rg, rd
        clipped_soums.append(item)
      self.mng_soums = clipped_soums
    self.mng_union = gis_helpers.clean_polygonal_geometry(unary_union([m["geom"] for m in self.mng_soums])) if self.mng_soums else None
    self.tusi_geoms_post1931 = dict(self.tusi_geoms)
    if self.mng_union is not None:
      for tid, tg in self.tusi_geoms.items():
        if tg["geom"].intersects(self.mng_union) and tg["geom"].intersection(self.mng_union).area > 0.01:
          rem = gis_helpers.clean_polygonal_geometry(tg["geom"].difference(self.mng_union))
          if rem is not None and rem.geom_type == "MultiPolygon":
            parts = [sub for sub in rem.geoms if sub.area >= 0.002]
            rem = gis_helpers.clean_polygonal_geometry(unary_union(parts)) if parts else None
          rg, rd = self._cache_geom(rem) if rem is not None else (None, None)
          if rg is not None and rg.area > 0.002:
            self.tusi_geoms_post1931[tid] = {"dict": rd, "geom": rg, "props": tg["props"]}

    annual_tusi_helpers.apply_reference_frontline_masks(self)
    self.tusi_host_atoms = annual_tusi_helpers.index_tusi_host_atoms(self.tusi_catalog, self.china_atoms, china_perm_union)

  def _cached_union (self, arg1_keys, arg2_geom_map):
    """Return cached unary_union (geom, mapping_dict) for a tuple/frozenset of keys."""
    # Convert from parameters
    geom_map = arg2_geom_map
    keys = frozenset(arg1_keys)

    if keys in self.union_cache:
      return self.union_cache[keys]

    geoms = [geom_map[k] for k in keys if k in geom_map]
    if not geoms:
      return None, None
    merged = geoms[0] if len(geoms) == 1 else gis_helpers.clean_polygonal_geometry(unary_union(geoms))
    cg, cd = self._cache_geom(merged)
    self.union_cache[keys] = (cg, cd)

    # Return statement
    return cg, cd

  def _match_citas_group (self, arg1_gb, arg2_prefix_list):
    """Check whether a CITAS GB code matches any prefix in a list."""
    # Convert from parameters
    gb = arg1_gb
    prefixes = arg2_prefix_list

    if not gb:
      return False
    for p in prefixes:
      if gb.startswith(p):
        return True

    # Return statement
    return False

  def _classify_china_atom (self, arg1_atom, arg2_year):
    """Classify a mainland China/Mongolia-1912-1931 atomic unit for 1 January arg2_year."""
    # Convert from parameters
    atom = arg1_atom
    year = int(arg2_year)

    # Declare local instance variables.
    adm1 = atom["l1_1911"]
    adm1_ch = ""
    adm2 = atom["l2_1911"]
    adm3 = atom["name_en"]
    category = "province"
    country = "Republic of China"
    gb = atom["gb"]
    l1 = atom["l1_1911"]
    l2 = atom["l2_1911"]
    name_en = atom["name_en"]
    occ = ""

    # 0. Chinese Altay / Hoboksar (1911 Wuliyasutai -> Altai Special Region 1912-1919 -> Xinjiang 1920+)
    if l1 == "Wuliyasutai" and gb.startswith("65"):
      if year == 1911:
        country = "Qing Empire"
      elif year >= 1950:
        country = "People's Republic of China"
      elif year <= 1928:
        country = "Republic of China (Beiyang)"
      else:
        country = "Republic of China"
      adm1 = "Xinjiang" if year >= 1920 else "Altai Special Region"
      cat_a = "province" if year >= 1920 else "special_region"
      adm2_a = "Ashan District" if year >= 1933 else ("Ashan Dao" if year >= 1920 else "Altai")
      return (adm1, self.reforms["adm1_zh_names"].get(adm1, adm1), adm2_a, adm3, country, "", cat_a)

    # 1. Outer Mongolia 1911-1931 (CHGIS Khalkha + Khovd banners; 1932+ handled by GADM MNG_2)
    if l1 == "Wuliyasutai":
      if year >= 1932:
        return None
      if year == 1911:
        country = "Qing Empire"
      elif year in (1920, 1921):
        country = "Mongolia (Beiyang Occupied)"
      elif year >= 1924:
        country = "Mongolian People's Republic"
      else:
        country = "Bogd Khanate of Mongolia"
      if "chechen" in l2.lower():
        adm1 = "Khan Khentii Uul" if year >= 1924 else "Setsen Khan Aimag"
      elif "tuxie" in l2.lower():
        adm1 = "Bogd Khan Uul" if year >= 1924 else "Tusheet Khan Aimag"
      elif "saiyin" in l2.lower():
        adm1 = "Tsetserleg Mandal Uul" if year >= 1924 else "Sain Noyon Khan Aimag"
      elif "zhasake" in l2.lower():
        adm1 = "Khan Taishir Uul" if year >= 1924 else "Zasagt Khan Aimag"
      elif "kebuduo" in l2.lower() or "wuliyasutai" in l2.lower():
        if year >= 1926:
          adm1 = "Chandmani Uul"
        elif year >= 1924:
          adm1 = "Khan Taishir Uul"
        else:
          adm1 = "Khovd Frontier"
      if year >= 1925 and "tuxietuhanzhong" in atom["orig_uid"]:
        adm1 = "Ulaanbaatar"
      return (adm1, adm1, l2, adm3, country, "", "aimag")

    # 2. Country sovereignty (Qing Empire 1911 vs Beiyang vs ROC vs PRC)
    if year == 1911:
      country = "Qing Empire"
    elif year >= 1950:
      if atom.get("is_roc_offshore"):
        country = "Republic of China"
      elif year == 1950 and (l2 in ("Qiongzhou Fu", "Dinghai Ting", "Ningyuan Fu")):
        country = "Republic of China"
      else:
        country = "People's Republic of China"
    elif year <= 1928:
      country = "Republic of China (Beiyang)"

    front_res = annual_tusi_helpers.classify_frontline_atom(atom, year, country)
    if front_res is not None:
      return front_res

    # 3. Kwantung Leased Territory (1912-1945)
    is_kwantung = (gb in ("210212", "210213", "210251")) or (name_en == "Jin Zhou Ting" and not gb)
    if is_kwantung and year <= 1945:
      return ("Guandongzhou (Kwantung)", "关东州", "Guandongzhou", adm3, "Empire of Japan", "Japan", "leased_territory")

    # 4. Coastal enclaves, treaty ports & colonies (Hong Kong, Macau, Guangzhouwan, Weihaiwei, Qingdao)
    enclave_res = annual_occupation_helpers.classify_coastal_enclave(atom, year, country)
    if enclave_res is not None:
      return enclave_res

    # 5. Manchuria + Rehe + Zhelimu (1912-1953)
    in_manchuria = l1 in ("Fengtian", "Jilin", "Heilongjiang") or l2 == "Zhelimu Meng"
    in_rehe_1915 = (l1 == "Zhili" and l2 in ("Chengde Fu", "Chaoyang Fu", "Chifeng Zhilizhou", "Chifeng Zhou")) or (gb.startswith("1504") or gb.startswith("1308") or gb.startswith("211322"))

    if in_manchuria or in_rehe_1915:
      # 1933-1945 Manchukuo (note: Rehe NOT occupied on 1 Jan 1933!)
      if 1933 <= year <= 1945 and (in_manchuria or year >= 1934):
        occ = "Manchukuo (Japan)"
        country = "Manchukuo"
        category = "puppet_province"
        if year == 1933:
          if gb.startswith("1521") or gb.startswith("1522") or gb.startswith("1523") or l2 == "Zhelimu Meng" or "hulun" in atom["orig_uid"]:
            adm1 = "Xing'an (Manchukuo)"
          elif l1 == "Heilongjiang":
            adm1 = "Heilongjiang (Manchukuo)"
          elif l1 == "Jilin":
            adm1 = "Jilin (Manchukuo)"
          else:
            adm1 = "Fengtian (Manchukuo)"
        elif year == 1934:
          if in_rehe_1915:
            adm1 = "Rehe (Manchukuo)"
          elif gb.startswith("1521") or gb.startswith("1522") or gb.startswith("1523") or l2 == "Zhelimu Meng" or "hulun" in atom["orig_uid"]:
            adm1 = "Xing'an (Manchukuo)"
          elif l1 == "Heilongjiang":
            adm1 = "Heilongjiang (Manchukuo)"
          elif l1 == "Jilin":
            adm1 = "Jilin (Manchukuo)"
          else:
            adm1 = "Fengtian (Manchukuo)"
        else:
          mk = self.reforms["manchukuo_provinces"]
          mk_rules = [
            ("Xing'an West (Manchukuo)", mk["xingan_west_citas"], "linxi" in atom["orig_uid"]),
            ("Rehe (Manchukuo)", mk["rehe_citas"], in_rehe_1915),
            ("Xing'an North (Manchukuo)", mk["xingan_north_citas"], "hulun" in atom["orig_uid"] or "jilalin" in atom["orig_uid"]),
            ("Xing'an East (Manchukuo)", mk["xingan_east_citas"], False),
            ("Xing'an South (Manchukuo)", mk["xingan_south_citas"], l2 == "Zhelimu Meng" or "kailu" in atom["orig_uid"]),
            ("Heihe (Manchukuo)", mk["heihe_citas"], False),
            ("Jiandao (Manchukuo)", mk["jiandao_citas"], False),
            ("Jinzhou (Manchukuo)", mk["jinzhou_citas"], False),
            ("Tonghua (Manchukuo)" if year >= 1938 else "Andong (Manchukuo)", mk["tonghua_citas"], False),
            ("Andong (Manchukuo)", mk["andong_citas"], False),
            ("Mudanjiang (Manchukuo)" if year >= 1938 else "Binjiang (Manchukuo)", mk["mudanjiang_citas"], False),
            ("Dong'an (Manchukuo)" if year >= 1940 else ("Mudanjiang (Manchukuo)" if year >= 1938 else "Binjiang (Manchukuo)"), mk["dongan_citas"], False),
            ("Bei'an (Manchukuo)" if year >= 1940 else "Longjiang (Manchukuo)", mk["beian_citas"], False),
            ("Sanjiang (Manchukuo)", mk["sanjiang_citas"], False),
            ("Binjiang (Manchukuo)", mk["binjiang_citas"], False),
            ("Longjiang (Manchukuo)", mk["longjiang_citas"], False),
            ("Siping (Manchukuo)" if year >= 1942 else "Fengtian (Manchukuo)", mk["siping_citas"], False),
            ("Jilin (Manchukuo)", mk["jilin_citas"], False),
            ("Fengtian (Manchukuo)", mk["fengtian_citas"], False),
          ]
          adm1 = None
          for m_name, m_citas, m_extra in mk_rules:
            if m_extra or self._match_citas_group(gb, m_citas):
              adm1 = m_name
              break
          if adm1 is None:
            adm1 = "Longjiang (Manchukuo)" if l1 == "Heilongjiang" else ("Jilin (Manchukuo)" if l1 == "Jilin" else "Fengtian (Manchukuo)")
        return (adm1, adm1, l2, adm3, country, occ, category)

      # 1932 Post-Mukden Incident Japanese-occupied Manchuria corridors
      if year == 1932 and annual_occupation_helpers.classify_manchuria_1932(atom, self.reforms):
        occ = "Japan"
        country = "Japanese Occupied Manchuria"

      # 1946-1949 ROC 9 Northeast Provinces + Rehe
      if 1946 <= year <= 1949:
        if in_rehe_1915:
          adm1 = "Rehe"
        else:
          roc9 = self.reforms["roc_9_ne_provinces"]
          adm1 = "Liaoning"
          for prov_key, plist in [
            ("Andong", roc9["andong_citas"]),
            ("Hejiang", roc9["hejiang_citas"]),
            ("Heilongjiang", roc9["heilongjiang_citas"]),
            ("Jilin", roc9["jilin_citas"]),
            ("Liaobei", roc9["liaobei_citas"]),
            ("Nenjiang", roc9["nenjiang_citas"]),
            ("Songjiang", roc9["songjiang_citas"]),
            ("Xing'an", roc9["xingan_citas"]),
            ("Liaoning", roc9["liaoning_citas"]),
          ]:
            if self._match_citas_group(gb, plist):
              adm1 = prov_key
              break
          if gb == "" and l1 == "Heilongjiang":
            adm1 = "Nenjiang"
          elif gb == "" and l1 == "Jilin":
            adm1 = "Jilin"
          elif gb == "" and l2 == "Zhelimu Meng":
            adm1 = "Liaobei"
        return (adm1, adm1, l2, adm3, country, occ, "province")

      # 1950-1953 PRC 6 Northeast Provinces + Inner Mongolia AR
      if year >= 1950:
        xw_citas = self.reforms["manchukuo_provinces"]["xingan_west_citas"]
        if gb.startswith("1521") or gb.startswith("1522") or gb.startswith("1523") or self._match_citas_group(gb, xw_citas) or (gb == "" and l2 == "Zhelimu Meng") or "linxi" in atom["orig_uid"] or "kailu" in atom["orig_uid"] or "hulun" in atom["orig_uid"] or "jilalin" in atom["orig_uid"]:
          return ("Inner Mongolia Autonomous Region", "内蒙古自治区", l2, adm3, country, "", "autonomous_region")
        if in_rehe_1915:
          return ("Rehe", "热河", l2, adm3, country, "", "province")
        prc6 = self.reforms["prc_6_ne_provinces"]
        adm1 = "Liaodong"
        for prov_key, plist in [
          ("Heilongjiang", prc6["heilongjiang_citas"]),
          ("Jilin", prc6["jilin_citas"]),
          ("Liaodong", prc6["liaodong_citas"]),
          ("Liaoxi", prc6["liaoxi_citas"]),
          ("Songjiang", prc6["songjiang_citas"]),
        ]:
          if self._match_citas_group(gb, plist):
            adm1 = prov_key
            break
        return (adm1, adm1, l2, adm3, country, "", "province")

      # 1912-1931 NE China & Rehe
      if in_rehe_1915:
        adm1 = "Rehe" if year >= 1915 else "Zhili"
      elif l2 == "Zhelimu Meng":
        adm1 = "Neimenggu"
      elif l1 == "Fengtian" and year >= 1930:
        adm1 = "Liaoning"
      return (adm1, adm1, l2, adm3, country, occ, "province")

    # 6. Mengjiang / Inner Mongolia / Chahar / Suiyuan / Ningxia / Altai / Hebei / Shanxi
    # Altai -> Xinjiang (1920+)
    if l2 == "A'ertai Diqu" or "aertai" in atom["orig_uid"]:
      adm1 = "Xinjiang" if year >= 1920 else "Altai Special Region"
      return (adm1, adm1, l2, adm3, country, "", "province")

    # Alashan & Ejina -> Ningxia (1929+)
    if l2 in ("Alashanelute Qi", "Ejinatuerhute Qi") or l2 == "Ningxia Fu":
      if year >= 1929:
        adm1 = "Ningxia"
      elif l2 == "Ningxia Fu":
        adm1 = "Gansu"
      else:
        adm1 = "Neimenggu"
      return (adm1, adm1, l2, adm3, country, "", "province")

    # Xining Fu (7 counties) -> Qinghai (1929+)
    if l1 == "Gansu" and l2 == "Xi'ning Fu":
      adm1 = "Qinghai" if year >= 1929 else "Gansu"
      return (adm1, adm1, l2, adm3, country, "", "province")

    # Xikang / Chuanbian & Kham (Chamdo)
    if l1 == "Sichuan" and (l2 in ("Dengke Fu", "Baan Fu", "Kangding Fu", "Xizangkangbu") or "xizangkangbu" in atom["orig_uid"]):
      # Post-1918 Rongbatsa line: Chamdo (5421xx) administered by Tibet 1919-1950, Chamdo 1951-1953
      if gb.startswith("5421"):
        if year >= 1951:
          return ("Chamdo", "昌都", "Chamdo", adm3, country, "", "special_region")
        if year >= 1919:
          return ("Xizang", "西藏", "Chamdo", adm3, country, "", "province")
      adm1 = "Xikang" if year >= 1929 else ("Chuanbian" if year >= 1915 else "Sichuan")
      return (adm1, adm1, l2, adm3, country, "", "province")

    if l1 == "Sichuan" and l2 in ("Yazhou Fu", "Ningyuan Fu"):
      if year >= 1939:
        adm1 = "Xikang"
      return (adm1, adm1, l2, adm3, country, "", "province")

    # Xizang (Tibet)
    if l1 == "Xizang":
      if (gb.startswith("5421") or l2 == "Chamdo") and year >= 1951:
        return ("Chamdo", "昌都", "Chamdo", adm3, country, "", "special_region")
      return ("Xizang", "西藏", l2, adm3, country, "", "province")

    # Chahar & Suiyuan & Inner Mongolia
    is_chahar_north = (l1 == "Zhili" and l2 in ("Zhangjiakou Ting", "Dushikou Ting", "Duolunnuo'er Ting", "Chaha'er")) or (l1 == "Shanxi" and l2 in ("Xinghe Ting", "Ningyuan Ting", "Fengzhen Ting", "Taolin Ting"))
    is_xuanhua = (l1 == "Zhili" and l2 == "Xuanhua Fu")
    is_suiyuan_core = (l1 == "Shanxi" and l2 in ("Guihuasuiyuan Cheng", "Wuchuan Ting", "Shalaqi Ting", "Tuoketuo Ting", "Helinge'er Ting", "Qingshuihe Ting", "Wuyuan Ting", "Dongsheng Ting")) or (l1 == "Neimenggu" and l2 in ("Wulanchabu Meng", "Yikezhao Meng"))
    is_xilingol = (l1 == "Neimenggu" and l2 == "Xilinguole Meng")

    if is_chahar_north or is_xuanhua or is_suiyuan_core or is_xilingol:
      # 1936-1937 Japanese North Chahar occupation
      if year in (1936, 1937) and (l2 in ("Duolunnuo'er Ting", "Chaha'er", "Dushikou Ting") or is_xilingol):
        return ("Chahar (Japanese / Mongol Occupied)", "察哈尔", l2, adm3, "Japanese Occupied Chahar", "Japan", "occupied_province")

      # 1938-1945 Mengjiang (Chanan, Jinbei, Menggu; West Suiyuan/Yikezhao/Wuyuan remains Free China ROC Suiyuan!)
      if 1938 <= year <= 1945:
        if is_xuanhua or l2 in ("Zhangjiakou Ting", "Dushikou Ting"):
          return ("Chanan (Mengjiang)", "察南", l2, adm3, "Mengjiang (Japan)", "Mengjiang", "puppet_province")
        if is_xilingol or l2 in ("Duolunnuo'er Ting", "Chaha'er", "Xinghe Ting", "Ningyuan Ting", "Fengzhen Ting", "Taolin Ting", "Guihuasuiyuan Cheng", "Wuchuan Ting", "Shalaqi Ting", "Tuoketuo Ting", "Helinge'er Ting", "Qingshuihe Ting", "Wulanchabu Meng"):
          return ("Menggu (Mengjiang)", "蒙古", l2, adm3, "Mengjiang (Japan)", "Mengjiang", "puppet_province")
        return ("Suiyuan", "绥远", l2, adm3, country, "", "province")

      # 1950-1953 Inner Mongolia AR, Chahar (abolished 1953!), Suiyuan
      if year >= 1950:
        if is_xilingol or gb.startswith("1525"):
          return ("Inner Mongolia Autonomous Region", "内蒙古自治区", l2, adm3, country, "", "autonomous_region")
        if is_suiyuan_core:
          return ("Suiyuan", "绥远", l2, adm3, country, "", "province")
        if is_chahar_north or is_xuanhua:
          if year <= 1952:
            return ("Chahar", "察哈尔", l2, adm3, country, "", "province")
          # Abolished 15 Nov 1952 -> 1 Jan 1953: Xuanhua/Zhangjiakou/Dushikou -> Hebei; Xinghe/Fengzhen/Ningyuan -> Suiyuan/Shanxi; Duolun/Chaha'er -> Inner Mongolia
          if l2 in ("Duolunnuo'er Ting", "Chaha'er"):
            return ("Inner Mongolia Autonomous Region", "内蒙古自治区", l2, adm3, country, "", "autonomous_region")
          if l1 == "Shanxi":
            return ("Suiyuan" if l2 in ("Taolin Ting", "Xinghe Ting") else "Shanxi", "山西", l2, adm3, country, "", "province")
          return ("Hebei", "河北", l2, adm3, country, "", "province")

      # 1912-1935 & 1946-1949
      if is_xilingol:
        adm1 = "Chahar" if year >= 1915 else "Neimenggu"
      elif is_chahar_north:
        adm1 = "Chahar" if year >= 1915 else l1
      elif is_xuanhua:
        adm1 = "Chahar" if year >= 1929 else "Zhili"
      elif is_suiyuan_core:
        adm1 = "Suiyuan" if year >= 1915 else ("Neimenggu" if l1 == "Neimenggu" else "Shanxi")
      return (adm1, adm1, l2, adm3, country, "", "province")

    # 7. Jinbei 13 counties (Mengjiang 1938-1945, Chahar 1950-1952, Shanxi 1912-1937 & 1946-1949 & 1953)
    if l1 == "Shanxi" and l2 in ("Datong  Fu", "Shuoping Fu") and name_en in self.reforms["jinbei_13_counties"]:
      if 1938 <= year <= 1945:
        return ("Jinbei (Mengjiang)", "晋北", l2, adm3, "Mengjiang (Japan)", "Mengjiang", "puppet_province")
      if 1950 <= year <= 1952:
        return ("Chahar", "察哈尔", l2, adm3, country, "", "province")
      return ("Shanxi", "山西", l2, adm3, country, "", "province")

    # 8. Pingyuan Province (1950-1952, abolished 1953)
    py_cfg = self.reforms["pingyuan_1950_1952"]
    if 1950 <= year <= 1952:
      if (l1 == "Zhili" and name_en in py_cfg["hebei_counties"]) or (l1 == "Henan" and l2 in py_cfg["henan_prefs"]) or (l1 == "Shandong" and l2 in py_cfg["shandong_prefs"]):
        return ("Pingyuan", "平原", l2, adm3, country, "", "province")

    # 9. Jingzhao / Zhili -> Hebei / Beiping / Tianjin
    if l1 == "Zhili":
      if 1936 <= year <= 1937 and name_en in self.reforms["east_hebei_1936_1937_counties"]:
        return ("East Hebei (Japanese Puppet)", "冀东防共自治政府", l2, adm3, "East Hebei Autonomous Council", "Japan/EastHebei", "puppet_province")
      if year >= 1929:
        adm1 = "Hebei"
      elif year >= 1915 and l2 == "Shuntian Fu":
        adm1 = "Jingzhao"
      else:
        adm1 = "Zhili"
      if year >= 1929 and name_en in ("Daxing Xian", "Wanping Xian"):
        adm1 = "Beijing" if year >= 1950 else "Beiping"
        category = "municipality"
      elif year >= 1929 and name_en == "Tianjin Xian":
        adm1 = "Tianjin"
        category = "municipality"

    # 10. Nanjing / Shanghai / Wuhan / Chongqing / Guangzhou / Xi'an Municipalities (1929+)
    if year >= 1929:
      if l1 == "Jiangsu" and name_en == "Shanghai Xian":
        adm1 = "Shanghai"
        category = "municipality"
      elif l1 == "Jiangsu" and name_en in ("Jiangning Xian", "Shangyuan Xian"):
        adm1 = "Nanjing" if year <= 1952 else "Jiangsu"
        category = "municipality" if year <= 1952 else "province"
      elif l1 == "Hubei" and name_en in ("Wuchang Xian", "Hanyang Xian", "Jiangxia Xian"):
        if year >= 1950:
          adm1 = "Wuhan"
          category = "municipality"
        elif name_en == "Hanyang Xian":
          adm1 = "Hankou"
          category = "municipality"
      elif l1 == "Sichuan" and name_en == "Ba Xian" and year >= 1940:
        adm1 = "Chongqing"
        category = "municipality"
      elif l1 == "Guangdong" and name_en == "Fanyu Xian" and year >= 1930:
        adm1 = "Guangzhou"
        category = "municipality"

    # 11. 1950-1952 Split Provinces (Subei/Sunan, Wanbei/Wannan, Chuanxi/Chuanbei/Chuandong/Chuannan)
    if 1950 <= year <= 1952:
      if adm1 == "Jiangsu":
        if l2 in ("Xuzhou Fu", "Hai Zhou", "Huai'an Fu", "Yangzhou Fu", "Tong Zhou", "Haimen Ting"):
          adm1 = "Subei"
        else:
          adm1 = "Sunan"
      elif adm1 == "Anhui":
        if l2 in ("Huizhou Fu", "Chizhou Fu", "Ningguo Fu", "Taiping Fu", "Guangde Zhou"):
          adm1 = "Wannan"
        else:
          adm1 = "Wanbei"
      elif adm1 == "Sichuan":
        if l2 in ("Chongqing Fu", "Kuizhou Fu", "Zhongzhou Zhilizhou", "Youyang Zhilizhou", "Shizhu Ting"):
          adm1 = "Chuandong"
        elif l2 in ("Baoning Fu", "Suiding Fu", "Shunqing Fu", "Tongchuan Fu"):
          adm1 = "Chuanbei"
        elif l2 in ("Luzhou Zhilizhou", "Yongning Zhilizhou", "Xuzhou Fu", "Zizhou Zhilizhou", "JIading Fu"):
          adm1 = "Chuannan"
        else:
          adm1 = "Chuanxi"

    # Administrative level-2 historical naming (1911-1913 Fu/Zhou/Ting -> 1914-1928 Dao -> 1929+ Inspectorate)
    if year >= 1933:
      adm2 = f"{l2} District"
    elif 1914 <= year <= 1928:
      adm2 = f"{l2} Dao"

    # 12. 1938-1945 Occupied China Proper Corridors (province-qualified + county-seat rules)
    if 1938 <= year <= 1945:
      occ_res = annual_occupation_helpers.classify_china_proper_occupation(atom, year, adm1, adm2, adm3, self.reforms)
      if occ_res is not None:
        return occ_res

    adm1_ch = self.reforms.get("adm1_zh_names", {}).get(adm1, adm1)

    # Return statement
    return (adm1, adm1_ch, adm2, adm3, country, occ, category)

  def _classify_taiwan_atom (self, arg1_item, arg2_year):
    """Classify a GADM TWN_2 subdivision at 1 January arg2_year."""
    # Convert from parameters
    item = arg1_item
    year = int(arg2_year)

    n2 = str(item["props"].get("NAME_2") or "").strip()
    n2_ch = str(item["props"].get("NL_NAME_2") or n2).strip()
    tr = self.reforms["taiwan_reforms"]

    if year <= 1945:
      if year <= 1920:
        adm2 = tr["1912_1920_12_cho"].get(n2, "Taihoku Cho")
      else:
        adm2 = tr["1921_1945_shu_cho"].get(n2, ["Taihoku Shu"])[0]
        if n2 == "Penghu" and year >= 1927:
          adm2 = "Hoko Cho"
      return ("Taiwan", "台湾", adm2, n2, "Empire of Japan", "Japan", "colony")

    if year <= 1950:
      adm2 = tr["1946_1950_8_counties"].get(n2, ["Taipei County"])[0]
    else:
      adm2 = n2
    return ("Taiwan", "台湾", adm2, n2_ch, "Republic of China", "", "province")

  def _classify_mongolia_atom (self, arg1_item, arg2_year):
    """Classify a GADM MNG_2 soum for 1932-1953 Mongolian People's Republic."""
    # Convert from parameters
    item = arg1_item
    year = int(arg2_year)

    n1 = str(item["props"].get("NAME_1") or "").strip()
    n2 = str(item["props"].get("NAME_2") or "").strip()
    # Collapse post-1953 aimags (Darhan-Uul, Orhon, Govisumber) into 1932-1953 aimags
    n1 = self.reforms["mongolia_gadm_merge_post1953"].get(n1, n1)

    merges = self.reforms["mongolia_1932_1941_aimag_merges"]
    if year <= 1934:
      n1 = merges["1932_1934"].get(n1, n1)
    elif year <= 1937:
      n1 = merges["1935_1937"].get(n1, n1)
    elif year <= 1940:
      n1 = merges["1938_1940"].get(n1, n1)
    elif year == 1941:
      n1 = merges["1941"].get(n1, n1)

    # Return statement
    return (n1, n1, n1, n2, "Mongolian People's Republic", "", "aimag")

  def _classify_tuva_atom (self, arg1_item, arg2_year):
    """Classify a GADM RUS_2 Tuva kozhuun for 1911-1953."""
    # Convert from parameters
    item = arg1_item
    year = int(arg2_year)

    n2 = str(item["props"].get("NAME_2") or "").strip()
    if n2 == "Chedi-Khol'skiyrayon":
      n2 = "Tandinskiyrayon"

    if year <= 1914:
      return ("Tannu Uriankhai", "唐努乌梁海", "Tannu Uriankhai", n2, "Qing Empire" if year == 1911 else "Tannu Uriankhai", "", "frontier_polity")
    if year <= 1921:
      return ("Uryankhay Krai", "乌梁海边疆区", "Uryankhay Krai", n2, "Uryankhay Krai", "", "frontier_polity")
    if year <= 1940:
      kh = self.reforms["tuva_1922_1940_khoshuuns"].get(n2, "Ulug-Khem")
      return ("Tuvan People's Republic", "图瓦人民共和国", kh, kh, "Tuvan People's Republic", "", "republic")
    if year <= 1944:
      return ("Tuvan People's Republic", "图瓦人民共和国", n2, n2, "Tuvan People's Republic", "", "republic")
    return ("Tuva Autonomous Oblast", "图瓦自治州", n2, n2, "USSR (Tuva AO)", "", "autonomous_oblast")

  def _write_fast_geojson (self, arg1_path, arg2_features):
    """Write pre-rounded GeoJSON feature dicts cleanly and quickly."""
    # Convert from parameters
    features = arg2_features
    path = arg1_path

    os.makedirs(os.path.dirname(path), exist_ok=True)
    for attempt in range(3):
      try:
        with open(path, "w", encoding="utf-8") as fh:
          json.dump({"type": "FeatureCollection", "features": features}, fh, ensure_ascii=False, separators=(",", ":"))
        break
      except OSError:
        if attempt == 2:
          raise
        time.sleep(0.3)

    # Return statement
    return len(features)

  def build_year (self, arg1_year):
    """Build and export adm_1_<year>.geojson, adm_2_<year>.geojson, and adm_3_<year>.geojson.

    @param arg1_year Snapshot year evaluated on 1 January 00:00 GMT+0.
    @return Dictionary of feature counts at levels 1, 2, 3.
    """
    # Convert from parameters
    year = int(arg1_year)

    # Declare local instance variables.
    tg_map = self.tusi_geoms_post1931 if year >= 1932 else self.tusi_geoms
    active_tusis = [
      t for t in self.tusi_catalog
      if t["tusi_id"] in tg_map
      and int(t.get("de_facto_start_year", t.get("start_year", 1911))) <= year <= int(t.get("de_facto_end_year", t.get("end_year", 1953)))
    ]
    active_chgis_tusi_uids = set()
    active_kriged_geoms = []
    adm1_buckets = {}
    adm2_buckets = {}
    adm3_features = []
    atom_geom_map = {}

    for t in active_tusis:
      if t.get("geometry_mode") == "chgis_direct":
        for cuid in t.get("chgis_unit_ids", []):
          active_chgis_tusi_uids.add(cuid)
      else:
        active_kriged_geoms.append(tg_map[t["tusi_id"]]["geom"])

    kriged_union = None
    kriged_tree = None
    if active_kriged_geoms:
      kriged_union = gis_helpers.clean_polygonal_geometry(unary_union(active_kriged_geoms))
      kriged_tree = STRtree(active_kriged_geoms)

    # Collect classified atomic units (China + Taiwan + Mongolia + Tuva)
    classified_atoms = []

    for atom in self.china_atoms:
      # Skip CHGIS direct-polygon Tusis here because they are emitted as first-level Tusis below
      if atom["orig_uid"] in active_chgis_tusi_uids:
        continue
      res = self._classify_china_atom(atom, year)
      if res is None:
        continue
      adm1, adm1_ch, adm2, adm3, country, occ, cat = res
      g = atom["geom"]
      g_dict = atom["dict"]

      # Subtract active kriged Tusis only if bounding boxes intersect
      if kriged_tree is not None and kriged_tree.query(g).size > 0:
        diff_key = (atom["atom_id"], year >= 1932, frozenset(t["tusi_id"] for t in active_tusis if t.get("geometry_mode") != "chgis_direct"))
        if diff_key in self.diff_cache:
          g, g_dict = self.diff_cache[diff_key]
        else:
          rem = gis_helpers.clean_polygonal_geometry(g.difference(kriged_union))
          if rem is None or rem.area <= 0.0005:
            self.diff_cache[diff_key] = (None, None)
            continue
          g, g_dict = self._cache_geom(rem)
          self.diff_cache[diff_key] = (g, g_dict)
        if g is None:
          continue

      key = f"ch_{atom['atom_id']}_{year}"
      atom_geom_map[key] = g
      classified_atoms.append((key, g_dict, adm1, adm1_ch, adm2, adm3, country, occ, cat))

    outer_layers = [
      ("twn", self.twn_counties, self._classify_taiwan_atom),
      ("mng", self.mng_soums if year >= 1932 else [], self._classify_mongolia_atom),
      ("tuva", self.tuva_kozhuuns, self._classify_tuva_atom),
    ]
    for prefix, items, fn in outer_layers:
      for idx, item in enumerate(items):
        adm1, adm1_ch, adm2, adm3, country, occ, cat = fn(item, year)
        key = f"{prefix}_{idx}"
        atom_geom_map[key] = item["geom"]
        classified_atoms.append((key, item["dict"], adm1, adm1_ch, adm2, adm3, country, occ, cat))

    resolved_tusis = annual_tusi_helpers.resolve_annual_tusis(self, year, active_tusis, tg_map)
    annual_occupation_helpers.enforce_occupation_topology(self, year, classified_atoms, atom_geom_map, resolved_tusis)

    adm1_ch_map = {}
    for key, g_dict, adm1, adm1_ch, adm2, adm3, country, occ, cat in classified_atoms:
      adm3_features.append({
        "type": "Feature",
        "properties": {
          "adm_level": 3,
          "category": cat,
          "country": country,
          "name_ch": adm3,
          "name_en": adm3,
          "occupied_by": occ,
          "parent_adm1": adm1,
          "parent_adm2": adm2,
          "unit_id": f"adm3_{gis_helpers.slugify_snake(adm1)}_{gis_helpers.slugify_snake(adm3)}_{key}",
          "year": year,
        },
        "geometry": g_dict,
      })
      b1 = (adm1, country, occ, cat)
      adm1_buckets.setdefault(b1, []).append(key)
      if adm1_ch:
        adm1_ch_map[b1] = adm1_ch
      b2 = (adm1, adm2, country, occ, cat)
      adm2_buckets.setdefault(b2, []).append(key)

    # Emit Level-1 and Level-2 polygons via cached unary_union
    adm1_features = []
    for (adm1, country, occ, cat), keys in sorted(adm1_buckets.items()):
      _, u_dict = self._cached_union(keys, atom_geom_map)
      if u_dict is None:
        continue
      b1 = (adm1, country, occ, cat)
      adm1_features.append({
        "type": "Feature",
        "properties": {"adm_level": 1, "category": cat, "country": country, "name_ch": adm1_ch_map.get(b1, adm1), "name_en": adm1, "occupied_by": occ, "parent_adm1": "", "unit_id": f"adm1_{gis_helpers.slugify_snake(adm1)}_{gis_helpers.slugify_snake(country)}", "year": year},
        "geometry": u_dict,
      })

    adm2_features = []
    for (adm1, adm2, country, occ, cat), keys in sorted(adm2_buckets.items()):
      _, u_dict = self._cached_union(keys, atom_geom_map)
      if u_dict is None:
        continue
      adm2_features.append({
        "type": "Feature",
        "properties": {"adm_level": 2, "category": cat, "country": country, "name_ch": adm2, "name_en": adm2, "occupied_by": occ, "parent_adm1": adm1, "unit_id": f"adm2_{gis_helpers.slugify_snake(adm1)}_{gis_helpers.slugify_snake(adm2)}", "year": year},
        "geometry": u_dict,
      })

    # Emit active Feudatories as first-level autonomous divisions across adm_1, adm_2, and adm_3
    annual_tusi_helpers.emit_resolved_tusis(year, resolved_tusis, adm1_features, adm2_features, adm3_features)

    c1 = self._write_fast_geojson(os.path.join(self.adm_annual_dir, f"adm_1_{year}.geojson"), adm1_features)
    c2 = self._write_fast_geojson(os.path.join(self.adm_annual_dir, f"adm_2_{year}.geojson"), adm2_features)
    c3 = self._write_fast_geojson(os.path.join(self.adm_annual_dir, f"adm_3_{year}.geojson"), adm3_features)

    # Return statement
    return {"adm_1": c1, "adm_2": c2, "adm_3": c3, "year": year}

  def build_all_years (self, arg1_start=1911, arg2_end=1953):
    """Build annual 1 January GeoJSON series for all years in [arg1_start, arg2_end]."""
    # Convert from parameters
    end_year = int(arg2_end)
    start_year = int(arg1_start)

    summaries = []
    for yr in range(start_year, end_year + 1):
      res = self.build_year(yr)
      summaries.append(res)
      print(f"[STEP 3] {yr}-01-01 -> L1={res['adm_1']} L2={res['adm_2']} L3={res['adm_3']}")

    # Return statement
    return summaries
