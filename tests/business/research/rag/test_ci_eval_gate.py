from __future__ import annotations

import json
from pathlib import Path

from business.research.rag.cli.run_ci_eval_gate import main
from business.research.rag.evaluation.ci_eval_gate import run_ci_eval_gate


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


def test_ci_eval_gate_cli_returns_nonzero_on_failed_threshold(tmp_path: Path) -> None:
    exit_code = main([
        "--output-dir",
        str(tmp_path / "ci-gate"),
        "--threshold",
        "retrieval.hit_rate=1.01",
    ])

    assert exit_code == 1
