"""
Integration test: fetch arXiv LaTeX source → compile → chunk → verify.
Uses "Attention Is All You Need" (1706.03762) as a real-world fixture.
Requires explicit NEWS_RUN_LIVE_RESEARCH_E2E opt-in.
"""
from __future__ import annotations

import os

import pytest

from business.research.document.chunker import PaperDocumentChunker
from business.research.document.latex_compiler import ArxivLatexDocumentCompiler
from business.research.domain.paper import PaperSourceRecord

ARXIV_ID = "1706.03762"
_RUN_LIVE_E2E = os.getenv("NEWS_RUN_LIVE_RESEARCH_E2E", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

pytestmark = [
    pytest.mark.live_research_e2e,
    pytest.mark.skipif(
        not _RUN_LIVE_E2E,
        reason="set NEWS_RUN_LIVE_RESEARCH_E2E=1 to run live arXiv LaTeX tests",
    ),
]

SOURCE = PaperSourceRecord(
    source_id="arxiv-1706.03762",
    paper_id="arxiv-1706.03762",
    source_type="arxiv",
    source_url=f"https://arxiv.org/abs/{ARXIV_ID}",
)


def _fetch_doc():
    compiler = ArxivLatexDocumentCompiler()
    return compiler.compile(SOURCE)


@pytest.fixture(scope="module")
def arxiv_doc():
    try:
        return _fetch_doc()
    except Exception as exc:
        pytest.skip(f"arXiv fetch failed (network?): {exc}")


@pytest.fixture(scope="module")
def chunks(arxiv_doc):
    return PaperDocumentChunker().chunk(arxiv_doc, "latex")


# ── document structure ────────────────────────────────────────────────────────

def test_document_has_sections(arxiv_doc):
    assert len(arxiv_doc.sections) >= 4, "expected ≥4 sections (abstract + main body)"


def test_document_has_equations(arxiv_doc):
    assert arxiv_doc.equations, "Attention paper should have equations"


def test_document_has_figures(arxiv_doc):
    assert arxiv_doc.figures, "Attention paper should have figures"


def test_parse_source_is_latex(arxiv_doc):
    assert arxiv_doc.metadata.get("parse_source") == "latex"


# ── chunker output ────────────────────────────────────────────────────────────

def test_chunks_produced(chunks):
    assert len(chunks) >= 10, f"expected ≥10 chunks, got {len(chunks)}"


def test_structure_detected(chunks):
    assert all(c.structure_detected for c in chunks), "all chunks should have structure_detected=True"


def test_abstract_chunk_present(chunks):
    assert any(c.chunk_type == "abstract" for c in chunks)


def test_method_role_present(chunks):
    assert any("method" in c.section_role for c in chunks)


def test_experiment_role_present(chunks):
    assert any("experiment" in c.section_role for c in chunks)


def test_parent_child_hierarchy(chunks):
    parent_ids = {c.chunk_id for c in chunks if c.metadata.get("is_parent")}
    for child in [c for c in chunks if c.parent_chunk_id]:
        assert child.parent_chunk_id in parent_ids


def test_formula_chunks_flagged(chunks):
    # Attention paper has equations; at least one chunk should be flagged
    assert any(c.has_formula for c in chunks)


def test_parse_source_propagated(chunks):
    assert all(c.parse_source == "latex" for c in chunks)


def test_no_empty_content(chunks):
    assert all(c.content.strip() for c in chunks), "no chunk should have empty content"


def test_print_summary(chunks, capsys):
    """Print a readable summary (always passes, useful for manual inspection)."""
    from collections import Counter
    roles = Counter(r for c in chunks for r in c.section_role)
    types = Counter(c.chunk_type for c in chunks)
    parents = sum(1 for c in chunks if c.metadata.get("is_parent"))
    print(f"\n=== Chunk summary for {ARXIV_ID} ===")
    print(f"  total chunks : {len(chunks)}")
    print(f"  parents      : {parents}")
    print(f"  types        : {dict(types)}")
    print(f"  roles        : {dict(roles)}")
    print(f"  has_formula  : {sum(c.has_formula for c in chunks)}")
    print(f"  has_figure   : {sum(c.has_figure for c in chunks)}")
