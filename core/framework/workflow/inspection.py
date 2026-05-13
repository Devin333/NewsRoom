from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Iterator

from core.framework.serialization import to_json_safe
from core.framework.specs import StepStatus, WorkflowStatus
from core.framework.workflow.manifest import (
    REQUIRED_RUN_ARTIFACTS,
    RUN_MANIFEST_SCHEMA_VERSION,
    RunManifestError,
    manifest_schema_version,
    manifest_step_artifact_key,
    validate_run_manifest,
)


class WorkflowRunInspectionError(RuntimeError):
    """Raised when a workflow run artifact directory cannot be inspected."""


STANDARD_JSON_ARTIFACT_KEYS = {
    "request",
    "workflow_spec",
    "workflow_version",
    "data_buffer_snapshot",
    "data_buffer_initial",
    "data_buffer_final",
    "data_buffer_diff",
    "step_results",
    "metrics",
    "redaction_report",
    "output",
    "error",
    "pause",
    "agent_loop_events",
    "evidence_bundle",
    "evidence_source_map",
    "evidence_scores",
    "candidate_claims",
    "verified_findings",
    "citation_check_result",
    "unsupported_claims",
    "rejected_claim_usage",
    "editor_review",
    "support_matrix",
    "report_quality_summary",
    "quality_events",
    "quality_gate_metrics",
    "rewrite_policy",
    "rewrite_instructions",
    "rewritten_report_draft",
    "human_review_request",
    "report_json",
    "blocked_report",
    "raw_items",
    "source_errors",
    "skipped_sources",
    "failed_sources",
    "source_fetch_requests",
    "source_fetch_results",
    "source_health_updates",
    "source_health_report",
    "source_duplicate_groups",
    "source_events",
    "source_pipeline_metrics",
    "source_connector_dispatch_report",
    "source_error_policy_report",
    "source_fallback_report",
    "source_selection_report",
    "source_coverage_report",
    "source_quality_scores",
    "source_quality_summary_report",
    "source_ranking_scores",
    "source_freshness_report",
    "source_traceability_report",
    "source_governance_report",
    "source_artifacts",
}

TERMINAL_ARTIFACT_BY_STATUS = {
    WorkflowStatus.SUCCEEDED.value: "output",
    WorkflowStatus.PAUSED.value: "pause",
    WorkflowStatus.WAITING_FOR_HUMAN.value: "pause",
    WorkflowStatus.FAILED.value: "error",
    WorkflowStatus.BLOCKED.value: "error",
    WorkflowStatus.CANCELLED.value: "error",
    WorkflowStatus.BUDGET_EXCEEDED.value: "error",
}


@dataclass(frozen=True)
class WorkflowArtifactRecord:
    artifact_key: str
    relative_path: str
    absolute_path: Path
    exists: bool
    content_type: str
    size_bytes: int | None = None
    checksum: str | None = None
    required: bool = False
    step_artifact: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "relative_path": self.relative_path,
            "absolute_path": str(self.absolute_path),
            "exists": self.exists,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "required": self.required,
            "step_artifact": self.step_artifact,
            "metadata": to_json_safe(self.metadata),
        }


@dataclass(frozen=True)
class WorkflowStepSummary:
    step_id: str
    status: str
    output_keys: list[str] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    artifact_count: int = 0
    lineage_count: int = 0
    next_hint: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == StepStatus.SUCCEEDED.value

    @property
    def failed(self) -> bool:
        return self.status in {
            StepStatus.FAILED.value,
            StepStatus.BLOCKED.value,
            StepStatus.TIMEOUT.value,
            StepStatus.CANCELLED.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "output_keys": list(self.output_keys),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "metrics": to_json_safe(self.metrics),
            "artifact_count": self.artifact_count,
            "lineage_count": self.lineage_count,
            "next_hint": self.next_hint,
        }


@dataclass(frozen=True)
class WorkflowEventRecord:
    event_id: str | None
    event_type: str
    run_id: str | None
    occurred_at: str | None = None
    step_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    line_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "occurred_at": self.occurred_at,
            "step_id": self.step_id,
            "payload": to_json_safe(self.payload),
            "line_number": self.line_number,
        }


@dataclass(frozen=True)
class WorkflowEventSummary:
    event_count: int
    event_type_counts: dict[str, int] = field(default_factory=dict)
    step_event_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    first_event_at: str | None = None
    last_event_at: str | None = None
    terminal_event_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_count": self.event_count,
            "event_type_counts": dict(self.event_type_counts),
            "step_event_counts": {
                step_id: dict(counts)
                for step_id, counts in self.step_event_counts.items()
            },
            "first_event_at": self.first_event_at,
            "last_event_at": self.last_event_at,
            "terminal_event_type": self.terminal_event_type,
        }


@dataclass(frozen=True)
class WorkflowTimelineItem:
    sequence: int
    event_type: str
    phase: str
    severity: str
    run_id: str | None = None
    occurred_at: str | None = None
    step_id: str | None = None
    edge_id: str | None = None
    source_step_id: str | None = None
    target_step_id: str | None = None
    status: str | None = None
    message: str | None = None
    payload_keys: list[str] = field(default_factory=list)
    payload_excerpt: dict[str, Any] = field(default_factory=dict)
    terminal: bool = False

    @property
    def is_error(self) -> bool:
        return self.severity == "error"

    @property
    def is_warning(self) -> bool:
        return self.severity == "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type,
            "phase": self.phase,
            "severity": self.severity,
            "run_id": self.run_id,
            "occurred_at": self.occurred_at,
            "step_id": self.step_id,
            "edge_id": self.edge_id,
            "source_step_id": self.source_step_id,
            "target_step_id": self.target_step_id,
            "status": self.status,
            "message": self.message,
            "payload_keys": list(self.payload_keys),
            "payload_excerpt": to_json_safe(self.payload_excerpt),
            "terminal": self.terminal,
        }


@dataclass(frozen=True)
class WorkflowTimelineSummary:
    event_count: int
    phase_counts: dict[str, int] = field(default_factory=dict)
    severity_counts: dict[str, int] = field(default_factory=dict)
    event_type_counts: dict[str, int] = field(default_factory=dict)
    step_event_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    first_event_at: str | None = None
    last_event_at: str | None = None
    duration_ms: float | None = None
    terminal_event_type: str | None = None
    traversed_edges: list[dict[str, Any]] = field(default_factory=list)
    rejected_edges: list[dict[str, Any]] = field(default_factory=list)
    retry_count: int = 0
    timeout_count: int = 0
    checkpoint_count: int = 0
    workflow_event_count: int = 0
    step_event_count: int = 0
    routing_event_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_count": self.event_count,
            "phase_counts": dict(self.phase_counts),
            "severity_counts": dict(self.severity_counts),
            "event_type_counts": dict(self.event_type_counts),
            "step_event_counts": {
                step_id: dict(counts)
                for step_id, counts in self.step_event_counts.items()
            },
            "first_event_at": self.first_event_at,
            "last_event_at": self.last_event_at,
            "duration_ms": self.duration_ms,
            "terminal_event_type": self.terminal_event_type,
            "traversed_edges": to_json_safe(self.traversed_edges),
            "rejected_edges": to_json_safe(self.rejected_edges),
            "retry_count": self.retry_count,
            "timeout_count": self.timeout_count,
            "checkpoint_count": self.checkpoint_count,
            "workflow_event_count": self.workflow_event_count,
            "step_event_count": self.step_event_count,
            "routing_event_count": self.routing_event_count,
        }


@dataclass(frozen=True)
class WorkflowArtifactInventory:
    artifact_count: int
    existing_count: int
    missing_count: int
    required_count: int
    missing_required_count: int
    step_artifact_count: int
    terminal_artifact_key: str | None = None
    terminal_artifact_exists: bool | None = None
    total_size_bytes: int = 0
    content_type_counts: dict[str, int] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)
    missing_artifact_keys: list[str] = field(default_factory=list)
    missing_required_keys: list[str] = field(default_factory=list)
    largest_artifacts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.missing_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_count": self.artifact_count,
            "existing_count": self.existing_count,
            "missing_count": self.missing_count,
            "required_count": self.required_count,
            "missing_required_count": self.missing_required_count,
            "step_artifact_count": self.step_artifact_count,
            "terminal_artifact_key": self.terminal_artifact_key,
            "terminal_artifact_exists": self.terminal_artifact_exists,
            "total_size_bytes": self.total_size_bytes,
            "content_type_counts": dict(self.content_type_counts),
            "category_counts": dict(self.category_counts),
            "missing_artifact_keys": list(self.missing_artifact_keys),
            "missing_required_keys": list(self.missing_required_keys),
            "largest_artifacts": to_json_safe(self.largest_artifacts),
            "complete": self.complete,
        }


@dataclass(frozen=True)
class WorkflowDataBufferChange:
    key: str
    change_type: str
    sensitive_key: bool
    previous_type: str | None = None
    current_type: str | None = None
    previous_size: int | None = None
    current_size: int | None = None

    @property
    def type_changed(self) -> bool:
        return (
            self.previous_type is not None
            and self.current_type is not None
            and self.previous_type != self.current_type
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "change_type": self.change_type,
            "sensitive_key": self.sensitive_key,
            "previous_type": self.previous_type,
            "current_type": self.current_type,
            "previous_size": self.previous_size,
            "current_size": self.current_size,
            "type_changed": self.type_changed,
        }


@dataclass(frozen=True)
class WorkflowDataBufferDiffSummary:
    added_count: int = 0
    changed_count: int = 0
    removed_count: int = 0
    added_keys: list[str] = field(default_factory=list)
    changed_keys: list[str] = field(default_factory=list)
    removed_keys: list[str] = field(default_factory=list)
    sensitive_keys: list[str] = field(default_factory=list)
    type_changed_keys: list[str] = field(default_factory=list)
    changes: list[WorkflowDataBufferChange] = field(default_factory=list)

    @property
    def total_change_count(self) -> int:
        return self.added_count + self.changed_count + self.removed_count

    @property
    def has_sensitive_changes(self) -> bool:
        return bool(self.sensitive_keys)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added_count": self.added_count,
            "changed_count": self.changed_count,
            "removed_count": self.removed_count,
            "total_change_count": self.total_change_count,
            "added_keys": list(self.added_keys),
            "changed_keys": list(self.changed_keys),
            "removed_keys": list(self.removed_keys),
            "sensitive_keys": list(self.sensitive_keys),
            "type_changed_keys": list(self.type_changed_keys),
            "has_sensitive_changes": self.has_sensitive_changes,
            "changes": [change.to_dict() for change in self.changes],
        }


@dataclass(frozen=True)
class WorkflowRunHealthReport:
    run_id: str | None
    workflow_id: str | None
    workflow_version: str | None
    status: str | None
    severity: str
    summary: str
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    blocked_steps: list[str] = field(default_factory=list)
    paused_steps: list[str] = field(default_factory=list)
    retry_count: int = 0
    timeout_count: int = 0
    checkpoint_count: int = 0
    event_count: int = 0
    artifact_count: int = 0
    missing_artifact_keys: list[str] = field(default_factory=list)
    unexpected_files: list[str] = field(default_factory=list)
    terminal_artifact_key: str | None = None
    terminal_artifact_exists: bool | None = None
    duration_ms: float | None = None

    @property
    def healthy(self) -> bool:
        return self.severity == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "status": self.status,
            "severity": self.severity,
            "healthy": self.healthy,
            "summary": self.summary,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "suggested_actions": list(self.suggested_actions),
            "failed_steps": list(self.failed_steps),
            "blocked_steps": list(self.blocked_steps),
            "paused_steps": list(self.paused_steps),
            "retry_count": self.retry_count,
            "timeout_count": self.timeout_count,
            "checkpoint_count": self.checkpoint_count,
            "event_count": self.event_count,
            "artifact_count": self.artifact_count,
            "missing_artifact_keys": list(self.missing_artifact_keys),
            "unexpected_files": list(self.unexpected_files),
            "terminal_artifact_key": self.terminal_artifact_key,
            "terminal_artifact_exists": self.terminal_artifact_exists,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class WorkflowManifestIntegrityReport:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_artifact_keys: list[str] = field(default_factory=list)
    missing_artifact_files: list[str] = field(default_factory=list)
    unexpected_files: list[str] = field(default_factory=list)
    artifact_count: int = 0
    file_count: int = 0
    total_size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "missing_artifact_keys": list(self.missing_artifact_keys),
            "missing_artifact_files": list(self.missing_artifact_files),
            "unexpected_files": list(self.unexpected_files),
            "artifact_count": self.artifact_count,
            "file_count": self.file_count,
            "total_size_bytes": self.total_size_bytes,
        }


@dataclass(frozen=True)
class WorkflowReplayBundle:
    run_dir: str
    manifest: dict[str, Any]
    request: Any = None
    workflow_spec: Any = None
    workflow_version: Any = None
    data_buffer_initial: Any = None
    data_buffer_final: Any = None
    data_buffer_diff: Any = None
    step_results: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    redaction_report: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: Any = None
    pause: Any = None
    events: list[WorkflowEventRecord] = field(default_factory=list)
    artifacts: list[WorkflowArtifactRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_dir": self.run_dir,
            "manifest": to_json_safe(self.manifest),
            "request": to_json_safe(self.request),
            "workflow_spec": to_json_safe(self.workflow_spec),
            "workflow_version": to_json_safe(self.workflow_version),
            "data_buffer_initial": to_json_safe(self.data_buffer_initial),
            "data_buffer_final": to_json_safe(self.data_buffer_final),
            "data_buffer_diff": to_json_safe(self.data_buffer_diff),
            "step_results": to_json_safe(self.step_results),
            "metrics": to_json_safe(self.metrics),
            "redaction_report": to_json_safe(self.redaction_report),
            "output": to_json_safe(self.output),
            "error": to_json_safe(self.error),
            "pause": to_json_safe(self.pause),
            "events": [event.to_dict() for event in self.events],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True)
class WorkflowRunDiagnostics:
    inspection: WorkflowRunInspection
    timeline: list[WorkflowTimelineItem] = field(default_factory=list)
    timeline_summary: WorkflowTimelineSummary | None = None
    artifact_inventory: WorkflowArtifactInventory | None = None
    data_buffer_diff_summary: WorkflowDataBufferDiffSummary | None = None
    health_report: WorkflowRunHealthReport | None = None

    @property
    def healthy(self) -> bool:
        return bool(self.health_report and self.health_report.healthy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "inspection": self.inspection.to_dict(),
            "timeline": [item.to_dict() for item in self.timeline],
            "timeline_summary": (
                self.timeline_summary.to_dict() if self.timeline_summary else None
            ),
            "artifact_inventory": (
                self.artifact_inventory.to_dict() if self.artifact_inventory else None
            ),
            "data_buffer_diff_summary": (
                self.data_buffer_diff_summary.to_dict()
                if self.data_buffer_diff_summary
                else None
            ),
            "health_report": self.health_report.to_dict() if self.health_report else None,
            "healthy": self.healthy,
        }


@dataclass(frozen=True)
class WorkflowRunInspection:
    run_dir: str
    run_id: str | None
    workflow_id: str | None
    workflow_version: str | None
    status: str | None
    profile: str | None
    started_at: str | None
    finished_at: str | None
    manifest_schema_version: str | None
    manifest: dict[str, Any]
    integrity: WorkflowManifestIntegrityReport
    artifacts: list[WorkflowArtifactRecord] = field(default_factory=list)
    steps: list[WorkflowStepSummary] = field(default_factory=list)
    event_summary: WorkflowEventSummary | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    redaction_report: dict[str, Any] = field(default_factory=dict)
    terminal_artifact_key: str | None = None
    timeline: list[WorkflowTimelineItem] = field(default_factory=list)
    timeline_summary: WorkflowTimelineSummary | None = None
    artifact_inventory: WorkflowArtifactInventory | None = None
    data_buffer_diff_summary: WorkflowDataBufferDiffSummary | None = None
    health_report: WorkflowRunHealthReport | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == WorkflowStatus.SUCCEEDED.value

    @property
    def failed(self) -> bool:
        return self.status in {
            WorkflowStatus.FAILED.value,
            WorkflowStatus.BLOCKED.value,
            WorkflowStatus.BUDGET_EXCEEDED.value,
            WorkflowStatus.CANCELLED.value,
        }

    @property
    def paused(self) -> bool:
        return self.status in {
            WorkflowStatus.PAUSED.value,
            WorkflowStatus.WAITING_FOR_HUMAN.value,
        }

    def artifact_by_key(self, artifact_key: str) -> WorkflowArtifactRecord | None:
        for artifact in self.artifacts:
            if artifact.artifact_key == artifact_key:
                return artifact
        return None

    def step_by_id(self, step_id: str) -> WorkflowStepSummary | None:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_dir": self.run_dir,
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "status": self.status,
            "profile": self.profile,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "manifest_schema_version": self.manifest_schema_version,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "paused": self.paused,
            "terminal_artifact_key": self.terminal_artifact_key,
            "integrity": self.integrity.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "steps": [step.to_dict() for step in self.steps],
            "event_summary": self.event_summary.to_dict() if self.event_summary else None,
            "metrics": to_json_safe(self.metrics),
            "redaction_report": to_json_safe(self.redaction_report),
            "timeline": [item.to_dict() for item in self.timeline],
            "timeline_summary": (
                self.timeline_summary.to_dict() if self.timeline_summary else None
            ),
            "artifact_inventory": (
                self.artifact_inventory.to_dict() if self.artifact_inventory else None
            ),
            "data_buffer_diff_summary": (
                self.data_buffer_diff_summary.to_dict()
                if self.data_buffer_diff_summary
                else None
            ),
            "health_report": self.health_report.to_dict() if self.health_report else None,
            "manifest": to_json_safe(self.manifest),
        }


class WorkflowRunInspector:
    def __init__(self, artifact_root: str | Path | None = None) -> None:
        self._artifact_root = Path(artifact_root) if artifact_root is not None else None

    def inspect_run(
        self,
        run_id: str | None = None,
        *,
        run_dir: str | Path | None = None,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunInspection:
        actual_run_dir = self._resolve_run_dir(run_id=run_id, run_dir=run_dir)
        manifest = self.load_manifest(actual_run_dir)
        integrity = self.validate_run_dir(
            actual_run_dir,
            manifest=manifest,
            verify_checksums=verify_checksums,
        )
        if strict and not integrity.valid:
            raise WorkflowRunInspectionError(
                "workflow run inspection failed: " + "; ".join(integrity.errors)
            )
        artifacts = self.list_artifacts(
            actual_run_dir,
            manifest=manifest,
            verify_checksums=verify_checksums,
        )
        step_results = self.read_json_artifact(
            actual_run_dir,
            "step_results",
            manifest=manifest,
            default={},
        )
        metrics = self.read_json_artifact(
            actual_run_dir,
            "metrics",
            manifest=manifest,
            default={},
        )
        redaction_report = self.read_json_artifact(
            actual_run_dir,
            "redaction_report",
            manifest=manifest,
            default={},
        )
        data_buffer_diff = self.read_json_artifact(
            actual_run_dir,
            "data_buffer_diff",
            manifest=manifest,
            default={},
        )
        events = self.read_events(actual_run_dir, manifest=manifest, missing_ok=True)
        steps = summarize_steps(step_results, manifest=manifest)
        event_summary = summarize_events(events)
        timeline = build_workflow_timeline(events)
        timeline_summary = summarize_workflow_timeline(timeline)
        artifact_inventory = build_artifact_inventory(
            artifacts,
            terminal_artifact_key=terminal_artifact_key(manifest),
        )
        data_buffer_diff_summary = summarize_data_buffer_diff(data_buffer_diff)
        inspection = WorkflowRunInspection(
            run_dir=str(actual_run_dir),
            run_id=_optional_string(manifest.get("run_id")),
            workflow_id=_optional_string(manifest.get("workflow_id")),
            workflow_version=_optional_string(manifest.get("workflow_version")),
            status=_optional_string(manifest.get("status")),
            profile=_optional_string(manifest.get("profile")),
            started_at=_optional_string(manifest.get("started_at")),
            finished_at=_optional_string(manifest.get("finished_at")),
            manifest_schema_version=manifest_schema_version(manifest),
            manifest=manifest,
            integrity=integrity,
            artifacts=artifacts,
            steps=steps,
            event_summary=event_summary,
            metrics=metrics if isinstance(metrics, dict) else {},
            redaction_report=redaction_report if isinstance(redaction_report, dict) else {},
            terminal_artifact_key=terminal_artifact_key(manifest),
            timeline=timeline,
            timeline_summary=timeline_summary,
            artifact_inventory=artifact_inventory,
            data_buffer_diff_summary=data_buffer_diff_summary,
        )
        return replace(
            inspection,
            health_report=build_run_health_report(inspection),
        )

    def build_replay_bundle(
        self,
        run_id: str | None = None,
        *,
        run_dir: str | Path | None = None,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowReplayBundle:
        actual_run_dir = self._resolve_run_dir(run_id=run_id, run_dir=run_dir)
        manifest = self.load_manifest(actual_run_dir)
        integrity = self.validate_run_dir(
            actual_run_dir,
            manifest=manifest,
            verify_checksums=verify_checksums,
        )
        if strict and not integrity.valid:
            raise WorkflowRunInspectionError(
                "workflow run replay bundle is invalid: " + "; ".join(integrity.errors)
            )
        terminal_key = terminal_artifact_key(manifest)
        return WorkflowReplayBundle(
            run_dir=str(actual_run_dir),
            manifest=manifest,
            request=self.read_json_artifact(actual_run_dir, "request", manifest=manifest),
            workflow_spec=self.read_json_artifact(actual_run_dir, "workflow_spec", manifest=manifest),
            workflow_version=self.read_json_artifact(
                actual_run_dir,
                "workflow_version",
                manifest=manifest,
            ),
            data_buffer_initial=self.read_json_artifact(
                actual_run_dir,
                "data_buffer_initial",
                manifest=manifest,
            ),
            data_buffer_final=self.read_json_artifact(
                actual_run_dir,
                "data_buffer_final",
                manifest=manifest,
            ),
            data_buffer_diff=self.read_json_artifact(
                actual_run_dir,
                "data_buffer_diff",
                manifest=manifest,
            ),
            step_results=self.read_json_artifact(
                actual_run_dir,
                "step_results",
                manifest=manifest,
                default={},
            ),
            metrics=self.read_json_artifact(actual_run_dir, "metrics", manifest=manifest, default={}),
            redaction_report=self.read_json_artifact(
                actual_run_dir,
                "redaction_report",
                manifest=manifest,
                default={},
            ),
            output=(
                self.read_json_artifact(actual_run_dir, "output", manifest=manifest, default=None)
                if terminal_key == "output"
                else None
            ),
            error=(
                self.read_json_artifact(actual_run_dir, "error", manifest=manifest, default=None)
                if terminal_key == "error"
                else None
            ),
            pause=(
                self.read_json_artifact(actual_run_dir, "pause", manifest=manifest, default=None)
                if terminal_key == "pause"
                else None
            ),
            events=self.read_events(actual_run_dir, manifest=manifest, missing_ok=True),
            artifacts=self.list_artifacts(
                actual_run_dir,
                manifest=manifest,
                verify_checksums=verify_checksums,
            ),
        )

    def build_diagnostics(
        self,
        run_id: str | None = None,
        *,
        run_dir: str | Path | None = None,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunDiagnostics:
        inspection = self.inspect_run(
            run_id,
            run_dir=run_dir,
            verify_checksums=verify_checksums,
            strict=strict,
        )
        return WorkflowRunDiagnostics(
            inspection=inspection,
            timeline=list(inspection.timeline),
            timeline_summary=inspection.timeline_summary,
            artifact_inventory=inspection.artifact_inventory,
            data_buffer_diff_summary=inspection.data_buffer_diff_summary,
            health_report=inspection.health_report,
        )

    def build_timeline(
        self,
        run_id: str | None = None,
        *,
        run_dir: str | Path | None = None,
    ) -> list[WorkflowTimelineItem]:
        actual_run_dir = self._resolve_run_dir(run_id=run_id, run_dir=run_dir)
        manifest = self.load_manifest(actual_run_dir)
        return build_workflow_timeline(
            self.read_events(actual_run_dir, manifest=manifest, missing_ok=True)
        )

    def build_artifact_inventory(
        self,
        run_id: str | None = None,
        *,
        run_dir: str | Path | None = None,
        verify_checksums: bool = False,
    ) -> WorkflowArtifactInventory:
        actual_run_dir = self._resolve_run_dir(run_id=run_id, run_dir=run_dir)
        manifest = self.load_manifest(actual_run_dir)
        return build_artifact_inventory(
            self.list_artifacts(
                actual_run_dir,
                manifest=manifest,
                verify_checksums=verify_checksums,
            ),
            terminal_artifact_key=terminal_artifact_key(manifest),
        )

    def summarize_data_buffer_diff(
        self,
        run_id: str | None = None,
        *,
        run_dir: str | Path | None = None,
    ) -> WorkflowDataBufferDiffSummary:
        actual_run_dir = self._resolve_run_dir(run_id=run_id, run_dir=run_dir)
        manifest = self.load_manifest(actual_run_dir)
        return summarize_data_buffer_diff(
            self.read_json_artifact(
                actual_run_dir,
                "data_buffer_diff",
                manifest=manifest,
                default={},
            )
        )

    def build_health_report(
        self,
        run_id: str | None = None,
        *,
        run_dir: str | Path | None = None,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunHealthReport:
        inspection = self.inspect_run(
            run_id,
            run_dir=run_dir,
            verify_checksums=verify_checksums,
            strict=strict,
        )
        if inspection.health_report is None:
            return build_run_health_report(inspection)
        return inspection.health_report

    def load_manifest(self, run_dir: str | Path) -> dict[str, Any]:
        path = Path(run_dir) / "manifest.json"
        if not path.exists():
            raise WorkflowRunInspectionError(f"workflow manifest not found: {path}")
        payload = _read_json_file(path)
        if not isinstance(payload, dict):
            raise WorkflowRunInspectionError(f"workflow manifest must be an object: {path}")
        return payload

    def validate_run_dir(
        self,
        run_dir: str | Path,
        *,
        manifest: dict[str, Any] | None = None,
        verify_checksums: bool = False,
    ) -> WorkflowManifestIntegrityReport:
        actual_run_dir = Path(run_dir)
        manifest_payload = manifest or self.load_manifest(actual_run_dir)
        errors: list[str] = []
        warnings: list[str] = []
        try:
            validate_run_manifest(manifest_payload, require_terminal_artifact=True)
        except RunManifestError as exc:
            errors.append(str(exc))

        artifacts = _manifest_artifact_map(manifest_payload)
        missing_artifact_keys = [
            key for key in REQUIRED_RUN_ARTIFACTS if key not in artifacts
        ]
        missing_artifact_files: list[str] = []
        total_size_bytes = 0
        for artifact_key, relative_path in artifacts.items():
            try:
                path = resolve_artifact_path(actual_run_dir, relative_path)
            except WorkflowRunInspectionError as exc:
                errors.append(f"{artifact_key}: {exc}")
                continue
            if not path.exists():
                missing_artifact_files.append(artifact_key)
                errors.append(f"manifest artifact file is missing: {artifact_key} -> {relative_path}")
                continue
            total_size_bytes += path.stat().st_size
            if verify_checksums:
                checksum_warning = _checksum_warning(manifest_payload, artifact_key, path)
                if checksum_warning is not None:
                    warnings.append(checksum_warning)

        unexpected_files = _unexpected_run_files(actual_run_dir, artifacts.values())
        return WorkflowManifestIntegrityReport(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            missing_artifact_keys=missing_artifact_keys,
            missing_artifact_files=missing_artifact_files,
            unexpected_files=unexpected_files,
            artifact_count=len(artifacts),
            file_count=_count_files(actual_run_dir),
            total_size_bytes=total_size_bytes,
        )

    def list_artifacts(
        self,
        run_dir: str | Path,
        *,
        manifest: dict[str, Any] | None = None,
        verify_checksums: bool = False,
    ) -> list[WorkflowArtifactRecord]:
        actual_run_dir = Path(run_dir)
        manifest_payload = manifest or self.load_manifest(actual_run_dir)
        step_artifact_keys = _step_artifact_keys(manifest_payload)
        records: list[WorkflowArtifactRecord] = []
        for artifact_key, relative_path in sorted(_manifest_artifact_map(manifest_payload).items()):
            try:
                path = resolve_artifact_path(actual_run_dir, relative_path)
                exists = path.exists()
            except WorkflowRunInspectionError:
                path = actual_run_dir / str(relative_path)
                exists = False
            size_bytes = path.stat().st_size if exists else None
            checksum = _sha256_file(path) if exists and verify_checksums else None
            records.append(
                WorkflowArtifactRecord(
                    artifact_key=artifact_key,
                    relative_path=_posix_artifact_path(relative_path),
                    absolute_path=path,
                    exists=exists,
                    content_type=content_type_for_path(path),
                    size_bytes=size_bytes,
                    checksum=checksum,
                    required=artifact_key in REQUIRED_RUN_ARTIFACTS,
                    step_artifact=artifact_key in step_artifact_keys,
                    metadata=_artifact_record_metadata(manifest_payload, artifact_key),
                )
            )
        return records

    def read_json_artifact(
        self,
        run_dir: str | Path,
        artifact_key: str,
        *,
        manifest: dict[str, Any] | None = None,
        default: Any = None,
    ) -> Any:
        path = self.artifact_path(run_dir, artifact_key, manifest=manifest, missing_ok=True)
        if path is None or not path.exists():
            return default
        return _read_json_file(path)

    def read_text_artifact(
        self,
        run_dir: str | Path,
        artifact_key: str,
        *,
        manifest: dict[str, Any] | None = None,
        default: str | None = None,
    ) -> str | None:
        path = self.artifact_path(run_dir, artifact_key, manifest=manifest, missing_ok=True)
        if path is None or not path.exists():
            return default
        return path.read_text(encoding="utf-8")

    def read_events(
        self,
        run_dir: str | Path,
        *,
        manifest: dict[str, Any] | None = None,
        missing_ok: bool = False,
    ) -> list[WorkflowEventRecord]:
        path = self.artifact_path(run_dir, "events", manifest=manifest, missing_ok=missing_ok)
        if path is None or not path.exists():
            if missing_ok:
                return []
            raise WorkflowRunInspectionError(f"workflow events artifact not found: {path}")
        return list(_read_event_jsonl(path))

    def artifact_path(
        self,
        run_dir: str | Path,
        artifact_key: str,
        *,
        manifest: dict[str, Any] | None = None,
        missing_ok: bool = False,
    ) -> Path | None:
        actual_run_dir = Path(run_dir)
        manifest_payload = manifest or self.load_manifest(actual_run_dir)
        artifacts = _manifest_artifact_map(manifest_payload)
        relative_path = artifacts.get(artifact_key)
        if relative_path is None:
            if missing_ok:
                return None
            raise WorkflowRunInspectionError(f"artifact key not found in manifest: {artifact_key}")
        return resolve_artifact_path(actual_run_dir, relative_path)

    def iter_artifacts(
        self,
        run_dir: str | Path,
        *,
        manifest: dict[str, Any] | None = None,
    ) -> Iterator[tuple[str, Path]]:
        actual_run_dir = Path(run_dir)
        manifest_payload = manifest or self.load_manifest(actual_run_dir)
        for artifact_key, relative_path in sorted(_manifest_artifact_map(manifest_payload).items()):
            yield artifact_key, resolve_artifact_path(actual_run_dir, relative_path)

    def _resolve_run_dir(
        self,
        *,
        run_id: str | None,
        run_dir: str | Path | None,
    ) -> Path:
        if run_dir is not None:
            return Path(run_dir)
        if run_id is None:
            raise WorkflowRunInspectionError("run_id or run_dir is required")
        if self._artifact_root is None:
            raise WorkflowRunInspectionError("artifact_root is required when inspecting by run_id")
        return self._artifact_root / run_id


def inspect_workflow_run(
    run_dir: str | Path,
    *,
    verify_checksums: bool = False,
    strict: bool = False,
) -> WorkflowRunInspection:
    return WorkflowRunInspector().inspect_run(
        run_dir=run_dir,
        verify_checksums=verify_checksums,
        strict=strict,
    )


def build_workflow_replay_bundle(
    run_dir: str | Path,
    *,
    verify_checksums: bool = False,
    strict: bool = False,
) -> WorkflowReplayBundle:
    return WorkflowRunInspector().build_replay_bundle(
        run_dir=run_dir,
        verify_checksums=verify_checksums,
        strict=strict,
    )


def inspect_workflow_run_diagnostics(
    run_dir: str | Path,
    *,
    verify_checksums: bool = False,
    strict: bool = False,
) -> WorkflowRunDiagnostics:
    return WorkflowRunInspector().build_diagnostics(
        run_dir=run_dir,
        verify_checksums=verify_checksums,
        strict=strict,
    )


def resolve_artifact_path(run_dir: str | Path, relative_path: str) -> Path:
    root = Path(run_dir).resolve()
    relative = Path(str(relative_path).replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise WorkflowRunInspectionError(
            f"artifact path must stay within the run directory: {relative_path}"
        )
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkflowRunInspectionError(
            f"artifact path must stay within the run directory: {relative_path}"
        ) from exc
    return path


def content_type_for_path(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".jsonl":
        return "application/x-ndjson"
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".txt":
        return "text/plain"
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".csv":
        return "text/csv"
    return "application/octet-stream"


def terminal_artifact_key(manifest: dict[str, Any]) -> str | None:
    status = manifest.get("status")
    if status is None:
        return None
    return TERMINAL_ARTIFACT_BY_STATUS.get(str(status))


def summarize_steps(
    step_results: Any,
    *,
    manifest: dict[str, Any] | None = None,
) -> list[WorkflowStepSummary]:
    if not isinstance(step_results, dict):
        return []
    manifest_steps = manifest.get("steps") if manifest else None
    summaries: list[WorkflowStepSummary] = []
    for step_id, raw_outcome in step_results.items():
        if not isinstance(raw_outcome, dict):
            continue
        outputs = raw_outcome.get("outputs")
        artifacts = raw_outcome.get("artifacts")
        lineage = raw_outcome.get("lineage")
        metrics = raw_outcome.get("metrics")
        status = str(raw_outcome.get("status") or StepStatus.SUCCEEDED.value)
        output_keys = sorted(str(key) for key in outputs) if isinstance(outputs, dict) else []
        summary = WorkflowStepSummary(
            step_id=str(step_id),
            status=status,
            output_keys=output_keys,
            error_type=_optional_string(raw_outcome.get("error_type")),
            error_message=_optional_string(raw_outcome.get("error_message")),
            metrics=dict(metrics) if isinstance(metrics, dict) else {},
            artifact_count=len(artifacts) if isinstance(artifacts, list) else 0,
            lineage_count=len(lineage) if isinstance(lineage, list) else 0,
            next_hint=_optional_string(raw_outcome.get("next_hint")),
        )
        if isinstance(manifest_steps, dict) and str(step_id) in manifest_steps:
            summary = _merge_manifest_step_summary(summary, manifest_steps[str(step_id)])
        summaries.append(summary)
    return sorted(summaries, key=lambda item: item.step_id)


def summarize_events(events: Iterable[WorkflowEventRecord]) -> WorkflowEventSummary:
    event_list = list(events)
    event_type_counts = Counter(event.event_type for event in event_list)
    step_event_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for event in event_list:
        if event.step_id:
            step_event_counts[event.step_id][event.event_type] += 1
    first_event_at = event_list[0].occurred_at if event_list else None
    last_event_at = event_list[-1].occurred_at if event_list else None
    terminal_event_type = None
    for event in reversed(event_list):
        if event.event_type.startswith("workflow_"):
            terminal_event_type = event.event_type
            break
    return WorkflowEventSummary(
        event_count=len(event_list),
        event_type_counts=dict(sorted(event_type_counts.items())),
        step_event_counts={
            step_id: dict(sorted(counts.items()))
            for step_id, counts in sorted(step_event_counts.items())
        },
        first_event_at=first_event_at,
        last_event_at=last_event_at,
        terminal_event_type=terminal_event_type,
    )


def build_workflow_timeline(
    events: Iterable[WorkflowEventRecord],
) -> list[WorkflowTimelineItem]:
    timeline: list[WorkflowTimelineItem] = []
    for index, event in enumerate(events, start=1):
        timeline.append(_timeline_item_from_event(event, sequence=index))
    return timeline


def summarize_workflow_timeline(
    timeline: Iterable[WorkflowTimelineItem],
) -> WorkflowTimelineSummary:
    items = list(timeline)
    phase_counts = Counter(item.phase for item in items)
    severity_counts = Counter(item.severity for item in items)
    event_type_counts = Counter(item.event_type for item in items)
    step_event_counts: dict[str, Counter[str]] = defaultdict(Counter)
    traversed_edges: list[dict[str, Any]] = []
    rejected_edges: list[dict[str, Any]] = []
    terminal_event_type = None
    for item in items:
        if item.step_id:
            step_event_counts[item.step_id][item.event_type] += 1
        if item.event_type == "edge_traversed":
            traversed_edges.append(_timeline_edge_dict(item))
        elif item.event_type == "edge_rejected":
            rejected_edges.append(_timeline_edge_dict(item))
        if item.terminal:
            terminal_event_type = item.event_type
    first_event_at = items[0].occurred_at if items else None
    last_event_at = items[-1].occurred_at if items else None
    return WorkflowTimelineSummary(
        event_count=len(items),
        phase_counts=dict(sorted(phase_counts.items())),
        severity_counts=dict(sorted(severity_counts.items())),
        event_type_counts=dict(sorted(event_type_counts.items())),
        step_event_counts={
            step_id: dict(sorted(counts.items()))
            for step_id, counts in sorted(step_event_counts.items())
        },
        first_event_at=first_event_at,
        last_event_at=last_event_at,
        duration_ms=_duration_ms(first_event_at, last_event_at),
        terminal_event_type=terminal_event_type,
        traversed_edges=traversed_edges,
        rejected_edges=rejected_edges,
        retry_count=event_type_counts.get("step_retry_scheduled", 0),
        timeout_count=event_type_counts.get("step_timeout", 0),
        checkpoint_count=event_type_counts.get("checkpoint_created", 0),
        workflow_event_count=phase_counts.get("workflow", 0),
        step_event_count=phase_counts.get("step", 0),
        routing_event_count=phase_counts.get("routing", 0),
    )


def build_artifact_inventory(
    artifacts: Iterable[WorkflowArtifactRecord],
    *,
    terminal_artifact_key: str | None = None,
    largest_limit: int = 10,
) -> WorkflowArtifactInventory:
    artifact_list = list(artifacts)
    content_type_counts = Counter(artifact.content_type for artifact in artifact_list)
    category_counts = Counter(_artifact_category(artifact) for artifact in artifact_list)
    missing = [artifact for artifact in artifact_list if not artifact.exists]
    required = [artifact for artifact in artifact_list if artifact.required]
    missing_required = [
        artifact.artifact_key
        for artifact in missing
        if artifact.required
    ]
    terminal_record = None
    if terminal_artifact_key is not None:
        for artifact in artifact_list:
            if artifact.artifact_key == terminal_artifact_key:
                terminal_record = artifact
                break
    largest_artifacts = [
        {
            "artifact_key": artifact.artifact_key,
            "relative_path": artifact.relative_path,
            "content_type": artifact.content_type,
            "size_bytes": artifact.size_bytes,
        }
        for artifact in sorted(
            (item for item in artifact_list if item.size_bytes is not None),
            key=lambda item: item.size_bytes or 0,
            reverse=True,
        )[: max(0, largest_limit)]
    ]
    return WorkflowArtifactInventory(
        artifact_count=len(artifact_list),
        existing_count=sum(1 for artifact in artifact_list if artifact.exists),
        missing_count=len(missing),
        required_count=len(required),
        missing_required_count=len(missing_required),
        step_artifact_count=sum(1 for artifact in artifact_list if artifact.step_artifact),
        terminal_artifact_key=terminal_artifact_key,
        terminal_artifact_exists=terminal_record.exists if terminal_record else None,
        total_size_bytes=sum(artifact.size_bytes or 0 for artifact in artifact_list),
        content_type_counts=dict(sorted(content_type_counts.items())),
        category_counts=dict(sorted(category_counts.items())),
        missing_artifact_keys=[artifact.artifact_key for artifact in missing],
        missing_required_keys=missing_required,
        largest_artifacts=largest_artifacts,
    )


def summarize_data_buffer_diff(diff_payload: Any) -> WorkflowDataBufferDiffSummary:
    if not isinstance(diff_payload, dict):
        return WorkflowDataBufferDiffSummary()
    added = _dict_or_empty(diff_payload.get("added"))
    changed = _dict_or_empty(diff_payload.get("changed"))
    removed = _dict_or_empty(diff_payload.get("removed"))
    changes: list[WorkflowDataBufferChange] = []

    for key, value in sorted(added.items()):
        changes.append(
            WorkflowDataBufferChange(
                key=str(key),
                change_type="added",
                sensitive_key=_looks_sensitive_buffer_key(str(key)),
                current_type=_value_type(value),
                current_size=_collection_size(value),
            )
        )
    for key, payload in sorted(changed.items()):
        previous_value = None
        current_value = None
        if isinstance(payload, dict):
            previous_value = payload.get("previous")
            current_value = payload.get("current")
        changes.append(
            WorkflowDataBufferChange(
                key=str(key),
                change_type="changed",
                sensitive_key=_looks_sensitive_buffer_key(str(key)),
                previous_type=_value_type(previous_value),
                current_type=_value_type(current_value),
                previous_size=_collection_size(previous_value),
                current_size=_collection_size(current_value),
            )
        )
    for key, value in sorted(removed.items()):
        changes.append(
            WorkflowDataBufferChange(
                key=str(key),
                change_type="removed",
                sensitive_key=_looks_sensitive_buffer_key(str(key)),
                previous_type=_value_type(value),
                previous_size=_collection_size(value),
            )
        )
    sensitive_keys = sorted(
        {change.key for change in changes if change.sensitive_key}
    )
    type_changed_keys = sorted(
        {change.key for change in changes if change.type_changed}
    )
    return WorkflowDataBufferDiffSummary(
        added_count=len(added),
        changed_count=len(changed),
        removed_count=len(removed),
        added_keys=sorted(str(key) for key in added),
        changed_keys=sorted(str(key) for key in changed),
        removed_keys=sorted(str(key) for key in removed),
        sensitive_keys=sensitive_keys,
        type_changed_keys=type_changed_keys,
        changes=changes,
    )


def build_run_health_report(
    inspection: WorkflowRunInspection,
) -> WorkflowRunHealthReport:
    timeline_summary = inspection.timeline_summary or summarize_workflow_timeline(
        inspection.timeline
    )
    artifact_inventory = inspection.artifact_inventory or build_artifact_inventory(
        inspection.artifacts,
        terminal_artifact_key=inspection.terminal_artifact_key,
    )
    issues: list[str] = []
    warnings: list[str] = []
    actions: list[str] = []
    failed_steps = sorted(
        step.step_id
        for step in inspection.steps
        if step.status
        in {
            StepStatus.FAILED.value,
            StepStatus.TIMEOUT.value,
            StepStatus.CANCELLED.value,
        }
    )
    blocked_steps = sorted(
        step.step_id for step in inspection.steps if step.status == StepStatus.BLOCKED.value
    )
    paused_steps = sorted(
        step.step_id for step in inspection.steps if step.status == StepStatus.PAUSED.value
    )

    if not inspection.integrity.valid:
        issues.extend(inspection.integrity.errors)
        actions.append("inspect manifest.json and restore missing run artifacts")
    if inspection.integrity.missing_artifact_keys:
        issues.append(
            "missing required manifest artifact keys: "
            + ", ".join(inspection.integrity.missing_artifact_keys)
        )
    if artifact_inventory.missing_artifact_keys:
        issues.append(
            "missing artifact files: " + ", ".join(artifact_inventory.missing_artifact_keys)
        )
    if failed_steps:
        issues.append("failed steps: " + ", ".join(failed_steps))
        actions.append("open step_results.json and events.jsonl for failed step details")
    if inspection.status in {
        WorkflowStatus.FAILED.value,
        WorkflowStatus.CANCELLED.value,
        WorkflowStatus.BUDGET_EXCEEDED.value,
    }:
        issues.append(f"workflow ended with status {inspection.status}")
    if inspection.status == WorkflowStatus.BLOCKED.value:
        warnings.append("workflow is blocked by policy or governance state")
        actions.append("inspect error.json and step policy output before retrying")
    if inspection.paused:
        warnings.append("workflow is paused and requires resume input")
        actions.append("resume from checkpoint after the required external input is available")
    if inspection.integrity.warnings:
        warnings.extend(inspection.integrity.warnings)
    if inspection.integrity.unexpected_files:
        warnings.append(
            "run directory contains files not referenced by manifest: "
            + ", ".join(inspection.integrity.unexpected_files[:10])
        )
    if timeline_summary.timeout_count:
        warnings.append(f"step timeout events: {timeline_summary.timeout_count}")
    if timeline_summary.retry_count:
        warnings.append(f"step retry events: {timeline_summary.retry_count}")
    if inspection.event_summary is None or inspection.event_summary.event_count == 0:
        warnings.append("run has no event records")
    if (
        inspection.terminal_artifact_key is not None
        and artifact_inventory.terminal_artifact_exists is False
    ):
        issues.append(f"terminal artifact is missing: {inspection.terminal_artifact_key}")

    severity = _health_severity(
        inspection,
        issues=issues,
        warnings=warnings,
    )
    summary = _health_summary(
        inspection,
        severity=severity,
        issue_count=len(issues),
        warning_count=len(warnings),
    )
    return WorkflowRunHealthReport(
        run_id=inspection.run_id,
        workflow_id=inspection.workflow_id,
        workflow_version=inspection.workflow_version,
        status=inspection.status,
        severity=severity,
        summary=summary,
        issues=_dedupe_preserve_order(issues),
        warnings=_dedupe_preserve_order(warnings),
        suggested_actions=_dedupe_preserve_order(actions),
        failed_steps=failed_steps,
        blocked_steps=blocked_steps,
        paused_steps=paused_steps,
        retry_count=timeline_summary.retry_count,
        timeout_count=timeline_summary.timeout_count,
        checkpoint_count=timeline_summary.checkpoint_count,
        event_count=timeline_summary.event_count,
        artifact_count=artifact_inventory.artifact_count,
        missing_artifact_keys=artifact_inventory.missing_artifact_keys,
        unexpected_files=list(inspection.integrity.unexpected_files),
        terminal_artifact_key=inspection.terminal_artifact_key,
        terminal_artifact_exists=artifact_inventory.terminal_artifact_exists,
        duration_ms=timeline_summary.duration_ms,
    )


def timeline_items_by_step(
    timeline: Iterable[WorkflowTimelineItem],
    step_id: str,
) -> list[WorkflowTimelineItem]:
    return [item for item in timeline if item.step_id == step_id]


def timeline_items_by_event_type(
    timeline: Iterable[WorkflowTimelineItem],
    event_type: str,
) -> list[WorkflowTimelineItem]:
    return [item for item in timeline if item.event_type == event_type]


def timeline_items_by_phase(
    timeline: Iterable[WorkflowTimelineItem],
    phase: str,
) -> list[WorkflowTimelineItem]:
    return [item for item in timeline if item.phase == phase]


def unhealthy_timeline_items(
    timeline: Iterable[WorkflowTimelineItem],
) -> list[WorkflowTimelineItem]:
    return [item for item in timeline if item.severity in {"warning", "error"}]


def health_report_summary(report: WorkflowRunHealthReport) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "workflow_id": report.workflow_id,
        "workflow_version": report.workflow_version,
        "status": report.status,
        "severity": report.severity,
        "healthy": report.healthy,
        "issue_count": len(report.issues),
        "warning_count": len(report.warnings),
        "failed_steps": list(report.failed_steps),
        "missing_artifact_keys": list(report.missing_artifact_keys),
        "retry_count": report.retry_count,
        "timeout_count": report.timeout_count,
        "event_count": report.event_count,
        "artifact_count": report.artifact_count,
    }


def _timeline_item_from_event(
    event: WorkflowEventRecord,
    *,
    sequence: int,
) -> WorkflowTimelineItem:
    payload = event.payload if isinstance(event.payload, dict) else {}
    outcome = payload.get("outcome") if isinstance(payload.get("outcome"), dict) else {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    step_id = (
        event.step_id
        or _optional_string(payload.get("step_id"))
        or _optional_string(outcome.get("step_id"))
    )
    edge_id = _optional_string(payload.get("edge_id"))
    source_step_id = _optional_string(payload.get("source_step_id"))
    target_step_id = _optional_string(payload.get("target_step_id"))
    status = (
        _optional_string(payload.get("status"))
        or _optional_string(outcome.get("status"))
        or _status_from_event_type(event.event_type)
    )
    severity = _event_severity(event.event_type, status=status)
    return WorkflowTimelineItem(
        sequence=sequence,
        event_type=event.event_type,
        phase=_event_phase(event.event_type),
        severity=severity,
        run_id=event.run_id,
        occurred_at=event.occurred_at,
        step_id=step_id,
        edge_id=edge_id,
        source_step_id=source_step_id,
        target_step_id=target_step_id,
        status=status,
        message=_timeline_message(
            event.event_type,
            step_id=step_id,
            source_step_id=source_step_id,
            target_step_id=target_step_id,
            edge_id=edge_id,
            status=status,
            payload=payload,
            outcome=outcome,
            error=error,
        ),
        payload_keys=sorted(str(key) for key in payload),
        payload_excerpt=_payload_excerpt(payload),
        terminal=_is_terminal_event(event.event_type),
    )


def _event_phase(event_type: str) -> str:
    if event_type.startswith("workflow_"):
        return "workflow"
    if event_type.startswith("step_"):
        return "step"
    if event_type.startswith("edge_"):
        return "routing"
    if event_type.startswith("checkpoint_"):
        return "checkpoint"
    if event_type in {"human_review_requested"}:
        return "human"
    if event_type in {"policy_violation"}:
        return "policy"
    return "runtime"


def _event_severity(event_type: str, *, status: str | None = None) -> str:
    error_events = {
        "workflow_failed",
        "workflow_loop_limit_exceeded",
        "step_failed",
        "step_timeout",
        "policy_violation",
    }
    warning_events = {
        "workflow_blocked",
        "workflow_paused",
        "step_blocked",
        "step_paused",
        "step_retry_scheduled",
        "edge_rejected",
        "human_review_requested",
    }
    if event_type in error_events:
        return "error"
    if event_type in warning_events:
        return "warning"
    if status in {
        StepStatus.FAILED.value,
        StepStatus.TIMEOUT.value,
        WorkflowStatus.FAILED.value,
        WorkflowStatus.BUDGET_EXCEEDED.value,
    }:
        return "error"
    if status in {
        StepStatus.BLOCKED.value,
        StepStatus.PAUSED.value,
        WorkflowStatus.BLOCKED.value,
        WorkflowStatus.PAUSED.value,
        WorkflowStatus.WAITING_FOR_HUMAN.value,
    }:
        return "warning"
    return "info"


def _status_from_event_type(event_type: str) -> str | None:
    if event_type == "workflow_succeeded":
        return WorkflowStatus.SUCCEEDED.value
    if event_type == "workflow_failed":
        return WorkflowStatus.FAILED.value
    if event_type == "workflow_blocked":
        return WorkflowStatus.BLOCKED.value
    if event_type == "workflow_paused":
        return WorkflowStatus.PAUSED.value
    if event_type == "step_succeeded":
        return StepStatus.SUCCEEDED.value
    if event_type == "step_failed":
        return StepStatus.FAILED.value
    if event_type == "step_timeout":
        return StepStatus.TIMEOUT.value
    if event_type == "step_blocked":
        return StepStatus.BLOCKED.value
    if event_type == "step_paused":
        return StepStatus.PAUSED.value
    return None


def _timeline_message(
    event_type: str,
    *,
    step_id: str | None,
    source_step_id: str | None,
    target_step_id: str | None,
    edge_id: str | None,
    status: str | None,
    payload: dict[str, Any],
    outcome: dict[str, Any],
    error: dict[str, Any],
) -> str:
    if event_type == "workflow_started":
        return "workflow started"
    if event_type == "workflow_resumed":
        checkpoint_id = payload.get("checkpoint_id")
        return f"workflow resumed from checkpoint {checkpoint_id}" if checkpoint_id else "workflow resumed"
    if event_type == "checkpoint_restored":
        return "checkpoint restored"
    if event_type == "checkpoint_created":
        checkpoint_id = payload.get("checkpoint_id")
        return f"checkpoint created {checkpoint_id}" if checkpoint_id else "checkpoint created"
    if event_type == "step_started":
        return f"step started: {step_id}" if step_id else "step started"
    if event_type == "step_succeeded":
        outputs = payload.get("outputs")
        if isinstance(outputs, list):
            return f"step succeeded: {step_id} outputs={len(outputs)}"
        return f"step succeeded: {step_id}" if step_id else "step succeeded"
    if event_type == "step_failed":
        message = outcome.get("error_message") or payload.get("message")
        return f"step failed: {step_id} ({message})" if message else f"step failed: {step_id}"
    if event_type == "step_timeout":
        return f"step timed out: {step_id}" if step_id else "step timed out"
    if event_type == "step_retry_scheduled":
        attempt = payload.get("attempt")
        return f"step retry scheduled: {step_id} attempt={attempt}"
    if event_type == "step_blocked":
        return f"step blocked: {step_id}" if step_id else "step blocked"
    if event_type == "step_paused":
        return f"step paused: {step_id}" if step_id else "step paused"
    if event_type == "edge_traversed":
        return _edge_message("edge traversed", edge_id, source_step_id, target_step_id)
    if event_type == "edge_rejected":
        return _edge_message("edge rejected", edge_id, source_step_id, target_step_id)
    if event_type == "edge_evaluated":
        return _edge_message("edge evaluated", edge_id, source_step_id, target_step_id)
    if event_type == "human_review_requested":
        return f"human review requested: {step_id}" if step_id else "human review requested"
    if event_type == "policy_violation":
        return _optional_string(payload.get("message")) or "policy violation"
    if event_type == "workflow_succeeded":
        return "workflow succeeded"
    if event_type == "workflow_failed":
        message = error.get("message") or payload.get("message")
        return f"workflow failed: {message}" if message else "workflow failed"
    if event_type == "workflow_blocked":
        return "workflow blocked"
    if event_type == "workflow_paused":
        return "workflow paused"
    if status:
        return f"{event_type}: {status}"
    return event_type


def _edge_message(
    prefix: str,
    edge_id: str | None,
    source_step_id: str | None,
    target_step_id: str | None,
) -> str:
    route = " -> ".join(
        item for item in (source_step_id, target_step_id) if item is not None
    )
    if edge_id and route:
        return f"{prefix}: {edge_id} {route}"
    if edge_id:
        return f"{prefix}: {edge_id}"
    if route:
        return f"{prefix}: {route}"
    return prefix


def _payload_excerpt(payload: dict[str, Any], *, max_keys: int = 8) -> dict[str, Any]:
    priority_keys = [
        "step_id",
        "checkpoint_id",
        "edge_id",
        "source_step_id",
        "target_step_id",
        "condition",
        "matched",
        "outputs",
        "error_type",
        "message",
        "reason",
        "path",
    ]
    excerpt: dict[str, Any] = {}
    for key in priority_keys:
        if key in payload:
            excerpt[key] = _value_preview(payload[key])
        if len(excerpt) >= max_keys:
            return excerpt
    for key in sorted(str(item) for item in payload):
        if key in excerpt:
            continue
        excerpt[key] = _value_preview(payload[key])
        if len(excerpt) >= max_keys:
            break
    return excerpt


def _value_preview(value: Any) -> Any:
    safe_value = to_json_safe(value)
    if isinstance(safe_value, dict):
        keys = sorted(str(key) for key in safe_value)
        return {
            "type": "dict",
            "key_count": len(keys),
            "keys": keys[:10],
        }
    if isinstance(safe_value, list):
        return {
            "type": "list",
            "item_count": len(safe_value),
        }
    if isinstance(safe_value, str) and len(safe_value) > 160:
        return safe_value[:157] + "..."
    return safe_value


def _is_terminal_event(event_type: str) -> bool:
    return event_type in {
        "workflow_succeeded",
        "workflow_failed",
        "workflow_blocked",
        "workflow_paused",
        "workflow_cancelled",
    }


def _timeline_edge_dict(item: WorkflowTimelineItem) -> dict[str, Any]:
    return {
        "edge_id": item.edge_id,
        "source_step_id": item.source_step_id,
        "target_step_id": item.target_step_id,
        "event_type": item.event_type,
        "sequence": item.sequence,
        "occurred_at": item.occurred_at,
    }


def _artifact_category(artifact: WorkflowArtifactRecord) -> str:
    key = artifact.artifact_key
    path = artifact.relative_path
    if artifact.step_artifact or key.startswith("step."):
        return "step"
    if key in REQUIRED_RUN_ARTIFACTS:
        return "required"
    if key in {"output", "error", "pause"}:
        return "terminal"
    if key.startswith("data_buffer"):
        return "data_buffer"
    if key.startswith("source_") or path.startswith("source_"):
        return "source"
    if "evidence" in key or "claim" in key or "citation" in key or "quality" in key:
        return "quality"
    if "report" in key:
        return "report"
    if key.startswith("agent_"):
        return "agent"
    return "runtime"


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _looks_sensitive_buffer_key(key: str) -> bool:
    key_lower = key.casefold()
    return any(
        token in key_lower
        for token in (
            "api_key",
            "apikey",
            "authorization",
            "client_secret",
            "credential",
            "password",
            "secret",
            "token",
        )
    )


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, tuple):
        return "tuple"
    if isinstance(value, set):
        return "set"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _collection_size(value: Any) -> int | None:
    if isinstance(value, (dict, list, tuple, set, str)):
        return len(value)
    return None


def _duration_ms(
    started_at: str | None,
    finished_at: str | None,
) -> float | None:
    started = _parse_timestamp(started_at)
    finished = _parse_timestamp(finished_at)
    if started is None or finished is None:
        return None
    return round((finished - started).total_seconds() * 1000, 3)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _health_severity(
    inspection: WorkflowRunInspection,
    *,
    issues: list[str],
    warnings: list[str],
) -> str:
    if issues:
        return "error"
    if inspection.status == WorkflowStatus.BLOCKED.value:
        return "blocked"
    if inspection.paused:
        return "paused"
    if warnings:
        return "warning"
    if inspection.status == WorkflowStatus.SUCCEEDED.value:
        return "ok"
    if inspection.status is None:
        return "unknown"
    return "warning"


def _health_summary(
    inspection: WorkflowRunInspection,
    *,
    severity: str,
    issue_count: int,
    warning_count: int,
) -> str:
    run_id = inspection.run_id or "<unknown>"
    status = inspection.status or "unknown"
    if severity == "ok":
        return f"run {run_id} completed successfully"
    if severity == "paused":
        return f"run {run_id} is paused with status {status}"
    if severity == "blocked":
        return f"run {run_id} is blocked"
    if severity == "error":
        return f"run {run_id} has {issue_count} issue(s)"
    if severity == "warning":
        return f"run {run_id} has {warning_count} warning(s)"
    return f"run {run_id} status is {status}"


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _merge_manifest_step_summary(
    summary: WorkflowStepSummary,
    manifest_step: Any,
) -> WorkflowStepSummary:
    if not isinstance(manifest_step, dict):
        return summary
    manifest_outputs = manifest_step.get("outputs")
    output_keys = list(summary.output_keys)
    if isinstance(manifest_outputs, dict):
        output_keys = sorted({*output_keys, *(str(key) for key in manifest_outputs)})
    artifacts = manifest_step.get("artifacts")
    lineage = manifest_step.get("lineage")
    metrics = dict(summary.metrics)
    manifest_metrics = manifest_step.get("metrics")
    if isinstance(manifest_metrics, dict):
        metrics.update(manifest_metrics)
    return WorkflowStepSummary(
        step_id=summary.step_id,
        status=summary.status,
        output_keys=output_keys,
        error_type=summary.error_type,
        error_message=summary.error_message,
        metrics=metrics,
        artifact_count=max(summary.artifact_count, len(artifacts) if isinstance(artifacts, list) else 0),
        lineage_count=max(summary.lineage_count, len(lineage) if isinstance(lineage, list) else 0),
        next_hint=summary.next_hint,
    )


def _read_json_file(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise WorkflowRunInspectionError(f"invalid JSON artifact: {path}") from exc
    except OSError as exc:
        raise WorkflowRunInspectionError(f"failed to read artifact: {path}") from exc


def _read_event_jsonl(path: Path) -> Iterator[WorkflowEventRecord]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise WorkflowRunInspectionError(
                        f"invalid event JSON at {path}:{line_number}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise WorkflowRunInspectionError(
                        f"event record must be an object at {path}:{line_number}"
                    )
                yield _event_from_payload(payload, line_number=line_number)
    except OSError as exc:
        raise WorkflowRunInspectionError(f"failed to read events artifact: {path}") from exc


def _event_from_payload(payload: dict[str, Any], *, line_number: int) -> WorkflowEventRecord:
    event_payload = payload.get("payload")
    if not isinstance(event_payload, dict):
        event_payload = {}
    step_id = payload.get("step_id") or event_payload.get("step_id")
    return WorkflowEventRecord(
        event_id=_optional_string(payload.get("event_id")),
        event_type=str(payload.get("event_type") or "unknown"),
        run_id=_optional_string(payload.get("run_id")),
        occurred_at=_optional_string(payload.get("occurred_at")),
        step_id=_optional_string(step_id),
        payload=event_payload,
        line_number=line_number,
    )


def _manifest_artifact_map(manifest: dict[str, Any]) -> dict[str, str]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in artifacts.items()
        if isinstance(value, str)
    }


def _step_artifact_keys(manifest: dict[str, Any]) -> set[str]:
    raw_step_artifacts = manifest.get("step_artifacts")
    if not isinstance(raw_step_artifacts, list):
        return set()
    keys: set[str] = set()
    for item in raw_step_artifacts:
        if not isinstance(item, dict):
            continue
        try:
            keys.add(manifest_step_artifact_key(item))
        except RunManifestError:
            continue
    return keys


def _artifact_record_metadata(manifest: dict[str, Any], artifact_key: str) -> dict[str, Any]:
    metadata = {
        "schema_version": manifest_schema_version(manifest),
        "run_id": manifest.get("run_id"),
        "workflow_id": manifest.get("workflow_id"),
        "workflow_version": manifest.get("workflow_version"),
        "status": manifest.get("status"),
    }
    if artifact_key in REQUIRED_RUN_ARTIFACTS:
        metadata["required"] = True
    terminal_key = terminal_artifact_key(manifest)
    if terminal_key == artifact_key:
        metadata["terminal"] = True
    return metadata


def _unexpected_run_files(run_dir: Path, manifest_paths: Iterable[str]) -> list[str]:
    if not run_dir.exists():
        return []
    manifest_path_set = {_posix_artifact_path(path) for path in manifest_paths}
    unexpected: list[str] = []
    for file_path in sorted(path for path in run_dir.rglob("*") if path.is_file()):
        try:
            relative = file_path.relative_to(run_dir).as_posix()
        except ValueError:
            continue
        if relative not in manifest_path_set:
            unexpected.append(relative)
    return unexpected


def _checksum_warning(
    manifest: dict[str, Any],
    artifact_key: str,
    path: Path,
) -> str | None:
    step_artifact = _step_artifact_payload_for_key(manifest, artifact_key)
    if step_artifact is None:
        return None
    expected = step_artifact.get("checksum")
    if not expected:
        return None
    actual = _sha256_file(path)
    if actual == expected:
        return None
    return f"manifest artifact checksum mismatch: {artifact_key}"


def _step_artifact_payload_for_key(
    manifest: dict[str, Any],
    artifact_key: str,
) -> dict[str, Any] | None:
    raw_step_artifacts = manifest.get("step_artifacts")
    if not isinstance(raw_step_artifacts, list):
        return None
    for item in raw_step_artifacts:
        if not isinstance(item, dict):
            continue
        try:
            key = manifest_step_artifact_key(item)
        except RunManifestError:
            continue
        if key == artifact_key:
            return item
    return None


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_files(run_dir: Path) -> int:
    if not run_dir.exists():
        return 0
    return sum(1 for path in run_dir.rglob("*") if path.is_file())


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def workflow_run_inspection_summary(inspection: WorkflowRunInspection) -> dict[str, Any]:
    failed_steps = [step.step_id for step in inspection.steps if step.failed]
    missing_artifacts = list(inspection.integrity.missing_artifact_files)
    return {
        "run_id": inspection.run_id,
        "workflow_id": inspection.workflow_id,
        "workflow_version": inspection.workflow_version,
        "status": inspection.status,
        "profile": inspection.profile,
        "started_at": inspection.started_at,
        "finished_at": inspection.finished_at,
        "valid": inspection.integrity.valid,
        "artifact_count": len(inspection.artifacts),
        "step_count": len(inspection.steps),
        "failed_steps": failed_steps,
        "missing_artifacts": missing_artifacts,
        "event_count": inspection.event_summary.event_count if inspection.event_summary else 0,
        "terminal_artifact_key": inspection.terminal_artifact_key,
        "health_severity": (
            inspection.health_report.severity if inspection.health_report else None
        ),
        "retry_count": (
            inspection.timeline_summary.retry_count if inspection.timeline_summary else 0
        ),
        "timeout_count": (
            inspection.timeline_summary.timeout_count if inspection.timeline_summary else 0
        ),
        "data_buffer_change_count": (
            inspection.data_buffer_diff_summary.total_change_count
            if inspection.data_buffer_diff_summary
            else 0
        ),
    }


def replay_bundle_summary(bundle: WorkflowReplayBundle) -> dict[str, Any]:
    manifest = bundle.manifest
    status = manifest.get("status")
    terminal_key = terminal_artifact_key(manifest)
    return {
        "run_id": manifest.get("run_id"),
        "workflow_id": manifest.get("workflow_id"),
        "workflow_version": manifest.get("workflow_version"),
        "status": status,
        "terminal_artifact_key": terminal_key,
        "event_count": len(bundle.events),
        "artifact_count": len(bundle.artifacts),
        "step_result_count": len(bundle.step_results),
        "has_request": bundle.request is not None,
        "has_output": bundle.output is not None,
        "has_error": bundle.error is not None,
        "has_pause": bundle.pause is not None,
    }


def filter_artifacts_by_prefix(
    artifacts: Iterable[WorkflowArtifactRecord],
    prefix: str,
) -> list[WorkflowArtifactRecord]:
    normalized_prefix = _posix_artifact_path(prefix).rstrip("/")
    return [
        artifact
        for artifact in artifacts
        if artifact.artifact_key == prefix
        or artifact.artifact_key.startswith(prefix)
        or artifact.relative_path == normalized_prefix
        or artifact.relative_path.startswith(f"{normalized_prefix}/")
    ]


def failed_step_summaries(inspection: WorkflowRunInspection) -> list[WorkflowStepSummary]:
    return [step for step in inspection.steps if step.failed]


def required_artifact_records(inspection: WorkflowRunInspection) -> list[WorkflowArtifactRecord]:
    return [artifact for artifact in inspection.artifacts if artifact.required]


def step_artifact_records(inspection: WorkflowRunInspection) -> list[WorkflowArtifactRecord]:
    return [artifact for artifact in inspection.artifacts if artifact.step_artifact]


def terminal_artifact_record(inspection: WorkflowRunInspection) -> WorkflowArtifactRecord | None:
    if inspection.terminal_artifact_key is None:
        return None
    return inspection.artifact_by_key(inspection.terminal_artifact_key)


def event_records_by_type(
    events: Iterable[WorkflowEventRecord],
    event_type: str,
) -> list[WorkflowEventRecord]:
    return [event for event in events if event.event_type == event_type]


def event_records_by_step(
    events: Iterable[WorkflowEventRecord],
    step_id: str,
) -> list[WorkflowEventRecord]:
    return [event for event in events if event.step_id == step_id]


def _posix_artifact_path(value: str | Path) -> str:
    return Path(str(value).replace("\\", "/")).as_posix()
