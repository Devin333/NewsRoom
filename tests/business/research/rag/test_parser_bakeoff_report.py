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
    assert "Parser-Level Metrics" in (tmp_path / "report.md").read_text(encoding="utf-8")


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
