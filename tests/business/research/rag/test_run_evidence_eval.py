from __future__ import annotations

import json

from business.research.rag.evidence_eval import EvidenceQAPair, save_evidence_golden_set
from business.research.rag.run_evidence_eval import main


def test_run_evidence_eval_writes_summary_report(tmp_path) -> None:
    golden = tmp_path / "golden.json"
    output = tmp_path / "report"
    save_evidence_golden_set([
        EvidenceQAPair(
            question="What is supported?",
            paper_id="p1",
            qa_type="citation_qa",
            gold_chunk_ids=["para-1"],
        ),
        EvidenceQAPair.negative(
            question="Does the paper discuss unrelated future work?",
            paper_id="p1",
        ),
    ], golden)

    exit_code = main(["--golden-set", str(golden), "--output-dir", str(output)])

    assert exit_code == 0
    payload = json.loads((output / "evidence_regression_report.json").read_text(encoding="utf-8"))
    assert payload["metadata"]["total_pairs"] == 2
    assert payload["metadata"]["qa_type_counts"] == {"citation_qa": 1, "negative_qa": 1}
    assert (output / "evidence_regression_report.md").exists()


def test_run_evidence_eval_returns_failure_for_unavailable_threshold(tmp_path) -> None:
    golden = tmp_path / "golden.json"
    output = tmp_path / "report"
    save_evidence_golden_set([
        EvidenceQAPair(
            question="What is supported?",
            paper_id="p1",
            qa_type="citation_qa",
            gold_chunk_ids=["para-1"],
        ),
    ], golden)

    exit_code = main([
        "--golden-set",
        str(golden),
        "--output-dir",
        str(output),
        "--threshold",
        "retrieval.evidence_coverage=0.8",
    ])

    assert exit_code == 1
    payload = json.loads((output / "evidence_regression_report.json").read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert "unavailable" in payload["issues"][0]
