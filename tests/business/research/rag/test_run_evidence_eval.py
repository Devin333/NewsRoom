from __future__ import annotations

import json

from business.research.rag.evaluation.paper_evidence_eval import EvidenceQAPair, save_evidence_golden_set
from business.research.rag.cli.run_evidence_eval import main


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


def test_run_evidence_eval_can_run_live_retrieval_from_parsed_papers(tmp_path) -> None:
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "p1"
    paper_dir.mkdir(parents=True)
    (paper_dir / "research_document.json").write_text(
        json.dumps(_research_document_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    golden = tmp_path / "golden.json"
    output = tmp_path / "report"

    exit_code = main([
        "--papers-dir",
        str(papers_dir),
        "--build-golden-set",
        "--golden-set",
        str(golden),
        "--live-retrieval",
        "--output-dir",
        str(output),
    ])

    assert exit_code == 0
    payload = json.loads((output / "evidence_regression_report.json").read_text(encoding="utf-8"))
    assert payload["metadata"]["mode"] == "live_retrieval"
    assert payload["metadata"]["chunks_total"] > 0
    assert payload["retrieval"]["answerable_total"] > 0
    distribution = payload["retrieval"]["field_embedding_distribution"]
    assert distribution["search_hits_by_field"]
    assert distribution["matched_evidence_count"] > 0
    components = payload["retrieval"]["score_breakdown_summary"]["components"]
    embedding_components = {
        name: stats
        for name, stats in components.items()
        if name.endswith("_embedding_score")
    }
    assert embedding_components
    assert any(stats["max"] > 0 for stats in embedding_components.values())
    assert golden.exists()


def test_run_evidence_eval_live_retrieval_can_enable_visual_index(tmp_path) -> None:
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "p1"
    image_dir = paper_dir / "figures"
    image_dir.mkdir(parents=True)
    (image_dir / "arch.png").write_bytes(b"not-a-real-image")
    payload = _research_document_payload()
    payload["figures"][0]["image_ref"] = "figures/arch.png"
    (paper_dir / "research_document.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    output = tmp_path / "report"

    exit_code = main([
        "--papers-dir",
        str(papers_dir),
        "--build-golden-set",
        "--live-retrieval",
        "--visual",
        "--image-root",
        str(papers_dir),
        "--output-dir",
        str(output),
    ])

    assert exit_code == 0
    report = json.loads((output / "evidence_regression_report.json").read_text(encoding="utf-8"))
    assert report["metadata"]["visual_fusion_enabled"] is True
    assert report["metadata"]["visual_indexed_chunks"] == 1


def test_run_evidence_eval_can_add_page_visual_chunks(tmp_path) -> None:
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "p1"
    image_dir = paper_dir / "figures"
    page_dir = paper_dir / "page_images"
    image_dir.mkdir(parents=True)
    page_dir.mkdir(parents=True)
    (image_dir / "arch.png").write_bytes(b"not-a-real-image")
    (page_dir / "p1_page_001.png").write_bytes(b"fake-page-image")
    payload = _research_document_payload()
    payload["figures"][0]["image_ref"] = "figures/arch.png"
    (paper_dir / "research_document.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    output = tmp_path / "report"

    exit_code = main([
        "--papers-dir",
        str(papers_dir),
        "--build-golden-set",
        "--live-retrieval",
        "--visual",
        "--page-visual",
        "--no-render-page-visual",
        "--image-root",
        str(papers_dir),
        "--output-dir",
        str(output),
    ])

    assert exit_code == 0
    report = json.loads((output / "evidence_regression_report.json").read_text(encoding="utf-8"))
    assert report["metadata"]["page_visual_enabled"] is True
    assert report["metadata"]["page_visual_chunks"] == 1
    assert report["metadata"]["visual_indexed_chunks"] == 2


def test_run_evidence_eval_records_retrieval_policy_metadata(tmp_path) -> None:
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "p1"
    paper_dir.mkdir(parents=True)
    (paper_dir / "research_document.json").write_text(
        json.dumps(_research_document_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    output = tmp_path / "report"

    exit_code = main([
        "--papers-dir",
        str(papers_dir),
        "--build-golden-set",
        "--live-retrieval",
        "--retrieval-policy",
        "paper_visual_rag_tuned",
        "--output-dir",
        str(output),
    ])

    assert exit_code == 0
    report = json.loads((output / "evidence_regression_report.json").read_text(encoding="utf-8"))
    metadata = report["metadata"]
    assert metadata["retrieval_policy"] == "paper_visual_rag_tuned"
    assert metadata["retrieval_policy_overfetch_multiplier"] == 5
    assert metadata["retrieval_policy_child_score_weights"] == {
        "semantic": 0.45,
        "field": 0.4,
        "position": 0.05,
        "graph": 0.1,
    }
    assert metadata["retrieval_policy_visual_fusion_weights"] == {
        "text": 0.85,
        "visual": 0.15,
    }


def _research_document_payload() -> dict:
    return {
        "paper_id": "p1",
        "source_hash": "hash",
        "sections": [
            {
                "section_id": "abstract",
                "title": "Abstract",
                "level": 1,
                "text": "This paper introduces a visual architecture.",
                "source_ref": "paper://p1/abstract",
            },
            {
                "section_id": "intro",
                "title": "Introduction",
                "level": 1,
                "text": "The visual architecture is shown in Figure 1. It improves retrieval.",
                "source_ref": "paper://p1/intro",
            },
            {
                "section_id": "method",
                "title": "Method",
                "level": 1,
                "text": "The model architecture uses encoder and decoder blocks.",
                "source_ref": "paper://p1/method",
            },
            {
                "section_id": "results",
                "title": "Results",
                "level": 1,
                "text": "Table 1 reports stronger accuracy and the conclusion confirms the gain.",
                "source_ref": "paper://p1/results",
            },
        ],
        "figures": [
            {
                "figure_id": "fig1",
                "caption": "Figure 1: visual architecture overview.",
                "source_ref": "paper://p1/fig1",
                "image_ref": "figures/arch.png",
                "page": 1,
            }
        ],
        "tables": [
            {
                "table_id": "tbl1",
                "caption": "Table 1: accuracy results.",
                "source_ref": "paper://p1/tbl1",
                "columns": ["metric", "value"],
                "rows": [{"metric": "accuracy", "value": "95"}],
                "page": 2,
            }
        ],
        "equations": [
            {
                "equation_id": "eq1",
                "latex": "y = f(x)",
                "source_ref": "paper://p1/eq1",
                "page": 2,
            }
        ],
        "references": [],
        "lineage": {
            "source_refs": ["paper://p1"],
            "source_hash": "hash",
            "artifact_refs": [],
            "metadata": {},
        },
        "metadata": {"parse_source": "nougat"},
    }
