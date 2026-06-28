from __future__ import annotations

import json
from pathlib import Path

from business.research.rag.evaluation.paper_benchmark_suite import (
    BenchmarkSuiteConfig,
    GoldEvidenceJudgeItem,
    GoldEvidenceJudgeReport,
    audit_question_ambiguity,
    audit_gold_evidence,
    run_benchmark_suite,
    split_paper_ids,
)
from business.research.document.models import PaperChunk
from business.research.rag.evaluation.paper_evidence_eval import EvidenceQAPair
from business.research.rag.cli.run_benchmark_suite import _parse_thresholds, main


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


def _paper_chunk(
    *,
    chunk_id: str,
    chunk_type: str,
    content: str,
    metadata: dict | None = None,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type=chunk_type,
        has_figure=chunk_type == "figure",
        has_table=chunk_type == "table",
        content=content,
        metadata=metadata or {},
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


def test_audit_gold_evidence_accepts_latex_table_without_image_ref() -> None:
    table = _paper_chunk(
        chunk_id="tbl1",
        chunk_type="table",
        content="Caption: Performance of architectural variants. Rows: baseline 31.2, large 33.8.",
        metadata={
            "source_locator": "paper://p1/table/1",
            "caption_text": "Performance of architectural variants.",
            "table_rows": [{"model": "baseline", "score": "31.2"}],
        },
    )
    pair = EvidenceQAPair(
        question="What quantitative evidence is reported for the architectural variants?",
        paper_id="p1",
        qa_type="table_qa",
        gold_chunk_ids=["tbl1"],
        required_evidence_types=["table"],
        answer_facts=["baseline 31.2"],
    )

    report = audit_gold_evidence([pair], [table], sample_size=10, seed="seed")

    assert report.passed == 1
    assert report.warning == 0
    assert report.items[0].image_ref_count == 0
    assert report.items[0].reason == "ok"


def test_audit_gold_evidence_accepts_caption_only_figure_without_image_ref() -> None:
    figure = _paper_chunk(
        chunk_id="fig1",
        chunk_type="figure",
        content="Caption: Schematic of the baseline objective and training process.",
        metadata={
            "source_locator": "paper://p1/figure/1",
            "caption_text": "Schematic of the baseline objective and training process.",
        },
    )
    pair = EvidenceQAPair(
        question="What visual evidence explains the baseline objective and training process?",
        paper_id="p1",
        qa_type="figure_qa",
        gold_chunk_ids=["fig1"],
        required_evidence_types=["figure"],
        answer_facts=["baseline objective"],
    )

    report = audit_gold_evidence([pair], [figure], sample_size=10, seed="seed")

    assert report.passed == 1
    assert report.warning == 0
    assert report.items[0].image_ref_count == 0
    assert report.items[0].reason == "ok"


def test_audit_gold_evidence_warns_for_figure_without_image_or_textual_evidence() -> None:
    figure = _paper_chunk(
        chunk_id="fig1",
        chunk_type="figure",
        content="Figure.",
        metadata={"source_locator": "paper://p1/figure/1"},
    )
    pair = EvidenceQAPair(
        question="What visual evidence explains the baseline objective?",
        paper_id="p1",
        qa_type="figure_qa",
        gold_chunk_ids=["fig1"],
        required_evidence_types=["figure"],
        answer_facts=["baseline objective"],
    )

    report = audit_gold_evidence([pair], [figure], sample_size=10, seed="seed")

    assert report.warning == 1
    assert report.items[0].reason == "visual_qa_without_image_ref"


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
    breakdown_summary = payload["candidate_test_report"]["retrieval"]["score_breakdown_summary"]
    assert breakdown_summary["evidence_count"] > 0
    assert "final_score" in breakdown_summary["components"]
    retrieval_payload = payload["candidate_test_report"]["retrieval"]
    assert retrieval_payload["intent_distribution"]
    assert retrieval_payload["route_distribution"]
    assert retrieval_payload["intent_confusion"]
    scorecard_metadata = payload["candidate_test_report"]["rag_evaluation_report"]["scorecard"]["metadata"]
    assert scorecard_metadata["score_breakdown_summary"]["evidence_count"] == breakdown_summary["evidence_count"]
    field_distribution = retrieval_payload["field_embedding_distribution"]
    assert field_distribution["search_hits_by_field"]
    assert field_distribution["matched_evidence_count"] > 0
    markdown = (output_dir / "benchmark_suite_report.md").read_text(encoding="utf-8")
    assert "## Score Breakdown" in markdown
    assert "## Field Embedding Distribution" in markdown
    assert "## Route Distribution" in markdown
    assert "## Intent Confusion" in markdown


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


def test_run_benchmark_suite_writes_blind_detemplated_protocol(tmp_path: Path) -> None:
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
        question_profile="blind_detemplated",
    ))

    payload = json.loads((output_dir / "benchmark_suite_report.json").read_text(encoding="utf-8"))
    markdown = (output_dir / "benchmark_suite_report.md").read_text(encoding="utf-8")
    golden_records = []
    for split in ("train", "dev", "test"):
        golden_records.extend(json.loads((output_dir / split / "golden_set.json").read_text(encoding="utf-8")))
    profiled = [record for record in golden_records if record["metadata"].get("question_profile") == "blind_detemplated"]

    assert result.question_profile == "blind_detemplated"
    assert payload["evaluation_protocol"]["question_profile"] == "blind_detemplated"
    assert payload["evaluation_protocol"]["blind_test"] is True
    assert "question profile: `blind_detemplated`" in markdown
    assert profiled
    assert all("template_question" in record["metadata"] for record in profiled)
    assert not any("Table 1:" in record["question"] for record in profiled)
    assert not any("Figure 1:" in record["question"] for record in profiled)


def test_run_benchmark_suite_writes_blind_semantic_protocol_and_question_audit(tmp_path: Path) -> None:
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
        question_profile="blind_semantic",
    ))

    payload = json.loads((output_dir / "benchmark_suite_report.json").read_text(encoding="utf-8"))
    markdown = (output_dir / "benchmark_suite_report.md").read_text(encoding="utf-8")
    golden_records = []
    for split in ("train", "dev", "test"):
        golden_records.extend(json.loads((output_dir / split / "golden_set.json").read_text(encoding="utf-8")))
    profiled = [record for record in golden_records if record["metadata"].get("question_profile") == "blind_semantic"]

    assert result.question_profile == "blind_semantic"
    assert payload["evaluation_protocol"]["question_profile"] == "blind_semantic"
    assert payload["evaluation_protocol"]["blind_test"] is True
    assert payload["evaluation_protocol"]["detemplate_policy"] == "semantic_anchors_no_labels_v1"
    assert payload["question_audit"]["total"] == payload["pairs_total"]
    assert "## Question Ambiguity Audit" in markdown
    assert "question profile: `blind_semantic`" in markdown
    assert profiled
    assert all("template_question" in record["metadata"] for record in profiled)
    assert any(record["metadata"].get("semantic_anchors") for record in profiled)
    assert not any("Table 1:" in record["question"] for record in profiled)
    assert not any("Figure 1:" in record["question"] for record in profiled)
    assert not any("Equation 1" in record["question"] for record in profiled)


def test_run_benchmark_suite_can_report_policy_promotion_checklist(tmp_path: Path) -> None:
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
        question_profile="blind_semantic",
        retrieval_policy="paper_blind_semantic_rag_v1",
    ))

    payload = json.loads((output_dir / "benchmark_suite_report.json").read_text(encoding="utf-8"))
    markdown = (output_dir / "benchmark_suite_report.md").read_text(encoding="utf-8")
    checklist = payload["policy_promotion_checklist"]
    distribution = payload["candidate_test_report"]["retrieval"]["rerank_distribution"]

    assert result.policy_promotion_checklist.policy_name == "paper_blind_semantic_rag_v1"
    assert (output_dir / "policy_promotion_checklist.json").exists()
    assert (output_dir / "policy_promotion_checklist.md").exists()
    assert checklist["policy_name"] == "paper_blind_semantic_rag_v1"
    assert checklist["ready_for_promotion"] is False
    assert any(check["check_id"] == "answer_success" and check["status"] == "fail" for check in checklist["checks"])
    assert "## Policy Promotion Checklist" in markdown
    assert result.candidate_test_report["metadata"]["lightweight_reranker_enabled"] is True
    assert result.candidate_test_report["metadata"]["retrieval_policy"] == "paper_blind_semantic_rag_v1"
    assert distribution["reranker_enabled_sample_count"] > 0
    assert distribution["reranked_evidence_count"] > 0
    assert distribution["max_score"] > 0.0
    assert "## Rerank Distribution" in markdown


def test_question_ambiguity_audit_flags_duplicate_ambiguous_and_label_leakage() -> None:
    pairs = [
        EvidenceQAPair(
            question="What quantitative evidence reports accuracy?",
            paper_id="p1",
            qa_type="table_qa",
            gold_chunk_ids=["tbl1"],
            required_evidence_types=["table"],
            metadata={"question_profile": "blind_semantic", "semantic_anchors": ["accuracy", "benchmark"]},
        ),
        EvidenceQAPair(
            question="What quantitative evidence reports accuracy?",
            paper_id="p1",
            qa_type="table_qa",
            gold_chunk_ids=["tbl2"],
            required_evidence_types=["table"],
            metadata={"question_profile": "blind_semantic", "semantic_anchors": ["accuracy", "benchmark"]},
        ),
        EvidenceQAPair(
            question="What does Table 1 show?",
            paper_id="p1",
            qa_type="table_qa",
            gold_chunk_ids=["tbl1"],
            required_evidence_types=["table"],
            metadata={"question_profile": "blind_semantic", "semantic_anchors": ["accuracy"]},
        ),
    ]

    report = audit_question_ambiguity(pairs, [])

    assert report.total == 3
    assert report.duplicate_questions == 2
    assert report.ambiguous_questions == 2
    assert report.missing_semantic_anchor == 1
    assert report.label_leakage == 1
    assert {reason for item in report.items for reason in item.reasons} >= {
        "duplicate_question",
        "ambiguous_question",
        "missing_semantic_anchor",
        "label_leakage",
    }


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
    assert all("context_score_breakdowns" in record for record in answer_sample_records)
    assert any(record["context_score_breakdowns"] for record in answer_sample_records)
    assert all("context_role_buckets" in record["metadata"] for record in answer_sample_records)
    assert any(record["metadata"]["primary_evidence_ids"] for record in answer_sample_records)
    assert all("locator_context" in record["metadata"] for record in answer_sample_records)
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
        "--question-profile",
        "blind_detemplated",
        "--no-page-visual",
    ])

    assert exit_code == 0
    payload = json.loads((output_dir / "benchmark_suite_report.json").read_text(encoding="utf-8"))
    assert payload["papers_total"] == 1
    assert payload["evaluation_protocol"]["question_profile"] == "blind_detemplated"
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
