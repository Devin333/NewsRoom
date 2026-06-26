from __future__ import annotations

import json
from pathlib import Path

from business.research.rag.benchmark_suite import (
    BenchmarkSuiteConfig,
    GoldEvidenceJudgeItem,
    GoldEvidenceJudgeReport,
    audit_gold_evidence,
    run_benchmark_suite,
    split_paper_ids,
)
from business.research.rag.evidence_eval import EvidenceQAPair
from business.research.rag.run_benchmark_suite import main


class _FakeGoldJudge:
    def judge(self, items):
        judged = tuple(
            GoldEvidenceJudgeItem(
                question=item.question,
                paper_id=item.paper_id,
                qa_type=item.qa_type,
                status="pass",
                reason="supported_by_fake_judge",
                supported=True,
                confidence=0.9,
            )
            for item in items
        )
        return GoldEvidenceJudgeReport(
            mode="fake",
            provider="fake",
            model="fake-gold-judge",
            sample_size=len(judged),
            passed=len(judged),
            warning=0,
            failed=0,
            error=0,
            items=judged,
        )


def test_split_paper_ids_is_stable_and_non_empty() -> None:
    paper_ids = [f"p{i}" for i in range(10)]

    first = split_paper_ids(paper_ids, seed="seed")
    second = split_paper_ids(list(reversed(paper_ids)), seed="seed")

    assert first == second
    assert set(first) == {"train", "dev", "test"}
    assert all(first[name] for name in ("train", "dev", "test"))
    assert sorted(first["train"] + first["dev"] + first["test"]) == sorted(paper_ids)


def test_audit_gold_evidence_reports_missing_chunks() -> None:
    pair = EvidenceQAPair(
        question="What does Table 1 show?",
        paper_id="p1",
        qa_type="table_qa",
        gold_chunk_ids=["missing"],
        required_evidence_types=["table"],
    )

    report = audit_gold_evidence([pair], [], sample_size=10, seed="seed")

    assert report.failed == 1
    assert report.items[0].reason == "missing_gold_chunks"


def test_run_benchmark_suite_writes_splits_and_baseline(tmp_path: Path) -> None:
    papers_dir = tmp_path / "papers"
    for paper_id in ("p1", "p2", "p3"):
        paper_dir = papers_dir / paper_id
        (paper_dir / "figures").mkdir(parents=True)
        (paper_dir / "figures" / "fig.png").write_bytes(b"fake")
        payload = _research_document_payload(paper_id)
        (paper_dir / "research_document.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    output_dir = tmp_path / "suite"
    result = run_benchmark_suite(BenchmarkSuiteConfig(
        papers_dir=papers_dir,
        output_dir=output_dir,
        min_papers=3,
        target_min_per_type=1,
        max_pairs_per_type=20,
        render_page_visual=False,
        gold_audit_sample_size=5,
        gold_judge_mode="fake",
        gold_judge_sample_size=2,
        gold_evidence_judge=_FakeGoldJudge(),
    ))

    assert result.papers_total == 3
    assert (output_dir / "benchmark_suite_report.json").exists()
    assert (output_dir / "benchmark_suite_report.md").exists()
    assert (output_dir / "test" / "candidate" / "evidence_regression_report.json").exists()
    assert (output_dir / "test" / "fixed_window" / "evidence_regression_report.json").exists()
    assert (output_dir / "train" / "golden_set.json").exists()
    assert (output_dir / "dev" / "golden_set.json").exists()
    assert (output_dir / "test" / "golden_set.json").exists()
    assert result.ab_report["baseline_name"] == "fixed_window"
    assert "mrr" in result.ab_report["deltas"]
    assert "relative_improvement" in result.ab_report
    assert result.gold_judge is not None
    assert result.gold_judge.model == "fake-gold-judge"
    payload = json.loads((output_dir / "benchmark_suite_report.json").read_text(encoding="utf-8"))
    assert payload["evaluation_protocol"]["reported_split"] == "test"


def test_run_benchmark_suite_cli(tmp_path: Path) -> None:
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "p1"
    paper_dir.mkdir(parents=True)
    (paper_dir / "research_document.json").write_text(
        json.dumps(_research_document_payload("p1"), ensure_ascii=False),
        encoding="utf-8",
    )
    output_dir = tmp_path / "suite"

    exit_code = main([
        "--papers-dir",
        str(papers_dir),
        "--output-dir",
        str(output_dir),
        "--min-papers",
        "1",
        "--target-min-per-type",
        "1",
        "--gold-audit-sample-size",
        "2",
        "--no-page-visual",
    ])

    assert exit_code == 0
    payload = json.loads((output_dir / "benchmark_suite_report.json").read_text(encoding="utf-8"))
    assert payload["papers_total"] == 1
    item = payload["gold_audit"]["items"][0]
    assert "evidence_previews" in item
    assert "answer_facts" in item


def _research_document_payload(paper_id: str) -> dict:
    return {
        "paper_id": paper_id,
        "source_hash": f"hash-{paper_id}",
        "sections": [
            {
                "section_id": f"{paper_id}-abstract",
                "title": "Abstract",
                "level": 1,
                "text": "This paper introduces a visual retrieval model.",
                "source_ref": f"paper://{paper_id}/abstract",
            },
            {
                "section_id": f"{paper_id}-results",
                "title": "Results",
                "level": 1,
                "text": "Figure 1 shows the architecture. Table 1 reports better accuracy. Equation 1 defines the score.",
                "source_ref": f"paper://{paper_id}/results",
            },
        ],
        "figures": [
            {
                "figure_id": "fig1",
                "caption": "Figure 1: architecture overview.",
                "source_ref": f"paper://{paper_id}/fig1",
                "image_ref": "figures/fig.png",
                "page": 1,
            }
        ],
        "tables": [
            {
                "table_id": "tbl1",
                "caption": "Table 1: accuracy results.",
                "source_ref": f"paper://{paper_id}/tbl1",
                "columns": ["metric", "value"],
                "rows": [{"metric": "accuracy", "value": "95"}],
                "page": 1,
            }
        ],
        "equations": [
            {
                "equation_id": "eq1",
                "latex": "s = x + y",
                "source_ref": f"paper://{paper_id}/eq1",
                "page": 1,
            }
        ],
        "references": [],
        "lineage": {
            "source_refs": [f"paper://{paper_id}"],
            "source_hash": f"hash-{paper_id}",
            "artifact_refs": [],
            "metadata": {},
        },
        "metadata": {"parse_source": "latex"},
    }
