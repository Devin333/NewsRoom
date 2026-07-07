from __future__ import annotations

import json

import pytest

from business.research.rag.cli import run_live_answer_eval as live_answer_cli
from business.research.rag.evaluation import live_answer_eval
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


def test_run_live_answer_eval_external_golden_set_bypasses_fixture_generation(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    golden_set = tmp_path / "real_golden_set.json"
    papers_dir = tmp_path / "papers"
    output_dir = tmp_path / "live-real"
    papers_dir.mkdir()
    golden_set.write_text("[]", encoding="utf-8")

    def fail_fixture_generation(path) -> None:
        raise AssertionError("external golden set mode must not generate fixture papers")

    def fake_run_evidence_eval_core(options, *, live_answer_ask=None) -> int:
        captured["options"] = options
        captured["live_answer_ask"] = live_answer_ask
        evidence_dir = output_dir / "evidence"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "evidence_regression_report.json").write_text(
            json.dumps({"passed": True}),
            encoding="utf-8",
        )
        (evidence_dir / "evidence_regression_report.md").write_text("passed\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(live_answer_eval, "write_ci_eval_fixture_papers", fail_fixture_generation)
    monkeypatch.setattr(live_answer_eval, "run_evidence_eval_core", fake_run_evidence_eval_core)

    result = run_live_answer_eval(
        output_dir=output_dir,
        golden_set_path=golden_set,
        papers_dir=papers_dir,
        live_answer_ask=lambda pair: {},
    )

    options = captured["options"]
    assert result.passed is True
    assert result.corpus_mode == "external"
    assert result.golden_set_path == golden_set
    assert result.papers_dir == papers_dir
    assert result.fixture_papers_dir is None
    assert options.build_golden_set is False
    assert options.golden_set == golden_set
    assert options.papers_dir == papers_dir
    assert options.live_answer_eval is True
    assert options.live_retrieval is True
    assert options.answer_eval_limit == 8


def test_run_live_answer_eval_passes_answer_eval_limit(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_write_ci_eval_fixture_papers(path) -> None:
        path.mkdir(parents=True)

    def fake_run_evidence_eval_core(options, *, live_answer_ask=None) -> int:
        captured["options"] = options
        evidence_dir = tmp_path / "live" / "evidence"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "evidence_regression_report.json").write_text(
            json.dumps({"passed": True}),
            encoding="utf-8",
        )
        (evidence_dir / "evidence_regression_report.md").write_text("passed\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(live_answer_eval, "write_ci_eval_fixture_papers", fake_write_ci_eval_fixture_papers)
    monkeypatch.setattr(live_answer_eval, "run_evidence_eval_core", fake_run_evidence_eval_core)

    result = run_live_answer_eval(
        output_dir=tmp_path / "live",
        answer_eval_limit=10,
        live_answer_ask=lambda pair: {},
    )

    assert result.passed is True
    assert captured["options"].answer_eval_limit == 10


def test_run_live_answer_eval_requires_external_golden_set_and_papers_dir_together(tmp_path) -> None:
    with pytest.raises(ValueError, match="must be provided together"):
        run_live_answer_eval(output_dir=tmp_path / "live", golden_set_path=tmp_path / "golden.json")


def test_run_live_answer_eval_cli_passes_external_golden_set_options(tmp_path, monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}
    golden_set = tmp_path / "golden.json"
    papers_dir = tmp_path / "papers"

    class _FakeResult:
        passed = True

        def to_dict(self) -> dict:
            return {"passed": True, "corpus_mode": "external"}

    def fake_run_live_answer_eval(**kwargs):
        captured.update(kwargs)
        return _FakeResult()

    monkeypatch.setattr(live_answer_cli, "run_live_answer_eval", fake_run_live_answer_eval)

    exit_code = live_answer_cli.main([
        "--golden-set",
        str(golden_set),
        "--papers-dir",
        str(papers_dir),
        "--output-dir",
        str(tmp_path / "out"),
        "--answer-eval-limit",
        "10",
    ])

    assert exit_code == 0
    assert captured["golden_set_path"] == golden_set
    assert captured["papers_dir"] == papers_dir
    assert captured["answer_eval_limit"] == 10
    payload = json.loads(capsys.readouterr().out)
    assert payload["corpus_mode"] == "external"
