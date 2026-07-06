from __future__ import annotations

import json

from business.research.rag.evaluation.live_answer_eval import run_live_answer_eval
from business.research.rag.evaluation.paper_evidence_eval import EvidenceQAPair


def test_run_live_answer_eval_uses_injected_ask_callable(tmp_path) -> None:
    calls: list[str] = []

    def ask(pair: EvidenceQAPair) -> dict:
        calls.append(pair.question)
        if pair.expected_behavior == "abstain":
            return {
                "status": "abstained",
                "generation_mode": "gated_harness",
                "answer": None,
                "answer_candidate": {"abstained": True, "answer_text": ""},
                "citations": [],
                "passages": [],
                "gate_results": [],
                "decision": {"decision_type": "abstain"},
                "transcript_id": "rag-transcript://test/abstain",
            }
        chunk_id = pair.gold_chunk_ids[0] if pair.gold_chunk_ids else "fixture-chunk"
        source_locator = pair.gold_source_locators[0] if pair.gold_source_locators else ""
        answer = " ".join(pair.answer_facts) or "The cited evidence supports the answer."
        return {
            "status": "answered",
            "generation_mode": "gated_harness",
            "answer": answer,
            "answer_candidate": {"abstained": False, "answer_text": answer},
            "citations": [{"chunk_id": chunk_id, "source_locator": source_locator}],
            "passages": [{"chunk_id": chunk_id}],
            "gate_results": [{"check_id": "answer.grounded", "passed": True}],
            "decision": {"decision_type": "answer"},
            "transcript_id": "rag-transcript://test/answer",
        }

    result = run_live_answer_eval(output_dir=tmp_path / "live", live_answer_ask=ask)

    assert result.passed is True
    assert calls
    assert result.golden_set_path.exists()
    assert result.fixture_papers_dir.exists()
    payload = json.loads(result.evidence_report_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["answer_eval_mode"] == "live"
    assert payload["answer"]["failure_reason_counts"] == {}
