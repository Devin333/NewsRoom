from __future__ import annotations

from typing import Any

from pydantic import Field

from business.boards.application.result import BoardRunApplicationResult
from business.boards.services.refs import BoardRunReferences
from business.foundation import BoardRunPipelineSnapshot
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
        application_result: BoardRunApplicationResult | None = None,
        output: BoardOutput | None = None,
        refs: BoardRunReferences | None = None,
        pipeline_snapshot: BoardRunPipelineSnapshot | dict[str, Any] | None = None,
    ) -> BoardRunMetadataPayload:
        if application_result is not None:
            output = application_result.output
            refs = application_result.refs
            pipeline_snapshot = application_result.pipeline_snapshot
        if output is None or refs is None or pipeline_snapshot is None:
            raise ValueError("application_result or output/refs/pipeline_snapshot is required")
        snapshot_payload = _pipeline_snapshot_payload(pipeline_snapshot)
        return BoardRunMetadataPayload(
            board_output=output.to_dict(),
            artifact_refs=[ref.to_dict() for ref in refs.artifact_refs],
            evidence_refs=[ref.to_dict() for ref in refs.evidence_refs],
            memory_refs=[ref.to_dict() for ref in refs.memory_refs],
            pipeline_snapshot=snapshot_payload,
            legacy_pipeline_fields=legacy_pipeline_metadata(pipeline_snapshot),
        )


def legacy_pipeline_metadata(snapshot: BoardRunPipelineSnapshot | dict[str, Any]) -> dict[str, Any]:
    payload = _pipeline_snapshot_payload(snapshot)
    return {
        "processed_relations": list(payload["processed_relations"]),
        "rejected_relations": list(payload["rejected_relations"]),
        "analysis": dict(payload["analysis"]),
    }


def _pipeline_snapshot_payload(snapshot: BoardRunPipelineSnapshot | dict[str, Any]) -> dict[str, Any]:
    if isinstance(snapshot, BoardRunPipelineSnapshot):
        return snapshot.to_dict()
    return dict(snapshot)


__all__ = ["BoardRunMetadataBuilder", "BoardRunMetadataPayload", "legacy_pipeline_metadata"]
