from __future__ import annotations

import gzip
import io
import tarfile
from unittest.mock import patch

import fitz
import pytest

from business.research.document.arxiv_parser import ArxivDocumentParser
from business.research.document.pdf_compiler import PdfDocumentParser, _parse_mmd, _run_nougat
from business.research.document.source_format import SourceFormat, detect_source_format

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_pdf(text_pages: list[str]) -> bytes:
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


_SAMPLE_MMD = r"""
This is the preamble abstract text.

# Introduction

Deep learning has advanced many fields.

## Method

We use a transformer-based approach.

\begin{equation}
\mathcal{L} = \sum_{i=1}^{N} \ell_i
\label{eq:loss}
\end{equation}

Figure 1: Architecture of our proposed model.
"""


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
    assert canonical == tgz


def test_detect_raw_bytes_treated_as_latex():
    fmt, _ = detect_source_format(b"some random bytes")
    assert fmt is SourceFormat.LATEX


# ── _parse_mmd (unit, no nougat needed) ──────────────────────────────────────


def test_parse_mmd_sections():
    sections, _, _ = _parse_mmd(_SAMPLE_MMD, "test_id", "arxiv://test_id/pdf")
    titles = [s.title for s in sections]
    assert "Abstract" in titles
    assert "Introduction" in titles
    assert "Method" in titles


def test_parse_mmd_section_levels():
    sections, _, _ = _parse_mmd(_SAMPLE_MMD, "test_id", "arxiv://test_id/pdf")
    by_title = {s.title: s.level for s in sections}
    assert by_title["Introduction"] == 1
    assert by_title["Method"] == 2


def test_parse_mmd_equations():
    _, equations, _ = _parse_mmd(_SAMPLE_MMD, "test_id", "arxiv://test_id/pdf")
    assert len(equations) == 1
    assert "eq:loss" in equations[0].equation_id
    assert r"\mathcal{L}" in equations[0].latex


def test_parse_mmd_figures():
    _, _, figures = _parse_mmd(_SAMPLE_MMD, "test_id", "arxiv://test_id/pdf")
    assert len(figures) == 1
    assert "Architecture" in figures[0].caption


def test_parse_mmd_source_ref_propagated():
    sections, equations, figures = _parse_mmd(_SAMPLE_MMD, "test_id", "arxiv://test_id/pdf")
    assert all(s.source_ref == "arxiv://test_id/pdf" for s in sections)
    assert all(e.source_ref == "arxiv://test_id/pdf" for e in equations)
    assert all(f.source_ref == "arxiv://test_id/pdf" for f in figures)


# ── PdfDocumentParser (nougat mocked) ────────────────────────────────────────


def test_run_nougat_invokes_docker_compose(monkeypatch, tmp_path):
    """_run_nougat shells out to `docker compose run --rm nougat` with the PDF
    staged inside the project tree and mapped to /workspace. The --model flag
    is injected by the container entrypoint (compose), not by Python."""
    monkeypatch.setattr(
        "business.research.document.pdf_compiler._project_root",
        lambda: str(tmp_path),
    )
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        # emulate nougat writing <id>.mmd into the host work dir
        work = tmp_path / ".newsroom" / "nougat"
        (work / "paper.mmd").write_text(_SAMPLE_MMD, encoding="utf-8")
        return None

    with patch("business.research.document.pdf_compiler.subprocess.run", side_effect=fake_run):
        result = _run_nougat(b"%PDF placeholder", "paper")

    assert result == _SAMPLE_MMD
    cmd = commands[0]
    assert cmd[:5] == ["docker", "compose", "run", "--rm", "nougat"]
    assert cmd[5] == "/workspace/.newsroom/nougat/paper.pdf"
    assert cmd[cmd.index("-o") + 1] == "/workspace/.newsroom/nougat"


@patch("business.research.document.pdf_compiler._run_nougat", return_value=_SAMPLE_MMD)
def test_pdf_parser_returns_document(mock_nougat):
    pdf_bytes = _make_pdf(["placeholder"])
    doc = PdfDocumentParser().parse("2501_12345", pdf_bytes)
    assert doc.paper_id == "2501_12345"
    assert doc.metadata.get("parse_source") == "nougat"
    assert len(doc.sections) >= 1


@patch("business.research.document.pdf_compiler._run_nougat", return_value=_SAMPLE_MMD)
def test_pdf_parser_source_ref_contains_paper_id(mock_nougat):
    pdf_bytes = _make_pdf(["placeholder"])
    doc = PdfDocumentParser().parse("2501_99999", pdf_bytes)
    assert any("2501_99999" in s.source_ref for s in doc.sections)


@patch("business.research.document.pdf_compiler._run_nougat", return_value=_SAMPLE_MMD)
def test_pdf_parser_extracts_equations(mock_nougat):
    pdf_bytes = _make_pdf(["placeholder"])
    doc = PdfDocumentParser().parse("2501_eq", pdf_bytes)
    assert len(doc.equations) == 1


@patch("business.research.document.pdf_compiler._run_nougat", return_value=_SAMPLE_MMD)
def test_pdf_parser_extracts_figures(mock_nougat):
    pdf_bytes = _make_pdf(["placeholder"])
    doc = PdfDocumentParser().parse("2501_fig", pdf_bytes)
    assert len(doc.figures) == 1
    assert "Architecture" in doc.figures[0].caption


# ── ArxivDocumentParser dispatcher ───────────────────────────────────────────


@patch("business.research.document.pdf_compiler._run_nougat", return_value=_SAMPLE_MMD)
def test_dispatcher_routes_pdf(mock_nougat):
    pdf_bytes = _make_pdf(["Abstract\n\nThis is an abstract."])
    doc = ArxivDocumentParser().parse("2501_11111", pdf_bytes)
    assert doc.metadata.get("parse_source") == "nougat"

@patch("business.research.document.pdf_compiler._run_nougat", return_value=_SAMPLE_MMD)
def test_dispatcher_routes_gzipped_pdf(mock_nougat):
    pdf_bytes = _make_pdf(["Introduction\n\nContent."])
    gzipped = gzip.compress(pdf_bytes)
    doc = ArxivDocumentParser().parse("2501_33333", gzipped)
    assert doc.metadata.get("parse_source") == "nougat"


def test_dispatcher_routes_latex():
    tex = (
        r"\documentclass{article}"
        r"egin{document}"
        r"egin{abstract}We propose a method.\end{abstract}"
        r"\section{Introduction}This is the introduction."
        r"\section{Method}This is the method."
        r"\end{document}"
    )
    tgz = _make_latex_targz(tex)
    doc = ArxivDocumentParser().parse("2501_22222", tgz)
    assert doc.metadata.get("parse_source") == "latex"
    titles = [s.title for s in doc.sections]
    assert any("Introduction" in t for t in titles)
