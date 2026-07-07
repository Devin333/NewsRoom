from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from business.research.domain.common import SourceLineage
from business.research.domain.document import ResearchDocument, ResearchSection
from business.research.rag.cli import ingest_golden_set_papers as ingest_cli
from business.research.rag.evaluation import golden_set_paper_ingest
from business.research.rag.evaluation.golden_set_paper_ingest import ingest_golden_set_papers
from business.research.rag.evaluation.paper_evidence_eval import EvidenceQAPair, save_evidence_golden_set


@dataclass(frozen=True)
class _FakePackage:
    arxiv_id: str
    content: bytes


class _RecordingFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_source_package(self, arxiv_id: str) -> _FakePackage:
        self.calls.append(arxiv_id)
        return _FakePackage(arxiv_id=arxiv_id, content=f"source:{arxiv_id}".encode())


class _FakeParser:
    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        return ResearchDocument(
            paper_id=paper_id,
            source_hash="hash",
            sections=[
                ResearchSection(
                    section_id=f"{paper_id}-intro",
                    title="Introduction",
                    text=f"Parsed content for {paper_id}.",
                    source_ref=f"arxiv://{paper_id}",
                )
            ],
            lineage=SourceLineage(source_refs=[f"arxiv://{paper_id}"], source_hash="hash"),
            metadata={"parse_source": "test"},
        )


def test_ingest_golden_set_papers_selects_missing_ids_only(tmp_path: Path) -> None:
    golden_set = tmp_path / "golden.json"
    papers_dir = tmp_path / "papers"
    manifest = tmp_path / "manifest.json"
    _write_existing_document(papers_dir, "p1")
    save_evidence_golden_set([
        EvidenceQAPair(
            question="What does p1 report?",
            paper_id="p1",
            qa_type="citation_qa",
            gold_chunk_ids=["p1-results"],
        ),
        EvidenceQAPair(
            question="What does p2 report?",
            paper_id="p2",
            qa_type="citation_qa",
            gold_chunk_ids=["p2-results"],
        ),
    ], golden_set)
    fetcher = _RecordingFetcher()

    report = ingest_golden_set_papers(
        golden_set=golden_set,
        papers_dir=papers_dir,
        manifest_path=manifest,
        fetcher=fetcher,
        parser=_FakeParser(),
    )

    assert report.selected_paper_ids == ("p2",)
    assert report.missing_before_ingest == ("p2",)
    assert report.missing_after_ingest == ()
    assert fetcher.calls == ["p2"]
    assert report.succeeded == 1
    assert report.failed == 0
    assert (papers_dir / "p2" / "research_document.json").exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["selected_paper_ids"] == ["p2"]
    assert payload["missing_before_ingest"] == ["p2"]
    assert payload["missing_after_ingest"] == []
    assert payload["ingest_report"]["succeeded"] == 1


def test_ingest_golden_set_papers_noops_when_golden_set_is_covered(tmp_path: Path) -> None:
    golden_set = tmp_path / "golden.json"
    papers_dir = tmp_path / "papers"
    _write_existing_document(papers_dir, "p1")
    save_evidence_golden_set([
        EvidenceQAPair(
            question="What does p1 report?",
            paper_id="p1",
            qa_type="citation_qa",
            gold_chunk_ids=["p1-results"],
        )
    ], golden_set)
    fetcher = _RecordingFetcher()

    report = ingest_golden_set_papers(
        golden_set=golden_set,
        papers_dir=papers_dir,
        fetcher=fetcher,
        parser=_FakeParser(),
    )

    assert report.selected_paper_ids == ()
    assert report.missing_before_ingest == ()
    assert report.missing_after_ingest == ()
    assert fetcher.calls == []
    assert report.succeeded == 0
    assert report.failed == 0


def test_ingest_golden_set_papers_force_selects_all_ids(tmp_path: Path) -> None:
    golden_set = tmp_path / "golden.json"
    papers_dir = tmp_path / "papers"
    _write_existing_document(papers_dir, "p1")
    save_evidence_golden_set([
        EvidenceQAPair(
            question="What does p1 report?",
            paper_id="p1",
            qa_type="citation_qa",
            gold_chunk_ids=["p1-results"],
        )
    ], golden_set)
    fetcher = _RecordingFetcher()

    report = ingest_golden_set_papers(
        golden_set=golden_set,
        papers_dir=papers_dir,
        force=True,
        fetcher=fetcher,
        parser=_FakeParser(),
    )

    assert report.selected_paper_ids == ("p1",)
    assert report.missing_before_ingest == ()
    assert report.missing_after_ingest == ()
    assert fetcher.calls == ["p1"]
    assert report.succeeded == 1


def test_ingest_golden_set_papers_cli_returns_underlying_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    class _FakeReport:
        failed = 1

        def to_dict(self) -> dict:
            return {"failed": 1, "selected_paper_ids": ["p1"]}

    def fake_ingest_golden_set_papers(**kwargs):
        assert kwargs["golden_set"] == tmp_path / "golden.json"
        assert kwargs["papers_dir"] == tmp_path / "papers"
        return _FakeReport()

    monkeypatch.setattr(ingest_cli, "ingest_golden_set_papers", fake_ingest_golden_set_papers)

    exit_code = ingest_cli.main([
        "--golden-set",
        str(tmp_path / "golden.json"),
        "--papers-dir",
        str(tmp_path / "papers"),
    ])

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["failed"] == 1


def test_ingest_golden_set_papers_cli_parser_forwards_options(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    class _FakeReport:
        failed = 0

        def to_dict(self) -> dict:
            return {"failed": 0}

    def fake_ingest_golden_set_papers(**kwargs):
        captured.update(kwargs)
        return _FakeReport()

    monkeypatch.setattr(golden_set_paper_ingest, "ingest_benchmark_papers", lambda *args, **kwargs: None)
    monkeypatch.setattr(ingest_cli, "ingest_golden_set_papers", fake_ingest_golden_set_papers)

    exit_code = ingest_cli.main([
        "--golden-set",
        str(tmp_path / "golden.json"),
        "--papers-dir",
        str(tmp_path / "papers"),
        "--manifest",
        str(tmp_path / "manifest.json"),
        "--max-papers",
        "2",
        "--force",
        "--pdf-parser-backend",
        "cascade",
        "--with-pdf-sidecar",
        "--pdf-sidecar-mode",
        "always",
        "--no-merge-pdf-visuals",
    ])

    assert exit_code == 0
    assert captured["max_papers"] == 2
    assert captured["force"] is True
    assert captured["pdf_parser_backend"] == "cascade"
    assert captured["with_pdf_sidecar"] is True
    assert captured["pdf_sidecar_mode"] == "always"
    assert captured["merge_pdf_visuals"] is False


def _write_existing_document(papers_dir: Path, paper_id: str) -> None:
    paper_dir = papers_dir / paper_id
    paper_dir.mkdir(parents=True)
    (paper_dir / "research_document.json").write_text(
        json.dumps({
            "paper_id": paper_id,
            "sections": [],
            "figures": [],
            "tables": [],
            "equations": [],
            "references": [],
            "metadata": {"parse_source": "test"},
        }),
        encoding="utf-8",
    )
