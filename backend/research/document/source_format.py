from __future__ import annotations

import gzip
import logging
from enum import Enum

_log = logging.getLogger(__name__)


class SourceFormat(str, Enum):
    PDF     = "pdf"      # raw PDF or gzip-wrapped PDF
    LATEX   = "latex"    # arXiv tar.gz / single .tex.gz / raw .tex
    HTML    = "html"     # web page
    ZIP     = "zip"      # zip archive (non-arXiv submission, datasets, etc.)
    UNKNOWN = "unknown"  # unrecognised format


_PDF_MAGIC   = b"%PDF"
_GZIP_MAGIC  = b"\x1f\x8b"
_ZIP_MAGIC   = b"PK\x03\x04"
_HTML_TAGS   = (b"<!doctype", b"<html")
_TAR_MAGIC_OFFSET = 257
_TAR_MAGIC = b"ustar"


def _sniff(data: bytes) -> SourceFormat:
    normalized = data.lstrip()
    head = normalized[:16].lower()
    if normalized[:4] == _PDF_MAGIC:
        return SourceFormat.PDF
    if normalized[:4] == _ZIP_MAGIC:
        return SourceFormat.ZIP
    if len(data) >= _TAR_MAGIC_OFFSET + len(_TAR_MAGIC) and data[_TAR_MAGIC_OFFSET:_TAR_MAGIC_OFFSET + len(_TAR_MAGIC)] == _TAR_MAGIC:
        return SourceFormat.LATEX
    if any(head.startswith(t) for t in _HTML_TAGS):
        return SourceFormat.HTML
    # Plain text LaTeX is intentionally accepted, but arbitrary binary input
    # must remain unsupported so the application can report a real format
    # diagnostic instead of attempting a misleading parse.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return SourceFormat.UNKNOWN
    if not text.strip():
        return SourceFormat.UNKNOWN
    # Keep the historical plain-text fallback for compatibility with raw
    # source fixtures; only non-text bytes are rejected as UNKNOWN.
    return SourceFormat.LATEX


def detect_source_format(data: bytes) -> tuple[SourceFormat, bytes]:
    """Detect arXiv source package format from magic bytes.

    Returns (format, canonical_bytes):
    - PDF:   canonical_bytes is raw PDF bytes (gzip wrapper stripped).
    - LATEX: canonical_bytes is the original bytes unchanged.
    - HTML / ZIP / UNKNOWN: canonical_bytes is the original bytes.
    """
    if data[:2] == _GZIP_MAGIC:
        try:
            inner = gzip.decompress(data)
            fmt = _sniff(inner)
            if fmt is SourceFormat.PDF:
                return SourceFormat.PDF, inner
            if fmt is SourceFormat.LATEX:
                return SourceFormat.LATEX, data
            # gzip-wrapped tar / single .tex — keep original so LatexSourceParser
            # can handle its own tar/gzip decompression
        except Exception as exc:
            _log.debug("gzip decompress failed for source package: %s", exc)
    return _sniff(data), data


__all__ = ["SourceFormat", "detect_source_format"]
