from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.artifact_sections import (
    publish_daily_artifact_sections,
)
from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    daily_output_contains as _output_contains,
    daily_output_value as _output_value,
)
from business.layers.signal.artifacts import SourceArtifactWriter
from framework.workflow.runtime.artifact_publishers import (
    ArtifactPublishContext,
    ArtifactPublishPhase,
    register_manifest_artifact_once,
)
from infrastructure.storage.artifacts import ArtifactRef


AGENTIC_WORKFLOW_IDS = {"daily-intelligence-agentic"}
DAILY_AGENT_STEPS = (
    {
        "label": "planner",
        "agent_id": "daily.planner",
        "step_id": "planner_agent",
    },
    {
        "label": "analyst",
        "agent_id": "daily.analyst",
        "step_id": "analyst_agent",
    },
    {
        "label": "writer",
        "agent_id": "daily.writer",
        "step_id": "writer_agent",
    },
    {
        "label": "verifier",
        "agent_id": "daily.verifier",
        "step_id": "verifier_agent",
    },
    {
        "label": "editor",
        "agent_id": "daily.editor",
        "step_id": "editor_agent",
    },
)
AGENT_LOOP_ARTIFACT_SUFFIXES = {
    "result": "agent_loop_result",
    "metrics": "agent_loop_metrics",
    "diagnostics": "agent_loop_diagnostics",
    "trace": "agent_loop_trace",
    "llm_call_artifacts": "llm_call_artifacts",
}


class DailyIntelligenceArtifactPublisher:
    publisher_id = "daily_intelligence"

    def supports(self, context: ArtifactPublishContext) -> bool:
        if context.phase != ArtifactPublishPhase.TERMINAL:
            return False
        return _is_daily_workflow_id(context.workflow.workflow_id)

    def publish(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        return publish_daily_artifact_sections(
            context,
            source_diagnostics=self._publish_source_diagnostics,
            evidence=self._publish_evidence_artifacts,
            quality=self._publish_quality_artifacts,
            agentic=self._publish_agentic_artifacts,
            report=self._publish_report_artifacts,
        )

    def _publish_evidence_artifacts(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        output = context.output
        if _output_contains(output, "evidence_bundle"):
            evidence_bundle = _output_value(output, "evidence_bundle")
            refs.append(
                _write_json_artifact(
                    context,
                    "evidence_bundle",
                    "evidence_bundle.json",
                    evidence_bundle,
                )
            )
            source_map = _output_value(output, "evidence_source_map")
            if source_map is None:
                source_map = _evidence_source_map(evidence_bundle)
            if source_map is not None:
                refs.append(
                    _write_json_artifact(
                        context,
                        "evidence_source_map",
                        "evidence_source_map.json",
                        source_map,
                    )
                )
        elif _output_contains(output, "evidence_source_map"):
            refs.append(
                _write_json_artifact(
                    context,
                    "evidence_source_map",
                    "evidence_source_map.json",
                    _output_value(output, "evidence_source_map"),
                )
            )
        refs.extend(
            _write_json_artifacts_from_output(
                context,
                {
                    "evidence_scores": "evidence_scores.json",
                    "candidate_claims": "candidate_claims.json",
                    "verified_findings": "verified_findings.json",
                },
            )
        )
        return refs

    def _publish_quality_artifacts(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        output = context.output
        if _output_contains(output, "citation_check_result"):
            citation_check = _output_value(output, "citation_check_result")
            refs.append(
                _write_json_artifact(
                    context,
                    "citation_check_result",
                    "citation_check_result.json",
                    citation_check,
                )
            )
            unsupported_claims = _field_value(citation_check, "unsupported_claims")
            if unsupported_claims:
                refs.append(
                    _write_json_artifact(
                        context,
                        "unsupported_claims",
                        "unsupported_claims.json",
                        unsupported_claims,
                    )
                )
            rejected_claim_usage = _field_value(citation_check, "rejected_claim_usage")
            if rejected_claim_usage:
                refs.append(
                    _write_json_artifact(
                        context,
                        "rejected_claim_usage",
                        "rejected_claim_usage.json",
                        rejected_claim_usage,
                    )
                )

        refs.extend(
            _write_json_artifacts_from_output(
                context,
                {
                    "editor_review": "editor_review.json",
                    "support_matrix": "support_matrix.json",
                    "report_quality_summary": "report_quality_summary.json",
                    "quality_events": "quality_events.json",
                    "quality_gate_metrics": "quality_gate_metrics.json",
                    "quality_result": "quality_result.json",
                    "rewrite_policy": "rewrite_policy.json",
                    "rewrite_instructions": "rewrite_instructions.json",
                    "rewritten_report_draft": "rewritten_report_draft.json",
                    "human_review_request": "human_review_request.json",
                },
            )
        )
        _update_quality_manifest_fields(context.manifest, output)
        return refs

    def _publish_agentic_artifacts(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        if not _is_agentic_workflow_id(context.workflow.workflow_id):
            return []

        refs: list[ArtifactRef] = []
        output = context.output
        context.manifest["agentic"] = True
        context.manifest["agent_count"] = len(DAILY_AGENT_STEPS)
        context.manifest["agent_steps"] = [agent["step_id"] for agent in DAILY_AGENT_STEPS]

        for agent in DAILY_AGENT_STEPS:
            label = agent["label"]
            for artifact_name, suffix in AGENT_LOOP_ARTIFACT_SUFFIXES.items():
                output_key = f"{label}_{suffix}"
                if not _output_contains(output, output_key):
                    continue
                artifact_key = f"{label}_{suffix}"
                relative_path = f"agentic/{artifact_key}.json"
                refs.append(
                    _write_json_artifact(
                        context,
                        artifact_key,
                        relative_path,
                        _agentic_artifact_payload(
                            artifact_name,
                            _output_value(output, output_key),
                        ),
                    )
                )

        refs.extend(
            _write_json_artifacts_from_output(
                context,
                {
                    "agent_feedback_events": "agentic/agent_feedback_events.json",
                    "agent_feedback_summary": "agentic/agent_feedback_summary.json",
                },
            )
        )
        feedback_summary = _dict_value(_output_value(output, "agent_feedback_summary"))
        feedback_events = _list_value(_output_value(output, "agent_feedback_events"))
        if feedback_summary or feedback_events:
            context.manifest["agent_feedback"] = {
                "event_count": len(feedback_events),
                "highest_severity": feedback_summary.get("highest_severity"),
                "artifact": "agentic/agent_feedback_summary.json",
            }

        summary = _agentic_summary(context)
        refs.append(
            _write_json_artifact(
                context,
                "agentic_summary",
                "agentic_summary.json",
                summary,
            )
        )
        context.manifest["agentic_summary"] = {
            "agent_count": summary["agent_count"],
            "final_decision": summary.get("final_decision"),
            "quality_score": summary.get("quality_score"),
            "artifact": "agentic_summary.json",
        }
        return refs

    def _publish_report_artifacts(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        output = context.output
        if _output_contains(output, "final_report"):
            refs.append(
                _write_json_artifact(
                    context,
                    "report_json",
                    "report.json",
                    _output_value(output, "final_report"),
                )
            )
        report_markdown = _output_value(output, "report_markdown")
        if isinstance(report_markdown, str):
            refs.append(
                _write_text_artifact(
                    context,
                    "report_markdown",
                    "report.md",
                    report_markdown,
                    content_type="text/markdown",
                )
            )
        if _output_contains(output, "blocked_report"):
            refs.append(
                _write_json_artifact(
                    context,
                    "blocked_report",
                    "blocked_report.json",
                    _output_value(output, "blocked_report"),
                )
            )
        return refs

    def _publish_source_diagnostics(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs = _write_json_artifacts_from_output(
            context,
            {
                "raw_items": "raw_items.json",
                "source_errors": "source_errors.json",
                "skipped_sources": "skipped_sources.json",
                "failed_sources": "failed_sources.json",
                "source_fetch_requests": "source_fetch_requests.json",
                "source_fetch_results": "source_fetch_results.json",
                "source_health_updates": "source_health_updates.json",
                "source_health_report": "source_health_report.json",
                "source_duplicate_groups": "source_duplicate_groups.json",
                "source_events": "source_events.json",
                "source_pipeline_metrics": "source_pipeline_metrics.json",
                "source_connector_dispatch_report": "source_connector_dispatch_report.json",
                "source_error_policy_report": "source_error_policy_report.json",
                "source_fallback_report": "source_fallback_report.json",
                "source_selection_report": "source_selection_report.json",
                "source_coverage_report": "source_coverage_report.json",
                "source_quality_scores": "source_quality_scores.json",
                "source_quality_summary_report": "source_quality_summary_report.json",
                "source_ranking_scores": "source_ranking_scores.json",
                "source_freshness_report": "source_freshness_report.json",
                "source_traceability_report": "source_traceability_report.json",
                "source_governance_report": "source_governance_report.json",
                "source_recollection_profile": "source_recollection/profile.json",
                "source_recollection_execution_plan": "source_recollection/execution_plan.json",
                "source_recollection_execution_report": "source_recollection/execution_report.json",
                "source_recollection_quality_assessment": (
                    "source_recollection/quality_assessment.json"
                ),
            },
        )
        output = context.output
        if _output_contains(output, "source_events"):
            context.manifest["source_event_count"] = len(_output_value(output, "source_events"))
        if _output_contains(output, "source_quality_scores"):
            context.manifest["source_quality_score_count"] = len(
                _output_value(output, "source_quality_scores")
            )
        if _output_contains(output, "source_ranking_scores"):
            context.manifest["source_ranking_score_count"] = len(
                _output_value(output, "source_ranking_scores")
            )
        _update_source_recollection_manifest_fields(context.manifest, output)
        source_artifacts = SourceArtifactWriter(context.artifact_manager).write_source_artifacts(
            context.run_id,
            raw_items=_output_value(output, "raw_items"),
            source_fetch_requests=_output_value(output, "source_fetch_requests"),
            source_fetch_results=_output_value(output, "source_fetch_results"),
            source_errors=_output_value(output, "source_errors"),
        )
        if source_artifacts:
            refs.append(
                _register_existing_artifact(
                    context,
                    "source_artifacts",
                    "source_artifacts/index.json",
                    content_type="application/json",
                )
            )
            context.manifest["source_artifacts"] = {
                "item_count": source_artifacts["item_count"],
                "error_count": source_artifacts["error_count"],
                "raw_content_count": source_artifacts["raw_content_count"],
                "fetch_request_count": source_artifacts["fetch_request_count"],
                "fetch_result_count": source_artifacts["fetch_result_count"],
                "total_count": len(source_artifacts["entries"]),
            }
            if source_artifacts.get("response_headers_count"):
                context.manifest["source_artifacts"]["response_headers_count"] = source_artifacts[
                    "response_headers_count"
                ]
            if source_artifacts.get("parsed_items_count"):
                context.manifest["source_artifacts"]["parsed_items_count"] = source_artifacts[
                    "parsed_items_count"
                ]
        return refs


def build_daily_intelligence_artifact_publishers() -> list[DailyIntelligenceArtifactPublisher]:
    return [DailyIntelligenceArtifactPublisher()]


def _write_json_artifacts_from_output(
    context: ArtifactPublishContext,
    artifacts: dict[str, str],
) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for artifact_key, relative_path in artifacts.items():
        if _output_contains(context.output, artifact_key):
            refs.append(
                _write_json_artifact(
                    context,
                    artifact_key,
                    relative_path,
                    _output_value(context.output, artifact_key),
                )
            )
    return refs


def _write_json_artifact(
    context: ArtifactPublishContext,
    artifact_key: str,
    relative_path: str,
    payload: Any,
) -> ArtifactRef:
    register_manifest_artifact_once(context.manifest, artifact_key, relative_path)
    path = context.artifact_manager.write_json(context.run_id, relative_path, payload)
    return _artifact_ref(
        context,
        artifact_id=artifact_key,
        artifact_type=artifact_key,
        relative_path=relative_path,
        path=path,
        content_type="application/json",
    )


def _write_text_artifact(
    context: ArtifactPublishContext,
    artifact_key: str,
    relative_path: str,
    text: str,
    *,
    content_type: str,
) -> ArtifactRef:
    register_manifest_artifact_once(context.manifest, artifact_key, relative_path)
    path = context.artifact_manager.write_text(context.run_id, relative_path, text)
    return _artifact_ref(
        context,
        artifact_id=artifact_key,
        artifact_type=artifact_key,
        relative_path=relative_path,
        path=path,
        content_type=content_type,
    )


def _register_existing_artifact(
    context: ArtifactPublishContext,
    artifact_key: str,
    relative_path: str,
    *,
    content_type: str,
) -> ArtifactRef:
    register_manifest_artifact_once(context.manifest, artifact_key, relative_path)
    path = context.artifact_manager.run_dir(context.run_id) / relative_path
    return _artifact_ref(
        context,
        artifact_id=artifact_key,
        artifact_type=artifact_key,
        relative_path=relative_path,
        path=path,
        content_type=content_type,
    )


def _artifact_ref(
    context: ArtifactPublishContext,
    *,
    artifact_id: str,
    artifact_type: str,
    relative_path: str,
    path: Path,
    content_type: str,
) -> ArtifactRef:
    data = path.read_bytes()
    return ArtifactRef(
        artifact_id=artifact_id,
        run_id=context.run_id,
        artifact_type=artifact_type,
        path=Path(relative_path).as_posix(),
        content_type=content_type,
        size_bytes=len(data),
        checksum=sha256(data).hexdigest(),
        redacted=True,
        metadata={
            "artifact_key": artifact_id,
            "workflow_id": context.workflow.workflow_id,
            "workflow_version": context.workflow.version,
            "phase": context.phase.value,
        },
    )


def _update_quality_manifest_fields(manifest: dict[str, Any], output: dict[str, Any]) -> None:
    if _output_contains(output, "report_quality_summary"):
        summary = _output_value(output, "report_quality_summary")
        if hasattr(summary, "quality_score"):
            manifest["quality_score"] = summary.quality_score
        elif isinstance(summary, dict):
            manifest["quality_score"] = summary.get("quality_score")
    if _output_contains(output, "quality_events"):
        manifest["quality_event_count"] = len(_output_value(output, "quality_events"))
    quality_result = _output_value(output, "quality_result")
    route = _field_value(quality_result, "route")
    if route is None:
        route = _output_value(output, "quality_route")
    if route is not None:
        manifest["quality_route"] = route
    decision = _field_value(quality_result, "decision")
    if decision is not None:
        manifest["quality_decision"] = decision


def _update_source_recollection_manifest_fields(
    manifest: dict[str, Any],
    output: dict[str, Any],
) -> None:
    report = _output_value(output, "source_recollection_execution_report")
    if report is None:
        return
    manifest["source_recollection"] = {
        "plan_id": _field_value(report, "plan_id"),
        "status": _field_value(report, "status"),
        "task_count": _int_value(_field_value(report, "task_count")),
        "raw_item_count": _int_value(_field_value(report, "raw_item_count")),
        "error_count": _int_value(_field_value(report, "error_count")),
        "fetch_request_count": _int_value(_field_value(report, "fetch_request_count")),
        "fetch_result_count": _int_value(_field_value(report, "fetch_result_count")),
        "artifact": "source_recollection/execution_report.json",
    }
    if _output_contains(output, "source_recollection_profile"):
        manifest["source_recollection"]["profile_artifact"] = "source_recollection/profile.json"
    if _output_contains(output, "source_recollection_execution_plan"):
        manifest["source_recollection"]["plan_artifact"] = "source_recollection/execution_plan.json"
    assessment = _output_value(output, "source_recollection_quality_assessment")
    if assessment is not None:
        manifest["source_recollection"]["quality"] = {
            "decision": _field_value(assessment, "decision"),
            "severity": _field_value(assessment, "severity"),
            "route": _field_value(assessment, "route"),
            "recommended_action": _field_value(assessment, "recommended_action"),
            "artifact": "source_recollection/quality_assessment.json",
        }


def _agentic_summary(context: ArtifactPublishContext) -> dict[str, Any]:
    output = context.output
    agents = []
    for agent in DAILY_AGENT_STEPS:
        label = agent["label"]
        result = _dict_value(_output_value(output, f"{label}_agent_loop_result"))
        metrics = _dict_value(_output_value(output, f"{label}_agent_loop_metrics"))
        diagnostics = _dict_value(_output_value(output, f"{label}_agent_loop_diagnostics"))
        trace = _dict_value(_output_value(output, f"{label}_agent_loop_trace"))
        summary = _dict_value(trace.get("summary"))
        agents.append(
            {
                "agent_id": agent["agent_id"],
                "step_id": agent["step_id"],
                "status": _agent_status(result),
                "success": result.get("success"),
                "llm_calls": _int_value(metrics.get("llm_calls")),
                "tool_calls": _int_value(metrics.get("tool_calls")),
                "stop_reason": (
                    result.get("stop_reason")
                    or summary.get("stop_reason")
                    or diagnostics.get("stop_reason")
                ),
                "diagnostics_present": (
                    _output_value(output, f"{label}_agent_loop_diagnostics")
                    is not None
                ),
                "trace_present": _output_value(output, f"{label}_agent_loop_trace") is not None,
                "llm_artifact_count": len(
                    _list_value(_output_value(output, f"{label}_llm_call_artifacts"))
                ),
            }
        )

    editor_review = _dict_value(_output_value(output, "editor_review"))
    quality_result = _dict_value(_output_value(output, "quality_result"))
    quality_summary = _dict_value(_output_value(output, "report_quality_summary"))
    feedback_summary = _dict_value(_output_value(output, "agent_feedback_summary"))
    feedback_events = _list_value(_output_value(output, "agent_feedback_events"))
    final_decision = (
        editor_review.get("decision")
        or quality_result.get("decision")
        or quality_summary.get("decision")
    )
    return {
        "run_id": context.run_id,
        "workflow_id": context.workflow.workflow_id,
        "workflow_version": context.workflow.version,
        "agent_count": len(agents),
        "agents": agents,
        "final_decision": final_decision,
        "quality_score": _first_not_none(
            editor_review.get("quality_score"),
            quality_result.get("quality_score"),
            quality_summary.get("quality_score"),
        ),
        "feedback_event_count": len(feedback_events),
        "feedback_highest_severity": feedback_summary.get("highest_severity"),
    }


def _agentic_artifact_payload(artifact_name: str, payload: Any) -> Any:
    if artifact_name == "result":
        return _redacted_agent_loop_result(payload)
    if artifact_name == "llm_call_artifacts":
        return _redacted_llm_artifact_index(payload)
    return payload


def _redacted_agent_loop_result(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    result = dict(payload)
    if "llm_call_artifacts" in result:
        result["llm_call_artifacts"] = _redacted_llm_artifact_index(result["llm_call_artifacts"])
    return result


def _redacted_llm_artifact_index(payload: Any) -> list[dict[str, Any]]:
    entries = []
    for item in _list_value(payload):
        if not isinstance(item, dict):
            continue
        response = _dict_value(item.get("response"))
        usage = _dict_value(response.get("usage"))
        artifact_ref = _dict_value(item.get("artifact_ref"))
        entries.append(
            {
                "artifact_id": item.get("artifact_id"),
                "iteration": item.get("iteration"),
                "metadata": _dict_value(item.get("metadata")),
                "artifact_ref": artifact_ref or None,
                "usage": usage or None,
                "redacted": True,
            }
        )
    return entries


def _agent_status(result: dict[str, Any]) -> str:
    status = result.get("status")
    if status:
        return str(status)
    if result.get("success") is True:
        return "succeeded"
    if result.get("success") is False:
        return "failed"
    return "unknown"


def _evidence_source_map(evidence_bundle: Any) -> dict[str, list[str]] | None:
    if isinstance(evidence_bundle, dict):
        source_map = evidence_bundle.get("source_map")
    else:
        source_map = getattr(evidence_bundle, "source_map", None)
    if source_map is None:
        return None
    return {str(key): list(value) for key, value in source_map.items()}


def _field_value(value: Any, field_name: str) -> Any:
    if hasattr(value, field_name):
        return getattr(value, field_name)
    if isinstance(value, dict):
        return value.get(field_name)
    return None


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _is_daily_workflow_id(workflow_id: str) -> bool:
    normalized = str(workflow_id).strip().lower()
    return normalized in {
        "daily",
        "daily-intelligence",
        "daily_intelligence",
    } or normalized.startswith("daily-intelligence")


def _is_agentic_workflow_id(workflow_id: str) -> bool:
    return str(workflow_id).strip().lower() in AGENTIC_WORKFLOW_IDS
