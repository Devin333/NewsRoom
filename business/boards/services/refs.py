from __future__ import annotations

from dataclasses import dataclass

from business.foundation import (
    AnalysisContext,
    BusinessArtifactRef,
    BusinessEvidenceRef,
    BusinessMemoryRef,
    BoardType,
    Signal,
    SourceRef,
    SourceReliability,
    SourceType,
)


@dataclass(frozen=True)
class BoardRunReferences:
    trace_ref: SourceRef
    manifest_ref: SourceRef
    artifact_refs: list[BusinessArtifactRef]
    evidence_refs: list[BusinessEvidenceRef]
    memory_refs: list[BusinessMemoryRef]


class BoardRunReferenceService:
    def build(
        self,
        *,
        run_id: str,
        board_type: BoardType,
        context: AnalysisContext,
        signals: list[Signal],
        relations,
    ) -> BoardRunReferences:
        trace_ref = self.run_source_ref(run_id, "workflow_trace", board_type)
        manifest_ref = self.run_source_ref(run_id, "run_manifest", board_type)
        return BoardRunReferences(
            trace_ref=trace_ref,
            manifest_ref=manifest_ref,
            artifact_refs=self.artifact_refs(
                run_id,
                board_type,
                trace_ref=trace_ref,
                manifest_ref=manifest_ref,
            ),
            evidence_refs=self.evidence_refs(signals, relations),
            memory_refs=self.memory_refs(context, board_type),
        )

    def run_source_ref(self, run_id: str, ref_type: str, board_type: BoardType) -> SourceRef:
        return SourceRef(
            source_name=f"{board_type.value}:{ref_type}",
            source_type=SourceType.MANUAL,
            url=f"business://{board_type.value}/{run_id}/{ref_type}",
            reliability=SourceReliability.HIGH,
            external_id=run_id,
        )

    def artifact_refs(
        self,
        run_id: str,
        board_type: BoardType,
        *,
        trace_ref: SourceRef,
        manifest_ref: SourceRef,
    ) -> list[BusinessArtifactRef]:
        return [
            BusinessArtifactRef.create(
                "board_output",
                label=f"{board_type.value} board output",
                uri=f"business://{board_type.value}/{run_id}/board_output",
                run_id=run_id,
                trace_ref=trace_ref,
                manifest_ref=manifest_ref,
                metadata={
                    "board_type": board_type.value,
                    "run_id": run_id,
                    "artifact_type": "board_output",
                },
            )
        ]

    def evidence_refs(self, signals: list[Signal], relations) -> list[BusinessEvidenceRef]:
        relation_ids_by_signal: dict[str, list[str]] = {}
        for relation in relations:
            for signal_id in relation.evidence_signal_ids:
                relation_ids_by_signal.setdefault(signal_id, []).append(relation.relation_id)
        refs: list[BusinessEvidenceRef] = []
        for signal in signals:
            refs.append(
                BusinessEvidenceRef.from_source(
                    signal.source,
                    signal_ids=[signal.signal_id],
                    relation_ids=relation_ids_by_signal.get(signal.signal_id, []),
                    confidence=signal.confidence.value if signal.confidence is not None else None,
                    metadata={"board_type": signal.board_type.value, "signal_type": signal.signal_type.value},
                )
            )
        return refs

    def memory_refs(self, context: AnalysisContext, board_type: BoardType) -> list[BusinessMemoryRef]:
        topic = context.metadata.get("topic") if isinstance(context.metadata, dict) else None
        if not topic:
            return []
        return [
            BusinessMemoryRef.create(
                memory_type="analysis_context",
                query=str(topic),
                score=0.75,
                metadata={"board_type": board_type.value},
            )
        ]


__all__ = ["BoardRunReferenceService", "BoardRunReferences"]
