from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any



@dataclass(frozen=True)
class RunPersistenceInput:
    run_id: str
    graph_id: str
    graph_version: str
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

    def __post_init__(self) -> None:
        if not isinstance(self.graph_id, str) or not self.graph_id.strip():
            raise ValueError("graph_id is required")
        if not isinstance(self.graph_version, str) or not self.graph_version.strip():
            raise ValueError("graph_version is required")


def run_persistence_input_from_result(
    result: Any,
    *,
    profile: str = "",
) -> RunPersistenceInput:
    return run_persistence_input_from_output(result, result.output, profile=profile)


def run_persistence_input_from_output(
    result: Any,
    output: Mapping[str, Any],
    *,
    profile: str = "",
) -> RunPersistenceInput:
    graph_id, graph_version = _graph_identity_from_result(result, output)
    return RunPersistenceInput(
        run_id=result.run_id,
        graph_id=graph_id,
        graph_version=graph_version,
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


def _graph_identity_from_result(
    result: Any,
    output: Mapping[str, Any],
) -> tuple[str, str]:
    candidates = (
        (getattr(result, "graph_id", None), getattr(result, "graph_version", None)),
        (output.get("graph_id"), output.get("graph_version")),
        _context_graph_identity(getattr(result, "context_envelope", None)),
    )
    for graph_id, graph_version in candidates:
        if _non_empty_text(graph_id) and _non_empty_text(graph_version):
            return str(graph_id), str(graph_version)
        if graph_id is not None or graph_version is not None:
            raise ValueError("graph_id and graph_version must both be present")
    raise ValueError("graph identity is required for persistence")


def _context_graph_identity(value: Any) -> tuple[Any, Any]:
    identity = getattr(value, "graph_identity", None)
    if identity is None:
        return None, None
    return getattr(identity, "graph_id", None), getattr(identity, "graph_version", None)


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "RunPersistenceInput",
    "run_persistence_input_from_output",
    "run_persistence_input_from_result",
]
