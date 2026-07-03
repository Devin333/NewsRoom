from __future__ import annotations

import os
from typing import Literal

from business.research.document.pdf_compiler import PdfDocumentParser
from business.research.domain.document import ResearchDocument

PdfParserBackendName = Literal["nougat", "mineru", "marker"]


def pdf_parser_backend_name(value: str | None = None) -> PdfParserBackendName:
    raw = (value or os.environ.get("NEWSROOM_PDF_PARSER_BACKEND") or "nougat").strip().lower()
    if raw in {"", "nougat", "default"}:
        return "nougat"
    if raw == "mineru":
        return "mineru"
    if raw == "marker":
        return "marker"
    raise ValueError(
        "NEWSROOM_PDF_PARSER_BACKEND must be one of: nougat, mineru, marker"
    )


def build_pdf_document_parser(
    backend: str | None = None,
) -> "PdfDocumentParser | MinerUPdfDocumentParser | MarkerPdfDocumentParser":
    name = pdf_parser_backend_name(backend)
    if name == "mineru":
        from business.research.document.mineru_pdf_parser import MinerUPdfDocumentParser

        return MinerUPdfDocumentParser()
    if name == "marker":
        from business.research.document.marker_pdf_parser import MarkerPdfDocumentParser

        return MarkerPdfDocumentParser()
    return PdfDocumentParser()


class PdfBackendDocumentParser:
    """Small adapter used by tests and ingest call sites that only parse PDFs."""

    def __init__(self, backend: str | None = None) -> None:
        self._parser = build_pdf_document_parser(backend)

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        return self._parser.parse(paper_id, source_bytes)


__all__ = [
    "PdfBackendDocumentParser",
    "PdfParserBackendName",
    "build_pdf_document_parser",
    "pdf_parser_backend_name",
]
