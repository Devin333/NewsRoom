from __future__ import annotations

from typing import Any

from business.foundation import AnalysisContext, BoardDefinition, BoardType
from business.layers.output import BoardOutput


class BoardOutputAnnotationService:
    def annotate(
        self,
        output: BoardOutput,
        *,
        board_type: BoardType,
        board_definition: BoardDefinition,
        context: AnalysisContext,
        signals: list[Any],
        extraction_results: list[Any],
        relation_result: Any,
        analysis: Any,
        report_title: str,
        report_summary: str,
    ) -> None:
        output.metadata.update(
            {
                "board_type": board_type.value,
                "board_name": board_definition.name,
                "board_definition": board_definition.to_dict(),
                "signal_count": len(signals),
                "selection": {
                    "signal_types": list(board_definition.signal_types),
                    "visible_sections": list(board_definition.visible_sections),
                },
                "extraction_count": len(extraction_results),
                "relation_count": len(relation_result.relations),
                "rejected_relation_count": len(relation_result.rejected_candidates),
                "analysis_metadata": dict(analysis.metadata),
                "report": {
                    **dict(output.metadata.get("report") or {}),
                    "board_type": board_type.value,
                    "board_name": board_definition.name,
                    "title": report_title,
                    "summary": report_summary,
                },
                "context": context.to_dict(),
            }
        )


__all__ = ["BoardOutputAnnotationService"]
