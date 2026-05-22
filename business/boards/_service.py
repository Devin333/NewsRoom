from __future__ import annotations

from typing import Any

from business.foundation import (
    AnalysisContext,
    BusinessArtifactRef,
    BusinessEvidenceRef,
    BusinessMemoryRef,
    BoardRegistry,
    BoardRunResult,
    BoardType,
    BusinessFeedbackEvent,
    BusinessPolicySnapshot,
    BusinessQualityCheck,
    BusinessQualitySnapshot,
    PolicyLoader,
    Report,
    Signal,
    SourceRef,
    SourceReliability,
    SourceType,
    create_policy_snapshot,
    quality_snapshot_from_checks,
)
from business.foundation.registry import default_board_registry
from business.layers.analysis import AnalysisPipeline, AnalysisResult
from business.layers.extraction import ExtractionPipeline, ExtractionResult
from business.layers.output import BoardOutput, BoardOutputPipeline
from business.layers.relation import RelationPipeline, RelationPipelineResult
from business.layers.signal import SignalPipeline


class BoardServiceBase:
    board_type: BoardType

    def __init__(
        self,
        *,
        board_registry: BoardRegistry | None = None,
        extraction_pipeline: ExtractionPipeline | None = None,
        relation_pipeline: RelationPipeline | None = None,
        analysis_pipeline: AnalysisPipeline | None = None,
        output_pipeline: BoardOutputPipeline | None = None,
    ) -> None:
        self.board_registry = board_registry or default_board_registry()
        self.board_definition = self.board_registry.get(self.board_type)
        self.extraction_pipeline = extraction_pipeline or ExtractionPipeline()
        self.relation_pipeline = relation_pipeline or RelationPipeline()
        self.analysis_pipeline = analysis_pipeline or AnalysisPipeline()
        self.output_pipeline = output_pipeline or BoardOutputPipeline()
        self.signal_pipeline = SignalPipeline()
        self.policy_loader = PolicyLoader()

    def build_board_output(
        self,
        signals: list[Signal],
        *,
        context: AnalysisContext | None = None,
    ) -> BoardOutput:
        resolved_context = self._resolve_context(context)
        _selected_signals, _extraction_results, _relation_result, _analysis, output = self._run_pipeline_for_output(
            signals,
            context=resolved_context,
        )
        return output

    def build_report(
        self,
        signals: list[Signal],
        *,
        context: AnalysisContext | None = None,
    ) -> Report:
        output = self.build_board_output(signals, context=context)
        report_payload = dict(output.metadata.get("report") or {})
        if not report_payload:
            raise ValueError("board output does not include a report payload")
        return Report.model_validate(report_payload)

    def build_board_run_result(
        self,
        signals: list[Signal],
        *,
        context: AnalysisContext | None = None,
    ) -> BoardRunResult:
        resolved_context = self._resolve_context(context)
        selected_signals, extraction_results, relation_result, analysis, output = self._run_pipeline_for_output(
            signals,
            context=resolved_context,
        )
        result = self._build_base_board_run_result(
            output=output,
            context=resolved_context,
            signals=selected_signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
        )
        return self.apply_board_specific_policy(result)

    def _run_pipeline_for_selected_signals(
        self,
        selected_signals: list[Signal],
        *,
        context: AnalysisContext,
    ) -> tuple[list[ExtractionResult], RelationPipelineResult, AnalysisResult, BoardOutput]:
        extraction_results = self.extraction_pipeline.run(selected_signals, context)
        relation_result = self.relation_pipeline.run(
            selected_signals,
            extraction_results,
            context=context,
        )
        analysis = self.analysis_pipeline.run(
            selected_signals,
            extraction_results,
            relation_result.relations,
            context,
        )
        output = self.output_pipeline.build_board_output(
            self.board_type,
            selected_signals,
            extraction_results,
            relation_result.relations,
            analysis,
            context,
        )
        self._annotate_output(
            output,
            context=context,
            signals=selected_signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
        )
        output = self._postprocess_board_output(
            output,
            context=context,
            signals=selected_signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
        )
        return extraction_results, relation_result, analysis, output

    def _build_base_board_run_result(
        self,
        *,
        output: BoardOutput,
        context: AnalysisContext,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relation_result: RelationPipelineResult,
        analysis: AnalysisResult,
    ) -> BoardRunResult:
        run_id = _run_id(context, self.board_type)
        policy_snapshot = create_policy_snapshot(
            run_id,
            self.policy_loader.active_profiles(board_type=self.board_type),
        )
        report_payload = output.metadata.get("report")
        reports = [Report.model_validate(_report_payload_for_validation(report_payload))] if isinstance(report_payload, dict) else []
        quality_summary = self._quality_summary(output)
        feedback_candidates = self._feedback_candidates(output, quality_summary, policy_snapshot)
        trace_ref = _run_source_ref(run_id, "workflow_trace", self.board_type)
        manifest_ref = _run_source_ref(run_id, "run_manifest", self.board_type)
        artifact_refs = _artifact_refs(run_id, self.board_type, trace_ref=trace_ref, manifest_ref=manifest_ref)
        evidence_refs = _evidence_refs(signals, relation_result.relations)
        memory_refs = _memory_refs(context, self.board_type)
        result = BoardRunResult(
            board_type=self.board_type,
            run_id=run_id,
            cards=list(output.cards),
            detail_pages=list(output.detail_pages),
            insights=list(output.insights),
            reports=reports,
            policy_snapshot=policy_snapshot,
            quality_summary=quality_summary,
            feedback_candidates=feedback_candidates,
            trace_ref=trace_ref,
            manifest_ref=manifest_ref,
            artifact_refs=artifact_refs,
            evidence_refs=evidence_refs,
            memory_refs=memory_refs,
            metadata={
                "board_output": output.to_dict(),
                "artifact_refs": [ref.to_dict() for ref in artifact_refs],
                "evidence_refs": [ref.to_dict() for ref in evidence_refs],
                "memory_refs": [ref.to_dict() for ref in memory_refs],
            },
        )
        return self._postprocess_run_result(
            result,
            output=output,
            context=context,
            signals=signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
        )

    def apply_board_specific_policy(self, result: BoardRunResult) -> BoardRunResult:
        return result

    def _run_pipeline_for_output(
        self,
        signals: list[Any],
        *,
        context: AnalysisContext,
    ) -> tuple[list[Signal], list[ExtractionResult], RelationPipelineResult, AnalysisResult, BoardOutput]:
        selected_signals = self._select_signals(signals, context=context)
        extraction_results, relation_result, analysis, output = self._run_pipeline_for_selected_signals(
            selected_signals,
            context=context,
        )
        return selected_signals, extraction_results, relation_result, analysis, output

    def _postprocess_board_output(
        self,
        output: BoardOutput,
        *,
        context: AnalysisContext,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relation_result: RelationPipelineResult,
        analysis: AnalysisResult,
    ) -> BoardOutput:
        return output

    def _postprocess_run_result(
        self,
        result: BoardRunResult,
        *,
        output: BoardOutput,
        context: AnalysisContext,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relation_result: RelationPipelineResult,
        analysis: AnalysisResult,
    ) -> BoardRunResult:
        metadata = {
            **dict(result.metadata),
            "processed_relations": [relation.to_dict() for relation in relation_result.relations],
            "rejected_relations": [rejected.to_dict() for rejected in relation_result.rejected_candidates],
            "analysis": analysis.to_dict(),
        }
        return result.model_copy(update={"metadata": metadata})

    def _resolve_context(self, context: AnalysisContext | None) -> AnalysisContext:
        if context is None:
            return AnalysisContext(board_type=self.board_type)
        if context.board_type == self.board_type:
            return context
        return context.for_board(self.board_type)

    def _select_signals(self, signals: list[Any], *, context: AnalysisContext) -> list[Signal]:
        coerced = self.signal_pipeline.coerce_signals(
            list(signals),
            context=context,
            board_type=self.board_type,
        ).signals
        if self.board_type == BoardType.CROSS_BOARD:
            return sorted(coerced, key=_signal_sort_key, reverse=True)
        selected = [
            signal
            for signal in coerced
            if signal.board_type == self.board_type
            or signal.signal_type.value in self.board_definition.signal_types
        ]
        return sorted(selected, key=_signal_sort_key, reverse=True)

    def _annotate_output(
        self,
        output: BoardOutput,
        *,
        context: AnalysisContext,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relation_result: RelationPipelineResult,
        analysis: AnalysisResult,
    ) -> None:
        output.metadata.update(
            {
                "board_type": self.board_type.value,
                "board_name": self.board_definition.name,
                "board_definition": self.board_definition.to_dict(),
                "signal_count": len(signals),
                "selection": {
                    "signal_types": list(self.board_definition.signal_types),
                    "visible_sections": list(self.board_definition.visible_sections),
                },
                "extraction_count": len(extraction_results),
                "relation_count": len(relation_result.relations),
                "rejected_relation_count": len(relation_result.rejected_candidates),
                "analysis_metadata": dict(analysis.metadata),
                "report": {
                    **dict(output.metadata.get("report") or {}),
                    "board_type": self.board_type.value,
                    "board_name": self.board_definition.name,
                    "title": self._report_title(),
                    "summary": self._report_summary(),
                },
                "context": context.to_dict(),
            }
        )

    def _report_title(self) -> str:
        return f"{self.board_definition.name} Report"

    def _report_summary(self) -> str:
        description = self.board_definition.description or self.board_definition.name
        return f"{description} generated from normalized signals."

    def _quality_summary(self, output: BoardOutput) -> BusinessQualitySnapshot:
        checks = [
            BusinessQualityCheck.create(
                "board_has_policy_compatible_cards",
                passed=all(card.ranking_reason for card in output.cards),
                severity="error",
                reason="Every board card must include ranking_reason.",
                observed={"card_count": len(output.cards)},
            ),
            BusinessQualityCheck.create(
                "top_cards_have_evidence",
                passed=all(card.evidence_refs for card in output.cards[:3]),
                severity="error",
                reason="Top cards must include evidence_refs.",
                observed={"top_card_count": len(output.cards[:3])},
            ),
        ]
        score = 1.0 if all(check.passed for check in checks) else 0.5
        return quality_snapshot_from_checks(checks, score=score, confidence=0.8)

    def _feedback_candidates(
        self,
        output: BoardOutput,
        quality_summary: BusinessQualitySnapshot,
        policy_snapshot: BusinessPolicySnapshot,
    ) -> list[BusinessFeedbackEvent]:
        events: list[BusinessFeedbackEvent] = []
        for check in quality_summary.checks:
            if check.passed:
                continue
            events.append(
                BusinessFeedbackEvent.create(
                    target_object_type="board_run",
                    target_object_id=output.board_type.value,
                    target_layer="board",
                    board_type=output.board_type.value,
                    feedback_type=check.check_type,
                    severity=check.severity,
                    observed=check.observed,
                    expected=check.expected,
                    error_tags=[check.check_type],
                    evidence_refs=list(check.evidence_refs),
                    related_policy_profile_id=policy_snapshot.profiles[0].profile_id if policy_snapshot.profiles else None,
                    related_policy_profile_version=policy_snapshot.profiles[0].version if policy_snapshot.profiles else None,
                )
            )
        return events


def _signal_sort_key(signal: Signal) -> tuple[int, str, str]:
    published_at = signal.published_at
    timestamp = int(published_at.timestamp()) if published_at is not None else 0
    return timestamp, signal.signal_id, signal.title


def _run_id(context: AnalysisContext, board_type: BoardType) -> str:
    run_context = getattr(context, "run_context", None)
    if run_context is not None and getattr(run_context, "run_id", None):
        return str(run_context.run_id)
    return f"{board_type.value}-run"


def _report_payload_for_validation(payload: dict[str, object]) -> dict[str, object]:
    cleaned = _drop_serialized_computed_fields(payload)
    if isinstance(cleaned, dict):
        cleaned.pop("board_name", None)
        return cleaned
    return dict(payload)


def _drop_serialized_computed_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _drop_serialized_computed_fields(item)
            for key, item in value.items()
            if key != "level"
        }
    if isinstance(value, list):
        return [_drop_serialized_computed_fields(item) for item in value]
    return value


def _run_source_ref(run_id: str, ref_type: str, board_type: BoardType) -> SourceRef:
    return SourceRef(
        source_name=f"{board_type.value}:{ref_type}",
        source_type=SourceType.MANUAL,
        url=f"business://{board_type.value}/{run_id}/{ref_type}",
        reliability=SourceReliability.HIGH,
        external_id=run_id,
    )


def _artifact_refs(
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


def _evidence_refs(signals: list[Signal], relations) -> list[BusinessEvidenceRef]:
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


def _memory_refs(context: AnalysisContext, board_type: BoardType) -> list[BusinessMemoryRef]:
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
