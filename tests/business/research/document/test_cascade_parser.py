from __future__ import annotations

import gzip

import fitz
import pytest

from business.research.document.cascade_parser import (
    CascadeArxivDocumentParser,
    CascadeDocumentParser,
    DocumentQualityProbe,
    PyMuPDFTextDocumentParser,
    parser_cascade_backend_names,
)
from business.research.domain.common import SourceLineage
from business.research.domain.document import ResearchDocument, ResearchSection


class _Parser:
    def __init__(self, document: ResearchDocument | None = None, exc: Exception | None = None) -> None:
        self.document = document
        self.exc = exc
        self.calls = 0

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        assert self.document is not None
        return self.document.model_copy(update={"paper_id": paper_id})


class _LatexParser:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        self.calls += 1
        return _doc(paper_id, "latex", sections=3, chars=120)


def _doc(
    paper_id: str,
    backend: str,
    *,
    sections: int,
    chars: int,
) -> ResearchDocument:
    text = "x" * chars
    source_ref = f"arxiv://{paper_id}/pdf"
    return ResearchDocument(
        paper_id=paper_id,
        source_hash="hash",
        sections=[
            ResearchSection(
                section_id=f"{backend}-s{index}",
                title=f"Section {index}",
                text=text,
                source_ref=source_ref,
                metadata={"parse_source": backend, "source_locator": source_ref},
            )
            for index in range(sections)
        ],
        lineage=SourceLineage(source_refs=[source_ref], source_hash="hash"),
        metadata={"parse_source": backend, "parser_backend": backend},
    )


def _pdf(text_pages: list[str]) -> bytes:
    doc = fitz.open()
    for text in text_pages:
        page = doc.new_page()
        page.insert_text((50, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _probe() -> DocumentQualityProbe:
    return DocumentQualityProbe(
        min_sections=2,
        min_body_chars=100,
        min_non_empty_section_ratio=0.5,
        max_replacement_char_ratio=0.2,
    )


def test_cascade_returns_first_backend_when_quality_passes() -> None:
    first = _Parser(_doc("paper-1", "mineru", sections=2, chars=80))
    second = _Parser(_doc("paper-1", "marker", sections=2, chars=80))
    parser = CascadeDocumentParser([("mineru", first), ("marker", second)], probe=_probe())

    doc = parser.parse("paper-1", b"%PDF-1.7")

    assert doc.metadata["parse_source"] == "mineru"
    assert doc.metadata["parser_cascade"]["used_backend"] == "mineru"
    assert doc.metadata["parser_cascade"]["attempts"][0]["status"] == "success"
    assert second.calls == 0


def test_cascade_falls_through_after_parse_error() -> None:
    first = _Parser(exc=RuntimeError("boom"))
    second = _Parser(_doc("paper-1", "marker", sections=2, chars=80))
    parser = CascadeDocumentParser([("mineru", first), ("marker", second)], probe=_probe())

    doc = parser.parse("paper-1", b"%PDF-1.7")

    attempts = doc.metadata["parser_cascade"]["attempts"]
    assert doc.metadata["parse_source"] == "marker"
    assert attempts[0]["backend"] == "mineru"
    assert attempts[0]["status"] == "parse_error"
    assert "RuntimeError: boom" in attempts[0]["reason"]
    assert attempts[1]["backend"] == "marker"
    assert attempts[1]["status"] == "success"


def test_cascade_falls_through_after_quality_rejection() -> None:
    first = _Parser(_doc("paper-1", "mineru", sections=1, chars=10))
    second = _Parser(_doc("paper-1", "marker", sections=2, chars=80))
    parser = CascadeDocumentParser([("mineru", first), ("marker", second)], probe=_probe())

    doc = parser.parse("paper-1", b"%PDF-1.7")

    attempts = doc.metadata["parser_cascade"]["attempts"]
    assert doc.metadata["parse_source"] == "marker"
    assert attempts[0]["status"] == "quality_rejected"
    assert attempts[0]["reason"] == "sections_below_threshold"
    assert attempts[0]["quality"]["passed"] is False


def test_cascade_uses_pymupdf_fallback_after_all_attempts_fail() -> None:
    parser = CascadeDocumentParser(
        [
            ("mineru", _Parser(exc=RuntimeError("mineru failed"))),
            ("marker", _Parser(_doc("paper-1", "marker", sections=1, chars=5))),
        ],
        probe=_probe(),
    )

    doc = parser.parse("paper-1", _pdf(["Native text page one."]))

    attempts = doc.metadata["parser_cascade"]["attempts"]
    assert doc.metadata["parse_source"] == "pymupdf"
    assert doc.metadata["degraded"] is True
    assert attempts[-1]["backend"] == "pymupdf"
    assert attempts[-1]["status"] == "fallback"
    assert doc.sections[0].title == "PDF Text Page 1"


def test_pymupdf_fallback_extracts_gzipped_pdf_via_cascade_arxiv_parser() -> None:
    latex = _LatexParser()
    pdf_parser = CascadeDocumentParser(
        [("mineru", _Parser(exc=RuntimeError("down")))],
        probe=_probe(),
        fallback=PyMuPDFTextDocumentParser(),
    )
    parser = CascadeArxivDocumentParser(latex_parser=latex, pdf_parser=pdf_parser)

    doc = parser.parse("paper-1", gzip.compress(_pdf(["Gzipped PDF text."])))

    assert latex.calls == 0
    assert doc.metadata["parse_source"] == "pymupdf"
    assert "Gzipped PDF text." in doc.sections[0].text


def test_cascade_arxiv_parser_keeps_latex_routing() -> None:
    latex = _LatexParser()
    pdf_parser = CascadeDocumentParser(
        [("mineru", _Parser(exc=RuntimeError("should not run")))],
        probe=_probe(),
    )
    parser = CascadeArxivDocumentParser(latex_parser=latex, pdf_parser=pdf_parser)

    doc = parser.parse("paper-1", b"\\section{Intro} latex")

    assert latex.calls == 1
    assert doc.metadata["parse_source"] == "latex"


def test_parser_cascade_backend_names_validates_env(monkeypatch) -> None:
    monkeypatch.setenv("NEWSROOM_PDF_PARSER_CASCADE", "mineru,marker")

    assert parser_cascade_backend_names() == ("mineru", "marker")

    with pytest.raises(ValueError, match="mineru, marker, pymupdf"):
        parser_cascade_backend_names("docling")
