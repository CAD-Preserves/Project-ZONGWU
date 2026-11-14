"""Stateless PDF compilation, integrity inspection, and Unicode archival PDF writer helpers."""

import html
import os
import re
import sys
import pymupdf

if os.path.abspath(os.path.join(os.path.dirname(__file__), "..")) not in sys.path:
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _build_font_css (arg1_font_paths=None):
  """Construct CSS @font-face rules referencing Windows Unicode fonts for PyMuPDF Story rendering.

  @param arg1_font_paths Optional dict of script-key -> font file path.
  @return CSS string suitable for pymupdf.Story(..., user_css=...).
  """
  # Convert from parameters
  font_paths = dict(arg1_font_paths or {})

  # Declare local instance variables.
  defaults = {
    "bo": "C:/Windows/Fonts/himalaya.ttf",
    "ja": "C:/Windows/Fonts/msgothic.ttc",
    "latin_cyrillic": "C:/Windows/Fonts/georgia.ttf",
    "mn_hudum": "C:/Windows/Fonts/monbaiti.ttf",
    "zh": "C:/Windows/Fonts/msyh.ttc",
  }
  faces = []
  families = []

  for key in ("zh", "ja", "bo", "mn_hudum", "latin_cyrillic"):
    fpath = str(font_paths.get(key) or defaults[key]).replace("\\", "/")
    if os.path.exists(fpath):
      fam = f"pz_{key}"
      faces.append(f"@font-face {{ font-family: {fam}; src: url('{fpath}'); }}")
      families.append(fam)

  fam_str = ", ".join(families + ["sans-serif"])
  css = "\n".join(faces) + (
    f"\nbody {{ font-family: {fam_str}; font-size: 10pt; line-height: 1.45; color: #111111; }}"
    f"\nh1 {{ font-size: 14pt; margin-bottom: 6pt; }}"
    f"\nh2 {{ font-size: 11.5pt; margin-top: 8pt; margin-bottom: 4pt; }}"
    f"\np {{ margin-top: 3pt; margin-bottom: 4pt; }}"
  )

  # Return statement
  return css


def _render_html_story_pdf (arg1_html_body, arg2_out_pdf, arg3_font_paths=None):
  """Render structured HTML text losslessly into an A4 searchable PDF via PyMuPDF Story.

  @param arg1_html_body Inner HTML string placed inside <html><body>...</body></html>.
  @param arg2_out_pdf Destination PDF file path.
  @param arg3_font_paths Optional font_fallbacks mapping from ocr_translation_config.json5.
  @return Integer page count rendered.
  """
  # Convert from parameters
  font_paths = arg3_font_paths
  html_body = str(arg1_html_body or "")
  out_pdf = os.path.normpath(str(arg2_out_pdf))

  # Declare local instance variables.
  css = _build_font_css(font_paths)
  dev = None
  full_html = f"<html><body>{html_body}</body></html>"
  mediabox = pymupdf.paper_rect("a4")
  more = True
  page_count = 0
  story = pymupdf.Story(html=full_html, user_css=css)
  tmp_pdf = f"{out_pdf}.tmp.{os.getpid()}"
  where = mediabox + (42, 42, -42, -42)
  writer = None

  os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
  writer = pymupdf.DocumentWriter(tmp_pdf)
  for _ in range(500):
    if not more:
      break
    dev = writer.begin_page(mediabox)
    more, _ = story.place(where)
    story.draw(dev)
    writer.end_page()
    page_count += 1
  writer.close()
  del writer

  if os.path.exists(tmp_pdf):
    os.replace(tmp_pdf, out_pdf)

  # Return statement
  return page_count


def compile_html_to_archival_pdf (arg1_title, arg2_source_url, arg3_paragraphs, arg4_options=None):
  """Compile structured primary-source HTML paragraphs into a searchable lossless archival PDF.

  @param arg1_title Document title string.
  @param arg2_source_url Canonical upstream URL.
  @param arg3_paragraphs Sequence of plain-text paragraph strings.
  @param arg4_options Optional dict (out_pdf, font_paths, extra_metadata).
  @return Tuple (out_pdf, page_count).
  """
  # Convert from parameters
  options = dict(arg4_options or {})
  paragraphs = [str(p).strip() for p in (arg3_paragraphs or []) if str(p).strip()]
  source_url = str(arg2_source_url or "")
  title = str(arg1_title or "Primary Source Document")

  # Declare local instance variables.
  blocks = [f"<h1>{html.escape(title)}</h1>"]
  font_paths = options.get("font_paths")
  out_pdf = str(options.get("out_pdf") or "")
  pages = 0

  if not out_pdf:
    print("[ERROR] compile_html_to_archival_pdf requires options['out_pdf']", file=sys.stderr)
    return ("", 0)

  if source_url:
    blocks.append(f"<p><b>Source URL:</b> {html.escape(source_url)}</p>")
  for para in paragraphs:
    blocks.append(f"<p>{html.escape(para)}</p>")
  if len(blocks) <= 2:
    blocks.append("<p>(No body paragraphs extracted.)</p>")

  pages = _render_html_story_pdf("\n".join(blocks), out_pdf, font_paths)

  # Return statement
  return (out_pdf, pages)


def compile_iiif_images_to_pdf (arg1_image_paths, arg2_out_pdf):
  """Package downloaded IIIF page images losslessly into a multi-page PDF without recompression.

  @param arg1_image_paths Ordered list of local image filepaths.
  @param arg2_out_pdf Destination PDF filepath.
  @return Integer page count compiled.
  """
  # Convert from parameters
  image_paths = [p for p in (arg1_image_paths or []) if os.path.isfile(p)]
  out_pdf = os.path.normpath(str(arg2_out_pdf))

  if not image_paths:
    return 0

  # Declare local instance variables.
  doc = pymupdf.open()
  page_count = 0
  tmp_pdf = f"{out_pdf}.tmp.{os.getpid()}"

  os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
  for img_path in image_paths:
    try:
      img_doc = pymupdf.open(img_path)
      pdf_bytes = img_doc.convert_to_pdf()
      img_doc.close()
      page_pdf = pymupdf.open("pdf", pdf_bytes)
      doc.insert_pdf(page_pdf)
      page_pdf.close()
      page_count += 1
    except Exception as exc:
      print(f"[WARN] Skipping unreadable image {img_path}: {exc}", file=sys.stderr)

  if page_count > 0:
    doc.save(tmp_pdf, deflate=True)
    doc.close()
    os.replace(tmp_pdf, out_pdf)
  else:
    doc.close()

  # Return statement
  return page_count


def inspect_compiled_pdf (arg1_pdf_path, arg2_ocr_cfg=None, arg3_section_keywords=None):
  """Validate compiled PDF integrity, embedded-text quality, and historical section boundaries.

  @param arg1_pdf_path Path to compiled _orig.pdf file.
  @param arg2_ocr_cfg Parsed common/ocr/ocr_translation_config.json5 dict.
  @param arg3_section_keywords Sequence of gazetteer section headings (e.g. 大事记, 兵事).
  @return Dict with valid, page_count, has_embedded_text, and sections list.
  """
  # Convert from parameters
  keywords = list(arg3_section_keywords or ["大事记", "大事記", "建置沿革", "兵事", "土司", "人物"])
  ocr_cfg = dict(arg2_ocr_cfg or {})
  pdf_path = str(arg1_pdf_path or "")

  if not pdf_path or not os.path.isfile(pdf_path):
    return {"has_embedded_text": False, "page_count": 0, "sections": [], "valid": False}

  # Declare local instance variables.
  doc = None
  garbled = 0
  hits = {}
  min_chars = int(ocr_cfg.get("embedded_text_validation", {}).get("min_chars_per_text_page", 40))
  max_garbled = float(ocr_cfg.get("embedded_text_validation", {}).get("max_garbled_ratio", 0.05))
  page_count = 0
  sections = []
  text_pages = 0
  total_chars = 0

  try:
    doc = pymupdf.open(pdf_path)
    page_count = len(doc)
    for idx in range(page_count):
      txt = doc[idx].get_text("text") or ""
      stripped = re.sub(r"\s+", "", txt)
      if len(stripped) >= min_chars:
        text_pages += 1
      total_chars += len(stripped)
      garbled += stripped.count("\ufffd")
      for kw in keywords:
        if kw in txt and kw not in hits:
          hits[kw] = idx + 1
    for level, title, page_no in (doc.get_toc() or []):
      for kw in keywords:
        if kw in str(title) and kw not in hits:
          hits[kw] = max(1, int(page_no))
    doc.close()
  except Exception as exc:
    if doc is not None:
      try:
        doc.close()
      except Exception:
        pass
    print(f"[ERROR] Failed inspecting PDF {pdf_path}: {exc}", file=sys.stderr)
    return {"has_embedded_text": False, "page_count": 0, "sections": [], "valid": False}

  sorted_hits = sorted(hits.items(), key=lambda x: x[1])
  for i, (kw, p_start) in enumerate(sorted_hits):
    p_end = (sorted_hits[i + 1][1] - 1) if (i + 1 < len(sorted_hits) and sorted_hits[i + 1][1] > p_start) else page_count
    sections.append({"page_end": max(p_start, p_end), "page_start": p_start, "title_zh": kw})

  garbled_ratio = (garbled / float(total_chars)) if total_chars > 0 else 1.0
  has_text = (page_count > 0) and (text_pages >= max(1, page_count // 3)) and (garbled_ratio <= max_garbled)

  # Return statement
  return {
    "has_embedded_text": bool(has_text),
    "page_count": page_count,
    "sections": sections,
    "valid": page_count > 0,
  }


def write_transcript_pdf (arg1_pages, arg2_out_pdf, arg3_options=None):
  """Write OCR or translated page text entries into a searchable Unicode PDF (_zh.pdf / _en.pdf).

  @param arg1_pages List of dicts {'page_num': int, 'text': str}.
  @param arg2_out_pdf Destination _zh.pdf or _en.pdf filepath.
  @param arg3_options Optional dict (title, font_paths).
  @return Integer page count rendered.
  """
  # Convert from parameters
  options = dict(arg3_options or {})
  out_pdf = str(arg2_out_pdf or "")
  pages = list(arg1_pages or [])

  # Declare local instance variables.
  blocks = []
  font_paths = options.get("font_paths")
  title = str(options.get("title") or os.path.basename(out_pdf))

  if not out_pdf:
    return 0

  blocks.append(f"<h1>{html.escape(title)}</h1>")
  for pg in pages:
    pno = int(pg.get("page_num") or 1)
    txt = str(pg.get("text") or "").strip()
    blocks.append(f"<h2>Page {pno}</h2>")
    for line in txt.splitlines():
      clean_line = line.strip()
      if clean_line:
        blocks.append(f"<p>{html.escape(clean_line)}</p>")

  # Return statement
  return _render_html_story_pdf("\n".join(blocks), out_pdf, font_paths)
