from __future__ import annotations

import gzip
from enum import Enum


class SourceFormat(str, Enum):
    LATEX = "latex"
    PDF = "pdf"


_PDF_MAGIC = b"%PDF"
_GZIP_MAGIC = b"\x1f\x8b"


def detect_source_format(data: bytes) -> tuple[SourceFormat, bytes]:
    """Detect arXiv source package format from magic bytes.

    Returns (format, canonical_bytes):
    - PDF:   canonical_bytes is raw PDF bytes (gzip wrapper is stripped).
    - LATEX: canonical_bytes is the original bytes unchanged; LatexSourceParser
             handles its own tar.gz / gzip decompression internally.
    """
    if data[:2] == _GZIP_MAGIC:
        try:
            inner = gzip.decompress(data)
            if inner[:4] == _PDF_MAGIC:
                return SourceFormat.PDF, inner
        except Exception:
            pass  # corrupt gzip; let LaTeX parser try
    if data[:4] == _PDF_MAGIC:
        return SourceFormat.PDF, data
    return SourceFormat.LATEX, data


__all__ = ["SourceFormat", "detect_source_format"]
