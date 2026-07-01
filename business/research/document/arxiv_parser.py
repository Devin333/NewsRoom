from __future__ import annotations

from business.research.domain.document import ResearchDocument
from business.research.document.latex_compiler import LatexSourceParser
from business.research.document.pdf_compiler import PdfDocumentParser
from business.research.document.pdf_parser_backend import build_pdf_document_parser
from business.research.document.source_format import SourceFormat, detect_source_format


class ArxivDocumentParser:
    """Implements DocumentParserPort for arXiv source packages.

    Detects the format of the raw bytes via magic-byte inspection, then routes
    to the appropriate parser:
      - LATEX  →  LatexSourceParser  (tar.gz / single .tex.gz / raw .tex)
      - PDF    →  PdfDocumentParser  (text extraction + surya OCR fallback)
    """

    def __init__(
        self,
        latex_parser: LatexSourceParser | None = None,
        pdf_parser: PdfDocumentParser | None = None,
        pdf_parser_backend: str | None = None,
    ) -> None:
        self._latex = latex_parser or LatexSourceParser()
        self._pdf = pdf_parser or build_pdf_document_parser(pdf_parser_backend)

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        fmt, canonical = detect_source_format(source_bytes)
        if fmt is SourceFormat.PDF:
            return self._pdf.parse(paper_id, canonical)
        if fmt in (SourceFormat.HTML, SourceFormat.ZIP, SourceFormat.UNKNOWN):
            raise NotImplementedError(
                f"ArxivDocumentParser does not support format '{fmt.value}' — "
                "add a dedicated parser for this source type."
            )
        return self._latex.parse(paper_id, source_bytes)


__all__ = ["ArxivDocumentParser"]
