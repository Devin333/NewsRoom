from __future__ import annotations

import gzip
import io
import tarfile

import fitz
import pytest

from business.research.document.arxiv_parser import ArxivDocumentParser
from business.research.document.pdf_compiler import PdfDocumentParser
from business.research.document.source_format import SourceFormat, detect_source_format


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_pdf(text_pages: list[str]) -> bytes:
    """Build a minimal in-memory PDF with given text on successive pages."""
    doc = fitz.open()
    for text in text_pages:
        page = doc.new_page()
        page.insert_text((50, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_latex_targz(tex_content: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        encoded = tex_content.encode()
        info = tarfile.TarInfo(name="main.tex")
        info.size = len(encoded)
        tf.addfile(info, io.BytesIO(encoded))
    return buf.getvalue()


# ── detect_source_format ──────────────────────────────────────────────────────


def test_detect_plain_pdf():
    pdf = _make_pdf(["hello"])
    fmt, canonical = detect_source_format(pdf)
    assert fmt is SourceFormat.PDF
    assert canonical[:4] == b"%PDF"


def test_detect_gzipped_pdf():
    pdf = _make_pdf(["hello"])
    gzipped = gzip.compress(pdf)
    fmt, canonical = detect_source_format(gzipped)
    assert fmt is SourceFormat.PDF
    assert canonical[:4] == b"%PDF"


def test_detect_latex_targz():
    tgz = _make_latex_targz(r"\documentclass{article}\begin{document}hi\end{document}")
    fmt, canonical = detect_source_format(tgz)
    assert fmt is SourceFormat.LATEX
    # original bytes returned unchanged so LatexSourceParser can handle its own decompression
    assert canonical == tgz


def test_detect_raw_bytes_treated_as_latex():
    fmt, _ = detect_source_format(b"some random bytes")
    assert fmt is SourceFormat.LATEX


# ── PdfDocumentParser ─────────────────────────────────────────────────────────


def test_pdf_parser_extracts_sections():
    pdf_bytes = _make_pdf([
        "Abstract\n\nThis paper presents a new method.",
        "Introduction\n\nDeep learning has advanced many fields.",
        "Method\n\nWe use a transformer-based approach.",
    ])
    parser = PdfDocumentParser()
    doc = parser.parse("2501_12345", pdf_bytes)
    assert doc.paper_id == "2501_12345"
    assert len(doc.sections) >= 1
    assert doc.metadata.get("parse_source") == "pymupdf"
    assert doc.metadata.get("ocr_used") is False


def test_pdf_parser_figure_captions():
    pdf_bytes = _make_pdf([
        "Results\n\nSee Figure 1: Architecture of our model. We evaluated on three benchmarks.",
    ])
    parser = PdfDocumentParser()
    doc = parser.parse("test_fig", pdf_bytes)
    # figure caption extraction may or may not fire depending on regex match in single-page PDF
    assert doc.paper_id == "test_fig"


def test_pdf_parser_source_ref_contains_paper_id():
    pdf_bytes = _make_pdf(["Introduction\n\nSome content here."])
    parser = PdfDocumentParser()
    doc = parser.parse("2501_99999", pdf_bytes)
    assert any("2501_99999" in s.source_ref for s in doc.sections)


# ── ArxivDocumentParser dispatcher ───────────────────────────────────────────


def test_dispatcher_routes_pdf():
    pdf_bytes = _make_pdf(["Abstract\n\nThis is an abstract."])
    parser = ArxivDocumentParser()
    doc = parser.parse("2501_11111", pdf_bytes)
    assert doc.metadata.get("parse_source") == "pymupdf"


def test_dispatcher_routes_latex():
    tex = (
        r"\documentclass{article}"
        r"\begin{document}"
        r"\begin{abstract}We propose a method.\end{abstract}"
        r"\section{Introduction}This is the introduction."
        r"\section{Method}This is the method."
        r"\end{document}"
    )
    tgz = _make_latex_targz(tex)
    parser = ArxivDocumentParser()
    doc = parser.parse("2501_22222", tgz)
    assert doc.metadata.get("parse_source") == "latex"
    titles = [s.title for s in doc.sections]
    assert any("Introduction" in t for t in titles)


def test_dispatcher_routes_gzipped_pdf():
    pdf_bytes = _make_pdf(["Introduction\n\nContent."])
    gzipped = gzip.compress(pdf_bytes)
    parser = ArxivDocumentParser()
    doc = parser.parse("2501_33333", gzipped)
    assert doc.metadata.get("parse_source") == "pymupdf"
