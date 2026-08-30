from __future__ import annotations

import json
from pathlib import Path

from backend.research.rag.cli.run_ci_eval_gate import main
from backend.research.rag.evaluation import ci_eval_gate
from backend.research.rag.evaluation.ci_eval_gate import run_ci_eval_gate


def test_ci_eval_gate_writes_evidence_and_promotion_reports(tmp_path: Path) -> None:
    output_dir = tmp_path / "ci-gate"

    result = run_ci_eval_gate(output_dir=output_dir)

    assert result.passed is True
    assert result.evidence_exit_code == 0
    assert result.evidence_report_path.exists()
    assert result.evidence_markdown_path.exists()
    assert result.promotion_report_path.exists()
    assert result.promotion_markdown_path.exists()
    assert result.golden_set_path.exists()

    evidence = json.loads(result.evidence_report_path.read_text(encoding="utf-8"))
    promotion = json.loads(result.promotion_report_path.read_text(encoding="utf-8"))

    assert evidence["metadata"]["mode"] == "live_retrieval"
    assert evidence["metadata"]["answer_eval_mode"] == "deterministic"
    assert evidence["metadata"]["total_pairs"] > 0
    assert evidence["metadata"]["expected_behavior_counts"]["abstain"] > 0
    assert evidence["metadata"]["expected_behavior_counts"]["answer"] > 0
    assert evidence["retrieval"]["answerable_total"] > 0
    assert evidence["retrieval"]["abstain_total"] > 0
    assert evidence["answer"]["abstention_accuracy"] >= 0.9
    assert evidence["answer"]["success_rate"] >= 0.9
    assert evidence["thresholds"]["retrieval.hit_rate"] >= 0.75
    assert evidence["thresholds"]["answer.abstention_accuracy"] >= 0.9
    assert promotion["ready_for_promotion"] is True
    assert promotion["evidence_report_path"] == str(result.evidence_report_path)
    assert promotion["status_counts"] == {"pass": len(promotion["checks"])}
    assert {check["check_id"] for check in promotion["checks"]} >= {
        "evidence_report_passed",
        "overall_hit_at_3",
        "overall_evidence_coverage_at_5",
        "overall_source_locator_coverage_at_5",
        "by_qa_type_metrics",
        "negative_abstention_samples",
        "answer_abstention_accuracy",
        "answer_success_rate",
    }
    labels = {check["check_id"]: check["label"] for check in promotion["checks"]}
    assert labels["answer_abstention_accuracy"].startswith("Deterministic answer-eval pipeline")
    assert labels["answer_success_rate"].startswith("Deterministic answer-eval pipeline")


def test_ci_eval_gate_returns_failed_result_for_threshold_regression(tmp_path: Path) -> None:
    result = run_ci_eval_gate(
        output_dir=tmp_path / "ci-gate",
        retrieval_thresholds={"retrieval.hit_rate": 1.01},
    )

    evidence = json.loads(result.evidence_report_path.read_text(encoding="utf-8"))
    promotion = json.loads(result.promotion_report_path.read_text(encoding="utf-8"))

    assert result.passed is False
    assert result.evidence_exit_code == 1
    assert evidence["passed"] is False
    assert any("retrieval.hit_rate" in issue for issue in evidence["issues"])
    assert any(
        check["check_id"] == "evidence_report_passed" and check["status"] == "fail"
        for check in promotion["checks"]
    )


def test_ci_eval_gate_returns_failed_result_for_abstention_threshold_regression(tmp_path: Path) -> None:
    result = run_ci_eval_gate(
        output_dir=tmp_path / "ci-gate",
        retrieval_thresholds={"answer.abstention_accuracy": 1.01},
    )

    evidence = json.loads(result.evidence_report_path.read_text(encoding="utf-8"))
    promotion = json.loads(result.promotion_report_path.read_text(encoding="utf-8"))

    assert result.passed is False
    assert result.evidence_exit_code == 1
    assert evidence["passed"] is False
    assert any("answer.abstention_accuracy" in issue for issue in evidence["issues"])
    assert any(
        check["check_id"] == "evidence_report_passed" and check["status"] == "fail"
        for check in promotion["checks"]
    )


def test_ci_eval_gate_uses_structured_evidence_eval_options(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def fake_run_evidence_eval_core(options, *, live_answer_ask=None) -> int:
        captured["options"] = options
        captured["live_answer_ask"] = live_answer_ask
        output_dir = Path(options.output_dir)
        output_dir.mkdir(parents=True)
        (output_dir / "evidence_regression_report.json").write_text(
            json.dumps({
                "passed": True,
                "issues": [],
                "metadata": {
                    "retrieval_policy": ci_eval_gate.DEFAULT_RETRIEVAL_POLICY,
                    "expected_behavior_counts": {"abstain": 1, "answer": 1},
                },
                "retrieval": {
                    "mrr": 1.0,
                    "by_k": {
                        str(k): {
                            "hit_rate": 1.0,
                            "evidence_coverage": 1.0,
                            "required_type_coverage": 1.0,
                            "source_locator_coverage": 1.0,
                        }
                        for k in (3, 5, 10)
                    },
                    "by_qa_type": {
                        qa_type: {"by_k": {"10": {"hit_rate": 1.0}}}
                        for qa_type in ("citation_qa", "figure_qa", "formula_qa", "table_qa")
                    },
                    "route_distribution": {"default": 1},
                    "field_embedding_distribution": {"matched_evidence_count": 1},
                    "rerank_distribution": {"reranked_evidence_count": 1},
                },
                "answer": {
                    "abstention_accuracy": 1.0,
                    "success_rate": 1.0,
                },
            }),
            encoding="utf-8",
        )
        (output_dir / "evidence_regression_report.md").write_text("passed\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(ci_eval_gate, "run_evidence_eval_core", fake_run_evidence_eval_core)

    result = ci_eval_gate.run_ci_eval_gate(output_dir=tmp_path / "ci-gate")

    options = captured["options"]
    assert result.passed is True
    assert result.evidence_exit_code == 0
    assert captured["live_answer_ask"] is None
    assert options.build_golden_set is True
    assert options.live_retrieval is True
    assert options.deterministic_answer_eval is True
    assert options.live_answer_eval is False
    assert options.max_pairs_per_type == 2
    assert options.domain == "ci"
    assert options.thresholds["answer.abstention_accuracy"] >= 0.9
    assert options.papers_dir == result.fixture_papers_dir
    assert options.golden_set == result.golden_set_path


def test_ci_eval_gate_cli_returns_nonzero_on_failed_threshold(tmp_path: Path) -> None:
    exit_code = main([
        "--output-dir",
        str(tmp_path / "ci-gate"),
        "--threshold",
        "retrieval.hit_rate=1.01",
    ])

    assert exit_code == 1
