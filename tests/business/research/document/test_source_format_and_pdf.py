from __future__ import annotations

import gzip
import io
import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from business.foundation import build_stable_id
from business.research.domain.common import SourceLineage
from business.research.domain.document import (
    ResearchDocument,
    ResearchEquation,
    ResearchFigure,
    ResearchSection,
    ResearchTable,
)
from business.research.document.arxiv_parser import ArxivDocumentParser
from business.research.document.marker_pdf_parser import MarkerPdfDocumentParser
from business.research.document.pdf_compiler import (
    FigureImageRef,
    PageTextEvidence,
    PdfDocumentParser,
    SuryaLayoutArtifacts,
    _attach_equation_positions,
    _attach_figure_images,
    _bbox_to_page_rect,
    _extract_missing_pages,
    _extract_surya_layout_artifacts,
    _extract_table_structure_from_words,
    _parse_mmd,
    _parse_surya_layout_response,
    _run_nougat,
    _with_nearest_caption_region,
)
from business.research.document.pdf_parser_backend import pdf_parser_backend_name
from business.research.document.pdf_visual_sidecar import merge_pdf_visual_sidecar
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
    return _make_latex_targz_with_files(tex_content, {})


def _make_latex_targz_with_files(tex_content: str, files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        encoded = tex_content.encode()
        info = tarfile.TarInfo(name="main.tex")
        info.size = len(encoded)
        tf.addfile(info, io.BytesIO(encoded))
        for name, content in files.items():
            file_info = tarfile.TarInfo(name=name)
            file_info.size = len(content)
            tf.addfile(file_info, io.BytesIO(content))
    return buf.getvalue()


def _write_marker_json(output_dir: Path, payload: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "input.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


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

_MMD_WITH_TABLE_CAPTION_ONLY = r"""
# Results

Table 1: Segmentation results.
"""

_MMD_WITH_CAPTION_BOUNDARY = r"""
# Intro

Figure 1: Architecture.

This sentence is normal body text and should not be part of the caption.
"""

_MMD_WITH_MISSING_PAGE = r"""
# Intro

This page parsed correctly.

[MISSING_PAGE_FAIL:2]
"""

_MMD_WITH_TWO_SECTIONS = r"""
# 1 Introduction

Unique introduction phrase appears on the first page.

# 2 Method

Distinct method phrase appears on the second page.
"""

_MMD_WITH_PREAMBLE_AND_SECTION = r"""
Abstract

Unique abstract phrase appears on the first page.

# 1 Introduction

Unique introduction phrase also starts on the first page.

# 2 Method

Distinct method phrase appears on the second page.
"""


@pytest.fixture(autouse=True)
def _disable_live_surya(monkeypatch):
    monkeypatch.delenv("SURYA_INFERENCE_URL", raising=False)
    monkeypatch.setenv("NEWSROOM_PDF_WRITE_ARTIFACTS", "0")


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
    assert equations[0].metadata["equation_number"] == "7"
    assert equations[0].metadata["equation_label"] == "7"


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


def test_parse_surya_layout_response_accepts_evidence_labels():
    response = """{"regions":[
      {"label":"Table","bbox":[0.1,0.2,0.8,0.3]},
      {"label":"Caption","bbox":[0.1,0.31,0.8,0.36]},
      {"label":"Equation_Block","bbox":[0.2,0.5,0.7,0.55]},
      {"label":"paragraph","bbox":[0.0,0.0,1.0,0.1]}
    ]}"""
    regions = _parse_surya_layout_response(
        response,
        page_number=4,
        allowed_labels={"table", "caption", "equation-block"},
    )

    assert [region["label"] for region in regions] == [
        "table",
        "caption",
        "equation-block",
    ]


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


def test_surya_caption_region_attaches_to_nearest_crop():
    refs = [
        FigureImageRef(
            image_ref="figures/fig1.png",
            page=1,
            metadata={"pdf_rect": [100.0, 100.0, 300.0, 200.0]},
        )
    ]
    regions = [
        {
            "page": 1,
            "index": 2,
            "label": "caption",
            "bbox": [0.1, 0.3, 0.5, 0.4],
            "pdf_rect": [95.0, 210.0, 305.0, 240.0],
            "layout_region_ref": "surya_layout.json#page=1&region=2",
            "text": "Figure 1: Architecture.",
            "text_source": "pymupdf_bbox",
        }
    ]

    attached = _with_nearest_caption_region(refs, regions)

    assert attached[0].metadata["caption_region_index"] == 2
    assert attached[0].metadata["caption_region_ref"] == "surya_layout.json#page=1&region=2"
    assert attached[0].metadata["caption_text"] == "Figure 1: Architecture."
    assert attached[0].metadata["caption_text_source"] == "pymupdf_bbox"
    assert attached[0].metadata["caption_pdf_rect"] == [95.0, 210.0, 305.0, 240.0]
    assert attached[0].metadata["caption_match_strategy"] == "same_page_nearest_caption_region"


def test_extract_table_structure_from_word_coordinates():
    doc = fitz.open()
    page = doc.new_page()
    for x, y, text in [
        (50, 70, "Name"),
        (150, 70, "Score"),
        (50, 90, "u-net"),
        (150, 90, "0.92"),
        (50, 110, "baseline"),
        (150, 110, "0.83"),
    ]:
        page.insert_text((x, y), text)

    columns, rows = _extract_table_structure_from_words(
        page,
        fitz.Rect(40, 50, 220, 130),
    )
    doc.close()

    assert columns == ["Name", "Score"]
    assert rows == [
        {"Name": "u-net", "Score": "0.92"},
        {"Name": "baseline", "Score": "0.83"},
    ]


@patch(
    "business.research.document.pdf_compiler._run_surya_layout",
    return_value=[
        {
            "page": 1,
            "index": 0,
            "label": "figure",
            "bbox": [100.0, 100.0, 900.0, 700.0],
            "caption": "Architecture",
            "confidence": 0.95,
        }
    ],
)
@patch("business.research.document.pdf_compiler._ocr_page", return_value="Encoder Decoder Attention")
def test_surya_figure_crop_ocr_is_disabled_by_default(
    mock_ocr,
    mock_layout,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("SURYA_INFERENCE_URL", "http://surya.test/v1")
    monkeypatch.delenv("NEWSROOM_PDF_FIGURE_OCR", raising=False)
    monkeypatch.setenv("NEWS_ARTIFACT_ROOT", str(tmp_path / "runs"))
    pdf_doc = fitz.open(stream=_make_pdf(["Figure 1: Architecture"]), filetype="pdf")
    try:
        artifacts = _extract_surya_layout_artifacts(pdf_doc, "2501_fig_ocr_disabled")
    finally:
        pdf_doc.close()

    assert len(artifacts.figure_images) == 1
    assert "ocr_text" not in artifacts.figure_images[0].metadata
    mock_ocr.assert_not_called()


@patch(
    "business.research.document.pdf_compiler._run_surya_layout",
    return_value=[
        {
            "page": 1,
            "index": 0,
            "label": "figure",
            "bbox": [100.0, 100.0, 900.0, 700.0],
            "caption": "Architecture",
            "confidence": 0.95,
        }
    ],
)
@patch("business.research.document.pdf_compiler._ocr_page", return_value="Encoder Decoder Attention")
def test_surya_figure_crop_ocr_metadata_when_enabled(
    mock_ocr,
    mock_layout,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("SURYA_INFERENCE_URL", "http://surya.test/v1")
    monkeypatch.setenv("NEWSROOM_PDF_FIGURE_OCR", "1")
    monkeypatch.setenv("NEWS_ARTIFACT_ROOT", str(tmp_path / "runs"))
    pdf_doc = fitz.open(stream=_make_pdf(["Figure 1: Architecture"]), filetype="pdf")
    try:
        artifacts = _extract_surya_layout_artifacts(pdf_doc, "2501_fig_ocr_enabled")
    finally:
        pdf_doc.close()

    assert len(artifacts.figure_images) == 1
    metadata = artifacts.figure_images[0].metadata
    assert metadata["ocr_attempted"] is True
    assert metadata["ocr_text_source"] == "surya_ocr_crop"
    assert metadata["ocr_chars"] == len("Encoder Decoder Attention")
    assert metadata["ocr_text"] == "Encoder Decoder Attention"
    assert metadata["ocr_truncated"] is False
    mock_ocr.assert_called_once()


@patch(
    "business.research.document.pdf_compiler._run_surya_layout",
    return_value=[
        {
            "page": 1,
            "index": 0,
            "label": "figure",
            "bbox": [100.0, 100.0, 900.0, 700.0],
            "caption": "Architecture",
            "confidence": 0.95,
        }
    ],
)
@patch("business.research.document.pdf_compiler._ocr_page", side_effect=RuntimeError("ocr down"))
def test_surya_figure_crop_ocr_failure_keeps_figure_metadata(
    mock_ocr,
    mock_layout,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("SURYA_INFERENCE_URL", "http://surya.test/v1")
    monkeypatch.setenv("NEWSROOM_PDF_FIGURE_OCR", "1")
    monkeypatch.setenv("NEWS_ARTIFACT_ROOT", str(tmp_path / "runs"))
    pdf_doc = fitz.open(stream=_make_pdf(["Figure 1: Architecture"]), filetype="pdf")
    try:
        artifacts = _extract_surya_layout_artifacts(pdf_doc, "2501_fig_ocr_error")
    finally:
        pdf_doc.close()

    assert len(artifacts.figure_images) == 1
    metadata = artifacts.figure_images[0].metadata
    assert metadata["ocr_attempted"] is True
    assert metadata["ocr_chars"] == 0
    assert metadata["ocr_error"] == "RuntimeError: ocr down"
    assert "ocr_text" not in metadata
    mock_ocr.assert_called_once()


def test_figure_image_alignment_prefers_caption_text_page():
    figures = [
        _parse_mmd(_SAMPLE_MMD, "align_id", "arxiv://align_id/pdf")[2][0]
    ]
    refs = [
        FigureImageRef(image_ref="figures/wrong.png", page=1, metadata={}),
        FigureImageRef(image_ref="figures/right.png", page=2, metadata={}),
    ]
    page_texts = [
        PageTextEvidence(
            page=1,
            native_text="Body text only.",
            selected_text="Body text only.",
            selected_source="pymupdf_text",
            native_chars=15,
            native_words=3,
        ),
        PageTextEvidence(
            page=2,
            native_text="Figure 1: Architecture of our proposed model.",
            selected_text="Figure 1: Architecture of our proposed model.",
            selected_source="pymupdf_text",
            native_chars=46,
            native_words=7,
        ),
    ]

    attached = _attach_figure_images(figures, refs, page_texts)

    assert attached[0].page == 2
    assert attached[0].image_ref == "figures/right.png"
    assert attached[0].metadata["alignment_strategy"] == "caption_text_page_match"


def test_figure_image_alignment_prefers_caption_region_number():
    figures = [
        _parse_mmd(_SAMPLE_MMD, "number_id", "arxiv://number_id/pdf")[2][0]
    ]
    refs = [
        FigureImageRef(
            image_ref="figures/figure2.png",
            page=2,
            metadata={"caption_text": "Figure 2: Different architecture."},
        ),
        FigureImageRef(
            image_ref="figures/figure1.png",
            page=2,
            metadata={"caption_text": "Figure 1: Architecture of our proposed model."},
        ),
    ]
    page_texts = [
        PageTextEvidence(
            page=2,
            native_text="Figure 1: Architecture of our proposed model.",
            selected_text="Figure 1: Architecture of our proposed model.",
            selected_source="pymupdf_text",
            native_chars=46,
            native_words=7,
        )
    ]

    attached = _attach_figure_images(figures, refs, page_texts)

    assert attached[0].page == 2
    assert attached[0].image_ref == "figures/figure1.png"
    assert attached[0].metadata["alignment_strategy"] == "caption_region_number_match"


def test_figure_image_alignment_uses_caption_token_overlap():
    mmd = """
Figure 3: HeLa cells on glass recorded with DIC (differential interference contrast)
microscopy. (**a**) raw image. (**b**) overlay with ground truth segmentation.
"""
    figures = [_parse_mmd(mmd, "fuzzy_id", "arxiv://fuzzy_id/pdf")[2][0]]
    refs = [
        FigureImageRef(image_ref="figures/wrong.png", page=1, metadata={}),
        FigureImageRef(image_ref="figures/right.png", page=5, metadata={}),
    ]
    page_texts = [
        PageTextEvidence(
            page=1,
            native_text="Figure 2: Another caption.",
            selected_text="Figure 2: Another caption.",
            selected_source="pymupdf_text",
            native_chars=26,
            native_words=4,
        ),
        PageTextEvidence(
            page=5,
            native_text=(
                "Figure 3 HeLa cells on glass recorded with DIC differential "
                "interference contrast microscopy raw image overlay with "
                "ground truth segmentation"
            ),
            selected_text=(
                "Figure 3 HeLa cells on glass recorded with DIC differential "
                "interference contrast microscopy raw image overlay with "
                "ground truth segmentation"
            ),
            selected_source="pymupdf_text",
            native_chars=132,
            native_words=19,
        ),
    ]

    attached = _attach_figure_images(figures, refs, page_texts)

    assert attached[0].page == 5
    assert attached[0].image_ref == "figures/right.png"
    assert attached[0].metadata["caption_text_match_score"] > 0.65


def test_extract_missing_pages_from_nougat_markers():
    assert _extract_missing_pages(_MMD_WITH_MISSING_PAGE) == {2}


def test_equation_position_falls_back_to_page_text_overlap():
    equation = ResearchEquation(
        equation_id="eq_lrate",
        latex=(
            r"\[\small\mathit{lrate}=d_{\text{model}}^{-0.5}"
            r"\cdot\min(\mathit{step\_num}^{-0.5},"
            r"\mathit{step\_num}\cdot warmup\_steps^{-1.5}) \tag{3}\]"
        ),
        source_ref="arxiv://paper/pdf",
        metadata={"parse_source": "nougat_mmd", "equation_number": "3"},
    )
    page_texts = [
        PageTextEvidence(
            page=8,
            native_text=(
                "The learning rate schedule uses lrate d model step num "
                "warmup steps during optimization."
            ),
            selected_text=(
                "The learning rate schedule uses lrate d model step num "
                "warmup steps during optimization."
            ),
            selected_source="pymupdf_text",
            native_chars=90,
            native_words=14,
        )
    ]

    attached = _attach_equation_positions([equation], [], page_texts)

    assert attached[0].page == 8
    assert attached[0].metadata["position_source"] == "pymupdf_text_search"
    assert attached[0].metadata["position_match_strategy"] == "equation_token_overlap"
    assert attached[0].metadata["position_match_score"] > 0.6
    assert attached[0].metadata["source_locator"] == "arxiv://paper/pdf#page=8"


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


def test_run_nougat_invokes_container_entrypoint_in_direct_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "business.research.document.pdf_compiler._project_root",
        lambda: str(tmp_path),
    )
    monkeypatch.setenv("NEWSROOM_NOUGAT_DIRECT", "1")
    commands = []
    work = tmp_path / ".newsroom" / "nougat"
    work.mkdir(parents=True)

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        assert kwargs["timeout"] == 3600
        (work / "paper.mmd").write_text(_SAMPLE_MMD, encoding="utf-8")
        return None

    with patch("business.research.document.pdf_compiler.subprocess.run", side_effect=fake_run):
        result = _run_nougat(b"%PDF placeholder", "paper")

    assert result == _SAMPLE_MMD
    cmd = commands[0]
    assert cmd[:2] == ["newsroom-nougat", "/workspace/.newsroom/nougat/paper.pdf"]
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


@patch("business.research.document.pdf_compiler._run_nougat", return_value=_MMD_WITH_TWO_SECTIONS)
def test_pdf_parser_attaches_section_page_bounds(mock_nougat):
    pdf_bytes = _make_pdf([
        "1 Introduction\nUnique introduction phrase appears on the first page.",
        "2 Method\nDistinct method phrase appears on the second page.",
    ])

    doc = PdfDocumentParser().parse("2501_sections", pdf_bytes)

    by_title = {section.title: section for section in doc.sections}
    assert by_title["1 Introduction"].page_start == 1
    assert by_title["1 Introduction"].page_end == 1
    assert by_title["1 Introduction"].metadata["source_locator"] == "arxiv://2501_sections/pdf#page=1"
    assert by_title["1 Introduction"].metadata["page_match_strategy"] == "title+body_exact"
    assert by_title["2 Method"].page_start == 2
    assert by_title["2 Method"].page_end == 2
    assert by_title["2 Method"].metadata["source_locator"] == "arxiv://2501_sections/pdf#page=2"
    assert doc.metadata["parse_quality"]["sections"]["with_page_bounds"] == 2
    assert doc.metadata["parse_quality"]["sections"]["with_source_locator"] == 2


@patch("business.research.document.pdf_compiler._run_nougat", return_value=_MMD_WITH_PREAMBLE_AND_SECTION)
def test_pdf_parser_keeps_same_page_section_bounds_tight(mock_nougat):
    pdf_bytes = _make_pdf([
        (
            "Abstract\nUnique abstract phrase appears on the first page.\n"
            "1 Introduction\nUnique introduction phrase also starts on the first page."
        ),
        "2 Method\nDistinct method phrase appears on the second page.",
    ])

    doc = PdfDocumentParser().parse("2501_same_page_sections", pdf_bytes)

    by_title = {section.title: section for section in doc.sections}
    assert by_title["Abstract"].page_start == 1
    assert by_title["Abstract"].page_end == 1
    assert by_title["1 Introduction"].page_start == 1
    assert by_title["1 Introduction"].page_end == 1
    assert by_title["2 Method"].page_start == 2
    assert by_title["2 Method"].page_end == 2


@patch("business.research.document.pdf_compiler._extract_pdf_images")
@patch(
    "business.research.document.pdf_compiler._extract_surya_layout_artifacts",
    return_value=SuryaLayoutArtifacts(
        figure_images=[
            FigureImageRef(
                image_ref="figures/surya_p001_fig001.png",
                page=1,
                metadata={"image_source": "surya_layout", "bbox": [0.1, 0.2, 0.8, 0.7]},
            )
        ],
        table_images=[],
        layout_ref="surya_layout.json",
        region_count=1,
    ),
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
    assert doc.metadata["surya_layout_ref"] == "surya_layout.json"
    assert doc.metadata["surya_layout_regions"] == 1
    assert doc.metadata["parse_quality"]["figures"]["with_image"] == 1
    assert doc.metadata["parse_quality"]["figures"]["alignment_strategies"] == {
        "layout_order": 1
    }
    assert doc.figures[0].image_ref == "figures/surya_p001_fig001.png"
    assert doc.figures[0].page == 1
    assert doc.figures[0].metadata["image_source"] == "surya_layout"
    assert doc.figures[0].metadata["figure_number"] == 1
    assert doc.figures[0].metadata["source_locator"] == "arxiv://2501_surya_fig/pdf#page=1"


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
    "business.research.document.pdf_compiler._extract_surya_layout_artifacts",
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


@patch(
    "business.research.document.pdf_compiler._extract_surya_layout_artifacts",
    return_value=SuryaLayoutArtifacts(
        figure_images=[],
        table_images=[
            FigureImageRef(
                image_ref="tables/surya_table_p002_001.png",
                page=2,
                metadata={
                    "image_source": "surya_table_layout",
                    "bbox": [100, 200, 900, 400],
                    "layout_label": "table",
                    "pdf_rect": [61.2, 158.4, 550.8, 316.8],
                },
            )
        ],
        layout_ref="surya_layout.json",
        region_count=1,
    ),
)
@patch("business.research.document.pdf_compiler._run_nougat", return_value=_MMD_WITH_TABLE)
def test_pdf_parser_attaches_surya_table_images(
    mock_nougat,
    mock_surya_artifacts,
):
    pdf_bytes = _make_pdf(["placeholder"])
    doc = PdfDocumentParser().parse("2501_table", pdf_bytes)

    assert len(doc.tables) == 1
    assert doc.metadata["table_images"] == 1
    assert doc.metadata["parse_quality"]["tables"]["with_image"] == 1
    assert doc.tables[0].page == 2
    assert doc.tables[0].metadata["image_ref"] == "tables/surya_table_p002_001.png"
    assert doc.tables[0].metadata["image_source"] == "surya_table_layout"
    assert doc.tables[0].metadata["bbox"] == [100, 200, 900, 400]
    assert doc.tables[0].metadata["layout_label"] == "table"
    assert doc.tables[0].metadata["source_locator"] == (
        "arxiv://2501_table/pdf#page=2&pdf_rect=61.200,158.400,550.800,316.800"
    )


@patch(
    "business.research.document.pdf_visual_sidecar._extract_page_text_evidence",
    return_value=[
        PageTextEvidence(
            page=1,
            native_text="Figure 1: Model architecture\nTable 1: Results",
            selected_text="Figure 1: Model architecture\nTable 1: Results",
            selected_source="pymupdf_text",
            native_chars=44,
            native_words=7,
        )
    ],
)
@patch(
    "business.research.document.pdf_visual_sidecar._extract_surya_layout_artifacts",
    return_value=SuryaLayoutArtifacts(
        figure_images=[
            FigureImageRef(
                image_ref="figures/surya_p001_fig001.png",
                page=1,
                metadata={
                    "image_source": "surya_layout",
                    "bbox": [100, 100, 900, 400],
                    "pdf_rect": [61.2, 79.2, 550.8, 316.8],
                },
            )
        ],
        table_images=[
            FigureImageRef(
                image_ref="tables/surya_table_p001_001.png",
                page=1,
                metadata={
                    "image_source": "surya_table_layout",
                    "bbox": [100, 450, 900, 650],
                    "pdf_rect": [61.2, 356.4, 550.8, 514.8],
                    "table_text": "Model  Score\nours  0.91\nbase  0.83",
                    "table_text_source": "pymupdf_bbox",
                },
            )
        ],
        layout_ref="surya_layout.json",
        region_count=2,
    ),
)
def test_pdf_visual_sidecar_merges_visual_refs_into_latex_document(
    mock_surya_artifacts,
    mock_page_text,
) -> None:
    source_ref = "arxiv://2501.00001/latex"
    doc = ResearchDocument(
        paper_id="2501.00001",
        source_hash="hash",
        sections=[
            ResearchSection(
                section_id="sec-intro",
                title="Introduction",
                text="Figure 1 and Table 1 summarize the method.",
                source_ref=source_ref,
            )
        ],
        figures=[
            ResearchFigure(
                figure_id="fig-1",
                caption="Model architecture",
                source_ref=source_ref,
                metadata={"figure_number": 1},
            )
        ],
        tables=[
            ResearchTable(
                table_id="tbl-1",
                caption="Results",
                source_ref=source_ref,
                metadata={"table_number": 1},
            )
        ],
        lineage=SourceLineage(source_refs=[source_ref], source_hash="hash"),
        metadata={"parse_source": "latex"},
    )

    merged = merge_pdf_visual_sidecar(doc, _make_pdf(["placeholder"]), paper_id="2501.00001")

    assert merged.lineage.source_refs == ["arxiv://2501.00001/latex", "arxiv://2501.00001/pdf"]
    assert merged.figures[0].source_ref == "arxiv://2501.00001/pdf"
    assert merged.figures[0].image_ref == "figures/surya_p001_fig001.png"
    assert merged.figures[0].page == 1
    assert merged.figures[0].metadata["source_locator"] == (
        "arxiv://2501.00001/pdf#page=1&pdf_rect=61.200,79.200,550.800,316.800"
    )
    assert merged.tables[0].source_ref == "arxiv://2501.00001/pdf"
    assert merged.tables[0].metadata["image_ref"] == "tables/surya_table_p001_001.png"
    assert merged.tables[0].rows == [
        {"Model": "ours", "Score": "0.91"},
        {"Model": "base", "Score": "0.83"},
    ]
    assert merged.metadata["pdf_sidecar_visual_merged_figures"] == 1
    assert merged.metadata["pdf_sidecar_visual_merged_tables"] == 1
    assert merged.metadata["parse_quality"]["figures"]["with_image"] == 1
    assert merged.metadata["parse_quality"]["tables"]["with_image"] == 1


@patch(
    "business.research.document.pdf_compiler._extract_surya_layout_artifacts",
    return_value=SuryaLayoutArtifacts(
        figure_images=[],
        table_images=[
            FigureImageRef(
                image_ref="tables/surya_table_p002_001.png",
                page=2,
                metadata={
                    "image_source": "surya_table_layout",
                    "bbox": [100, 200, 900, 400],
                    "layout_label": "table",
                    "table_text": "Name  Score\nu-net  0.92\nbaseline  0.83",
                    "table_text_source": "pymupdf_bbox",
                },
            )
        ],
        layout_ref="surya_layout.json",
        region_count=1,
    ),
)
@patch("business.research.document.pdf_compiler._run_nougat", return_value=_MMD_WITH_TABLE_CAPTION_ONLY)
def test_pdf_parser_builds_table_rows_from_bbox_text_when_mmd_has_no_tabular(
    mock_nougat,
    mock_surya_artifacts,
):
    pdf_bytes = _make_pdf(["placeholder"])

    doc = PdfDocumentParser().parse("2501_table_text", pdf_bytes)

    assert doc.tables[0].columns == ["Name", "Score"]
    assert doc.tables[0].rows == [
        {"Name": "u-net", "Score": "0.92"},
        {"Name": "baseline", "Score": "0.83"},
    ]
    assert doc.tables[0].metadata["table_structure_source"] == "pymupdf_bbox_text"
    assert doc.tables[0].metadata["table_text_source"] == "pymupdf_bbox"


@patch(
    "business.research.document.pdf_compiler._extract_surya_layout_artifacts",
    return_value=SuryaLayoutArtifacts(
        figure_images=[],
        table_images=[
            FigureImageRef(
                image_ref="tables/surya_table_p002_001.png",
                page=2,
                metadata={
                    "image_source": "surya_table_layout",
                    "layout_label": "table",
                    "table_columns": ["Name", "Score"],
                    "table_rows": [
                        {"Name": "u-net", "Score": "0.92"},
                        {"Name": "baseline", "Score": "0.83"},
                    ],
                    "table_structure_source": "pymupdf_word_bbox",
                    "table_text": "this should not be needed",
                },
            )
        ],
        layout_ref="surya_layout.json",
        region_count=1,
    ),
)
@patch("business.research.document.pdf_compiler._run_nougat", return_value=_MMD_WITH_TABLE_CAPTION_ONLY)
def test_pdf_parser_prefers_structured_table_metadata_over_text_fallback(
    mock_nougat,
    mock_surya_artifacts,
):
    pdf_bytes = _make_pdf(["placeholder"])

    doc = PdfDocumentParser().parse("2501_table_words", pdf_bytes)

    assert doc.tables[0].columns == ["Name", "Score"]
    assert doc.tables[0].rows == [
        {"Name": "u-net", "Score": "0.92"},
        {"Name": "baseline", "Score": "0.83"},
    ]
    assert doc.tables[0].metadata["table_structure_source"] == "pymupdf_word_bbox"


@patch(
    "business.research.document.pdf_compiler._extract_surya_layout_artifacts",
    return_value=SuryaLayoutArtifacts(
        figure_images=[],
        table_images=[],
        layout_ref="surya_layout.json",
        region_count=0,
    ),
)
@patch("business.research.document.pdf_compiler._ocr_page", return_value="Recovered OCR text from page two.")
@patch("business.research.document.pdf_compiler._run_nougat", return_value=_MMD_WITH_MISSING_PAGE)
def test_pdf_parser_ocr_fallback_for_missing_nougat_page(
    mock_nougat,
    mock_ocr,
    mock_surya_artifacts,
    monkeypatch,
):
    monkeypatch.setenv("SURYA_INFERENCE_URL", "http://surya.test/v1")
    pdf_bytes = _make_pdf(["This page has native text. " * 10, ""])

    doc = PdfDocumentParser().parse("2501_missing_page", pdf_bytes)

    mock_ocr.assert_called_once()
    assert doc.metadata["nougat_missing_pages"] == [2]
    assert doc.metadata["ocr_used"] is True
    assert doc.metadata["ocr_attempted_pages"] == [2]
    assert doc.metadata["ocr_pages"] == [2]
    assert doc.metadata["text_fallback_pages"] == [2]
    assert any(section.title == "OCR Page 2" for section in doc.sections)
    fallback = next(section for section in doc.sections if section.title == "OCR Page 2")
    assert fallback.text == "Recovered OCR text from page two."
    assert fallback.metadata["fallback_reason"] == "nougat_missing_page"


@patch(
    "business.research.document.pdf_compiler._extract_surya_layout_artifacts",
    return_value=SuryaLayoutArtifacts(
        figure_images=[],
        table_images=[],
        layout_ref="surya_layout.json",
        region_count=0,
    ),
)
@patch("business.research.document.pdf_compiler._ocr_page", return_value="OCR text from a sparse native page.")
@patch("business.research.document.pdf_compiler._run_nougat", return_value="# Intro\n\nParsed content.")
def test_pdf_parser_ocr_fallback_for_low_native_text_page(
    mock_nougat,
    mock_ocr,
    mock_surya_artifacts,
    monkeypatch,
):
    monkeypatch.setenv("SURYA_INFERENCE_URL", "http://surya.test/v1")
    pdf_bytes = _make_pdf(["tiny"])

    doc = PdfDocumentParser().parse("2501_low_text", pdf_bytes)

    mock_ocr.assert_called_once()
    assert doc.metadata["low_native_text_pages"] == [1]
    assert doc.metadata["ocr_attempted_pages"] == [1]
    assert doc.metadata["ocr_pages"] == [1]
    assert doc.metadata["text_fallback_pages"] == [1]
    fallback = next(section for section in doc.sections if section.title == "OCR Page 1")
    assert fallback.text == "OCR text from a sparse native page."
    assert fallback.metadata["fallback_reason"] == "low_native_text"


@patch(
    "business.research.document.pdf_compiler._extract_surya_layout_artifacts",
    return_value=SuryaLayoutArtifacts(
        figure_images=[],
        table_images=[],
        layout_ref="surya_layout.json",
        region_count=1,
        regions=[
            {
                "page": 4,
                "index": 6,
                "label": "equation-block",
                "bbox": [327.0, 497.0, 787.0, 537.0],
                "bbox_coordinate_system": "surya_1000",
                "pdf_rect": [192.1, 385.6, 489.6, 433.3],
            }
        ],
    ),
)
@patch("business.research.document.pdf_compiler._run_nougat", return_value=_MMD_WITH_DISPLAY_MATH)
def test_pdf_parser_attaches_surya_equation_positions(
    mock_nougat,
    mock_surya_artifacts,
):
    pdf_bytes = _make_pdf(["placeholder"])

    doc = PdfDocumentParser().parse("2501_equation_layout", pdf_bytes)

    assert len(doc.equations) == 1
    assert doc.equations[0].page == 4
    assert doc.equations[0].metadata["position_source"] == "surya_equation_layout"
    assert doc.metadata["parse_quality"]["equations"]["with_bbox"] == 1
    assert doc.metadata["parse_quality"]["equations"]["position_sources"] == {
        "surya_equation_layout": 1
    }
    assert doc.equations[0].metadata["bbox"] == [327.0, 497.0, 787.0, 537.0]
    assert doc.equations[0].metadata["pdf_rect"] == [192.1, 385.6, 489.6, 433.3]
    assert doc.equations[0].metadata["source_locator"] == (
        "arxiv://2501_equation_layout/pdf#page=4&pdf_rect=192.100,385.600,489.600,433.300"
    )


# ── ArxivDocumentParser dispatcher ───────────────────────────────────────────


@patch("business.research.document.pdf_compiler._run_nougat", return_value=_SAMPLE_MMD)
def test_pdf_parser_writes_parse_artifact_bundle(mock_nougat, monkeypatch, tmp_path):
    artifact_root = tmp_path / ".newsroom" / "runs"
    monkeypatch.setenv("NEWS_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("NEWSROOM_PDF_WRITE_ARTIFACTS", "1")
    pdf_bytes = _make_pdf(["Introduction\n\nDeep learning has advanced many fields."])

    doc = PdfDocumentParser().parse("2501_artifacts", pdf_bytes)

    paper_dir = tmp_path / ".newsroom" / "papers" / "2501_artifacts"
    expected_files = {
        "research_document.json",
        "sections.md",
        "parse_summary.txt",
        "nougat.mmd",
        "figures.json",
        "tables.json",
        "equations.json",
    }
    assert {path.name for path in paper_dir.iterdir()} >= expected_files

    payload = json.loads((paper_dir / "research_document.json").read_text(encoding="utf-8"))
    assert payload["paper_id"] == "2501_artifacts"
    assert payload["metadata"]["parse_quality"]["sections"]["total"] == len(doc.sections)
    assert payload["metadata"]["parse_artifacts"]["research_document"].endswith(
        "research_document.json"
    )
    assert "Introduction" in (paper_dir / "sections.md").read_text(encoding="utf-8")
    assert "figures: total=1" in (paper_dir / "parse_summary.txt").read_text(encoding="utf-8")
    assert (paper_dir / "nougat.mmd").read_text(encoding="utf-8").strip() == _SAMPLE_MMD.strip()


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


def test_marker_pdf_parser_converts_json_blocks(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWSROOM_PARSER_RUN_ROOT", str(tmp_path / "parser-runs"))
    monkeypatch.setenv("NEWS_ARTIFACT_ROOT", str(tmp_path / ".newsroom" / "runs"))

    def fake_run(command, *, timeout_seconds):
        assert command[:7] == ["docker", "run", "--rm", "--gpus", "all", "-e", "TORCH_DEVICE=cuda"]
        output_dir = Path(command[command.index("-v", command.index("-v") + 1) + 1].rsplit(":", 1)[0])
        image_path = output_dir / "figure.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"png")
        _write_marker_json(
            output_dir,
            {
                "children": [
                    {
                        "block_type": "SectionHeader",
                        "text": "Introduction",
                        "page": 1,
                        "polygon": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.15], [0.1, 0.15]],
                    },
                    {"block_type": "Text", "text": "This paper studies parser backends.", "page": 1},
                    {
                        "block_type": "Equation",
                        "latex": "E=mc^2",
                        "page": 1,
                        "polygon": [[0.1, 0.2], [0.4, 0.2], [0.4, 0.25], [0.1, 0.25]],
                    },
                    {
                        "block_type": "Figure",
                        "caption": "Figure 1: Overview.",
                        "image_path": "figure.png",
                        "page": 1,
                        "polygon": [[0.1, 0.3], [0.6, 0.3], [0.6, 0.7], [0.1, 0.7]],
                    },
                    {
                        "block_type": "Table",
                        "caption": "Table 1: Scores.",
                        "page": 1,
                        "polygon": [[0.1, 0.75], [0.6, 0.75], [0.6, 0.95], [0.1, 0.95]],
                        "rows": [["Model", "Score"], ["baseline", "0.8"]],
                    },
                ]
            },
        )

    monkeypatch.setattr(
        "business.research.document.marker_pdf_parser.run_docker_command",
        fake_run,
    )
    pdf_bytes = _make_pdf(["Introduction\nThis paper studies parser backends."])

    doc = MarkerPdfDocumentParser().parse("2501_marker", pdf_bytes)

    assert doc.metadata["parse_source"] == "marker"
    assert doc.metadata["parser_backend"] == "marker"
    assert len(doc.sections) == 1
    assert doc.sections[0].title == "Introduction"
    assert len(doc.equations) == 1
    assert doc.equations[0].metadata["source_locator"].startswith("arxiv://2501_marker/pdf#page=1")
    assert len(doc.figures) == 1
    assert Path(doc.figures[0].image_ref).exists()
    assert len(doc.tables) == 1
    assert doc.tables[0].columns == ["Model", "Score"]
    assert doc.tables[0].rows == [{"Model": "baseline", "Score": "0.8"}]
    assert doc.metadata["parse_quality"]["figures"]["with_bbox"] == 1


def test_dispatcher_can_select_marker_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWSROOM_PARSER_RUN_ROOT", str(tmp_path / "parser-runs"))

    def fake_run(command, *, timeout_seconds):
        output_dir = Path(command[command.index("-v", command.index("-v") + 1) + 1].rsplit(":", 1)[0])
        _write_marker_json(
            output_dir,
            {
                "children": [
                    {"block_type": "SectionHeader", "text": "Abstract", "page": 1},
                    {"block_type": "Text", "text": "Parsed by Marker.", "page": 1},
                ]
            },
        )

    monkeypatch.setattr(
        "business.research.document.marker_pdf_parser.run_docker_command",
        fake_run,
    )

    doc = ArxivDocumentParser(pdf_parser_backend="marker").parse(
        "2501_dispatch_marker",
        _make_pdf(["Parsed by Marker."]),
    )

    assert doc.metadata["parse_source"] == "marker"


def test_pdf_parser_backend_name_rejects_unknown_marker_branch_backend():
    with pytest.raises(ValueError, match="NEWSROOM_PDF_PARSER_BACKEND"):
        pdf_parser_backend_name("mineru")


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


def test_latex_parser_extracts_includegraphics_image(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWS_ARTIFACT_ROOT", str(tmp_path / ".newsroom" / "runs"))
    tex = (
        r"\documentclass{article}"
        r"\begin{document}"
        r"\section{Method}"
        r"\begin{figure}"
        r"\includegraphics[width=\linewidth]{figures/arch}"
        r"\caption{Architecture overview.}"
        r"\label{fig:arch}"
        r"\end{figure}"
        r"\end{document}"
    )
    image_bytes = b"\x89PNG\r\n\x1a\n" + (b"x" * 1200)
    tgz = _make_latex_targz_with_files(tex, {"figures/arch.png": image_bytes})

    doc = ArxivDocumentParser().parse("2501_latex_image", tgz)

    assert len(doc.figures) == 1
    assert doc.figures[0].image_ref
    assert Path(doc.figures[0].image_ref).exists()
    assert Path(doc.figures[0].image_ref).name == "arch.png"
