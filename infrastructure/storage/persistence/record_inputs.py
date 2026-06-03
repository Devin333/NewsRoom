from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from framework import RunResult


@dataclass(frozen=True)
class RunPersistenceInput:
    run_id: str
    workflow_id: str
    workflow_version: str
    status: str
    profile: str
    artifact_dir: str | None = None
    manifest_path: str | None = None
    events_path: str | None = None
    error: dict[str, Any] | None = None
    source_pipeline_metrics: Any | None = None
    agent_loop_metrics: Any | None = None
    report_quality_summary: Any | None = None
    quality_gate_metrics: Any | None = None
    final_report: Any | None = None
    blocked_report: Any | None = None
    report_markdown: str | None = None
    quality_result: Any | None = None
    quality_route: str | None = None
    citation_check_result: Any | None = None
    support_matrix: Any | None = None
    editor_review: Any | None = None
    raw_items: tuple[Any, ...] = field(default_factory=tuple)
    evidence_bundle: Any | None = None
    verified_findings: Any | None = None


def run_persistence_input_from_result(
    result: RunResult,
    *,
    profile: str = "",
) -> RunPersistenceInput:
    return run_persistence_input_from_output(result, result.output, profile=profile)


def run_persistence_input_from_output(
    result: RunResult,
    output: Mapping[str, Any],
    *,
    profile: str = "",
) -> RunPersistenceInput:
    return RunPersistenceInput(
        run_id=result.run_id,
        workflow_id=result.workflow_id,
        workflow_version=result.workflow_version,
        status=result.status.value,
        profile=profile,
        artifact_dir=result.artifact_dir,
        manifest_path=result.manifest_path,
        events_path=result.events_path,
        error=result.error,
        source_pipeline_metrics=output.get("source_pipeline_metrics"),
        agent_loop_metrics=output.get("agent_loop_metrics"),
        report_quality_summary=output.get("report_quality_summary"),
        quality_gate_metrics=output.get("quality_gate_metrics"),
        final_report=output.get("final_report"),
        blocked_report=output.get("blocked_report"),
        report_markdown=output.get("report_markdown"),
        quality_result=output.get("quality_result"),
        quality_route=output.get("quality_route"),
        citation_check_result=output.get("citation_check_result"),
        support_matrix=output.get("support_matrix"),
        editor_review=output.get("editor_review"),
        raw_items=tuple(output.get("raw_items", ()) or ()),
        evidence_bundle=output.get("evidence_bundle"),
        verified_findings=output.get("verified_findings"),
    )


__all__ = [
    "RunPersistenceInput",
    "run_persistence_input_from_output",
    "run_persistence_input_from_result",
]
