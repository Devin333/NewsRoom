from __future__ import annotations

import json
from pathlib import Path

from business.research.rag.evaluation.paper_parser_bakeoff_report import (
    ParserArtifactInput,
    ParserBakeoffReportConfig,
    build_parser_bakeoff_report,
)


def test_build_parser_bakeoff_report_summarizes_parser_artifacts(tmp_path: Path) -> None:
    parser_dir = tmp_path / "papers-marker"
    _write_doc(
        parser_dir / "paper1" / "research_document.json",
        paper_id="paper1",
        sections=[{"text": "hello world", "metadata": {"source_locator": "pdf#page=1"}}],
        figures=[{
            "caption": "Figure 1",
            "image_ref": "fig.png",
            "source_ref": "pdf#page=1",
            "metadata": {"source_locator": "pdf#page=1", "pdf_rect": [1, 2, 3, 4]},
        }],
        tables=[{
            "caption": "Table 1",
            "rows": [{"Model": "base"}],
            "source_ref": "pdf#page=1",
            "metadata": {"source_locator": "pdf#page=1", "pdf_rect": [1, 2, 3, 4]},
        }],
        equations=[{
            "latex": "E=mc^2",
            "source_ref": "pdf#page=1",
            "metadata": {"source_locator": "pdf#page=1", "pdf_rect": [1, 2, 3, 4]},
        }],
    )
    rag_report = tmp_path / "benchmark_suite_report.json"
    rag_report.write_text(
        json.dumps({
            "reports": {
                "candidate": {
                    "metrics": {
                        "mrr": 0.5,
                        "by_k": {
                            "3": {"hit_rate": 0.3},
                            "5": {"hit_rate": 0.5, "ndcg": 0.4, "evidence_coverage": 0.6, "source_locator_coverage": 1.0},
                            "10": {"hit_rate": 0.8, "evidence_coverage": 0.7, "source_locator_coverage": 1.0},
                        },
                    },
                    "by_qa_type": {
                        "table_qa": {"by_k": {"5": {"evidence_coverage": 0.9}}},
                        "figure_qa": {"by_k": {"5": {"evidence_coverage": 0.8}}},
                        "formula_explanation_qa": {"mrr": 0.6},
                    },
                }
            }
        }),
        encoding="utf-8",
    )

    report = build_parser_bakeoff_report(ParserBakeoffReportConfig(
        inputs=(ParserArtifactInput("marker", parser_dir, rag_report),),
        output_json=tmp_path / "report.json",
        output_markdown=tmp_path / "report.md",
    ))

    payload = report.to_dict()
    metrics = payload["parsers"]["marker"]["parser_metrics"]
    assert metrics["parse_success_rate"] == 1.0
    assert metrics["section_count_avg"] == 1.0
    assert metrics["table_rows_coverage"] == 1.0
    assert metrics["image_ref_coverage"] == 1.0
    assert metrics["element_source_locator_coverage"] == 1.0
    assert metrics["bbox_coverage"] == 1.0
    assert payload["parsers"]["marker"]["rag_metrics"]["hit_at_5"] == 0.5
    assert payload["parsers"]["marker"]["rag_metrics"]["table_qa_evidence_coverage_at_5"] == 0.9
    assert (tmp_path / "report.json").exists()
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Parser-Level Metrics" in markdown
    assert "RAG-Level Metrics" in markdown


def test_build_parser_bakeoff_report_reads_benchmark_suite_candidate_schema(tmp_path: Path) -> None:
    parser_dir = tmp_path / "papers-marker"
    _write_doc(
        parser_dir / "paper1" / "research_document.json",
        paper_id="paper1",
        sections=[{"text": "hello world"}],
        figures=[],
        tables=[],
        equations=[],
    )
    rag_report = tmp_path / "benchmark_suite_report.json"
    rag_report.write_text(
        json.dumps({
            "papers_total": 20,
            "chunks_total": 100,
            "pairs_total": 50,
            "evaluation_protocol": {"reported_split": "test"},
            "candidate_test_report": {
                "retrieval": {
                    "mrr": 0.55,
                    "by_k": {
                        "3": {"hit_rate": 0.7},
                        "5": {
                            "hit_rate": 0.75,
                            "ndcg": 0.6,
                            "evidence_coverage": 0.72,
                            "source_locator_coverage": 0.82,
                        },
                        "10": {
                            "hit_rate": 0.84,
                            "equivalent_hit_rate": 0.92,
                            "evidence_coverage": 0.8,
                            "source_locator_coverage": 0.9,
                        },
                    },
                    "by_qa_type": {
                        "table_qa": {"by_k": {"5": {"evidence_coverage": 0.91}}},
                        "figure_qa": {"by_k": {"5": {"evidence_coverage": 0.81}}},
                        "formula_explanation_qa": {"mrr": 0.61},
                    },
                }
            },
        }),
        encoding="utf-8",
    )

    report = build_parser_bakeoff_report(ParserBakeoffReportConfig(
        inputs=(ParserArtifactInput("marker", parser_dir, rag_report),),
        output_json=tmp_path / "report.json",
        output_markdown=tmp_path / "report.md",
    ))

    rag_metrics = report.to_dict()["parsers"]["marker"]["rag_metrics"]
    assert rag_metrics["papers_total"] == 20
    assert rag_metrics["pairs_total"] == 50
    assert rag_metrics["hit_at_3"] == 0.7
    assert rag_metrics["hit_at_10"] == 0.84
    assert rag_metrics["equivalent_hit_at_10"] == 0.92
    assert rag_metrics["mrr"] == 0.55
    assert rag_metrics["table_qa_evidence_coverage_at_5"] == 0.91
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "84.0%" in markdown
    assert "0.55" in markdown


def test_bakeoff_report_uses_artifact_directory_as_canonical_paper_id(tmp_path: Path) -> None:
    parser_dir = tmp_path / "papers-marker"
    _write_doc(
        parser_dir / "1706.03762" / "research_document.json",
        paper_id="1706.03762_marker_smoke",
        sections=[],
        figures=[],
        tables=[],
        equations=[],
    )

    report = build_parser_bakeoff_report(ParserBakeoffReportConfig(
        inputs=(ParserArtifactInput("marker", parser_dir),),
        output_json=tmp_path / "report.json",
        output_markdown=tmp_path / "report.md",
    ))

    payload = report.to_dict()
    assert payload["paper_ids"] == ["1706.03762"]
    assert payload["parsers"]["marker"]["paper_ids"] == ["1706.03762"]
    assert payload["parsers"]["marker"]["paper_id_mismatches"] == [{
        "artifact_paper_id": "1706.03762",
        "reported_paper_id": "1706.03762_marker_smoke",
    }]


def test_bakeoff_report_uses_ingest_manifest_for_requested_and_failed_items(tmp_path: Path) -> None:
    parser_dir = tmp_path / "papers-mineru"
    _write_doc(
        parser_dir / "paper1" / "research_document.json",
        paper_id="paper1",
        sections=[],
        figures=[],
        tables=[],
        equations=[],
    )
    manifest_path = tmp_path / "mineru-ingest.json"
    manifest_path.write_text(
        json.dumps({
            "backend": "mineru",
            "papers_dir": str(parser_dir),
            "requested": 2,
            "succeeded": 1,
            "skipped": 0,
            "failed": 1,
            "items": [
                {
                    "arxiv_id": "paper1",
                    "paper_id": "paper1",
                    "status": "succeeded",
                    "backend": "mineru",
                    "output_path": str(parser_dir / "paper1" / "research_document.json"),
                },
                {
                    "arxiv_id": "paper2",
                    "paper_id": "paper2",
                    "status": "failed",
                    "backend": "mineru",
                    "reason": "RuntimeError: docker parser failed (exit 1)",
                    "output_path": str(parser_dir / "paper2" / "research_document.json"),
                },
            ],
        }),
        encoding="utf-8",
    )

    report = build_parser_bakeoff_report(ParserBakeoffReportConfig(
        inputs=(ParserArtifactInput("mineru", parser_dir, ingest_manifest_path=manifest_path),),
        output_json=tmp_path / "report.json",
        output_markdown=tmp_path / "report.md",
    ))

    payload = report.to_dict()
    parser_payload = payload["parsers"]["mineru"]
    metrics = parser_payload["parser_metrics"]
    assert payload["paper_ids"] == ["paper1", "paper2"]
    assert parser_payload["paper_count"] == 2
    assert parser_payload["artifact_document_count"] == 1
    assert metrics["parse_requested_count"] == 2
    assert metrics["parse_success_count"] == 1
    assert metrics["parse_success_rate"] == 0.5
    assert parser_payload["failed_items"][0]["paper_id"] == "paper2"
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "50.0% (1/2)" in markdown
    assert "failed `paper2`" in markdown


def _write_doc(
    path: Path,
    *,
    paper_id: str,
    sections: list[dict[str, object]],
    figures: list[dict[str, object]],
    tables: list[dict[str, object]],
    equations: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "paper_id": paper_id,
            "source_hash": "hash",
            "sections": sections,
            "figures": figures,
            "tables": tables,
            "equations": equations,
            "lineage": {"source_refs": ["pdf"], "source_hash": "hash"},
            "metadata": {
                "parser_duration_seconds": 1.5,
                "parser_warnings": [],
            },
        }),
        encoding="utf-8",
    )
