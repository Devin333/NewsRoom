from __future__ import annotations

import json

from business.research.rag.cli import check_live_answer_readiness as readiness_cli
from business.research.rag.evaluation.live_answer_readiness import (
    build_live_answer_readiness,
    write_live_answer_readiness,
)
from business.research.rag.evaluation.paper_evidence_eval import EvidenceQAPair, save_evidence_golden_set


def test_live_answer_readiness_writes_missing_secret_artifacts_without_leaking_values(tmp_path) -> None:
    golden_set = tmp_path / "golden.json"
    papers_dir = tmp_path / "papers"
    output_dir = tmp_path / "readiness"
    save_evidence_golden_set([
        EvidenceQAPair(
            question="What does the paper report?",
            paper_id="p1",
            qa_type="citation_qa",
            gold_chunk_ids=["p1-results"],
        )
    ], golden_set)

    result = write_live_answer_readiness(
        output_dir=output_dir,
        golden_set_path=golden_set,
        papers_dir=papers_dir,
        env={
            "OPENAI_BASE_URL": "https://secret.example/v1",
            "OPENAI_API_KEY": "",
            "OPENAI_MODEL": "gpt-readiness",
        },
    )

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert result.markdown_path.exists()
    assert payload["baseline_status"] == "missing_llm_secrets"
    assert payload["llm"]["required"]["OPENAI_BASE_URL"]["present"] is True
    assert payload["llm"]["required"]["OPENAI_API_KEY"]["present"] is False
    assert payload["eligibility"]["fixture_live_answer_eval"]["eligible"] is False
    assert "missing_llm_secrets:OPENAI_API_KEY" in payload["eligibility"]["fixture_live_answer_eval"]["reasons"]
    assert "https://secret.example/v1" not in serialized
    assert "sk-" not in serialized


def test_live_answer_readiness_summarizes_real_corpus_and_eligibility(tmp_path) -> None:
    golden_set = tmp_path / "golden.json"
    papers_dir = tmp_path / "papers"
    _write_research_document(papers_dir, "p1")
    _write_research_document(papers_dir, "p2")
    save_evidence_golden_set([
        EvidenceQAPair(
            question="What does the first paper report?",
            paper_id="p1",
            qa_type="citation_qa",
            gold_chunk_ids=["p1-results"],
        ),
        EvidenceQAPair.negative(
            question="Does the second paper discuss unrelated weather data?",
            paper_id="p2",
        ),
    ], golden_set)

    payload = build_live_answer_readiness(
        output_dir=tmp_path / "readiness",
        golden_set_path=golden_set,
        papers_dir=papers_dir,
        env={
            "OPENAI_BASE_URL": "https://secret.example/v1",
            "OPENAI_API_KEY": "sk-test-secret",
            "OPENAI_MODEL": "gpt-readiness",
        },
    )

    serialized = json.dumps(payload)
    assert payload["baseline_status"] == "ready"
    assert payload["llm"]["required_present"] is True
    assert payload["llm"]["optional"]["OPENAI_MODEL"]["value"] == "gpt-readiness"
    assert payload["golden_set"]["pair_count"] == 2
    assert payload["golden_set"]["expected_behavior_counts"] == {"abstain": 1, "answer": 1}
    assert payload["golden_set"]["distinct_paper_ids"] == 2
    assert payload["papers"]["research_document_count"] == 2
    assert payload["eligibility"]["fixture_live_answer_eval"]["eligible"] is True
    assert payload["eligibility"]["real_corpus_live_answer_eval"]["eligible"] is True
    assert "sk-test-secret" not in serialized
    assert "https://secret.example/v1" not in serialized


def test_check_live_answer_readiness_cli_writes_artifacts(tmp_path, monkeypatch, capsys) -> None:
    golden_set = tmp_path / "golden.json"
    papers_dir = tmp_path / "papers"
    output_dir = tmp_path / "readiness"
    save_evidence_golden_set([
        EvidenceQAPair(
            question="What does the paper report?",
            paper_id="p1",
            qa_type="citation_qa",
            gold_chunk_ids=["p1-results"],
        )
    ], golden_set)
    _write_research_document(papers_dir, "p1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://secret.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")

    exit_code = readiness_cli.main([
        "--output-dir",
        str(output_dir),
        "--golden-set",
        str(golden_set),
        "--papers-dir",
        str(papers_dir),
    ])

    assert exit_code == 0
    assert (output_dir / "readiness.json").exists()
    assert (output_dir / "readiness.md").exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline_status"] == "ready"


def _write_research_document(papers_dir, paper_id: str) -> None:
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
