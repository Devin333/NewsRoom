"""Standalone diagnostic: fetch + parse + chunk an arXiv paper WITHOUT touching
Postgres/Qdrant.  Lets you eyeball the parse result (latex vs pymupdf path).

Usage:
    python scripts/diag_parse.py 1706.03762 2307.03109
"""
from __future__ import annotations

import sys

from framework.shared.env import load_root_env

from infrastructure.external.sources.arxiv import ArxivSourceConnector
from business.research.document.arxiv_parser import ArxivDocumentParser
from business.research.document.chunker import PaperDocumentChunker
from business.research.document.source_format import detect_source_format


def diagnose(arxiv_id: str) -> None:
    paper_id = arxiv_id.replace("/", "_")
    print(f"\n{'=' * 60}\n[{arxiv_id}]")

    fetcher = ArxivSourceConnector()
    pkg = fetcher.fetch_source_package(arxiv_id)
    fmt, canonical = detect_source_format(pkg.content)
    print(f"  raw bytes        : {len(pkg.content):,}")
    print(f"  detected format  : {fmt.value}  (canonical {len(canonical):,} bytes)")

    parser = ArxivDocumentParser()
    doc = parser.parse(paper_id, pkg.content)
    print(f"  parse_source     : {doc.metadata.get('parse_source')}")
    print(f"  ocr_used         : {doc.metadata.get('ocr_used', 'n/a')}")
    print(f"  sections         : {len(doc.sections)}")
    print(f"  figures          : {len(doc.figures)}")
    print(f"  equations        : {len(doc.equations)}")
    print(f"  tables           : {len(doc.tables)}")

    for s in doc.sections[:6]:
        preview = s.text[:80].replace("\n", " ")
        print(f"    - [{s.title[:40]:40s}] {preview}...")

    parse_source = doc.metadata.get("parse_source", "latex")
    chunks = PaperDocumentChunker().chunk(doc, parse_source)
    by_type: dict[str, int] = {}
    for c in chunks:
        by_type[c.chunk_type] = by_type.get(c.chunk_type, 0) + 1
    print(f"  chunks           : {len(chunks)}  {by_type}")
    print(f"  structure_detected: {any(c.structure_detected for c in chunks)}")


def main() -> int:
    load_root_env()
    ids = sys.argv[1:] or ["1706.03762"]
    for arxiv_id in ids:
        try:
            diagnose(arxiv_id)
        except Exception as exc:  # noqa: BLE001 - diagnostic, show everything
            import traceback
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            traceback.print_exc()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
