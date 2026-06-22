from __future__ import annotations

import re
from collections import Counter
from hashlib import sha256
from typing import Any

import fitz  # PyMuPDF — already in pyproject.toml

from business.foundation import build_stable_id
from business.research.domain.common import SourceLineage
from business.research.domain.document import ResearchDocument, ResearchFigure, ResearchSection

# Average characters-per-page below this threshold → likely a scanned PDF → use OCR
_OCR_CHAR_THRESHOLD = 100

# Minimum heading-to-body font-size ratio
_HEADING_SIZE_RATIO = 1.12

# Maximum line length for a span to be considered a heading candidate
_HEADING_MAX_CHARS = 150

_FIGURE_CAPTION_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:Fig(?:ure)?\.?\s*\d+[.:])\s*(.+?)(?=\n[ \t]*(?:Fig(?:ure)?\.?\s*\d+[.:]|Table\s*\d+[.:])|$)",
    re.DOTALL | re.IGNORECASE,
)
_TABLE_CAPTION_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:Table\s*\d+[.:])\s*(.+?)(?=\n[ \t]*(?:Table\s*\d+[.:]|Fig(?:ure)?\.?\s*\d+[.:])|$)",
    re.DOTALL | re.IGNORECASE,
)
# Numbered section heading: "1 Introduction", "2.1 Method", "A. Appendix"
_SECTION_NUM_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+|[A-Z]\.\s+)\S")


def _estimate_body_font_size(pdf_doc: fitz.Document) -> float:
    """Find the modal font size across the first few pages (most frequent = body text)."""
    sizes: Counter[int] = Counter()
    for page in list(pdf_doc)[:8]:
        for blk in page.get_text("dict").get("blocks", []):  # type: ignore[union-attr]
            for line in blk.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        sizes[round(span.get("size", 0))] += len(text)
    return float(sizes.most_common(1)[0][0]) if sizes else 10.0


def _span_is_heading(span: dict[str, Any], body_size: float, line_text: str) -> bool:
    size: float = span.get("size", 0.0)
    bold: bool = bool(span.get("flags", 0) & 16)
    if len(line_text) > _HEADING_MAX_CHARS:
        return False
    if size >= body_size * _HEADING_SIZE_RATIO:
        return True
    if bold and size >= body_size * 0.95 and _SECTION_NUM_RE.match(line_text):
        return True
    return False


def _page_is_header_footer(blk: dict[str, Any], page_height: float) -> bool:
    """Heuristic: discard text blocks in top 7% or bottom 7% of the page."""
    y0: float = blk.get("bbox", [0, 0, 0, 0])[1]
    y1: float = blk.get("bbox", [0, 0, 0, 0])[3]
    return y0 < page_height * 0.07 or y1 > page_height * 0.93


def _extract_via_text(
    pdf_bytes: bytes, paper_id: str, source_ref: str
) -> tuple[list[ResearchSection], list[ResearchFigure]]:
    pdf_doc: fitz.Document = fitz.open(stream=pdf_bytes, filetype="pdf")
    body_size = _estimate_body_font_size(pdf_doc)

    sections: list[ResearchSection] = []
    current_title = ""
    current_lines: list[str] = []
    current_page: int = 1
    sec_idx = 0
    all_lines: list[str] = []

    def _flush() -> None:
        nonlocal sec_idx
        text = " ".join(current_lines).strip()
        if text and current_title:
            sections.append(
                ResearchSection(
                    section_id=build_stable_id("sec", paper_id, current_title, str(sec_idx)),
                    title=current_title,
                    level=1,
                    text=text,
                    page_start=current_page,
                    source_ref=source_ref,
                )
            )
            sec_idx += 1

    for page in pdf_doc:
        page_height: float = page.rect.height
        for blk in page.get_text("dict").get("blocks", []):  # type: ignore[union-attr]
            if blk.get("type") != 0:  # skip image blocks
                continue
            if _page_is_header_footer(blk, page_height):
                continue
            for line in blk.get("lines", []):
                spans: list[dict[str, Any]] = line.get("spans", [])
                if not spans:
                    continue
                line_text = "".join(s.get("text", "") for s in spans).strip()
                if not line_text:
                    continue
                all_lines.append(line_text)
                is_heading = any(_span_is_heading(s, body_size, line_text) for s in spans)
                if is_heading:
                    _flush()
                    current_title = line_text
                    current_lines = []
                    current_page = page.number + 1  # type: ignore[attr-defined]
                else:
                    current_lines.append(line_text)

    _flush()
    pdf_doc.close()

    # Extract figure captions from full text
    full_text = "\n".join(all_lines)
    figures: list[ResearchFigure] = []
    for i, m in enumerate(_FIGURE_CAPTION_RE.finditer(full_text)):
        caption = m.group(1).strip().replace("\n", " ")
        if caption:
            figures.append(
                ResearchFigure(
                    figure_id=build_stable_id("fig", paper_id, f"pdf_fig_{i}"),
                    caption=caption[:500],
                    source_ref=source_ref,
                )
            )

    return sections, figures


def _extract_via_ocr(
    pdf_bytes: bytes, paper_id: str, source_ref: str
) -> tuple[list[ResearchSection], list[ResearchFigure]]:
    """OCR using remote surya-ocr API when pymupdf text extraction yields insufficient content.

    Requires SURYA_OCR_ENDPOINT in environment (e.g., http://localhost:8000/ocr).
    """
    import base64
    import json
    import os
    import urllib.request

    endpoint = os.environ.get("SURYA_OCR_ENDPOINT", "").strip()
    if not endpoint:
        raise RuntimeError(
            "SURYA_OCR_ENDPOINT not set. Set it to your surya Docker API endpoint "
            "(e.g., http://localhost:8000/ocr) in .env"
        )

    # Convert PDF pages to PNG base64
    pdf_doc: fitz.Document = fitz.open(stream=pdf_bytes, filetype="pdf")
    images_b64: list[str] = []
    for page in pdf_doc:
        pix = page.get_pixmap(dpi=150)
        png_bytes = pix.pil_tobytes(format="PNG")
        images_b64.append(base64.b64encode(png_bytes).decode("utf-8"))
    pdf_doc.close()

    # Call surya API
    request_body = json.dumps({"images": images_b64}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "NewsRoom/0.1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Surya OCR API returned {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to call surya OCR API at {endpoint}: {exc}") from exc

    # Parse response (expected: {"results": [{"text_lines": [{"text": "..."}]}]})
    sections: list[ResearchSection] = []
    predictions = result.get("results", [])
    for page_num, pred in enumerate(predictions):
        text_lines = pred.get("text_lines", [])
        page_text = "\n".join(
            line.get("text", "").strip()
            for line in text_lines
            if isinstance(line, dict) and line.get("text", "").strip()
        )
        if page_text.strip():
            sections.append(
                ResearchSection(
                    section_id=build_stable_id("sec", paper_id, f"page_{page_num}"),
                    title=f"Page {page_num + 1}",
                    level=1,
                    text=page_text,
                    page_start=page_num + 1,
                    source_ref=source_ref,
                )
            )

    return sections, []


def _parse_pdf(
    paper_id: str,
    source_ref: str,
    source_hash: str,
    pdf_bytes: bytes,
) -> ResearchDocument:
    # Determine whether OCR is needed
    probe: fitz.Document = fitz.open(stream=pdf_bytes, filetype="pdf")
    num_pages = probe.page_count
    total_chars = sum(len(page.get_text()) for page in probe)
    probe.close()

    use_ocr = num_pages > 0 and (total_chars / num_pages) < _OCR_CHAR_THRESHOLD

    if use_ocr:
        sections, figures = _extract_via_ocr(pdf_bytes, paper_id, source_ref)
        meta: dict[str, Any] = {"parse_source": "pymupdf", "ocr_used": True}
    else:
        sections, figures = _extract_via_text(pdf_bytes, paper_id, source_ref)
        meta = {"parse_source": "pymupdf", "ocr_used": False}

    return ResearchDocument(
        paper_id=paper_id,
        source_hash=source_hash,
        sections=sections,
        figures=figures,
        lineage=SourceLineage(source_refs=[source_ref], source_hash=source_hash),
        metadata=meta,
    )


class PdfDocumentParser:
    """Implements DocumentParserPort: parse raw PDF bytes to ResearchDocument.

    Uses PyMuPDF for text extraction. Falls back to surya-ocr API when the
    extracted text density indicates a scanned document.
    """

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        return _parse_pdf(
            paper_id=paper_id,
            source_ref=f"arxiv://{paper_id}/pdf",
            source_hash=sha256(source_bytes).hexdigest(),
            pdf_bytes=source_bytes,
        )


__all__ = ["PdfDocumentParser"]
