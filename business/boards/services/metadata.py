from __future__ import annotations

from typing import Any

from pydantic import Field

from business.boards.services.refs import BoardRunReferences
from business.foundation import PrimitiveModel
from business.layers.output import BoardOutput


class BoardRunMetadataPayload(PrimitiveModel):
    schema_version: str = "business.board.run.metadata.v1"
    board_output: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    memory_refs: list[dict[str, Any]] = Field(default_factory=list)
    pipeline_snapshot: dict[str, Any] = Field(default_factory=dict)
    legacy_pipeline_fields: dict[str, Any] = Field(default_factory=dict)

    def to_result_metadata(self) -> dict[str, Any]:
        return {
            "board_output": dict(self.board_output),
            "artifact_refs": [dict(ref) for ref in self.artifact_refs],
            "evidence_refs": [dict(ref) for ref in self.evidence_refs],
            "memory_refs": [dict(ref) for ref in self.memory_refs],
            "pipeline_snapshot": dict(self.pipeline_snapshot),
            **dict(self.legacy_pipeline_fields),
        }


class BoardRunMetadataBuilder:
    def build(
        self,
        *,
        output: BoardOutput,
        refs: BoardRunReferences,
        pipeline_snapshot: dict[str, Any],
    ) -> BoardRunMetadataPayload:
        return BoardRunMetadataPayload(
            board_output=output.to_dict(),
            artifact_refs=[ref.to_dict() for ref in refs.artifact_refs],
            evidence_refs=[ref.to_dict() for ref in refs.evidence_refs],
            memory_refs=[ref.to_dict() for ref in refs.memory_refs],
            pipeline_snapshot=pipeline_snapshot,
            legacy_pipeline_fields=legacy_pipeline_metadata(pipeline_snapshot),
        )


def legacy_pipeline_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "processed_relations": list(snapshot["processed_relations"]),
        "rejected_relations": list(snapshot["rejected_relations"]),
        "analysis": dict(snapshot["analysis"]),
    }


__all__ = ["BoardRunMetadataBuilder", "BoardRunMetadataPayload", "legacy_pipeline_metadata"]
