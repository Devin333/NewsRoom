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
from business.research.rag.run_benchmark_suite import _parse_thresholds, main


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


async def _fake_answer_llm(prompt: str) -> str:
    return (
        "Figure 1: architecture overview. Table 1: accuracy results. "
        "The table reports accuracy 95, Equation 1 defines the score, "
        "and s = x + y. [1]"
    )


async def _fake_judge_llm(prompt: str) -> str:
    if "Score (0-100)" in prompt:
        return "100"
    if "Verdicts (yes/no per passage)" in prompt:
        return "yes\nyes\nyes"
    return "yes"


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


def test_run_benchmark_suite_writes_splits_without_fixed_window_by_default(tmp_path: Path) -> None:
    papers_dir = tmp_path / "papers"
    _write_research_document_fixtures(papers_dir, ("p1", "p2", "p3"))

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
    assert not (output_dir / "test" / "fixed_window").exists()
    assert (output_dir / "train" / "golden_set.json").exists()
    assert (output_dir / "dev" / "golden_set.json").exists()
    assert (output_dir / "test" / "golden_set.json").exists()
    assert result.baseline_test_report is None
    assert result.ab_report is None
    assert result.gold_judge is not None
    assert result.gold_judge.model == "fake-gold-judge"
    payload = json.loads((output_dir / "benchmark_suite_report.json").read_text(encoding="utf-8"))
    assert payload["evaluation_protocol"]["reported_split"] == "test"
    assert payload["baseline_test_report"] is None
    assert payload["ab_report"] is None


def test_run_benchmark_suite_can_write_fixed_window_baseline_when_requested(tmp_path: Path) -> None:
    papers_dir = tmp_path / "papers"
    _write_research_document_fixtures(papers_dir, ("p1", "p2", "p3"))

    output_dir = tmp_path / "suite"
    result = run_benchmark_suite(BenchmarkSuiteConfig(
        papers_dir=papers_dir,
        output_dir=output_dir,
        min_papers=3,
        target_min_per_type=1,
        max_pairs_per_type=20,
        render_page_visual=False,
        gold_audit_sample_size=5,
        include_fixed_window_baseline=True,
    ))

    assert (output_dir / "test" / "fixed_window" / "evidence_regression_report.json").exists()
    assert result.baseline_test_report is not None
    assert result.ab_report is not None
    assert result.ab_report["baseline_name"] == "fixed_window"
    assert "mrr" in result.ab_report["deltas"]
    assert "relative_improvement" in result.ab_report


def test_run_benchmark_suite_writes_answer_eval_judge_and_spot_check(tmp_path: Path) -> None:
    papers_dir = tmp_path / "papers"
    _write_research_document_fixtures(papers_dir, ("p1", "p2", "p3"))
    annotations_path = tmp_path / "spot_annotations.jsonl"
    annotations_path.write_text(
        "\n".join([
            json.dumps({"label": "pass"}),
            json.dumps({"verdict": "needs_fix"}),
        ]),
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
        answer_eval_enabled=True,
        answer_eval_sample_size=2,
        answer_llm_call=_fake_answer_llm,
        answer_judge_mode="llm",
        answer_judge_sample_size=1,
        answer_judge_llm_call=_fake_judge_llm,
        spot_check_sample_size=2,
        spot_check_annotations_path=annotations_path,
        quality_thresholds={"answer.success_rate": 1.1},
    ))

    candidate_dir = output_dir / "test" / "candidate"
    candidate = result.candidate_test_report
    report_payload = json.loads((output_dir / "benchmark_suite_report.json").read_text(encoding="utf-8"))
    markdown = (output_dir / "benchmark_suite_report.md").read_text(encoding="utf-8")
    answer_samples = (candidate_dir / "answer_samples.jsonl").read_text(encoding="utf-8").splitlines()
    spot_samples = (candidate_dir / "spot_check_samples.jsonl").read_text(encoding="utf-8").splitlines()
    answer_sample_records = [json.loads(line) for line in answer_samples]

    assert candidate["answer"]["total"] == 2
    assert candidate["generation"]["total"] == 1
    assert candidate["spot_check"]["annotated_count"] == 2
    assert report_payload["spot_check"]["label_counts"] == {"needs_fix": 1, "pass": 1}
    assert len(answer_samples) == 2
    assert all("deterministic_scores" in record for record in answer_sample_records)
    assert all(
        "retrieval_context_coverage" in record["deterministic_scores"]
        for record in answer_sample_records
    )
    assert len(spot_samples) == 2
    assert "candidate_quality_gate_failed" in result.warnings
    assert any(warning.startswith("candidate_quality_issue:answer.success_rate=") for warning in result.warnings)
    assert "## Answer Metrics" in markdown
    assert "## Generation Judge" in markdown
    assert "## Spot Check" in markdown


def test_spot_check_generation_is_capped_by_sample_size(tmp_path: Path) -> None:
    papers_dir = tmp_path / "papers"
    _write_research_document_fixtures(papers_dir, ("p1", "p2", "p3"))
    prompts: list[str] = []

    async def fake_answer(prompt: str) -> str:
        prompts.append(prompt)
        return "The answer is in the selected context. [1]"

    output_dir = tmp_path / "suite"
    result = run_benchmark_suite(BenchmarkSuiteConfig(
        papers_dir=papers_dir,
        output_dir=output_dir,
        min_papers=3,
        target_min_per_type=1,
        max_pairs_per_type=20,
        render_page_visual=False,
        gold_audit_sample_size=5,
        answer_llm_call=fake_answer,
        spot_check_sample_size=1,
    ))

    assert len(prompts) == 1
    assert result.spot_check is not None
    assert result.spot_check.sample_size == 1


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
        "--quality-threshold",
        "retrieval.hit_rate=0",
        "--no-page-visual",
    ])

    assert exit_code == 0
    payload = json.loads((output_dir / "benchmark_suite_report.json").read_text(encoding="utf-8"))
    assert payload["papers_total"] == 1
    item = payload["gold_audit"]["items"][0]
    assert "evidence_previews" in item
    assert "answer_facts" in item


def test_parse_thresholds_requires_metric_value_pairs() -> None:
    assert _parse_thresholds(["answer.success_rate=0.8"]) == {"answer.success_rate": 0.8}

    try:
        _parse_thresholds(["answer.success_rate"])
    except ValueError as exc:
        assert "METRIC=VALUE" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def _write_research_document_fixtures(papers_dir: Path, paper_ids: tuple[str, ...]) -> None:
    for paper_id in paper_ids:
        paper_dir = papers_dir / paper_id
        (paper_dir / "figures").mkdir(parents=True)
        (paper_dir / "figures" / "fig.png").write_bytes(b"fake")
        payload = _research_document_payload(paper_id)
        (paper_dir / "research_document.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )


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
