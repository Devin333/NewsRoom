from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from business.research.domain.common import SourceLineage
from business.research.domain.document import (
    ResearchDocument,
    ResearchFigure,
    ResearchSection,
    ResearchTable,
)
from business.research.rag.evaluation.paper_benchmark_ingest import ingest_benchmark_papers


@dataclass(frozen=True)
class _FakePackage:
    arxiv_id: str
    content: bytes


class _FakeFetcher:
    def fetch_source_package(self, arxiv_id: str) -> _FakePackage:
        return _FakePackage(arxiv_id=arxiv_id, content=b"\\section{Intro} hello")


class _FakePdfFetcher(_FakeFetcher):
    def fetch_pdf_package(self, arxiv_id: str) -> _FakePackage:
        return _FakePackage(arxiv_id=arxiv_id, content=b"%PDF-1.7\nfake pdf")


class _FakeParser:
    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        return ResearchDocument(
            paper_id=paper_id,
            source_hash="hash",
            sections=[
                ResearchSection(
                    section_id=f"{paper_id}-intro",
                    title="Introduction",
                    text="This paper has benchmark content.",
                    source_ref=f"arxiv://{paper_id}",
                )
            ],
            lineage=SourceLineage(source_refs=[f"arxiv://{paper_id}"], source_hash="hash"),
            metadata={"parse_source": "latex"},
        )


class _FakeVisualParser:
    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        source_ref = f"arxiv://{paper_id}/latex"
        return ResearchDocument(
            paper_id=paper_id,
            source_hash="hash",
            sections=[
                ResearchSection(
                    section_id=f"{paper_id}-intro",
                    title="Introduction",
                    text="Figure 1 and Table 1 summarize the result.",
                    source_ref=source_ref,
                )
            ],
            figures=[
                ResearchFigure(
                    figure_id="fig-1",
                    caption="Architecture",
                    source_ref=source_ref,
                )
            ],
            tables=[
                ResearchTable(
                    table_id="tbl-1",
                    caption="Results",
                    source_ref=source_ref,
                )
            ],
            lineage=SourceLineage(source_refs=[source_ref], source_hash="hash"),
            metadata={"parse_source": "latex"},
        )


def test_ingest_benchmark_papers_writes_documents_and_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"

    report = ingest_benchmark_papers(
        ["https://arxiv.org/abs/1706.03762", "1706.03762", "2006.11239"],
        papers_dir=tmp_path / "papers",
        manifest_path=manifest,
        fetcher=_FakeFetcher(),
        parser=_FakeParser(),
    )

    assert report.requested == 2
    assert report.succeeded == 2
    assert report.failed == 0
    assert (tmp_path / "papers" / "1706.03762" / "research_document.json").exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["succeeded"] == 2
    assert payload["items"][0]["parse_source"] == "latex"


def test_ingest_benchmark_papers_skips_existing_documents(tmp_path: Path) -> None:
    paper_dir = tmp_path / "papers" / "1706.03762"
    paper_dir.mkdir(parents=True)
    (paper_dir / "research_document.json").write_text("{}", encoding="utf-8")

    report = ingest_benchmark_papers(
        ["1706.03762"],
        papers_dir=tmp_path / "papers",
        fetcher=_FakeFetcher(),
        parser=_FakeParser(),
    )

    assert report.skipped == 1
    assert report.items[0].reason == "research_document_exists"


def test_ingest_benchmark_papers_force_overwrites_existing_document(tmp_path: Path) -> None:
    paper_dir = tmp_path / "papers" / "1706.03762"
    paper_dir.mkdir(parents=True)
    (paper_dir / "research_document.json").write_text('{"paper_id":"old"}', encoding="utf-8")

    report = ingest_benchmark_papers(
        ["1706.03762"],
        papers_dir=tmp_path / "papers",
        force=True,
        fetcher=_FakeFetcher(),
        parser=_FakeParser(),
    )

    payload = json.loads((paper_dir / "research_document.json").read_text(encoding="utf-8"))
    assert report.succeeded == 1
    assert payload["metadata"]["parse_source"] == "latex"
    assert payload["paper_id"] == "1706.03762"


def test_ingest_benchmark_papers_merges_pdf_sidecar_visuals(monkeypatch, tmp_path: Path) -> None:
    def fake_merge(document: ResearchDocument, pdf_bytes: bytes, *, paper_id: str) -> ResearchDocument:
        assert pdf_bytes.startswith(b"%PDF")
        figures = [
            document.figures[0].model_copy(update={
                "image_ref": "figures/fig1.png",
                "page": 1,
                "metadata": {"image_ref": "figures/fig1.png"},
            })
        ]
        tables = [
            document.tables[0].model_copy(update={
                "page": 1,
                "metadata": {"image_ref": "tables/table1.png"},
            })
        ]
        return document.model_copy(update={
            "figures": figures,
            "tables": tables,
            "metadata": {**document.metadata, "pdf_sidecar_enabled": True},
        })

    monkeypatch.setattr(
        "business.research.rag.evaluation.paper_benchmark_ingest.merge_pdf_visual_sidecar",
        fake_merge,
    )

    report = ingest_benchmark_papers(
        ["1706.03762"],
        papers_dir=tmp_path / "papers",
        with_pdf_sidecar=True,
        fetcher=_FakePdfFetcher(),
        parser=_FakeVisualParser(),
    )

    item = report.items[0]
    payload = json.loads(
        (tmp_path / "papers" / "1706.03762" / "research_document.json").read_text(encoding="utf-8")
    )
    assert item.pdf_sidecar_status == "merged"
    assert item.pdf_sidecar_bytes == len(b"%PDF-1.7\nfake pdf")
    assert item.pdf_sidecar_visual_merged_figures == 1
    assert item.pdf_sidecar_visual_merged_tables == 1
    assert payload["figures"][0]["image_ref"] == "figures/fig1.png"
    assert payload["tables"][0]["metadata"]["image_ref"] == "tables/table1.png"
    assert (tmp_path / "papers" / "1706.03762" / "1706.03762_original.pdf").exists()


def test_ingest_benchmark_papers_passes_pdf_parser_backend(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str | None] = {}

    class FakeArxivDocumentParser:
        def __init__(self, *, pdf_parser_backend: str | None = None):
            captured["backend"] = pdf_parser_backend

        def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
            return _FakeParser().parse(paper_id, source_bytes)

    monkeypatch.setattr(
        "business.research.rag.evaluation.paper_benchmark_ingest.ArxivDocumentParser",
        FakeArxivDocumentParser,
    )

    report = ingest_benchmark_papers(
        ["1706.03762"],
        papers_dir=tmp_path / "papers",
        fetcher=_FakeFetcher(),
        pdf_parser_backend="marker",
    )

    assert report.succeeded == 1
    assert captured["backend"] == "marker"
