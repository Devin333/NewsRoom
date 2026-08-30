from __future__ import annotations

from pathlib import Path


def test_framework_rag_has_no_research_imports_or_paper_parser_terms():
    root = Path("framework/rag")
    forbidden = (
        "backend.research",
        "PaperChunk",
        "arxiv",
        "Nougat",
        "Surya",
        "PDF",
    )

    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for term in forbidden:
            if term in text:
                offenders.append(f"{path}:{term}")

    assert offenders == []


def test_framework_harness_rag_has_no_research_imports():
    root = Path("framework/harness/rag")
    forbidden = ("backend.research",)

    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for term in forbidden:
            if term in text:
                offenders.append(f"{path}:{term}")

    assert offenders == []
