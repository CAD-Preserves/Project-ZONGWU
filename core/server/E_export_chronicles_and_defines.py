"""Step 4 exporter creating ./chronicles/ directories, province_defines.json5, and EN-GB/FR/DE localisation."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gis_helpers


CATEGORY_LOC = {
  "aimag": {
    "de": "Aimag",
    "en_gb": "Aimag",
    "fr": "Aïmag",
  },
  "frontier_territory": {
    "de": "Grenzgebiet",
    "en_gb": "Frontier territory",
    "fr": "Territoire frontalier",
  },
  "japan_puppet_puppet": {
    "de": "Besetztes / Marionettengebiet",
    "en_gb": "Occupied or puppet administration",
    "fr": "Administration occupée ou fantoche",
  },
  "japanese_colony": {
    "de": "Japanisches Generalgouvernement",
    "en_gb": "Japanese governorate-general",
    "fr": "Gouvernorat général japonais",
  },
  "kozhuun": {
    "de": "Choschuun",
    "en_gb": "Khoshuun",
    "fr": "Khochoun",
  },
  "league_special_banner": {
    "de": "Bund / Sonderbanner",
    "en_gb": "League or special banner",
    "fr": "Ligue ou bannière spéciale",
  },
  "manchukuo_province": {
    "de": "Provinz (Mandschukuo)",
    "en_gb": "Manchukuo province",
    "fr": "Province du Mandchoukouo",
  },
  "municipality": {
    "de": "Regierungsunmittelbare Stadt",
    "en_gb": "Direct-controlled municipality",
    "fr": "Municipalité relevant du gouvernement central",
  },
  "occupied_puppet": {
    "de": "Besetzte Verwaltung",
    "en_gb": "Occupied administration",
    "fr": "Administration occupée",
  },
  "prc_adm_area": {
    "de": "Verwaltungsgebiet",
    "en_gb": "Administrative area",
    "fr": "Zone administrative",
  },
  "prc_autonomous_region": {
    "de": "Autonomes Gebiet",
    "en_gb": "Autonomous region",
    "fr": "Région autonome",
  },
  "prc_province": {
    "de": "Provinz",
    "en_gb": "Province",
    "fr": "Province",
  },
  "province": {
    "de": "Provinz",
    "en_gb": "Province",
    "fr": "Province",
  },
  "roc_province": {
    "de": "Provinz",
    "en_gb": "Province",
    "fr": "Province",
  },
  "special_region": {
    "de": "Sonderverwaltungsgebiet",
    "en_gb": "Special administrative region",
    "fr": "Région administrative spéciale",
  },
  "tusi": {
    "de": "Tusi-Häuptlingstum",
    "en_gb": "Tusi polity",
    "fr": "Chefferie Tusi",
  },
  "unknown": {
    "de": "Unbekannt",
    "en_gb": "Unknown",
    "fr": "Inconnu",
  },
}

EXONYMS_FR_DE = {
  "beijing": ("Pékin", "Peking"),
  "east_hebei": ("Hebei oriental", "Ost-Hebei"),
  "guangzhou": ("Canton", "Kanton"),
  "hebei": ("Hebei", "Hebei"),
  "heilongjiang": ("Heilongjiang", "Heilongjiang"),
  "hubei": ("Hubei", "Hubei"),
  "inner_mongolia": ("Mongolie-Intérieure", "Innere Mongolei"),
  "jiangsu": ("Jiangsu", "Jiangsu"),
  "jilin": ("Jilin", "Jilin"),
  "kovd": ("Khovd", "Chowd"),
  "liaoning": ("Liaoning", "Liaoning"),
  "manchuria": ("Mandchourie", "Mandschurei"),
  "mongolia": ("Mongolie", "Mongolei"),
  "nanjing": ("Nankin", "Nanking"),
  "outer_mongolia": ("Mongolie-Extérieure", "Äußere Mongolei"),
  "pingyuan": ("Pingyuan", "Pingyuan"),
  "qinghai": ("Qinghai", "Qinghai"),
  "rehe": ("Jéhol", "Jehol"),
  "shanghai": ("Shanghai", "Schanghai"),
  "shaanxi": ("Shaanxi", "Shaanxi"),
  "shandong": ("Shandong", "Schandong"),
  "shanxi": ("Shanxi", "Shanxi"),
  "sichuan": ("Sichuan", "Sichuan"),
  "suiyuan": ("Suiyuan", "Suiyuan"),
  "taiwan": ("Taïwan", "Taiwan"),
  "tibet": ("Tibet", "Tibet"),
  "tuva": ("Touva", "Tuwa"),
  "uliastai": ("Uliastai", "Uliastai"),
  "xikang": ("Xikang", "Xikang"),
  "xinjiang": ("Xinjiang", "Xinjiang"),
  "yunnan": ("Yunnan", "Yunnan"),
}


class ChroniclesDefinesExporter:
  """Exports first-level chronicle folders, province_defines.json5, and multilingual localisation."""

  def __init__ (self, arg1_base_dir):
    """Initialise exporter paths and runtime containers.

    @param arg1_base_dir Project root directory.
    """
    # Convert from parameters
    base_dir = os.path.abspath(arg1_base_dir)

    # Declare local instance variables.
    self.base_dir = base_dir
    self.chronicles_dir = os.path.join(base_dir, "chronicles")
    self.defines_path = os.path.join(base_dir, "common", "defines", "province_defines.json5")
    self.gis_dir = os.path.join(base_dir, "gis")
    self.loc_dir = os.path.join(base_dir, "localisation")
    self.province_records = {}
    self.tusi_catalog_path = os.path.join(base_dir, "common", "tusi", "tusi_catalog.json5")

  def _add_division_record (self, arg1_slug, arg2_info):
    """Merge a first-level division or Tusi observation into self.province_records.

    @param arg1_slug Canonical snake_case slug.
    @param arg2_info Dict describing name, zh, category, polity, year, and unit_id.
    """
    # Convert from parameters
    info = arg2_info
    slug = arg1_slug

    if not slug:
      return

    if slug not in self.province_records:
      self.province_records[slug] = {
        "active_years": set(),
        "categories": set(),
        "gis_unit_ids": set(),
        "name": info.get("name") or slug,
        "name_zh": info.get("name_zh") or "",
        "polities": set(),
      }

    rec = self.province_records[slug]
    if info.get("name") and len(str(info["name"])) > len(str(rec["name"])):
      rec["name"] = info["name"]
    if info.get("name_zh") and not rec["name_zh"]:
      rec["name_zh"] = info["name_zh"]
    if info.get("category"):
      rec["categories"].add(str(info["category"]))
    if info.get("polity"):
      rec["polities"].add(str(info["polity"]))
    if info.get("year") is not None:
      rec["active_years"].add(int(info["year"]))
    if info.get("unit_id"):
      rec["gis_unit_ids"].add(str(info["unit_id"]))

  def _format_loc_names (self, arg1_slug, arg2_name, arg3_is_tusi):
    """Build EN-GB, FR, and DE display labels for a division or Tusi.

    @param arg1_slug Division slug.
    @param arg2_name English canonical name.
    @param arg3_is_tusi Boolean indicating whether division is a Tusi.
    @return Tuple (en_gb, fr, de).
    """
    # Convert from parameters
    is_tusi = bool(arg3_is_tusi)
    name = str(arg2_name).strip()
    slug = str(arg1_slug).strip()

    # Declare local instance variables.
    de_name = name
    en_name = name
    fr_name = name

    if slug in EXONYMS_FR_DE:
      fr_name, de_name = EXONYMS_FR_DE[slug]
    elif is_tusi:
      base_title = name
      if base_title.endswith(" Tusi"):
        base_title = base_title[:-5].strip()
      fr_name = f"Tusi de {base_title}"
      de_name = f"Tusi von {base_title}"
      if not name.lower().endswith("tusi"):
        en_name = f"{name} Tusi"

    # Return statement
    return (en_name, fr_name, de_name)

  def _load_tusi_catalog (self):
    """Ingest all documented Tusis from ./common/tusi/tusi_catalog.json5 as first-level divisions."""
    if not os.path.exists(self.tusi_catalog_path):
      return

    payload = gis_helpers.load_json5(self.tusi_catalog_path)
    entries = payload.get("tusis", []) if isinstance(payload, dict) else payload
    for entry in entries:
      tusi_id = str(entry.get("tusi_id") or "").strip()
      slug = gis_helpers.slugify_snake(tusi_id or entry.get("name_en", ""))
      name_en = str(entry.get("name_en") or tusi_id).strip()
      name_zh = str(entry.get("name_zh") or entry.get("name_ch") or "").strip()
      start_y = int(entry.get("start_year", 1912))
      end_y = int(entry.get("end_year", 1953))
      years = range(max(1911, start_y), min(1953, end_y) + 1)

      for yr in years:
        self._add_division_record(slug, {
          "category": "tusi",
          "name": name_en,
          "name_zh": name_zh,
          "polity": entry.get("polity_parent") or entry.get("province_1912") or "China",
          "unit_id": tusi_id or slug,
          "year": yr,
        })

  def _scan_adm1_geojsons (self):
    """Scan adm_1_1911.geojson through adm_1_1953.geojson for first-level divisions."""
    for yr in range(1911, 1954):
      path = os.path.join(self.gis_dir, f"adm_1_{yr}.geojson")
      if not os.path.exists(path):
        continue

      with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

      for feat in data.get("features", []):
        props = feat.get("properties", {})
        name_en = str(props.get("name_en") or props.get("LEV1_PY") or props.get("unit_id") or "").strip()
        name_zh = str(props.get("name_ch") or props.get("LEV1_CH") or "").strip()
        # Avoid storing Latin name in name_zh when upstream copied name_en
        if name_zh == name_en and name_en.isascii():
          name_zh = ""
        cat = str(props.get("category") or "province").strip()
        country = str(props.get("country") or "ROC").strip()
        unit_id = str(props.get("unit_id") or "").strip()

        slug = gis_helpers.slugify_snake(name_en)
        if not slug:
          continue

        self._add_division_record(slug, {
          "category": cat,
          "name": name_en,
          "name_zh": name_zh,
          "polity": country,
          "unit_id": unit_id,
          "year": yr,
        })

  def _write_json5_file (self, arg1_path, arg2_header, arg3_payload):
    """Write formatted JSON5 payload with 2-space indentation and leading comment header.

    @param arg1_path Output filepath.
    @param arg2_header Single-line or multi-line JSON5 comment header.
    @param arg3_payload Dict payload to serialise.
    """
    # Convert from parameters
    header = str(arg2_header).strip()
    out_path = str(arg1_path)
    payload = arg3_payload

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    body = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    with open(out_path, "w", encoding="utf-8") as fh:
      fh.write(f"// {header}\n")
      fh.write(body)
      fh.write("\n")

  def export_all (self):
    """Scan annual adm_1 files and Tusi catalogue, then write chronicles dirs, defines, and localisation."""
    self._scan_adm1_geojsons()
    self._load_tusi_catalog()
    os.makedirs(self.chronicles_dir, exist_ok=True)
    os.makedirs(self.loc_dir, exist_ok=True)

    # Declare local instance variables.
    de_strings = {}
    defines_map = {}
    en_gb_strings = {}
    fr_strings = {}

    for cat_key, cat_loc in sorted(CATEGORY_LOC.items()):
      loc_key = f"category.{cat_key}"
      en_gb_strings[loc_key] = cat_loc["en_gb"]
      fr_strings[loc_key] = cat_loc["fr"]
      de_strings[loc_key] = cat_loc["de"]

    for slug in sorted(self.province_records.keys()):
      rec = self.province_records[slug]
      chronicle_dir = os.path.join(self.chronicles_dir, slug)
      os.makedirs(chronicle_dir, exist_ok=True)

      categories_sorted = sorted(rec["categories"])
      is_tusi = "tusi" in categories_sorted
      primary_cat = "tusi" if is_tusi else (categories_sorted[0] if categories_sorted else "province")
      loc_key = f"province.{slug}"
      en_label, fr_label, de_label = self._format_loc_names(slug, rec["name"], is_tusi)

      en_gb_strings[loc_key] = en_label
      fr_strings[loc_key] = fr_label
      de_strings[loc_key] = de_label

      years_sorted = sorted(rec["active_years"])
      defines_map[slug] = {
        "active_years": [years_sorted[0], years_sorted[-1]] if years_sorted else [],
        "categories": categories_sorted,
        "category": primary_cat,
        "chronicle_path": f"./chronicles/{slug}/",
        "gis_unit_ids": sorted(rec["gis_unit_ids"]),
        "localisation_key": loc_key,
        "name": en_label,
        "name_zh": rec["name_zh"],
        "polities": sorted(rec["polities"]),
      }

    defines_payload = {
      "schema_version": 1,
      "time_reference": "00:00 GMT+0 (1 January)",
      "total_first_level_divisions": len(defines_map),
      "provinces": defines_map,
    }
    self._write_json5_file(
      self.defines_path,
      "First-level administrative division and Tusi chronicle registry (1911-1953, GMT+0).",
      defines_payload,
    )
    self._write_json5_file(
      os.path.join(self.loc_dir, "en_gb.json5"),
      "Project-ZONGWU localisation strings (EN-GB).",
      {"locale": "EN-GB", "strings": en_gb_strings},
    )
    self._write_json5_file(
      os.path.join(self.loc_dir, "fr.json5"),
      "Project-ZONGWU localisation strings (FR).",
      {"locale": "FR", "strings": fr_strings},
    )
    self._write_json5_file(
      os.path.join(self.loc_dir, "de.json5"),
      "Project-ZONGWU localisation strings (DE).",
      {"locale": "DE", "strings": de_strings},
    )

    summary = {
      "chronicle_dirs": len(defines_map),
      "defines_path": self.defines_path,
      "localisation_keys": len(en_gb_strings),
    }

    # Return statement
    return summary


if __name__ == "__main__":
  root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
  exporter = ChroniclesDefinesExporter(root_dir)
  result = exporter.export_all()
  print(json.dumps(result, ensure_ascii=False))
