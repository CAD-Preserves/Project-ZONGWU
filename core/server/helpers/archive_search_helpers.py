"""Stateless archive query and polite rate-limited HTTP retrieval helpers for Series A."""

import html
import json
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
import requests

if os.path.abspath(os.path.join(os.path.dirname(__file__), "..")) not in sys.path:
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_RATE_STATE = {"last_ts": 0.0}


def _clean_html_with_parser (arg1_html_text):
  """Extract structured headings and paragraphs from MediaWiki HTML without bs4/lxml.

  @param arg1_html_text Raw HTML string returned by MediaWiki parse API.
  @return List of clean paragraph/heading strings.
  """
  # Convert from parameters
  html_text = str(arg1_html_text or "")

  if not html_text:
    return []

  # Strip edit links, scripts, styles, and navboxes before tag stripping
  cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
  cleaned = re.sub(r"<span[^>]*class=\"[^\"]*mw-editsection[^\"]*\"[^>]*>.*?</span>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
  block_split = re.split(r"</(?:p|h[1-6]|li|tr|div|dd|blockquote)>", cleaned, flags=re.IGNORECASE)
  out = []

  for chunk in block_split:
    plain = html.unescape(re.sub(r"<[^>]+>", " ", chunk))
    txt = re.sub(r"\s+", " ", plain).strip()
    if len(txt) >= 2:
      out.append(txt)

  # Return statement
  return out


def _polite_sleep (arg1_delay_sec):
  """Enforce polite spacing between outbound repository HTTP requests.

  @param arg1_delay_sec Minimum interval in seconds between requests.
  """
  # Convert from parameters
  delay_sec = max(0.0, float(arg1_delay_sec or 0.0))

  # Declare local instance variables.
  elapsed = time.time() - _RATE_STATE["last_ts"]

  if elapsed < delay_sec:
    time.sleep(delay_sec - elapsed)
  _RATE_STATE["last_ts"] = time.time()


def _score_text_relevance (arg1_title, arg2_snippet, arg3_keywords):
  """Compute deterministic relevance score favouring 1911-1953 gazetteer sections and press terms.

  @param arg1_title Candidate document title.
  @param arg2_snippet Candidate snippet or filename.
  @param arg3_keywords Section keywords from series_a_sources_config.json5.
  @return Integer score (higher is more relevant).
  """
  # Convert from parameters
  keywords = list(arg3_keywords or [])
  snippet = str(arg2_snippet or "")
  title = str(arg1_title or "")

  # Declare local instance variables.
  blob = f"{title} {snippet}"
  score = 0

  for kw in keywords:
    if kw and kw in blob:
      score += 5
  for era_tok in ("民國", "民国", "191", "192", "193", "194", "195", "公報", "縣志", "县志", "通志", "Tuva", "Тува", "Mongolia", "臺灣"):
    if era_tok in blob:
      score += 3
  if "卷一" in title or "首卷" in title:
    score += 4
  if len(title) > 160:
    score -= 2

  # Return statement
  return score


def build_wikisource_parse_url (arg1_api_url, arg2_page_title):
  """Construct deterministic MediaWiki action=parse JSON URL for a Wikisource page.

  @param arg1_api_url Base Wikisource API endpoint (e.g. https://zh.wikisource.org/w/api.php).
  @param arg2_page_title Canonical Wikisource page title.
  @return Encoded GET URL string.
  """
  # Convert from parameters
  api_url = str(arg1_api_url or "").strip()
  title = str(arg2_page_title or "").strip()

  # Declare local instance variables.
  params = urllib.parse.urlencode({
    "action": "parse",
    "format": "json",
    "page": title,
    "prop": "displaytitle|text",
    "redirects": "1",
  })

  # Return statement
  return f"{api_url}?{params}"


def extract_paragraphs_from_html (arg1_html_text):
  """Extract clean paragraph lines from HTML content.

  @param arg1_html_text Raw HTML fragment.
  @return List of clean plain-text paragraph strings.
  """
  # Convert from parameters
  html_text = str(arg1_html_text or "")

  # Return statement
  return _clean_html_with_parser(html_text)


def fetch_url_bytes (arg1_url, arg2_options=None):
  """Download URL bytes with polite rate-limiting, retries, and max size protection.

  @param arg1_url Remote HTTP/HTTPS URL.
  @param arg2_options Optional dict (headers, timeout, delay, max_bytes, params).
  @return Tuple (ok_bool, content_bytes, content_type_str).
  """
  # Convert from parameters
  options = dict(arg2_options or {})
  url = str(arg1_url or "").strip()

  # Declare local instance variables.
  cl_raw = ""
  ctype = ""
  delay = float(options.get("delay", 0.4))
  headers = dict(options.get("headers") or {"User-Agent": "ProjectZongwuArchivalIndexer/1.0 (https://confoederatio.org; historical-research)"})
  max_bytes = int(options.get("max_bytes", 83886080))
  params = options.get("params")
  resp = None
  timeout = float(options.get("timeout", 45.0))

  if not url:
    return (False, b"", "")

  for attempt in range(3):
    _polite_sleep(delay*(attempt + 1))
    try:
      resp = requests.get(url, params=params, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
      if resp.status_code in (429, 500, 502, 503, 504):
        time.sleep(1.5*(attempt + 1))
        continue
      if not resp.ok:
        return (False, b"", "")
      cl_raw = str(resp.headers.get("Content-Length") or "")
      if cl_raw.isdigit() and int(cl_raw) > max_bytes:
        resp.close()
        return (False, b"", "")
      chunks = []
      total = 0
      for part in resp.iter_content(chunk_size=131072):
        if not part:
          continue
        total += len(part)
        if total > max_bytes:
          resp.close()
          return (False, b"", "")
        chunks.append(part)
      ctype = str(resp.headers.get("Content-Type") or "")
      return (True, b"".join(chunks), ctype)
    except Exception as exc:
      if attempt == 2:
        print(f"[WARN] HTTP fetch failed for {url}: {exc}", file=sys.stderr)
      time.sleep(1.0*(attempt + 1))

  # Return statement
  return (False, b"", "")


def query_internet_archive (arg1_queries, arg2_cfg, arg3_options=None):
  """Search Internet Archive texts and resolve downloadable lossless PDF or IIIF manifest URLs.

  @param arg1_queries List of search title/keyword strings.
  @param arg2_cfg Parsed common/sources/series_a_sources_config.json5 dict.
  @param arg3_options Optional dict (limit_per_query, max_results).
  @return List of candidate source metadata dicts.
  """
  # Convert from parameters
  cfg = dict(arg2_cfg or {})
  options = dict(arg3_options or {})
  queries = [str(q).strip() for q in (arg1_queries or []) if str(q).strip()]

  # Declare local instance variables.
  candidates = []
  delay = float(cfg.get("request_delay_seconds", 0.4))
  ep_meta = str(cfg.get("api_endpoints", {}).get("internet_archive_metadata", "https://archive.org/metadata/"))
  ep_search = str(cfg.get("api_endpoints", {}).get("internet_archive_search", "https://archive.org/advancedsearch.php"))
  headers = {"User-Agent": str(cfg.get("user_agent") or "ProjectZongwuArchivalIndexer/1.0")}
  limit_q = int(options.get("limit_per_query", 3))
  max_bytes = int(cfg.get("max_single_pdf_bytes", 83886080))
  max_res = int(options.get("max_results", 6))
  seen_ids = set()
  timeout = float(cfg.get("request_timeout_seconds", 45))

  for q_str in queries[:6]:
    if len(candidates) >= max_res:
      break
    ok, raw, _ = fetch_url_bytes(ep_search, {
      "delay": delay,
      "headers": headers,
      "params": {
        "fl[]": ["identifier", "title", "year", "language"],
        "output": "json",
        "q": f'("{q_str}") AND mediatype:texts',
        "rows": limit_q,
      },
      "timeout": timeout,
    })
    if not ok:
      continue
    try:
      docs = requests.models.json.loads(raw.decode("utf-8", errors="replace")).get("response", {}).get("docs", [])
    except Exception:
      docs = []
    for doc in docs:
      ia_id = str(doc.get("identifier") or "").strip()
      if not ia_id or ia_id in seen_ids:
        continue
      seen_ids.add(ia_id)
      ok_m, raw_m, _ = fetch_url_bytes(f"{ep_meta}{ia_id}", {"delay": delay, "headers": headers, "timeout": timeout})
      if not ok_m:
        continue
      try:
        meta = requests.models.json.loads(raw_m.decode("utf-8", errors="replace"))
      except Exception:
        continue
      files = meta.get("files", [])
      best_pdf = None
      for f_rec in files:
        fname = str(f_rec.get("name") or "")
        if not fname.lower().endswith(".pdf"):
          continue
        sz = int(f_rec.get("size") or 0)
        if sz <= 0 or sz > max_bytes:
          continue
        if best_pdf is None or ("_bw" not in fname and "_bw" in best_pdf["name"]):
          best_pdf = {"name": fname, "size": sz}
      if best_pdf:
        candidates.append({
          "format": "pdf",
          "language_hint": str(doc.get("language") or ""),
          "score": _score_text_relevance(doc.get("title"), ia_id, cfg.get("gazetteer_section_keywords", [])) + 2,
          "size_bytes": best_pdf["size"],
          "source_repo": "internet_archive",
          "title": str(doc.get("title") or ia_id),
          "url": f"https://archive.org/download/{ia_id}/{urllib.parse.quote(best_pdf['name'])}",
          "year": doc.get("year"),
        })
      elif any(str(f_rec.get("name") or "").endswith("_jp2.zip") for f_rec in files):
        candidates.append({
          "format": "iiif_manifest",
          "language_hint": str(doc.get("language") or ""),
          "score": _score_text_relevance(doc.get("title"), ia_id, cfg.get("gazetteer_section_keywords", [])),
          "size_bytes": 0,
          "source_repo": "internet_archive",
          "title": str(doc.get("title") or ia_id),
          "url": f"https://iiif.archive.org/iiif/3/{ia_id}/manifest.json",
          "year": doc.get("year"),
        })
      if len(candidates) >= max_res:
        break

  candidates.sort(key=lambda x: x["score"], reverse=True)

  # Return statement
  return candidates[:max_res]


def query_ndl_archive (arg1_queries, arg2_cfg, arg3_options=None):
  """Search Japan National Diet Library OpenSearch and resolve open IIIF manifests.

  @param arg1_queries List of Japanese/Taiwan/Manchukuo search strings.
  @param arg2_cfg Parsed series_a_sources_config.json5 dict.
  @param arg3_options Optional dict (limit_per_query, max_results).
  @return List of NDL IIIF candidate dicts.
  """
  # Convert from parameters
  cfg = dict(arg2_cfg or {})
  options = dict(arg3_options or {})
  queries = [str(q).strip() for q in (arg1_queries or []) if str(q).strip()]

  # Declare local instance variables.
  candidates = []
  delay = float(cfg.get("request_delay_seconds", 0.4))
  ep_open = str(cfg.get("api_endpoints", {}).get("ndl_opensearch", "https://ndlsearch.ndl.go.jp/api/opensearch"))
  headers = {"User-Agent": str(cfg.get("user_agent") or "ProjectZongwuArchivalIndexer/1.0")}
  limit_q = int(options.get("limit_per_query", 5))
  max_res = int(options.get("max_results", 5))
  seen_pids = set()
  tmpl = str(cfg.get("api_endpoints", {}).get("ndl_iiif_manifest_template", "https://dl.ndl.go.jp/api/iiif/{pid}/manifest.json"))
  timeout = float(cfg.get("request_timeout_seconds", 45))

  for q_str in queries[:4]:
    if len(candidates) >= max_res:
      break
    ok, raw, _ = fetch_url_bytes(ep_open, {
      "delay": delay,
      "headers": headers,
      "params": {"cnt": limit_q, "title": q_str},
      "timeout": timeout,
    })
    if not ok:
      continue
    try:
      root = ET.fromstring(raw.decode("utf-8", errors="replace"))
    except Exception:
      continue
    for item in root.findall(".//item"):
      title = str(item.findtext("title") or "").strip()
      link = str(item.findtext("link") or "").strip()
      guid = str(item.findtext("guid") or "").strip()
      m_pid = re.search(r"pid/(\d+)", f"{link} {guid}")
      if not m_pid:
        continue
      pid = m_pid.group(1)
      if pid in seen_pids:
        continue
      seen_pids.add(pid)
      man_url = tmpl.format(pid=pid)
      ok_m, raw_m, _ = fetch_url_bytes(man_url, {"delay": delay, "headers": headers, "max_bytes": 5242880, "timeout": 15})
      if not ok_m:
        continue
      try:
        m_json = requests.models.json.loads(raw_m.decode("utf-8", errors="replace"))
      except Exception:
        continue
      if not (m_json.get("sequences") or m_json.get("items")):
        continue
      candidates.append({
        "format": "iiif_manifest",
        "language_hint": "ja",
        "score": _score_text_relevance(title, pid, cfg.get("gazetteer_section_keywords", [])),
        "size_bytes": 0,
        "source_repo": "ndl_japan",
        "title": title or f"NDL {pid}",
        "url": man_url,
        "year": None,
      })
      if len(candidates) >= max_res:
        break

  candidates.sort(key=lambda x: x["score"], reverse=True)

  # Return statement
  return candidates[:max_res]


def query_wikimedia_commons (arg1_queries, arg2_cfg, arg3_options=None):
  """Search Wikimedia Commons for Republican-era NLC/SSID gazetteer and official gazette PDFs.

  @param arg1_queries List of search terms (e.g. from modern_gazetteer_crosswalk).
  @param arg2_cfg Parsed series_a_sources_config.json5 dict.
  @param arg3_options Optional dict (limit_per_query, max_results).
  @return Ranked list of candidate PDF dicts within max_single_pdf_bytes.
  """
  # Convert from parameters
  cfg = dict(arg2_cfg or {})
  options = dict(arg3_options or {})
  queries = [str(q).strip() for q in (arg1_queries or []) if str(q).strip()]

  # Declare local instance variables.
  candidates = []
  delay = float(cfg.get("request_delay_seconds", 0.4))
  ep = str(cfg.get("api_endpoints", {}).get("wikimedia_commons", "https://commons.wikimedia.org/w/api.php"))
  headers = {"User-Agent": str(cfg.get("user_agent") or "ProjectZongwuArchivalIndexer/1.0")}
  kws = cfg.get("gazetteer_section_keywords", [])
  limit_q = int(options.get("limit_per_query", 6))
  max_bytes = int(cfg.get("max_single_pdf_bytes", 83886080))
  max_res = int(options.get("max_results", 8))
  seen_urls = set()
  timeout = float(cfg.get("request_timeout_seconds", 45))

  for q_str in queries[:6]:
    if len(candidates) >= max_res*2:
      break
    ok, raw, _ = fetch_url_bytes(ep, {
      "delay": delay,
      "headers": headers,
      "params": {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrlimit": limit_q,
        "gsrnamespace": 6,
        "gsrsearch": f"{q_str} filetype:pdf",
        "iiprop": "url|size|mime|sha1",
        "prop": "imageinfo",
      },
      "timeout": timeout,
    })
    if not ok:
      continue
    try:
      pages = requests.models.json.loads(raw.decode("utf-8", errors="replace")).get("query", {}).get("pages", {})
    except Exception:
      pages = {}
    for _, pg in pages.items():
      ii = (pg.get("imageinfo") or [{}])[0]
      url_raw = str(ii.get("url") or "").strip()
      url_clean = url_raw.split("?", 1)[0]
      sz = int(ii.get("size") or 0)
      title = str(pg.get("title") or "").replace("File:", "").strip()
      if not url_clean or url_clean in seen_urls or sz <= 0 or sz > max_bytes:
        continue
      seen_urls.add(url_clean)
      m_yr = re.search(r"\((19[1-5]\d)\)", title)
      candidates.append({
        "format": "pdf",
        "language_hint": "zh_hant",
        "score": _score_text_relevance(title, q_str, kws),
        "sha1": str(ii.get("sha1") or ""),
        "size_bytes": sz,
        "source_repo": "wikimedia_commons",
        "title": title,
        "url": url_clean,
        "year": int(m_yr.group(1)) if m_yr else None,
      })

  candidates.sort(key=lambda x: (x["score"], -x["size_bytes"]), reverse=True)

  # Return statement
  return candidates[:max_res]


def query_wikisource (arg1_queries, arg2_lang_code, arg3_cfg, arg4_options=None):
  """Search Multilingual Wikisource for primary texts and return MediaWiki JSON parse URLs.

  @param arg1_queries List of search strings.
  @param arg2_lang_code Wikisource subdomain key ('zh', 'en', 'ru', or 'ja').
  @param arg3_cfg Parsed series_a_sources_config.json5 dict.
  @param arg4_options Optional dict (limit_per_query, max_results).
  @return Ranked list of Wikisource candidate dicts.
  """
  # Convert from parameters
  cfg = dict(arg3_cfg or {})
  lang_key = str(arg2_lang_code or "zh").strip().lower()
  options = dict(arg4_options or {})
  queries = [str(q).strip() for q in (arg1_queries or []) if str(q).strip()]

  # Declare local instance variables.
  candidates = []
  delay = float(cfg.get("request_delay_seconds", 0.4))
  ep_map = cfg.get("api_endpoints", {})
  ep = str(ep_map.get(f"wikisource_{lang_key}", f"https://{lang_key}.wikisource.org/w/api.php"))
  headers = {"User-Agent": str(cfg.get("user_agent") or "ProjectZongwuArchivalIndexer/1.0")}
  kws = cfg.get("gazetteer_section_keywords", [])
  limit_q = int(options.get("limit_per_query", 5))
  max_res = int(options.get("max_results", 8))
  seen_titles = set()
  timeout = float(cfg.get("request_timeout_seconds", 45))

  for q_str in queries[:6]:
    if len(candidates) >= max_res*2:
      break
    ok, raw, _ = fetch_url_bytes(ep, {
      "delay": delay,
      "headers": headers,
      "params": {
        "action": "query",
        "format": "json",
        "list": "search",
        "srlimit": limit_q,
        "srnamespace": 0,
        "srsearch": q_str,
      },
      "timeout": timeout,
    })
    if not ok:
      continue
    try:
      hits = requests.models.json.loads(raw.decode("utf-8", errors="replace")).get("query", {}).get("search", [])
    except Exception:
      hits = []
    for hit in hits:
      title = str(hit.get("title") or "").strip()
      if not title or title in seen_titles:
        continue
      seen_titles.add(title)
      snippet = re.sub(r"<[^>]+>", "", str(hit.get("snippet") or ""))
      candidates.append({
        "format": "wikisource_parse",
        "language_hint": "zh_hant" if lang_key == "zh" else lang_key,
        "score": _score_text_relevance(title, snippet, kws),
        "size_bytes": int(hit.get("size") or 0),
        "source_repo": f"wikisource_{lang_key}",
        "title": title,
        "url": build_wikisource_parse_url(ep, title),
        "year": None,
      })

  candidates.sort(key=lambda x: (x["score"], x["size_bytes"]), reverse=True)

  # Return statement
  return candidates[:max_res]
