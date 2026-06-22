"""Force OCR on an arXiv paper via surya-vllm and dump the extracted text.

Usage:
    python scripts/diag_ocr.py 2307.03109
    python scripts/diag_ocr.py 2307.03109 --pages 3   # first 3 pages only
"""
from __future__ import annotations

import argparse
import base64
import sys

from framework.shared.env import load_root_env


def ocr_paper(arxiv_id: str, max_pages: int | None) -> None:
    import fitz
    from infrastructure.external.sources.arxiv import ArxivSourceConnector
    from business.research.document.source_format import detect_source_format, SourceFormat
    from business.research.document.pdf_compiler import _ocr_page
    import os

    base_url = os.environ.get("SURYA_INFERENCE_URL", "").strip()
    model = os.environ.get("SURYA_INFERENCE_MODEL", "datalab-to/surya-ocr-2")
    if not base_url:
        print("ERROR: SURYA_INFERENCE_URL not set in .env")
        return

    print(f"\nFetching {arxiv_id}...")
    pkg = ArxivSourceConnector().fetch_source_package(arxiv_id)
    fmt, canonical = detect_source_format(pkg.content)
    print(f"Format: {fmt.value}  ({len(canonical):,} bytes)")

    if fmt != SourceFormat.PDF:
        print("Not a PDF-only paper — fetching PDF directly via abstract page.")
        # Fall back to downloading the rendered PDF
        import urllib.request
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        with urllib.request.urlopen(pdf_url, timeout=60) as r:
            canonical = r.read()
        print(f"Downloaded PDF: {len(canonical):,} bytes")

    pdf_doc = fitz.open(stream=canonical, filetype="pdf")
    total = pdf_doc.page_count
    pages_to_run = list(range(min(max_pages or total, total)))
    print(f"Pages: {total} total, running OCR on {len(pages_to_run)}")
    print(f"Model: {model}  Endpoint: {base_url}\n")

    for page_num in pages_to_run:
        page = pdf_doc[page_num]
        native_chars = len(page.get_text())
        pix = page.get_pixmap(dpi=150)
        image_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
        print(f"{'─' * 60}")
        print(f"Page {page_num + 1}/{total}  (native text chars: {native_chars})")
        try:
            text = _ocr_page(base_url, model, image_b64)
            print(text)
        except Exception as exc:
            print(f"OCR FAILED: {exc}")

    pdf_doc.close()


def main() -> int:
    load_root_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("arxiv_id")
    ap.add_argument("--pages", type=int, default=None, help="Limit to first N pages")
    args = ap.parse_args()
    ocr_paper(args.arxiv_id, args.pages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
