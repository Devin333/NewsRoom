from __future__ import annotations

import re
from collections import Counter
from hashlib import sha256
from typing import Any

import fitz  # PyMuPDF

from business.foundation import build_stable_id
from business.research.domain.common import SourceLineage
from business.research.domain.document import ResearchDocument, ResearchFigure, ResearchSection

_OCR_CHAR_THRESHOLD = 100
_HEADING_SIZE_RATIO = 1.12
_HEADING_MAX_CHARS = 150

_FIGURE_CAPTION_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:Fig(?:ure)?\.?\s*\d+[.:])\s*(.+?)(?=\n[ \t]*(?:Fig(?:ure)?\.?\s*\d+[.:]|Table\s*\d+[.:])|$)",
    re.DOTALL | re.IGNORECASE,
)
_SECTION_NUM_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+|[A-Z]\.\s+)\S")


def _estimate_body_font_size(pdf_doc: fitz.Document) -> float:
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
            sections.append(ResearchSection(
                section_id=build_stable_id("sec", paper_id, current_title, str(sec_idx)),
                title=current_title,
                level=1,
                text=text,
                page_start=current_page,
                source_ref=source_ref,
            ))
            sec_idx += 1

    for page in pdf_doc:
        page_height: float = page.rect.height
        for blk in page.get_text("dict").get("blocks", []):  # type: ignore[union-attr]
            if blk.get("type") != 0:
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

    full_text = "\n".join(all_lines)
    figures: list[ResearchFigure] = []
    for i, m in enumerate(_FIGURE_CAPTION_RE.finditer(full_text)):
        caption = m.group(1).strip().replace("\n", " ")
        if caption:
            figures.append(ResearchFigure(
                figure_id=build_stable_id("fig", paper_id, f"pdf_fig_{i}"),
                caption=caption[:500],
                source_ref=source_ref,
            ))

    return sections, figures


def _ocr_page(base_url: str, model: str, image_b64: str) -> str:
    import json
    import urllib.request

    body = json.dumps({
        "model": model,
        "messages": [{
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}],
        }],
        "max_tokens": 4096,
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Surya vLLM {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
        ) from exc
    return data["choices"][0]["message"]["content"]


def _extract_via_ocr(
    pdf_bytes: bytes, paper_id: str, source_ref: str
) -> tuple[list[ResearchSection], list[ResearchFigure]]:
    import base64
    import os

    base_url = os.environ.get("SURYA_INFERENCE_URL", "").strip()
    if not base_url:
        raise RuntimeError(
            "SURYA_INFERENCE_URL not set in .env "
            "(e.g., SURYA_INFERENCE_URL=http://localhost:3010/v1)"
        )
    model = os.environ.get("SURYA_INFERENCE_MODEL", "datalab-to/surya-ocr-2")

    pdf_doc: fitz.Document = fitz.open(stream=pdf_bytes, filetype="pdf")
    sections: list[ResearchSection] = []
    for page_num, page in enumerate(pdf_doc):
        pix = page.get_pixmap(dpi=150)
        image_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
        page_text = _ocr_page(base_url, model, image_b64).strip()
        if page_text:
            sections.append(ResearchSection(
                section_id=build_stable_id("sec", paper_id, f"page_{page_num}"),
                title=f"Page {page_num + 1}",
                level=1,
                text=page_text,
                page_start=page_num + 1,
                source_ref=source_ref,
            ))
    pdf_doc.close()
    return sections, []


def _parse_pdf(
    paper_id: str,
    source_ref: str,
    source_hash: str,
    pdf_bytes: bytes,
) -> ResearchDocument:
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
    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        return _parse_pdf(
            paper_id=paper_id,
            source_ref=f"arxiv://{paper_id}/pdf",
            source_hash=sha256(source_bytes).hexdigest(),
            pdf_bytes=source_bytes,
        )


__all__ = ["PdfDocumentParser"]
