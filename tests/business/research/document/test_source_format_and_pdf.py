from __future__ import annotations

import gzip
import io
import tarfile
from unittest.mock import patch

import fitz
import pytest

from business.foundation import build_stable_id
from business.research.document.arxiv_parser import ArxivDocumentParser
from business.research.document.pdf_compiler import (
    FigureImageRef,
    PdfDocumentParser,
    _bbox_to_page_rect,
    _parse_mmd,
    _parse_surya_layout_response,
    _run_nougat,
)
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

_MMD_WITH_DISPLAY_MATH = r"""
# Method

\[E=mc^2 \tag{7}\]
"""

_MMD_WITH_TABLE = r"""
# Results

\begin{table}
\begin{tabular}{l c}
Name & Score \\
u-net & 0.92 \\
baseline & 0.83 \\
\end{tabular}
\end{table}
Table 1: Segmentation results.
"""

_MMD_WITH_CAPTION_BOUNDARY = r"""
# Intro

Figure 1: Architecture.

This sentence is normal body text and should not be part of the caption.
"""


@pytest.fixture(autouse=True)
def _disable_live_surya(monkeypatch):
    monkeypatch.delenv("SURYA_INFERENCE_URL", raising=False)


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
    sections, _, _, _ = _parse_mmd(_SAMPLE_MMD, "test_id", "arxiv://test_id/pdf")
    titles = [s.title for s in sections]
    assert "Abstract" in titles
    assert "Introduction" in titles
    assert "Method" in titles


def test_parse_mmd_section_levels():
    sections, _, _, _ = _parse_mmd(_SAMPLE_MMD, "test_id", "arxiv://test_id/pdf")
    by_title = {s.title: s.level for s in sections}
    assert by_title["Introduction"] == 1
    assert by_title["Method"] == 2


def test_parse_mmd_equations():
    _, equations, _, _ = _parse_mmd(_SAMPLE_MMD, "test_id", "arxiv://test_id/pdf")
    assert len(equations) == 1
    assert equations[0].equation_id == build_stable_id("eq", "test_id", "eq:loss")
    assert r"\mathcal{L}" in equations[0].latex


def test_parse_mmd_figures():
    _, _, figures, _ = _parse_mmd(_SAMPLE_MMD, "test_id", "arxiv://test_id/pdf")
    assert len(figures) == 1
    assert "Architecture" in figures[0].caption
    assert figures[0].metadata["figure_number"] == 1


def test_parse_mmd_display_equations():
    _, equations, _, _ = _parse_mmd(
        _MMD_WITH_DISPLAY_MATH,
        "math_id",
        "arxiv://math_id/pdf",
    )

    assert len(equations) == 1
    assert equations[0].equation_id == build_stable_id("eq", "math_id", "7")
    assert r"E=mc^2" in equations[0].latex
    assert equations[0].metadata["parse_source"] == "nougat_mmd"


def test_parse_mmd_tables():
    _, _, _, tables = _parse_mmd(
        _MMD_WITH_TABLE,
        "table_id",
        "arxiv://table_id/pdf",
    )

    assert len(tables) == 1
    assert tables[0].caption == "Segmentation results."
    assert tables[0].columns == ["Name", "Score"]
    assert tables[0].rows == [
        {"Name": "u-net", "Score": "0.92"},
        {"Name": "baseline", "Score": "0.83"},
    ]
    assert tables[0].metadata["table_number"] == 1


def test_parse_mmd_figure_caption_stops_at_blank_line():
    _, _, figures, _ = _parse_mmd(
        _MMD_WITH_CAPTION_BOUNDARY,
        "caption_id",
        "arxiv://caption_id/pdf",
    )

    assert len(figures) == 1
    assert figures[0].caption == "Architecture."


def test_parse_surya_layout_response_extracts_regions():
    response = """Here is the layout JSON:
    ```json
    {"figures":[
      {"label":"figure","bbox":[0.1,0.2,0.8,0.7],"caption":"Architecture","confidence":0.9},
      {"label":"table","bbox":[0.1,0.75,0.8,0.9]},
      {"label":"paragraph","bbox":[0.0,0.0,1.0,0.1]}
    ]}
    ```
    Done."""
    regions = _parse_surya_layout_response(response, page_number=3)

    assert regions == [{
        "page": 3,
        "index": 0,
        "label": "figure",
        "bbox": [0.1, 0.2, 0.8, 0.7],
        "caption": "Architecture",
        "confidence": 0.9,
    }]


def test_parse_surya_layout_response_accepts_surya_bbox_strings():
    response = '[{"label":"Diagram","bbox":"314 88 680 497","count":1670}]'
    regions = _parse_surya_layout_response(response, page_number=3)

    assert regions == [{
        "page": 3,
        "index": 0,
        "label": "diagram",
        "bbox": [314.0, 88.0, 680.0, 497.0],
        "caption": "",
        "confidence": None,
    }]


def test_surya_bbox_conversion_uses_thousand_point_page_scale():
    rect = _bbox_to_page_rect(
        [314.0, 88.0, 680.0, 497.0],
        page_rect=fitz.Rect(0, 0, 612, 792),
        pix_width=1275,
        pix_height=1650,
    )

    assert rect.x0 == pytest.approx(184.168)
    assert rect.y0 == pytest.approx(61.696)
    assert rect.x1 == pytest.approx(424.16)
    assert rect.y1 == pytest.approx(401.624)


def test_parse_mmd_source_ref_propagated():
    sections, equations, figures, tables = _parse_mmd(_SAMPLE_MMD, "test_id", "arxiv://test_id/pdf")
    assert all(s.source_ref == "arxiv://test_id/pdf" for s in sections)
    assert all(e.source_ref == "arxiv://test_id/pdf" for e in equations)
    assert all(f.source_ref == "arxiv://test_id/pdf" for f in figures)
    assert all(t.source_ref == "arxiv://test_id/pdf" for t in tables)


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
    work = tmp_path / ".newsroom" / "nougat"
    work.mkdir(parents=True)
    (work / "paper.mmd").write_text("stale output", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        assert kwargs["timeout"] == 3600
        assert not (work / "paper.mmd").exists()
        # emulate nougat writing <id>.mmd into the host work dir
        (work / "paper.mmd").write_text(_SAMPLE_MMD, encoding="utf-8")
        return None

    with patch("business.research.document.pdf_compiler.subprocess.run", side_effect=fake_run):
        result = _run_nougat(b"%PDF placeholder", "paper")

    assert result == _SAMPLE_MMD
    cmd = commands[0]
    assert cmd[:5] == ["docker", "compose", "run", "--rm", "nougat"]
    assert cmd[5] == "/workspace/.newsroom/nougat/paper.pdf"
    assert cmd[cmd.index("-o") + 1] == "/workspace/.newsroom/nougat"
    assert "--recompute" in cmd


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


@patch("business.research.document.pdf_compiler._extract_pdf_images")
@patch(
    "business.research.document.pdf_compiler._extract_surya_figure_images",
    return_value=[
        FigureImageRef(
            image_ref="figures/surya_p001_fig001.png",
            page=1,
            metadata={"image_source": "surya_layout", "bbox": [0.1, 0.2, 0.8, 0.7]},
        )
    ],
)
@patch("business.research.document.pdf_compiler._run_nougat", return_value=_SAMPLE_MMD)
def test_pdf_parser_prefers_surya_figure_images(
    mock_nougat,
    mock_surya_images,
    mock_pdf_images,
):
    pdf_bytes = _make_pdf(["placeholder"])
    doc = PdfDocumentParser().parse("2501_surya_fig", pdf_bytes)

    mock_pdf_images.assert_not_called()
    assert doc.metadata["figure_image_source"] == "surya_layout"
    assert doc.metadata["figure_images"] == 1
    assert doc.figures[0].image_ref == "figures/surya_p001_fig001.png"
    assert doc.figures[0].page == 1
    assert doc.figures[0].metadata["image_source"] == "surya_layout"
    assert doc.figures[0].metadata["figure_number"] == 1


@patch(
    "business.research.document.pdf_compiler._extract_pdf_images",
    return_value=[
        FigureImageRef(
            image_ref="figures/img1.png",
            page=1,
            metadata={"image_source": "pdf_embedded", "xref": 12},
        )
    ],
)
@patch(
    "business.research.document.pdf_compiler._extract_surya_figure_images",
    side_effect=RuntimeError("surya unavailable"),
)
@patch("business.research.document.pdf_compiler._run_nougat", return_value=_SAMPLE_MMD)
def test_pdf_parser_falls_back_when_surya_fails(
    mock_nougat,
    mock_surya_images,
    mock_pdf_images,
):
    pdf_bytes = _make_pdf(["placeholder"])
    doc = PdfDocumentParser().parse("2501_surya_fallback", pdf_bytes)

    mock_pdf_images.assert_called_once()
    assert doc.metadata["figure_image_source"] == "pdf_embedded"
    assert doc.metadata["figure_images"] == 1
    assert doc.metadata["surya_layout_error"] == "RuntimeError: surya unavailable"
    assert doc.figures[0].image_ref == "figures/img1.png"
    assert doc.figures[0].metadata["image_source"] == "pdf_embedded"


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
