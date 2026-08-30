"""Force OCR on an arXiv paper via surya-vllm. Writes output to ocr_result.txt."""
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # noqa: E702

import argparse
import base64
import os

from framework.shared.env import load_root_env


def _log(out, msg: str) -> None:
    out.write(msg + "\n")
    out.flush()


def ocr_paper(arxiv_id: str, max_pages: int | None, out) -> None:
    import fitz
    import urllib.request
    from infrastructure.external.sources.arxiv import ArxivSourceConnector
    from backend.research.document.source_format import detect_source_format, SourceFormat
    from backend.research.document.pdf_compiler import _ocr_page

    base_url = os.environ.get("SURYA_INFERENCE_URL", "").strip()
    model = os.environ.get("SURYA_INFERENCE_MODEL", "datalab-to/surya-ocr-2")
    if not base_url:
        _log(out, "ERROR: SURYA_INFERENCE_URL not set in .env")
        return

    _log(out, f"\nFetching {arxiv_id} ...")
    pkg = ArxivSourceConnector().fetch_source_package(arxiv_id)
    fmt, canonical = detect_source_format(pkg.content)
    _log(out, f"Format : {fmt.value}  ({len(canonical):,} bytes)")

    if fmt != SourceFormat.PDF:
        _log(out, "Not PDF-only — downloading rendered PDF from arxiv.org ...")
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        with urllib.request.urlopen(pdf_url, timeout=60) as r:
            canonical = r.read()
        _log(out, f"Downloaded PDF : {len(canonical):,} bytes")

    pdf_doc = fitz.open(stream=canonical, filetype="pdf")
    total = pdf_doc.page_count
    pages_to_run = list(range(min(max_pages or total, total)))
    _log(out, f"Pages  : {total} total, OCR on {len(pages_to_run)}")
    _log(out, f"Model  : {model}")
    _log(out, f"URL    : {base_url}\n")

    for page_num in pages_to_run:
        page = pdf_doc[page_num]
        native_chars = len(page.get_text())
        pix = page.get_pixmap(dpi=150)
        image_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
        _log(out, f"{'─' * 60}")
        _log(out, f"Page {page_num + 1}/{total}  (native text chars: {native_chars})")
        try:
            text = _ocr_page(base_url, model, image_b64)
            _log(out, text if text.strip() else "(empty response from model)")
        except Exception as exc:
            _log(out, f"OCR FAILED: {type(exc).__name__}: {exc}")

    pdf_doc.close()


def main() -> int:
    load_root_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("arxiv_id")
    ap.add_argument("--pages", type=int, default=None)
    args = ap.parse_args()

    out_path = pathlib.Path(__file__).resolve().parent.parent / "ocr_result.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        ocr_paper(args.arxiv_id, args.pages, f)

    print(f"Done. Results written to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
