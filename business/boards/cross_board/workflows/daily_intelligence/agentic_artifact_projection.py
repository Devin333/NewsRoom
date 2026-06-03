from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    daily_output_contains,
    daily_output_value,
)


@dataclass(frozen=True)
class DailyAgentArtifactSpec:
    label: str
    agent_id: str
    step_id: str


@dataclass(frozen=True)
class DailyAgentLoopArtifactSpec:
    artifact_name: str
    output_suffix: str


@dataclass(frozen=True)
class DailyAgenticArtifact:
    artifact_key: str
    relative_path: str
    payload: Any


@dataclass(frozen=True)
class DailyAgenticArtifactProjection:
    artifacts: list[DailyAgenticArtifact]
    manifest_fields: dict[str, Any]


DAILY_AGENT_ARTIFACT_SPECS = (
    DailyAgentArtifactSpec(
        label="planner",
        agent_id="daily.planner",
        step_id="planner_agent",
    ),
    DailyAgentArtifactSpec(
        label="analyst",
        agent_id="daily.analyst",
        step_id="analyst_agent",
    ),
    DailyAgentArtifactSpec(
        label="writer",
        agent_id="daily.writer",
        step_id="writer_agent",
    ),
    DailyAgentArtifactSpec(
        label="verifier",
        agent_id="daily.verifier",
        step_id="verifier_agent",
    ),
    DailyAgentArtifactSpec(
        label="editor",
        agent_id="daily.editor",
        step_id="editor_agent",
    ),
)
DAILY_AGENT_LOOP_ARTIFACT_SPECS = (
    DailyAgentLoopArtifactSpec("result", "agent_loop_result"),
    DailyAgentLoopArtifactSpec("metrics", "agent_loop_metrics"),
    DailyAgentLoopArtifactSpec("diagnostics", "agent_loop_diagnostics"),
    DailyAgentLoopArtifactSpec("trace", "agent_loop_trace"),
    DailyAgentLoopArtifactSpec("llm_call_artifacts", "llm_call_artifacts"),
)


def project_daily_agentic_artifacts(
    *,
    run_id: str,
    workflow_id: str,
    workflow_version: str,
    output: Mapping[str, Any],
) -> DailyAgenticArtifactProjection:
    artifacts: list[DailyAgenticArtifact] = []
    manifest_fields: dict[str, Any] = {
        "agentic": True,
        "agent_count": len(DAILY_AGENT_ARTIFACT_SPECS),
        "agent_steps": [agent.step_id for agent in DAILY_AGENT_ARTIFACT_SPECS],
    }

    artifacts.extend(_agent_loop_artifacts(output))
    artifacts.extend(_agent_feedback_artifacts(output))

    feedback_summary = _dict_value(daily_output_value(output, "agent_feedback_summary"))
    feedback_events = _list_value(daily_output_value(output, "agent_feedback_events"))
    if feedback_summary or feedback_events:
        manifest_fields["agent_feedback"] = {
            "event_count": len(feedback_events),
            "highest_severity": feedback_summary.get("highest_severity"),
            "artifact": "agentic/agent_feedback_summary.json",
        }

    summary = _agentic_summary(
        run_id=run_id,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        output=output,
    )
    artifacts.append(
        DailyAgenticArtifact(
            artifact_key="agentic_summary",
            relative_path="agentic_summary.json",
            payload=summary,
        )
    )
    manifest_fields["agentic_summary"] = {
        "agent_count": summary["agent_count"],
        "final_decision": summary.get("final_decision"),
        "quality_score": summary.get("quality_score"),
        "artifact": "agentic_summary.json",
    }
    return DailyAgenticArtifactProjection(
        artifacts=artifacts,
        manifest_fields=manifest_fields,
    )


def _agent_loop_artifacts(output: Mapping[str, Any]) -> list[DailyAgenticArtifact]:
    artifacts: list[DailyAgenticArtifact] = []
    for agent in DAILY_AGENT_ARTIFACT_SPECS:
        for artifact_spec in DAILY_AGENT_LOOP_ARTIFACT_SPECS:
            output_key = f"{agent.label}_{artifact_spec.output_suffix}"
            if not daily_output_contains(output, output_key):
                continue
            artifact_key = f"{agent.label}_{artifact_spec.output_suffix}"
            artifacts.append(
                DailyAgenticArtifact(
                    artifact_key=artifact_key,
                    relative_path=f"agentic/{artifact_key}.json",
                    payload=_agentic_artifact_payload(
                        artifact_spec.artifact_name,
                        daily_output_value(output, output_key),
                    ),
                )
            )
    return artifacts


def _agent_feedback_artifacts(output: Mapping[str, Any]) -> list[DailyAgenticArtifact]:
    artifacts: list[DailyAgenticArtifact] = []
    for artifact_key, relative_path in {
        "agent_feedback_events": "agentic/agent_feedback_events.json",
        "agent_feedback_summary": "agentic/agent_feedback_summary.json",
    }.items():
        if daily_output_contains(output, artifact_key):
            artifacts.append(
                DailyAgenticArtifact(
                    artifact_key=artifact_key,
                    relative_path=relative_path,
                    payload=daily_output_value(output, artifact_key),
                )
            )
    return artifacts


def _agentic_summary(
    *,
    run_id: str,
    workflow_id: str,
    workflow_version: str,
    output: Mapping[str, Any],
) -> dict[str, Any]:
    agents = []
    for agent in DAILY_AGENT_ARTIFACT_SPECS:
        label = agent.label
        result = _dict_value(daily_output_value(output, f"{label}_agent_loop_result"))
        metrics = _dict_value(daily_output_value(output, f"{label}_agent_loop_metrics"))
        diagnostics = _dict_value(daily_output_value(output, f"{label}_agent_loop_diagnostics"))
        trace = _dict_value(daily_output_value(output, f"{label}_agent_loop_trace"))
        summary = _dict_value(trace.get("summary"))
        agents.append(
            {
                "agent_id": agent.agent_id,
                "step_id": agent.step_id,
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
                    daily_output_value(output, f"{label}_agent_loop_diagnostics") is not None
                ),
                "trace_present": daily_output_value(output, f"{label}_agent_loop_trace") is not None,
                "llm_artifact_count": len(
                    _list_value(daily_output_value(output, f"{label}_llm_call_artifacts"))
                ),
            }
        )

    editor_review = _dict_value(daily_output_value(output, "editor_review"))
    quality_result = _dict_value(daily_output_value(output, "quality_result"))
    quality_summary = _dict_value(daily_output_value(output, "report_quality_summary"))
    feedback_summary = _dict_value(daily_output_value(output, "agent_feedback_summary"))
    feedback_events = _list_value(daily_output_value(output, "agent_feedback_events"))
    final_decision = (
        editor_review.get("decision")
        or quality_result.get("decision")
        or quality_summary.get("decision")
    )
    return {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "workflow_version": workflow_version,
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


__all__ = [
    "DAILY_AGENT_ARTIFACT_SPECS",
    "DAILY_AGENT_LOOP_ARTIFACT_SPECS",
    "DailyAgentArtifactSpec",
    "DailyAgentLoopArtifactSpec",
    "DailyAgenticArtifact",
    "DailyAgenticArtifactProjection",
    "project_daily_agentic_artifacts",
]
