from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from business.research.domain.common import SourceLineage
from business.research.domain.document import ResearchDocument, ResearchSection
from business.research.rag.evaluation.paper_benchmark_ingest import ingest_benchmark_papers


@dataclass(frozen=True)
class _FakePackage:
    arxiv_id: str
    content: bytes


class _FakeFetcher:
    def fetch_source_package(self, arxiv_id: str) -> _FakePackage:
        return _FakePackage(arxiv_id=arxiv_id, content=b"\\section{Intro} hello")


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

