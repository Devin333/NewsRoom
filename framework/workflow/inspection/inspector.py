from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping

from framework.artifacts import (
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactStoreMetadataError,
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_sha256_checksum,
    verify_sha256_checksum,
)
from framework.artifacts.observability import (
    emit_artifact_checksum_missing,
    emit_artifact_metadata_corrupt,
)
from framework.shared.json import to_jsonable as to_json_safe
from framework.specs import StepStatus, WorkflowStatus
from framework.workflow.runtime.manifest import (
    REQUIRED_RUN_ARTIFACTS,
    RunManifestError,
    manifest_schema_version,
    manifest_step_artifact_key,
    validate_run_manifest,
)


DEFAULT_ARTIFACT_INDEX_KEYS = ("artifact_index", "source_artifacts")


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
class StepTimelineItem:
    step_id: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    attempts: int = 0
    retry_count: int = 0
    duration_ms: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "attempts": self.attempts,
            "retry_count": self.retry_count,
            "duration_ms": self.duration_ms,
            "events": to_json_safe(self.events),
        }


@dataclass(frozen=True)
class RootCauseResult:
    root_cause: str | None
    failed_step_id: str | None = None
    blocked_step_id: str | None = None
    event_type: str | None = None
    phase: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "failed_step_id": self.failed_step_id,
            "blocked_step_id": self.blocked_step_id,
            "event_type": self.event_type,
            "phase": self.phase,
            "message": self.message,
            "metadata": to_json_safe(self.metadata),
        }


@dataclass(frozen=True)
class ArtifactIntegrityReport:
    valid: bool
    missing_artifacts: list[str] = field(default_factory=list)
    checksum_failures: list[str] = field(default_factory=list)
    size_mismatches: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "missing_artifacts": list(self.missing_artifacts),
            "checksum_failures": list(self.checksum_failures),
            "size_mismatches": list(self.size_mismatches),
            "warnings": list(self.warnings),
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
    checks: dict[str, str] = field(default_factory=dict)

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
            "checks": dict(self.checks),
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
    integrity: dict[str, Any] = field(default_factory=dict)
    step_timeline: list[StepTimelineItem] = field(default_factory=list)
    routing_diagnostics: dict[str, Any] = field(default_factory=dict)

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
            "integrity": to_json_safe(self.integrity),
            "step_timeline": [item.to_dict() for item in self.step_timeline],
            "routing_diagnostics": to_json_safe(self.routing_diagnostics),
        }


@dataclass(frozen=True)
class WorkflowArtifactContentRecord:
    artifact_key: str
    relative_path: str
    content_type: str
    size_bytes: int | None
    absolute_path: str | None = None
    content: Any = None
    read_error: str | None = None
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def readable(self) -> bool:
        return self.read_error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "absolute_path": self.absolute_path,
            "content": to_json_safe(self.content),
            "read_error": self.read_error,
            "truncated": self.truncated,
            "metadata": to_json_safe(self.metadata),
            "readable": self.readable,
        }


@dataclass(frozen=True)
class _VerifiedArtifactSnapshot:
    """Immutable bytes and declarations captured by strict replay preflight."""

    artifact_key: str
    relative_path: str
    absolute_path: Path
    metadata: Mapping[str, Any]
    content_type: str
    size_bytes: int
    content_bytes: bytes


@dataclass(frozen=True)
class _VerifiedIndexEntryPlan:
    artifact_key: str
    relative_path: str
    checksum: str
    content_type: str | None
    size_bytes: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class WorkflowReplayContentBundle:
    run_id: str | None
    manifest: dict[str, Any]
    manifest_path: str
    events: list[dict[str, Any]]
    artifacts: list[WorkflowArtifactContentRecord]
    step_results: dict[str, Any] = field(default_factory=dict)
    integrity: dict[str, Any] = field(default_factory=dict)
    step_timeline: list[dict[str, Any]] = field(default_factory=list)
    routing_diagnostics: dict[str, Any] = field(default_factory=dict)
    events_path: str | None = None
    events_error: str | None = None

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    @property
    def event_count(self) -> int:
        return len(self.events)

    def artifact_by_key(self, artifact_key: str) -> WorkflowArtifactContentRecord | None:
        for artifact in self.artifacts:
            if artifact.artifact_key == artifact_key:
                return artifact
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "manifest": to_json_safe(self.manifest),
            "manifest_path": self.manifest_path,
            "event_count": self.event_count,
            "events": to_json_safe(self.events),
            "events_path": self.events_path,
            "events_error": self.events_error,
            "artifact_count": self.artifact_count,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "step_result_count": len(self.step_results),
            "step_results": to_json_safe(self.step_results),
            "integrity": to_json_safe(self.integrity),
            "step_timeline": to_json_safe(self.step_timeline),
            "routing_diagnostics": to_json_safe(self.routing_diagnostics),
        }


@dataclass(frozen=True)
class WorkflowRunDiagnostics:
    inspection: WorkflowRunInspection
    timeline: list[WorkflowTimelineItem] = field(default_factory=list)
    timeline_summary: WorkflowTimelineSummary | None = None
    artifact_inventory: WorkflowArtifactInventory | None = None
    data_buffer_diff_summary: WorkflowDataBufferDiffSummary | None = None
    health_report: WorkflowRunHealthReport | None = None
    severity: str = "unknown"
    status: str | None = None
    root_cause: str | None = None
    failed_step_id: str | None = None
    blocked_step_id: str | None = None
    missing_artifacts: list[str] = field(default_factory=list)
    checksum_failures: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)
    resume_available: bool = False
    suggested_actions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return bool(self.health_report and self.health_report.healthy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "inspection": self.inspection.to_dict(),
            "severity": self.severity,
            "status": self.status,
            "root_cause": self.root_cause,
            "failed_step_id": self.failed_step_id,
            "blocked_step_id": self.blocked_step_id,
            "missing_artifacts": list(self.missing_artifacts),
            "checksum_failures": list(self.checksum_failures),
            "policy_violations": list(self.policy_violations),
            "resume_available": self.resume_available,
            "suggested_actions": list(self.suggested_actions),
            "metadata": to_json_safe(self.metadata),
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


class WorkflowRootCauseAnalyzer:
    def analyze(
        self,
        manifest: dict[str, Any],
        events: list[dict[str, Any]],
        step_results: dict[str, Any],
    ) -> RootCauseResult:
        for step_id, result in step_results.items():
            if not isinstance(result, dict):
                continue
            if result.get("error_type") == "WorkflowBudgetExceeded" or _truthy_nested(
                result.get("error_details"),
                "budget_exceeded",
            ):
                return RootCauseResult(
                    root_cause="WorkflowBudgetExceeded",
                    failed_step_id=str(step_id),
                    event_type="workflow_budget_exceeded",
                    phase="workflow",
                    message=_optional_string(result.get("error_message")),
                )
        for violation in _manifest_policy_violations(manifest):
            policy = _optional_string(violation.get("policy") or violation.get("code"))
            if policy and policy.startswith("resource."):
                return RootCauseResult(
                    root_cause="WorkflowResourcePolicyViolation",
                    blocked_step_id=_optional_string(violation.get("step_id")),
                    event_type="policy_violation",
                    phase="policy",
                    message=_optional_string(violation.get("message")),
                    metadata={"policy": policy},
                )
        for step_id, result in step_results.items():
            if not isinstance(result, dict):
                continue
            status = _optional_string(result.get("status"))
            if status == StepStatus.BLOCKED.value:
                return RootCauseResult(
                    root_cause=result.get("error_type") or "StepBlocked",
                    blocked_step_id=str(step_id),
                    event_type="step_blocked",
                    phase="step",
                    message=_optional_string(result.get("error_message")),
                )
        for step_id, result in step_results.items():
            if not isinstance(result, dict):
                continue
            status = _optional_string(result.get("status"))
            if status in {StepStatus.FAILED.value, StepStatus.TIMEOUT.value}:
                return RootCauseResult(
                    root_cause=result.get("error_type") or "StepFailed",
                    failed_step_id=str(step_id),
                    event_type="step_failed",
                    phase="step",
                    message=_optional_string(result.get("error_message")),
                )
        for event in events:
            if not isinstance(event, dict):
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                payload = {}
            if payload.get("phase") == "routing" or event.get("event_type") in {
                "edge_rejected",
                "routing_error",
            }:
                return RootCauseResult(
                    root_cause="RoutingError",
                    failed_step_id=_optional_string(payload.get("step_id")),
                    event_type=_optional_string(event.get("event_type")),
                    phase="routing",
                    message=_optional_string(payload.get("message")),
                )
        missing = _manifest_missing_artifacts(manifest)
        if missing:
            return RootCauseResult(
                root_cause="MissingArtifact",
                phase="artifact",
                message="missing artifact: " + ", ".join(missing),
            )
        return RootCauseResult(root_cause=None)


class ArtifactIntegrityInspector:
    def inspect(
        self,
        run_dir: Path,
        manifest: dict[str, Any],
        *,
        strict: bool,
    ) -> ArtifactIntegrityReport:
        missing: list[str] = []
        checksum_failures: list[str] = []
        size_mismatches: list[str] = []
        warnings: list[str] = []
        for artifact_key, relative_path in _manifest_artifact_map(manifest).items():
            try:
                path = resolve_artifact_path(run_dir, relative_path)
            except WorkflowRunInspectionError:
                missing.append(artifact_key)
                continue
            if not path.exists():
                missing.append(artifact_key)
                continue
            if artifact_key == "manifest":
                continue
            metadata = _artifact_record_metadata(manifest, artifact_key)
            expected_size = _optional_int(metadata.get("size_bytes"))
            if expected_size is not None and path.stat().st_size != expected_size:
                size_mismatches.append(artifact_key)
            expected_checksum = _optional_string(metadata.get("checksum"))
            if expected_checksum and _sha256_file(path) != expected_checksum:
                checksum_failures.append(artifact_key)
        terminal_key = terminal_artifact_key(manifest)
        if terminal_key and terminal_key not in _manifest_artifact_map(manifest):
            missing.append(terminal_key)
        if checksum_failures and not strict:
            warnings.extend(
                f"manifest artifact checksum mismatch: {artifact_key}"
                for artifact_key in checksum_failures
            )
        return ArtifactIntegrityReport(
            valid=not missing and not size_mismatches and not (strict and checksum_failures),
            missing_artifacts=_dedupe_preserve_order(missing),
            checksum_failures=_dedupe_preserve_order(checksum_failures),
            size_mismatches=_dedupe_preserve_order(size_mismatches),
            warnings=_dedupe_preserve_order(warnings),
        )


class WorkflowTimelineBuilder:
    def build(self, events: list[dict[str, Any]]) -> list[StepTimelineItem]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            if not isinstance(event, dict):
                continue
            step_id = _event_step_id(event)
            if step_id is not None:
                grouped[step_id].append(event)
        items: list[StepTimelineItem] = []
        for step_id, step_events in sorted(grouped.items()):
            started_at = _first_event_time(step_events, {"step_started"})
            finished_at = _last_terminal_step_event_time(step_events)
            status = _last_step_status(step_events) or "unknown"
            attempts = sum(1 for event in step_events if event.get("event_type") == "step_started")
            retry_count = sum(
                1 for event in step_events if event.get("event_type") == "step_retry_scheduled"
            )
            items.append(
                StepTimelineItem(
                    step_id=step_id,
                    status=status,
                    started_at=started_at,
                    finished_at=finished_at,
                    attempts=attempts,
                    retry_count=retry_count,
                    duration_ms=_duration_ms(started_at, finished_at),
                    events=step_events,
                )
            )
        return items


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


@dataclass(frozen=True)
class WorkflowRunListItem:
    run_id: str
    run_dir: str
    manifest_path: str
    status: str | None = None
    workflow_id: str | None = None
    workflow_version: str | None = None
    profile: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    manifest_schema_version: str | None = None
    step_count: int | None = None
    event_count: int | None = None
    checkpoint_count: int | None = None
    artifact_count: int | None = None
    terminal_artifact_key: str | None = None
    valid_manifest: bool = True
    invalid_reason: str | None = None

    @property
    def completed(self) -> bool:
        return self.finished_at is not None

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "manifest_path": self.manifest_path,
            "status": self.status,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "profile": self.profile,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "manifest_schema_version": self.manifest_schema_version,
            "step_count": self.step_count,
            "event_count": self.event_count,
            "checkpoint_count": self.checkpoint_count,
            "artifact_count": self.artifact_count,
            "terminal_artifact_key": self.terminal_artifact_key,
            "valid_manifest": self.valid_manifest,
            "invalid_reason": self.invalid_reason,
            "completed": self.completed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "paused": self.paused,
        }


@dataclass(frozen=True)
class WorkflowRunCatalog:
    artifact_root: str
    runs: list[WorkflowRunListItem] = field(default_factory=list)
    invalid_run_dirs: list[str] = field(default_factory=list)
    total_run_count: int = 0
    returned_run_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    workflow_counts: dict[str, int] = field(default_factory=dict)
    profile_counts: dict[str, int] = field(default_factory=dict)
    latest_started_at: str | None = None
    oldest_started_at: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.runs

    def latest(self) -> WorkflowRunListItem | None:
        return self.runs[0] if self.runs else None

    def by_run_id(self, run_id: str) -> WorkflowRunListItem | None:
        for run in self.runs:
            if run.run_id == run_id:
                return run
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_root": self.artifact_root,
            "run_count": len(self.runs),
            "total_run_count": self.total_run_count,
            "returned_run_count": self.returned_run_count,
            "invalid_run_dirs": list(self.invalid_run_dirs),
            "status_counts": dict(self.status_counts),
            "workflow_counts": dict(self.workflow_counts),
            "profile_counts": dict(self.profile_counts),
            "latest_started_at": self.latest_started_at,
            "oldest_started_at": self.oldest_started_at,
            "filters": to_json_safe(self.filters),
            "runs": [run.to_dict() for run in self.runs],
        }


@dataclass(frozen=True)
class WorkflowRunCatalogHealth:
    artifact_root: str
    severity: str
    summary: str
    run_count: int
    valid_run_count: int
    invalid_run_count: int
    succeeded_count: int = 0
    failed_count: int = 0
    paused_count: int = 0
    running_count: int = 0
    latest_run_id: str | None = None
    latest_status: str | None = None
    latest_successful_run_id: str | None = None
    latest_failed_run_id: str | None = None
    latest_paused_run_id: str | None = None
    failed_run_ids: list[str] = field(default_factory=list)
    paused_run_ids: list[str] = field(default_factory=list)
    running_run_ids: list[str] = field(default_factory=list)
    invalid_run_dirs: list[str] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)
    workflow_counts: dict[str, int] = field(default_factory=dict)
    profile_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return self.severity == "ok"

    @property
    def has_open_runs(self) -> bool:
        return bool(self.paused_run_ids or self.running_run_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_root": self.artifact_root,
            "severity": self.severity,
            "healthy": self.healthy,
            "summary": self.summary,
            "run_count": self.run_count,
            "valid_run_count": self.valid_run_count,
            "invalid_run_count": self.invalid_run_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "paused_count": self.paused_count,
            "running_count": self.running_count,
            "latest_run_id": self.latest_run_id,
            "latest_status": self.latest_status,
            "latest_successful_run_id": self.latest_successful_run_id,
            "latest_failed_run_id": self.latest_failed_run_id,
            "latest_paused_run_id": self.latest_paused_run_id,
            "failed_run_ids": list(self.failed_run_ids),
            "paused_run_ids": list(self.paused_run_ids),
            "running_run_ids": list(self.running_run_ids),
            "invalid_run_dirs": list(self.invalid_run_dirs),
            "status_counts": dict(self.status_counts),
            "workflow_counts": dict(self.workflow_counts),
            "profile_counts": dict(self.profile_counts),
            "warnings": list(self.warnings),
            "suggested_actions": list(self.suggested_actions),
            "has_open_runs": self.has_open_runs,
        }


@dataclass(frozen=True)
class WorkflowRunComparison:
    base_run_id: str | None
    target_run_id: str | None
    base_status: str | None
    target_status: str | None
    base_workflow_version: str | None
    target_workflow_version: str | None
    same_workflow: bool
    status_changed: bool
    workflow_version_changed: bool
    step_count_delta: int
    event_count_delta: int
    artifact_count_delta: int
    duration_ms_delta: float | None = None
    added_steps: list[str] = field(default_factory=list)
    removed_steps: list[str] = field(default_factory=list)
    changed_step_statuses: dict[str, dict[str, str | None]] = field(default_factory=dict)
    added_artifacts: list[str] = field(default_factory=list)
    removed_artifacts: list[str] = field(default_factory=list)
    added_output_keys: dict[str, list[str]] = field(default_factory=dict)
    removed_output_keys: dict[str, list[str]] = field(default_factory=dict)
    health_severity_changed: bool = False
    base_health_severity: str | None = None
    target_health_severity: str | None = None
    path_diff: dict[str, Any] = field(default_factory=dict)
    output_diff: dict[str, Any] = field(default_factory=dict)
    metric_diff: dict[str, Any] = field(default_factory=dict)
    artifact_diff: dict[str, Any] = field(default_factory=dict)

    @property
    def has_behavioral_change(self) -> bool:
        return bool(
            self.status_changed
            or self.workflow_version_changed
            or self.added_steps
            or self.removed_steps
            or self.changed_step_statuses
            or self.added_output_keys
            or self.removed_output_keys
            or self.health_severity_changed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_run_id": self.base_run_id,
            "target_run_id": self.target_run_id,
            "base_status": self.base_status,
            "target_status": self.target_status,
            "base_workflow_version": self.base_workflow_version,
            "target_workflow_version": self.target_workflow_version,
            "same_workflow": self.same_workflow,
            "status_changed": self.status_changed,
            "workflow_version_changed": self.workflow_version_changed,
            "step_count_delta": self.step_count_delta,
            "event_count_delta": self.event_count_delta,
            "artifact_count_delta": self.artifact_count_delta,
            "duration_ms_delta": self.duration_ms_delta,
            "added_steps": list(self.added_steps),
            "removed_steps": list(self.removed_steps),
            "changed_step_statuses": to_json_safe(self.changed_step_statuses),
            "added_artifacts": list(self.added_artifacts),
            "removed_artifacts": list(self.removed_artifacts),
            "added_output_keys": to_json_safe(self.added_output_keys),
            "removed_output_keys": to_json_safe(self.removed_output_keys),
            "health_severity_changed": self.health_severity_changed,
            "base_health_severity": self.base_health_severity,
            "target_health_severity": self.target_health_severity,
            "path_diff": to_json_safe(self.path_diff),
            "output_diff": to_json_safe(self.output_diff),
            "metric_diff": to_json_safe(self.metric_diff),
            "artifact_diff": to_json_safe(self.artifact_diff),
            "has_behavioral_change": self.has_behavioral_change,
        }


class WorkflowRunInspector:
    def __init__(self, artifact_root: str | Path | None = None) -> None:
        self._artifact_root = Path(artifact_root) if artifact_root is not None else None

    def list_runs(
        self,
        *,
        limit: int | None = 50,
        offset: int = 0,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        status: str | WorkflowStatus | None = None,
        profile: str | None = None,
        include_invalid: bool = False,
    ) -> WorkflowRunCatalog:
        artifact_root = self._require_artifact_root()
        if limit is not None and limit < 0:
            raise WorkflowRunInspectionError("limit must be non-negative")
        if offset < 0:
            raise WorkflowRunInspectionError("offset must be non-negative")
        requested_status = _status_value(status)
        filters = {
            "workflow_id": workflow_id,
            "workflow_version": workflow_version,
            "status": requested_status,
            "profile": profile,
            "include_invalid": include_invalid,
            "limit": limit,
            "offset": offset,
        }
        all_items: list[WorkflowRunListItem] = []
        invalid_run_dirs: list[str] = []
        if artifact_root.exists():
            for candidate in sorted(artifact_root.iterdir()):
                try:
                    run_dir = resolve_run_dir(artifact_root, candidate.name)
                except WorkflowRunInspectionError:
                    invalid_run_dirs.append(str(candidate))
                    continue
                if not run_dir.is_dir():
                    continue
                item = _run_list_item_from_dir(run_dir)
                if item is None:
                    continue
                if not item.valid_manifest:
                    invalid_run_dirs.append(item.run_dir)
                    if not include_invalid:
                        continue
                all_items.append(item)
        filtered_items = [
            item
            for item in all_items
            if _run_list_item_matches(
                item,
                workflow_id=workflow_id,
                workflow_version=workflow_version,
                status=requested_status,
                profile=profile,
            )
        ]
        sorted_items = sorted(filtered_items, key=_run_list_sort_key, reverse=True)
        if offset:
            sorted_items = sorted_items[offset:]
        if limit is not None:
            sorted_items = sorted_items[:limit]
        return WorkflowRunCatalog(
            artifact_root=str(artifact_root),
            runs=sorted_items,
            invalid_run_dirs=sorted(invalid_run_dirs),
            total_run_count=len(filtered_items),
            returned_run_count=len(sorted_items),
            status_counts=_catalog_counts(filtered_items, "status"),
            workflow_counts=_catalog_counts(filtered_items, "workflow_id"),
            profile_counts=_catalog_counts(filtered_items, "profile"),
            latest_started_at=_latest_started_at(filtered_items),
            oldest_started_at=_oldest_started_at(filtered_items),
            filters={key: value for key, value in filters.items() if value is not None},
        )

    def latest_run(
        self,
        *,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        status: str | WorkflowStatus | None = None,
        profile: str | None = None,
        include_invalid: bool = False,
    ) -> WorkflowRunListItem | None:
        catalog = self.list_runs(
            limit=1,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            status=status,
            profile=profile,
            include_invalid=include_invalid,
        )
        return catalog.latest()

    def catalog_health(
        self,
        *,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        profile: str | None = None,
        include_invalid: bool = True,
    ) -> WorkflowRunCatalogHealth:
        catalog = self.list_runs(
            limit=None,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            profile=profile,
            include_invalid=include_invalid,
        )
        return build_run_catalog_health(catalog)

    def compare_runs(
        self,
        base_run_id: str,
        target_run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunComparison:
        base = self.inspect_run(
            base_run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )
        target = self.inspect_run(
            target_run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )
        return compare_workflow_run_inspections(base, target)

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
            strict_checksums=strict,
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
            strict_checksums=strict,
        )
        if strict and not integrity.valid:
            raise WorkflowRunInspectionError(
                "workflow run replay bundle is invalid: " + "; ".join(integrity.errors)
            )
        terminal_key = terminal_artifact_key(manifest)
        events = self.read_events(actual_run_dir, manifest=manifest, missing_ok=True)
        event_payloads = [event.to_dict() for event in events]
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
            events=events,
            artifacts=self.list_artifacts(
                actual_run_dir,
                manifest=manifest,
                verify_checksums=verify_checksums,
            ),
            integrity=integrity.to_dict(),
            step_timeline=WorkflowTimelineBuilder().build(event_payloads),
            routing_diagnostics=_routing_diagnostics_from_events(event_payloads),
        )

    def build_replay_content_bundle(
        self,
        run_id: str | None = None,
        *,
        run_dir: str | Path | None = None,
        redact: bool = True,
        expand_artifact_indexes: bool = True,
        artifact_index_keys: Iterable[str] | None = None,
        expand_source_artifacts: bool = True,
        max_artifact_bytes: int | None = None,
        strict_artifact_integrity: bool = False,
    ) -> WorkflowReplayContentBundle:
        actual_run_dir = self._resolve_run_dir(run_id=run_id, run_dir=run_dir)
        if strict_artifact_integrity:
            try:
                return self._build_strict_replay_content_bundle(
                    actual_run_dir,
                    redact=redact,
                    expand_artifact_indexes=expand_artifact_indexes,
                    artifact_index_keys=artifact_index_keys,
                    expand_source_artifacts=expand_source_artifacts,
                    max_artifact_bytes=max_artifact_bytes,
                )
            except ArtifactStoreMetadataError as exc:
                _emit_strict_workflow_metadata_failure(exc)
                raise
        manifest = self.load_manifest(actual_run_dir)
        integrity = self.validate_run_dir(actual_run_dir, manifest=manifest)
        artifact_paths = _manifest_artifact_map(manifest)
        events: list[dict[str, Any]] = []
        events_path = None
        events_error = None
        if "events" in artifact_paths:
            try:
                event_records = self.read_events(actual_run_dir, manifest=manifest)
                events = [
                    _redact_if_needed(event.to_dict(), redact=redact)
                    for event in event_records
                ]
                events_path_obj = self.artifact_path(
                    actual_run_dir,
                    "events",
                    manifest=manifest,
                    missing_ok=True,
                )
                events_path = str(events_path_obj) if events_path_obj is not None else None
            except WorkflowRunInspectionError as exc:
                events_error = str(exc)
        artifacts = [
            read_workflow_artifact_content(
                actual_run_dir,
                artifact_key,
                relative_path,
                redact=redact,
                max_bytes=max_artifact_bytes,
            )
            for artifact_key, relative_path in sorted(artifact_paths.items())
        ]
        if expand_artifact_indexes and expand_source_artifacts:
            artifacts.extend(
                read_artifact_index_content_records(
                    actual_run_dir,
                    artifact_paths,
                    index_keys=artifact_index_keys,
                    redact=redact,
                    max_bytes=max_artifact_bytes,
                )
            )
        return WorkflowReplayContentBundle(
            run_id=_optional_string(manifest.get("run_id")) or actual_run_dir.name,
            manifest=_redact_if_needed(manifest, redact=redact),
            manifest_path=str(resolve_artifact_path(actual_run_dir, "manifest.json")),
            events=events,
            events_path=events_path,
            events_error=events_error,
            artifacts=artifacts,
            step_results=self.read_json_artifact(
                actual_run_dir,
                "step_results",
                manifest=manifest,
                default={},
            ),
            integrity=integrity.to_dict(),
            step_timeline=[
                item.to_dict() for item in WorkflowTimelineBuilder().build(events)
            ],
            routing_diagnostics=_routing_diagnostics_from_events(events),
        )

    def _build_strict_replay_content_bundle(
        self,
        run_dir: Path,
        *,
        redact: bool,
        expand_artifact_indexes: bool,
        artifact_index_keys: Iterable[str] | None,
        expand_source_artifacts: bool,
        max_artifact_bytes: int | None,
    ) -> WorkflowReplayContentBundle:
        manifest_snapshot, manifest = _capture_and_validate_run_manifest(run_dir)
        artifact_paths = _manifest_artifact_map(manifest)
        snapshots: dict[str, _VerifiedArtifactSnapshot] = {
            "manifest": manifest_snapshot,
        }
        for artifact_key in sorted(artifact_paths):
            if artifact_key == "manifest":
                continue
            snapshots[artifact_key] = _capture_verified_artifact_snapshot(
                run_dir,
                manifest,
                artifact_key,
            )

        indexed_snapshots: list[_VerifiedArtifactSnapshot] = []
        if expand_artifact_indexes and expand_source_artifacts:
            for index_artifact_key in _selected_artifact_index_keys(
                artifact_paths,
                index_keys=artifact_index_keys,
            ):
                indexed_snapshots.extend(
                    _capture_verified_artifact_index_snapshots(
                        run_dir,
                        snapshots,
                        artifact_paths,
                        run_id=_required_index_run_id(manifest),
                        index_artifact_key=index_artifact_key,
                    )
                )

        # From this point onward strict replay projects only captured bytes. Paths are
        # retained for response metadata and are never reopened.
        event_records = _event_records_from_snapshot(snapshots.get("events"))
        events = [
            _redact_if_needed(event.to_dict(), redact=redact)
            for event in event_records
        ]
        artifacts = [
            _content_record_from_snapshot(
                snapshots[artifact_key],
                redact=redact,
                max_bytes=max_artifact_bytes,
            )
            for artifact_key in sorted(artifact_paths)
        ]
        artifacts.extend(
            _indexed_content_record_from_snapshot(
                snapshot,
                redact=redact,
                max_bytes=max_artifact_bytes,
            )
            for snapshot in indexed_snapshots
        )
        step_results_payload = _json_payload_from_snapshot(
            snapshots.get("step_results"),
            default={},
        )
        step_results = (
            step_results_payload if isinstance(step_results_payload, dict) else {}
        )
        step_results = _redact_if_needed(step_results, redact=redact)
        return WorkflowReplayContentBundle(
            run_id=_optional_string(manifest.get("run_id")) or run_dir.name,
            manifest=_redact_if_needed(manifest, redact=redact),
            manifest_path=str(manifest_snapshot.absolute_path),
            events=events,
            events_path=(
                str(snapshots["events"].absolute_path)
                if "events" in snapshots
                else None
            ),
            events_error=None,
            artifacts=artifacts,
            step_results=step_results,
            integrity=_strict_snapshot_integrity_report(
                artifact_paths,
                snapshots,
                indexed_snapshot_count=len(indexed_snapshots),
            ),
            step_timeline=[
                item.to_dict() for item in WorkflowTimelineBuilder().build(events)
            ],
            routing_diagnostics=_routing_diagnostics_from_events(events),
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
        summary_payload = _diagnostics_summary_payload(inspection)
        return WorkflowRunDiagnostics(
            inspection=inspection,
            timeline=list(inspection.timeline),
            timeline_summary=inspection.timeline_summary,
            artifact_inventory=inspection.artifact_inventory,
            data_buffer_diff_summary=inspection.data_buffer_diff_summary,
            health_report=inspection.health_report,
            **summary_payload,
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
        path = resolve_artifact_path(run_dir, "manifest.json")
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
        strict_checksums: bool = False,
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
        artifact_integrity = ArtifactIntegrityInspector().inspect(
            actual_run_dir,
            manifest_payload,
            strict=False,
        )
        warnings.extend(artifact_integrity.warnings)
        if artifact_integrity.size_mismatches:
            warnings.extend(
                f"manifest artifact size mismatch: {artifact_key}"
                for artifact_key in artifact_integrity.size_mismatches
            )
        if strict_checksums and artifact_integrity.checksum_failures:
            errors.extend(
                f"manifest artifact checksum mismatch: {artifact_key}"
                for artifact_key in artifact_integrity.checksum_failures
            )
        return WorkflowManifestIntegrityReport(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            missing_artifact_keys=missing_artifact_keys,
            missing_artifact_files=_dedupe_preserve_order(
                missing_artifact_files + artifact_integrity.missing_artifacts
            ),
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
            path = resolve_artifact_path(actual_run_dir, relative_path)
            exists = path.exists()
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
            candidate = Path(run_dir)
            if self._artifact_root is None:
                return candidate.resolve(strict=False)
            artifact_root = self._require_artifact_root()
            if not candidate.is_absolute() and len(candidate.parts) == 1:
                return resolve_run_dir(artifact_root, str(candidate))
            expected = resolve_run_dir(artifact_root, candidate.name)
            actual = candidate.resolve(strict=False)
            if actual != expected:
                raise WorkflowRunInspectionError(
                    f"run directory must stay within the artifact root: {run_dir}"
                )
            return expected
        if run_id is None:
            raise WorkflowRunInspectionError("run_id or run_dir is required")
        artifact_root = self._require_artifact_root()
        return resolve_run_dir(artifact_root, run_id)

    def _require_artifact_root(self) -> Path:
        if self._artifact_root is None:
            raise WorkflowRunInspectionError("artifact_root is required")
        return self._artifact_root.resolve(strict=False)


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


def build_workflow_replay_content_bundle(
    run_dir: str | Path,
    *,
    redact: bool = True,
    expand_artifact_indexes: bool = True,
    artifact_index_keys: Iterable[str] | None = None,
    expand_source_artifacts: bool = True,
    max_artifact_bytes: int | None = None,
) -> WorkflowReplayContentBundle:
    return WorkflowRunInspector().build_replay_content_bundle(
        run_dir=run_dir,
        redact=redact,
        expand_artifact_indexes=expand_artifact_indexes,
        artifact_index_keys=artifact_index_keys,
        expand_source_artifacts=expand_source_artifacts,
        max_artifact_bytes=max_artifact_bytes,
    )


def list_workflow_runs(
    artifact_root: str | Path,
    *,
    limit: int | None = 50,
    offset: int = 0,
    workflow_id: str | None = None,
    workflow_version: str | None = None,
    status: str | WorkflowStatus | None = None,
    profile: str | None = None,
    include_invalid: bool = False,
) -> WorkflowRunCatalog:
    return WorkflowRunInspector(artifact_root).list_runs(
        limit=limit,
        offset=offset,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        status=status,
        profile=profile,
        include_invalid=include_invalid,
    )


def latest_workflow_run(
    artifact_root: str | Path,
    *,
    workflow_id: str | None = None,
    workflow_version: str | None = None,
    status: str | WorkflowStatus | None = None,
    profile: str | None = None,
    include_invalid: bool = False,
) -> WorkflowRunListItem | None:
    return WorkflowRunInspector(artifact_root).latest_run(
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        status=status,
        profile=profile,
        include_invalid=include_invalid,
    )


def workflow_run_catalog_health(
    artifact_root: str | Path,
    *,
    workflow_id: str | None = None,
    workflow_version: str | None = None,
    profile: str | None = None,
    include_invalid: bool = True,
) -> WorkflowRunCatalogHealth:
    return WorkflowRunInspector(artifact_root).catalog_health(
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        profile=profile,
        include_invalid=include_invalid,
    )


def compare_workflow_runs(
    artifact_root: str | Path,
    base_run_id: str,
    target_run_id: str,
    *,
    verify_checksums: bool = False,
    strict: bool = False,
) -> WorkflowRunComparison:
    return WorkflowRunInspector(artifact_root).compare_runs(
        base_run_id,
        target_run_id,
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
    try:
        return resolve_artifact_descendant(
            run_dir,
            relative_path,
            field="artifact_path",
        )
    except ArtifactPathError as exc:
        raise WorkflowRunInspectionError(
            f"artifact path must stay within the run directory: {relative_path}"
        ) from exc


def resolve_run_dir(artifact_root: str | Path, run_id: str) -> Path:
    try:
        validated_run_id = validate_artifact_path_segment(run_id, field="run_id")
        return resolve_artifact_descendant(
            artifact_root,
            validated_run_id,
            field="run_id",
        )
    except ArtifactPathError as exc:
        raise WorkflowRunInspectionError(
            f"run_id must stay within the artifact root: {run_id}"
        ) from exc


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


def read_workflow_artifact_content(
    run_dir: str | Path,
    artifact_key: str,
    relative_path: str,
    *,
    redact: bool = True,
    max_bytes: int | None = None,
) -> WorkflowArtifactContentRecord:
    content_type = content_type_for_path(relative_path)
    try:
        path = _artifact_content_path(Path(run_dir), relative_path)
        content, truncated = _read_artifact_content(
            path,
            content_type,
            max_bytes=max_bytes,
        )
        return WorkflowArtifactContentRecord(
            artifact_key=artifact_key,
            relative_path=_posix_artifact_path(relative_path),
            absolute_path=str(path),
            content_type=content_type,
            size_bytes=path.stat().st_size,
            content=_redact_if_needed(content, redact=redact),
            truncated=truncated,
        )
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
        WorkflowRunInspectionError,
    ) as exc:
        return WorkflowArtifactContentRecord(
            artifact_key=artifact_key,
            relative_path=_posix_artifact_path(relative_path),
            absolute_path=None,
            content_type=content_type,
            size_bytes=None,
            read_error=str(exc),
        )


def read_strict_workflow_artifact_content(
    run_dir: str | Path,
    manifest: dict[str, Any],
    artifact_key: str,
    *,
    redact: bool = True,
    max_bytes: int | None = None,
) -> WorkflowArtifactContentRecord:
    """Read one manifest-listed artifact only after expected-checksum verification."""

    try:
        # Preserve the public signature while making the persisted manifest bytes the
        # single validation owner. This closes a load/validate/use gap in callers that
        # previously supplied an earlier manifest object.
        del manifest
        manifest_snapshot, persisted_manifest = _capture_and_validate_run_manifest(
            Path(run_dir)
        )
        if artifact_key == "manifest":
            snapshot = manifest_snapshot
        else:
            snapshot = _capture_verified_artifact_snapshot(
                Path(run_dir), persisted_manifest, artifact_key
            )
    except ArtifactStoreMetadataError as exc:
        _emit_strict_workflow_metadata_failure(exc)
        raise
    return _content_record_from_snapshot(
        snapshot,
        redact=redact,
        max_bytes=max_bytes,
    )


def _content_record_from_snapshot(
    snapshot: _VerifiedArtifactSnapshot,
    *,
    redact: bool,
    max_bytes: int | None,
) -> WorkflowArtifactContentRecord:
    if max_bytes is not None and max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if redact and snapshot.content_type in {
        "application/json",
        "application/x-ndjson",
    }:
        content, truncated = _read_redacted_structured_snapshot_content(
            snapshot,
            max_bytes=max_bytes,
        )
    else:
        content, truncated = _read_artifact_content_bytes(
            snapshot.content_bytes,
            snapshot.content_type,
            max_bytes=max_bytes,
        )
        content = _redact_if_needed(content, redact=redact)
    return WorkflowArtifactContentRecord(
        artifact_key=snapshot.artifact_key,
        relative_path=snapshot.relative_path,
        absolute_path=str(snapshot.absolute_path),
        content_type=snapshot.content_type,
        size_bytes=snapshot.size_bytes,
        content=content,
        truncated=truncated,
        metadata=_redact_if_needed(dict(snapshot.metadata), redact=redact),
    )


def _read_redacted_structured_snapshot_content(
    snapshot: _VerifiedArtifactSnapshot,
    *,
    max_bytes: int | None,
) -> tuple[Any, bool]:
    if snapshot.content_type == "application/json":
        decoded = json.loads(snapshot.content_bytes.decode("utf-8"))
    else:
        decoded = _read_jsonl_bytes_values(snapshot.content_bytes)
    redacted = redact_sensitive_values(decoded)
    if max_bytes is None or len(snapshot.content_bytes) <= max_bytes:
        return redacted, False
    serialized = json.dumps(
        redacted,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    preview = serialized[:max_bytes]
    return {
        "encoding": "utf-8",
        "text_preview": preview.decode("utf-8", errors="replace"),
        "preview_size_bytes": len(preview),
        "redacted": True,
    }, True


def read_artifact_index_content_records(
    run_dir: str | Path,
    artifact_paths: dict[str, str],
    *,
    index_keys: Iterable[str] | None = None,
    redact: bool = True,
    max_bytes: int | None = None,
) -> list[WorkflowArtifactContentRecord]:
    index_artifact_key, index_path_value = _first_artifact_index_path(
        artifact_paths,
        index_keys=index_keys,
    )
    if index_artifact_key is None or not isinstance(index_path_value, str):
        return []
    try:
        index_path = _artifact_content_path(Path(run_dir), index_path_value)
        index_payload = _read_json_file(index_path)
    except (OSError, ValueError, WorkflowRunInspectionError):
        return []
    if not isinstance(index_payload, dict):
        return []
    entries = index_payload.get("entries")
    if not isinstance(entries, list):
        return []
    records: list[WorkflowArtifactContentRecord] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        relative_path = entry.get("path")
        if not isinstance(relative_path, str):
            continue
        record = read_workflow_artifact_content(
            run_dir,
            _artifact_index_entry_key(index_artifact_key, entry),
            relative_path,
            redact=redact,
            max_bytes=max_bytes,
        )
        records.append(
            replace(
                record,
                metadata={
                    **dict(record.metadata),
                    "artifact_index": True,
                    "index_artifact_key": index_artifact_key,
                    "source_id": entry.get("source_id"),
                    "entity_id": entry.get("entity_id"),
                    "artifact_type": entry.get("artifact_type"),
                    "object_id": entry.get("object_id"),
                },
            )
        )
    return records


def read_source_artifact_content_records(
    run_dir: str | Path,
    artifact_paths: dict[str, str],
    *,
    redact: bool = True,
    max_bytes: int | None = None,
) -> list[WorkflowArtifactContentRecord]:
    return read_artifact_index_content_records(
        run_dir,
        artifact_paths,
        index_keys=("source_artifacts",),
        redact=redact,
        max_bytes=max_bytes,
    )


def redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if _looks_sensitive_buffer_key(str(key)):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = redact_sensitive_values(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_values(item) for item in value)
    return value


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
    policy_violations = _inspection_policy_violations(inspection)
    budget_summary = _inspection_budget_summary(inspection)
    resume_metadata = _resume_metadata_for_inspection(inspection)

    if not inspection.integrity.valid:
        issues.extend(inspection.integrity.errors)
        actions.append("inspect manifest.json and restore missing run artifacts")
        actions.append("rebuild missing artifacts or rerun_from_step from the latest checkpoint")
    if inspection.integrity.missing_artifact_keys:
        issues.append(
            "missing required manifest artifact keys: "
            + ", ".join(inspection.integrity.missing_artifact_keys)
        )
    if artifact_inventory.missing_artifact_keys:
        issues.append(
            "missing artifact files: " + ", ".join(artifact_inventory.missing_artifact_keys)
        )
        actions.append("rebuild missing artifacts or rerun_from_step before replay")
    if failed_steps:
        issues.append("failed steps: " + ", ".join(failed_steps))
        actions.append("open step_results.json and events.jsonl for failed step details")
        actions.append("rerun_from_step from the failed step after fixing the root cause")
    if inspection.status in {
        WorkflowStatus.FAILED.value,
        WorkflowStatus.CANCELLED.value,
        WorkflowStatus.BUDGET_EXCEEDED.value,
    }:
        issues.append(f"workflow ended with status {inspection.status}")
    if inspection.status == WorkflowStatus.BLOCKED.value:
        warnings.append("workflow is blocked by policy or governance state")
        actions.append("inspect error.json and step policy output before retrying")
    for violation in policy_violations:
        message = _policy_violation_message(violation)
        if message:
            warnings.append(message)
        actions.extend(_policy_violation_actions(violation))
    if budget_summary.get("exceeded") is True:
        exceeded_reason = _optional_string(budget_summary.get("exceeded_reason"))
        if exceeded_reason:
            issues.append(f"workflow budget exceeded: {exceeded_reason}")
        else:
            issues.append("workflow budget exceeded")
        actions.append(
            "reduce source_limit, max_items, prompt size, or increase workflow budget before retrying"
        )
    if inspection.paused:
        warnings.append("workflow is paused and requires resume input")
        actions.append("resume from checkpoint after the required external input is available")
        if inspection.status == WorkflowStatus.WAITING_FOR_HUMAN.value:
            actions.append("submit human review decision before resuming the run")
    if resume_metadata.get("available") is True:
        actions.append("resume_from_checkpoint is available for this run")
    elif resume_metadata.get("rerun_from_step_available") is True:
        actions.append("rerun_from_step is available from the latest checkpoint")
    elif resume_metadata.get("mark_blocked_resolved_available") is True:
        actions.append("mark_blocked_resolved before rerun_from_step or resume_with_patch")
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
        checks=_health_checks(
            inspection,
            artifact_inventory=artifact_inventory,
            resume_metadata=resume_metadata,
        ),
    )


def _inspection_policy_violations(
    inspection: WorkflowRunInspection,
) -> list[dict[str, Any]]:
    violations = inspection.manifest.get("policy_violations")
    if not isinstance(violations, list):
        return []
    return [violation for violation in violations if isinstance(violation, dict)]


def _inspection_budget_summary(inspection: WorkflowRunInspection) -> dict[str, Any]:
    metrics = inspection.metrics if isinstance(inspection.metrics, dict) else {}
    budget = metrics.get("budget")
    if isinstance(budget, dict):
        return budget
    manifest_metrics = inspection.manifest.get("metrics")
    if isinstance(manifest_metrics, dict):
        budget = manifest_metrics.get("budget")
        if isinstance(budget, dict):
            return budget
    return {}


def _diagnostics_summary_payload(
    inspection: WorkflowRunInspection,
) -> dict[str, Any]:
    event_payloads = [event.to_dict() for event in _inspection_events(inspection)]
    step_results = _step_results_from_manifest_or_summary(inspection)
    root_cause = WorkflowRootCauseAnalyzer().analyze(
        inspection.manifest,
        event_payloads,
        step_results,
    )
    health = inspection.health_report
    artifact_integrity = ArtifactIntegrityInspector().inspect(
        Path(inspection.run_dir),
        inspection.manifest,
        strict=False,
    )
    policy_violations = _policy_violation_strings(_inspection_policy_violations(inspection))
    resume_metadata = _resume_metadata_for_inspection(inspection)
    selected_edges = [
        item.edge_id
        for item in inspection.timeline
        if item.event_type == "edge_traversed" and item.edge_id is not None
    ]
    routing_evaluations = [
        item.payload_excerpt
        for item in inspection.timeline
        if item.event_type == "edge_evaluated"
    ]
    step_timeline = WorkflowTimelineBuilder().build(event_payloads)
    suggested_actions = list(health.suggested_actions if health else [])
    if resume_metadata.get("available") is True:
        suggested_actions.append("resume_from_checkpoint is available")
    return {
        "severity": health.severity if health else "unknown",
        "status": inspection.status,
        "root_cause": root_cause.root_cause,
        "failed_step_id": root_cause.failed_step_id or _first_failed_step_id(inspection),
        "blocked_step_id": root_cause.blocked_step_id or _first_blocked_step_id(inspection),
        "missing_artifacts": _dedupe_preserve_order(
            list(inspection.integrity.missing_artifact_files)
            + list(artifact_integrity.missing_artifacts)
        ),
        "checksum_failures": artifact_integrity.checksum_failures,
        "policy_violations": policy_violations,
        "resume_available": bool(resume_metadata.get("available")),
        "suggested_actions": _dedupe_preserve_order(suggested_actions),
        "metadata": {
            "root_cause": root_cause.to_dict(),
            "resume": resume_metadata,
            "routing": {
                "selected_edge_ids": selected_edges,
                "selected_edge_id": selected_edges[0] if selected_edges else None,
                "evaluations": routing_evaluations,
            },
            "step_timeline": [item.to_dict() for item in step_timeline],
            "artifact_integrity": artifact_integrity.to_dict(),
        },
    }


def _inspection_events(inspection: WorkflowRunInspection) -> list[WorkflowEventRecord]:
    events_path = resolve_artifact_path(inspection.run_dir, "events.jsonl")
    if not events_path.exists():
        return []
    try:
        return list(_read_event_jsonl(events_path))
    except WorkflowRunInspectionError:
        return []


def _step_results_from_manifest_or_summary(
    inspection: WorkflowRunInspection,
) -> dict[str, Any]:
    step_results_path = resolve_artifact_path(
        inspection.run_dir,
        "step_results.json",
    )
    if step_results_path.exists():
        try:
            payload = _read_json_file(step_results_path)
            if isinstance(payload, dict):
                return payload
        except WorkflowRunInspectionError:
            pass
    return {
        step.step_id: {
            "status": step.status,
            "error_type": step.error_type,
            "error_message": step.error_message,
        }
        for step in inspection.steps
    }


def _policy_violation_strings(violations: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for violation in violations:
        policy = _optional_string(violation.get("policy") or violation.get("code"))
        step_id = _optional_string(violation.get("step_id"))
        if policy and step_id:
            values.append(f"{policy}:{step_id}")
        elif policy:
            values.append(policy)
    return _dedupe_preserve_order(values)


def _resume_metadata_for_inspection(inspection: WorkflowRunInspection) -> dict[str, Any]:
    status = inspection.status
    latest_checkpoint_id = _optional_string(
        inspection.manifest.get("latest_checkpoint_id")
        or inspection.manifest.get("resumed_from_checkpoint_id")
    )
    checkpoint_count = int(inspection.manifest.get("checkpoint_count") or 0)
    has_checkpoint = bool(latest_checkpoint_id or checkpoint_count > 0)
    supported_modes: list[str] = []
    available = False
    if status in {WorkflowStatus.PAUSED.value, WorkflowStatus.WAITING_FOR_HUMAN.value}:
        available = has_checkpoint
        if available:
            supported_modes.extend(["resume_exact", "resume_with_patch"])
            if status == WorkflowStatus.WAITING_FOR_HUMAN.value:
                supported_modes.append("resume_after_human_review")
    rerun_from_step_available = bool(
        has_checkpoint
        and status
        in {
            WorkflowStatus.FAILED.value,
            WorkflowStatus.BLOCKED.value,
            WorkflowStatus.CANCELLED.value,
            WorkflowStatus.SUCCEEDED.value,
        }
    )
    mark_blocked_resolved_available = status == WorkflowStatus.BLOCKED.value
    return {
        "available": available,
        "latest_checkpoint_id": latest_checkpoint_id,
        "supported_modes": supported_modes,
        "rerun_from_step_available": rerun_from_step_available,
        "mark_blocked_resolved_available": mark_blocked_resolved_available,
        "checkpoint_count": checkpoint_count,
    }


def _health_checks(
    inspection: WorkflowRunInspection,
    *,
    artifact_inventory: WorkflowArtifactInventory,
    resume_metadata: dict[str, Any],
) -> dict[str, str]:
    manifest_health = "passed" if inspection.integrity.valid else "failed"
    artifact_health = "passed"
    if artifact_inventory.missing_count:
        artifact_health = "failed"
    elif inspection.integrity.warnings:
        artifact_health = "warning"
    event_health = "passed"
    if inspection.event_summary is None or inspection.event_summary.event_count == 0:
        event_health = "warning"
    runtime_health = "passed"
    if inspection.status in {
        WorkflowStatus.FAILED.value,
        WorkflowStatus.BLOCKED.value,
        WorkflowStatus.BUDGET_EXCEEDED.value,
        WorkflowStatus.CANCELLED.value,
    }:
        runtime_health = "failed"
    elif inspection.paused:
        runtime_health = "warning"
    checkpoint_health = "passed"
    if inspection.paused and not resume_metadata.get("latest_checkpoint_id"):
        checkpoint_health = "failed"
    resume_health = "passed"
    if inspection.paused and not resume_metadata.get("available"):
        resume_health = "failed"
    elif resume_metadata.get("available") or resume_metadata.get("rerun_from_step_available"):
        resume_health = "passed"
    return {
        "artifact_health": artifact_health,
        "checkpoint_health": checkpoint_health,
        "event_health": event_health,
        "manifest_health": manifest_health,
        "runtime_health": runtime_health,
        "resume_health": resume_health,
    }


def _policy_violation_message(violation: dict[str, Any]) -> str | None:
    policy = _optional_string(violation.get("policy") or violation.get("code"))
    step_id = _optional_string(violation.get("step_id"))
    message = _optional_string(violation.get("message"))
    if policy and step_id and message:
        return f"policy violation {policy} on step {step_id}: {message}"
    if policy and step_id:
        return f"policy violation {policy} on step {step_id}"
    if policy:
        return f"policy violation {policy}"
    return message


def _policy_violation_actions(violation: dict[str, Any]) -> list[str]:
    policy = _optional_string(violation.get("policy") or violation.get("code")) or ""
    error_type = _optional_string(violation.get("error_type")) or ""
    if policy == "resource.max_items":
        return ["reduce source_limit/max_items input size or increase step resource_policy.max_items"]
    if policy == "resource.max_input_tokens":
        return [
            "reduce prompt/input text size or increase step resource_policy.max_input_tokens"
        ]
    if policy == "resource.max_artifact_bytes":
        return [
            "reduce artifact payload size or increase step resource_policy.max_artifact_bytes"
        ]
    if policy == "resource.max_parallelism":
        return [
            "reduce parallel branch count or increase step resource_policy.max_parallelism"
        ]
    if policy.startswith("runtime_safety.") or error_type == "WorkflowRuntimeSafetyViolation":
        return ["collect required approval or adjust runtime safety policy before retrying"]
    if policy:
        return ["inspect policy_violations in manifest.json before retrying"]
    return []


def _routing_diagnostics_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    evaluations: list[dict[str, Any]] = []
    selected_edge_ids: list[str] = []
    rejected_edge_ids: list[str] = []
    target_step_ids: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = _optional_string(event.get("event_type"))
        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if event_type == "edge_evaluated":
            evaluations.append(dict(payload))
        elif event_type == "edge_traversed":
            edge_id = _optional_string(payload.get("edge_id"))
            target_step_id = _optional_string(payload.get("target_step_id"))
            if edge_id:
                selected_edge_ids.append(edge_id)
            if target_step_id:
                target_step_ids.append(target_step_id)
        elif event_type == "edge_rejected":
            edge_id = _optional_string(payload.get("edge_id"))
            if edge_id:
                rejected_edge_ids.append(edge_id)
    return {
        "selected_edge_id": selected_edge_ids[0] if selected_edge_ids else None,
        "selected_edge_ids": _dedupe_preserve_order(selected_edge_ids),
        "target_step_ids": _dedupe_preserve_order(target_step_ids),
        "rejected_edge_ids": _dedupe_preserve_order(rejected_edge_ids),
        "evaluations": evaluations,
    }


def _manifest_policy_violations(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    violations = manifest.get("policy_violations")
    if not isinstance(violations, list):
        return []
    return [violation for violation in violations if isinstance(violation, dict)]


def _manifest_missing_artifacts(manifest: dict[str, Any]) -> list[str]:
    artifacts = _manifest_artifact_map(manifest)
    return [key for key in REQUIRED_RUN_ARTIFACTS if key not in artifacts]


def _truthy_nested(payload: Any, key: str) -> bool:
    return isinstance(payload, dict) and bool(payload.get(key))


def _event_step_id(event: dict[str, Any]) -> str | None:
    step_id = _optional_string(event.get("step_id"))
    if step_id:
        return step_id
    payload = event.get("payload")
    if isinstance(payload, dict):
        step_id = _optional_string(payload.get("step_id"))
        if step_id:
            return step_id
        outcome = payload.get("outcome")
        if isinstance(outcome, dict):
            return _optional_string(outcome.get("step_id"))
    return None


def _first_event_time(events: list[dict[str, Any]], event_types: set[str]) -> str | None:
    for event in events:
        if event.get("event_type") in event_types:
            return _optional_string(event.get("occurred_at"))
    return None


def _last_terminal_step_event_time(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("event_type") in {
            "step_succeeded",
            "step_failed",
            "step_blocked",
            "step_paused",
            "step_timeout",
        }:
            return _optional_string(event.get("occurred_at"))
    return None


def _last_step_status(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        status = _status_from_event_type(_optional_string(event.get("event_type")) or "")
        if status is not None:
            return status
        payload = event.get("payload")
        if isinstance(payload, dict):
            status = _optional_string(payload.get("status"))
            if status:
                return status
    return None


def _first_failed_step_id(inspection: WorkflowRunInspection) -> str | None:
    for step in inspection.steps:
        if step.status in {StepStatus.FAILED.value, StepStatus.TIMEOUT.value}:
            return step.step_id
    return None


def _first_blocked_step_id(inspection: WorkflowRunInspection) -> str | None:
    for step in inspection.steps:
        if step.status == StepStatus.BLOCKED.value:
            return step.step_id
    return None


def _manifest_path_list(manifest: dict[str, Any]) -> list[str]:
    path = manifest.get("path")
    if isinstance(path, list):
        return [str(item) for item in path]
    step_results = manifest.get("step_results")
    if isinstance(step_results, dict):
        return [str(key) for key in step_results]
    return []


def _manifest_output_keys(manifest: dict[str, Any]) -> list[str]:
    output_keys = manifest.get("output_keys")
    if isinstance(output_keys, list):
        return sorted(str(key) for key in output_keys)
    return []


def _inspection_output_keys(inspection: WorkflowRunInspection) -> list[str]:
    keys = _manifest_output_keys(inspection.manifest)
    if keys:
        return keys
    output_path = resolve_artifact_path(inspection.run_dir, "output.json")
    if output_path.exists():
        try:
            output = _read_json_file(output_path)
        except WorkflowRunInspectionError:
            return []
        if isinstance(output, dict):
            return sorted(str(key) for key in output)
    return []


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


def compare_workflow_run_inspections(
    base: WorkflowRunInspection,
    target: WorkflowRunInspection,
) -> WorkflowRunComparison:
    base_steps = {step.step_id: step for step in base.steps}
    target_steps = {step.step_id: step for step in target.steps}
    base_step_ids = set(base_steps)
    target_step_ids = set(target_steps)
    shared_step_ids = sorted(base_step_ids & target_step_ids)
    changed_step_statuses: dict[str, dict[str, str | None]] = {
        step_id: {
            "base": base_steps[step_id].status,
            "target": target_steps[step_id].status,
        }
        for step_id in shared_step_ids
        if base_steps[step_id].status != target_steps[step_id].status
    }
    added_output_keys: dict[str, list[str]] = {}
    removed_output_keys: dict[str, list[str]] = {}
    for step_id in shared_step_ids:
        base_outputs = set(base_steps[step_id].output_keys)
        target_outputs = set(target_steps[step_id].output_keys)
        added = sorted(target_outputs - base_outputs)
        removed = sorted(base_outputs - target_outputs)
        if added:
            added_output_keys[step_id] = added
        if removed:
            removed_output_keys[step_id] = removed

    base_artifacts = {artifact.artifact_key for artifact in base.artifacts}
    target_artifacts = {artifact.artifact_key for artifact in target.artifacts}
    base_event_count = base.event_summary.event_count if base.event_summary else 0
    target_event_count = target.event_summary.event_count if target.event_summary else 0
    base_duration_ms = (
        base.timeline_summary.duration_ms if base.timeline_summary else None
    )
    target_duration_ms = (
        target.timeline_summary.duration_ms if target.timeline_summary else None
    )
    base_health = base.health_report.severity if base.health_report else None
    target_health = target.health_report.severity if target.health_report else None
    base_path = _manifest_path_list(base.manifest)
    target_path = _manifest_path_list(target.manifest)
    base_output_keys = _inspection_output_keys(base)
    target_output_keys = _inspection_output_keys(target)
    base_metrics = base.metrics if isinstance(base.metrics, dict) else {}
    target_metrics = target.metrics if isinstance(target.metrics, dict) else {}
    return WorkflowRunComparison(
        base_run_id=base.run_id,
        target_run_id=target.run_id,
        base_status=base.status,
        target_status=target.status,
        base_workflow_version=base.workflow_version,
        target_workflow_version=target.workflow_version,
        same_workflow=base.workflow_id == target.workflow_id,
        status_changed=base.status != target.status,
        workflow_version_changed=base.workflow_version != target.workflow_version,
        step_count_delta=len(target.steps) - len(base.steps),
        event_count_delta=target_event_count - base_event_count,
        artifact_count_delta=len(target.artifacts) - len(base.artifacts),
        duration_ms_delta=_delta_or_none(base_duration_ms, target_duration_ms),
        added_steps=sorted(target_step_ids - base_step_ids),
        removed_steps=sorted(base_step_ids - target_step_ids),
        changed_step_statuses=changed_step_statuses,
        added_artifacts=sorted(target_artifacts - base_artifacts),
        removed_artifacts=sorted(base_artifacts - target_artifacts),
        added_output_keys=added_output_keys,
        removed_output_keys=removed_output_keys,
        health_severity_changed=base_health != target_health,
        base_health_severity=base_health,
        target_health_severity=target_health,
        path_diff={
            "base": base_path,
            "target": target_path,
            "changed": base_path != target_path,
        },
        output_diff={
            "base_keys": base_output_keys,
            "target_keys": target_output_keys,
            "added_keys": sorted(set(target_output_keys) - set(base_output_keys)),
            "removed_keys": sorted(set(base_output_keys) - set(target_output_keys)),
            "changed": base_output_keys != target_output_keys,
        },
        metric_diff={
            "budget": {
                "base": to_json_safe(base_metrics.get("budget")),
                "target": to_json_safe(target_metrics.get("budget")),
                "changed": base_metrics.get("budget") != target_metrics.get("budget"),
            },
            "changed": base_metrics != target_metrics,
        },
        artifact_diff={
            "base_keys": sorted(base_artifacts),
            "target_keys": sorted(target_artifacts),
            "added_keys": sorted(target_artifacts - base_artifacts),
            "removed_keys": sorted(base_artifacts - target_artifacts),
            "changed": base_artifacts != target_artifacts,
        },
    )


def workflow_run_catalog_summary(catalog: WorkflowRunCatalog) -> dict[str, Any]:
    latest = catalog.latest()
    return {
        "artifact_root": catalog.artifact_root,
        "run_count": len(catalog.runs),
        "total_run_count": catalog.total_run_count,
        "returned_run_count": catalog.returned_run_count,
        "invalid_run_dir_count": len(catalog.invalid_run_dirs),
        "status_counts": dict(catalog.status_counts),
        "workflow_counts": dict(catalog.workflow_counts),
        "profile_counts": dict(catalog.profile_counts),
        "latest_started_at": catalog.latest_started_at,
        "oldest_started_at": catalog.oldest_started_at,
        "latest_run_id": latest.run_id if latest else None,
    }


def build_run_catalog_health(catalog: WorkflowRunCatalog) -> WorkflowRunCatalogHealth:
    runs = list(catalog.runs)
    valid_runs = [run for run in runs if run.valid_manifest]
    invalid_runs = [run for run in runs if not run.valid_manifest]
    failed_runs = [run for run in valid_runs if run.failed]
    paused_runs = [run for run in valid_runs if run.paused]
    running_runs = [
        run
        for run in valid_runs
        if run.status in {
            WorkflowStatus.CREATED.value,
            WorkflowStatus.RUNNING.value,
            WorkflowStatus.RETRYING.value,
        }
    ]
    invalid_dirs = _dedupe_preserve_order(
        [run.run_dir for run in invalid_runs] + list(catalog.invalid_run_dirs)
    )
    succeeded_runs = [run for run in valid_runs if run.succeeded]
    latest = catalog.latest()
    latest_success = _first_run_with_status(valid_runs, WorkflowStatus.SUCCEEDED.value)
    latest_failed = _first_failed_run(valid_runs)
    latest_paused = _first_paused_run(valid_runs)
    warnings: list[str] = []
    actions: list[str] = []
    if invalid_runs or catalog.invalid_run_dirs:
        warnings.append("catalog contains invalid run manifests")
        actions.append("inspect invalid run directories and restore or remove bad manifests")
    if latest and latest.failed:
        warnings.append(f"latest run ended with status {latest.status}")
        actions.append("inspect latest failed run diagnostics before promoting downstream output")
    if paused_runs:
        warnings.append("catalog contains paused runs")
        actions.append("resume or cancel paused runs through the application layer")
    if running_runs:
        warnings.append("catalog contains non-terminal runs")
        actions.append("confirm worker/checkpoint state for non-terminal runs")
    severity = _catalog_health_severity(
        latest=latest,
        invalid_count=len(invalid_dirs),
        failed_count=len(failed_runs),
        paused_count=len(paused_runs),
        running_count=len(running_runs),
    )
    return WorkflowRunCatalogHealth(
        artifact_root=catalog.artifact_root,
        severity=severity,
        summary=_catalog_health_summary(
            latest=latest,
            severity=severity,
            run_count=len(runs),
            invalid_count=len(invalid_dirs),
        ),
        run_count=len(runs),
        valid_run_count=len(valid_runs),
        invalid_run_count=len(invalid_dirs),
        succeeded_count=len(succeeded_runs),
        failed_count=len(failed_runs),
        paused_count=len(paused_runs),
        running_count=len(running_runs),
        latest_run_id=latest.run_id if latest else None,
        latest_status=latest.status if latest else None,
        latest_successful_run_id=latest_success.run_id if latest_success else None,
        latest_failed_run_id=latest_failed.run_id if latest_failed else None,
        latest_paused_run_id=latest_paused.run_id if latest_paused else None,
        failed_run_ids=[run.run_id for run in failed_runs],
        paused_run_ids=[run.run_id for run in paused_runs],
        running_run_ids=[run.run_id for run in running_runs],
        invalid_run_dirs=invalid_dirs,
        status_counts=dict(catalog.status_counts),
        workflow_counts=dict(catalog.workflow_counts),
        profile_counts=dict(catalog.profile_counts),
        warnings=_dedupe_preserve_order(warnings),
        suggested_actions=_dedupe_preserve_order(actions),
    )


def workflow_run_catalog_health_summary(
    health: WorkflowRunCatalogHealth,
) -> dict[str, Any]:
    return {
        "artifact_root": health.artifact_root,
        "severity": health.severity,
        "healthy": health.healthy,
        "run_count": health.run_count,
        "valid_run_count": health.valid_run_count,
        "invalid_run_count": health.invalid_run_count,
        "latest_run_id": health.latest_run_id,
        "latest_status": health.latest_status,
        "latest_successful_run_id": health.latest_successful_run_id,
        "latest_failed_run_id": health.latest_failed_run_id,
        "failed_count": health.failed_count,
        "paused_count": health.paused_count,
        "running_count": health.running_count,
        "warning_count": len(health.warnings),
    }


def catalog_runs_by_status(
    catalog: WorkflowRunCatalog,
    status: str | WorkflowStatus,
) -> list[WorkflowRunListItem]:
    requested_status = _status_value(status)
    return [run for run in catalog.runs if run.status == requested_status]


def catalog_runs_by_workflow(
    catalog: WorkflowRunCatalog,
    workflow_id: str,
) -> list[WorkflowRunListItem]:
    return [run for run in catalog.runs if run.workflow_id == workflow_id]


def catalog_runs_by_profile(
    catalog: WorkflowRunCatalog,
    profile: str,
) -> list[WorkflowRunListItem]:
    return [run for run in catalog.runs if run.profile == profile]


def failed_run_items(catalog: WorkflowRunCatalog) -> list[WorkflowRunListItem]:
    return [run for run in catalog.runs if run.failed]


def paused_run_items(catalog: WorkflowRunCatalog) -> list[WorkflowRunListItem]:
    return [run for run in catalog.runs if run.paused]


def invalid_run_items(catalog: WorkflowRunCatalog) -> list[WorkflowRunListItem]:
    return [run for run in catalog.runs if not run.valid_manifest]


def unhealthy_run_items(catalog: WorkflowRunCatalog) -> list[WorkflowRunListItem]:
    return [
        run
        for run in catalog.runs
        if run.failed or run.paused or not run.valid_manifest
    ]


def workflow_run_comparison_summary(comparison: WorkflowRunComparison) -> dict[str, Any]:
    return {
        "base_run_id": comparison.base_run_id,
        "target_run_id": comparison.target_run_id,
        "same_workflow": comparison.same_workflow,
        "status_changed": comparison.status_changed,
        "workflow_version_changed": comparison.workflow_version_changed,
        "health_severity_changed": comparison.health_severity_changed,
        "has_behavioral_change": comparison.has_behavioral_change,
        "added_steps": list(comparison.added_steps),
        "removed_steps": list(comparison.removed_steps),
        "changed_step_status_count": len(comparison.changed_step_statuses),
        "added_artifact_count": len(comparison.added_artifacts),
        "removed_artifact_count": len(comparison.removed_artifacts),
        "step_count_delta": comparison.step_count_delta,
        "event_count_delta": comparison.event_count_delta,
        "artifact_count_delta": comparison.artifact_count_delta,
    }


def _timeline_item_from_event(
    event: WorkflowEventRecord,
    *,
    sequence: int,
) -> WorkflowTimelineItem:
    payload: dict[str, Any] = event.payload if isinstance(event.payload, dict) else {}
    raw_outcome = payload.get("outcome")
    raw_error = payload.get("error")
    outcome: dict[str, Any] = raw_outcome if isinstance(raw_outcome, dict) else {}
    error: dict[str, Any] = raw_error if isinstance(raw_error, dict) else {}
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


def _run_list_item_from_dir(run_dir: Path) -> WorkflowRunListItem | None:
    try:
        manifest_path = resolve_artifact_path(run_dir, "manifest.json")
    except WorkflowRunInspectionError as exc:
        return WorkflowRunListItem(
            run_id=run_dir.name,
            run_dir=str(run_dir),
            manifest_path="",
            valid_manifest=False,
            invalid_reason=str(exc),
        )
    if not manifest_path.exists():
        return None
    try:
        manifest = _read_json_file(manifest_path)
    except WorkflowRunInspectionError as exc:
        return WorkflowRunListItem(
            run_id=run_dir.name,
            run_dir=str(run_dir),
            manifest_path=str(manifest_path),
            valid_manifest=False,
            invalid_reason=str(exc),
        )
    if not isinstance(manifest, dict):
        return WorkflowRunListItem(
            run_id=run_dir.name,
            run_dir=str(run_dir),
            manifest_path=str(manifest_path),
            valid_manifest=False,
            invalid_reason="manifest must be an object",
        )
    invalid_reason = None
    try:
        validate_run_manifest(manifest, require_terminal_artifact=False)
    except RunManifestError as exc:
        invalid_reason = str(exc)
    artifacts = _manifest_artifact_map(manifest)
    run_id = _optional_string(manifest.get("run_id")) or run_dir.name
    status = _optional_string(manifest.get("status"))
    return WorkflowRunListItem(
        run_id=run_id,
        run_dir=str(run_dir),
        manifest_path=str(manifest_path),
        status=status,
        workflow_id=_optional_string(manifest.get("workflow_id")),
        workflow_version=_optional_string(manifest.get("workflow_version")),
        profile=_optional_string(manifest.get("profile")),
        started_at=_optional_string(manifest.get("started_at")),
        finished_at=_optional_string(manifest.get("finished_at")),
        manifest_schema_version=manifest_schema_version(manifest),
        step_count=_optional_int(manifest.get("step_count")),
        event_count=_optional_int(manifest.get("event_count")),
        checkpoint_count=_optional_int(manifest.get("checkpoint_count")),
        artifact_count=len(artifacts),
        terminal_artifact_key=terminal_artifact_key(manifest),
        valid_manifest=invalid_reason is None,
        invalid_reason=invalid_reason,
    )


def _artifact_content_path(run_dir: Path, relative_path: str) -> Path:
    try:
        path = resolve_artifact_path(run_dir, relative_path)
    except WorkflowRunInspectionError as exc:
        raise ValueError(str(exc)) from exc
    if not path.exists():
        raise FileNotFoundError(f"artifact file not found: {relative_path}")
    return path


def _read_artifact_content(
    path: Path,
    content_type: str,
    *,
    max_bytes: int | None,
) -> tuple[Any, bool]:
    return _read_artifact_content_bytes(
        path.read_bytes(),
        content_type,
        max_bytes=max_bytes,
    )


def _read_artifact_content_bytes(
    content_bytes: bytes,
    content_type: str,
    *,
    max_bytes: int | None,
) -> tuple[Any, bool]:
    if max_bytes is not None and max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    size_bytes = len(content_bytes)
    truncated = max_bytes is not None and size_bytes > max_bytes
    preview = content_bytes[:max_bytes] if max_bytes is not None else content_bytes
    if content_type == "application/json":
        if truncated:
            return preview.decode("utf-8", errors="replace"), True
        return json.loads(content_bytes.decode("utf-8")), False
    if content_type == "application/x-ndjson":
        if truncated:
            return preview.decode("utf-8", errors="replace"), True
        return _read_jsonl_bytes_values(content_bytes), False
    if content_type.startswith("text/"):
        return preview.decode("utf-8"), truncated
    binary_preview = content_bytes[: max_bytes if max_bytes is not None else 256]
    return {
        "encoding": "hex",
        "bytes_preview": binary_preview.hex(),
        "preview_size_bytes": len(binary_preview),
    }, truncated


def _read_text_preview(path: Path, *, max_bytes: int | None) -> str:
    if max_bytes is None:
        return path.read_text(encoding="utf-8")
    with path.open("rb") as handle:
        data = handle.read(max_bytes)
    return data.decode("utf-8", errors="replace")


def _read_binary_preview(path: Path, *, max_bytes: int | None) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = handle.read(max_bytes if max_bytes is not None else 256)
    return {
        "encoding": "hex",
        "bytes_preview": data.hex(),
        "preview_size_bytes": len(data),
    }


def _redact_if_needed(value: Any, *, redact: bool) -> Any:
    return redact_sensitive_values(value) if redact else value


def _first_artifact_index_path(
    artifact_paths: dict[str, str],
    *,
    index_keys: Iterable[str] | None,
) -> tuple[str | None, str | None]:
    for index_key in index_keys or DEFAULT_ARTIFACT_INDEX_KEYS:
        path = artifact_paths.get(str(index_key))
        if isinstance(path, str):
            return str(index_key), path
    return None, None


def _artifact_index_entry_key(index_artifact_key: str, entry: dict[str, Any]) -> str:
    parts = [
        str(index_artifact_key),
        str(entry.get("artifact_type") or "unknown"),
        str(entry.get("entity_id") or entry.get("source_id") or "unknown-entity"),
        str(entry.get("object_id") or "unknown-object"),
    ]
    return ".".join(_artifact_key_segment(part) for part in parts)


def _capture_verified_artifact_index_snapshots(
    run_dir: Path,
    snapshots: Mapping[str, _VerifiedArtifactSnapshot],
    artifact_paths: dict[str, str],
    *,
    run_id: str,
    index_artifact_key: str,
) -> list[_VerifiedArtifactSnapshot]:
    if index_artifact_key not in artifact_paths:
        return []
    index_snapshot = snapshots.get(index_artifact_key)
    if index_snapshot is None:
        raise ArtifactStoreMetadataError(
            f"verified artifact index snapshot is missing: {index_artifact_key}"
        )
    try:
        payload = json.loads(index_snapshot.content_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactStoreMetadataError(
            f"artifact index is not valid JSON: {index_artifact_key}"
        ) from exc
    if not isinstance(payload, dict):
        raise ArtifactStoreMetadataError(
            f"artifact index must be an object: {index_artifact_key}"
        )
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ArtifactStoreMetadataError(
            f"artifact index entries must be a list: {index_artifact_key}"
        )

    plans: list[tuple[_VerifiedIndexEntryPlan, dict[str, Any]]] = []
    projected_keys: set[str] = set()
    for position, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise ArtifactStoreMetadataError(
                f"artifact index entry must be an object: {index_artifact_key}[{position}]"
            )
        entry = dict(raw_entry)
        projected_entry = _canonical_index_entry_projection(entry, position=position)
        artifact_key = _artifact_index_entry_key(index_artifact_key, projected_entry)
        if artifact_key in projected_keys:
            raise ArtifactStoreMetadataError(
                f"artifact index projected key is duplicated: {artifact_key}"
            )
        projected_keys.add(artifact_key)
        plans.append(
            (
                _verified_index_entry_plan(
                    artifact_key,
                        entry,
                        projected_entry,
                        run_id=run_id,
                        index_artifact_key=index_artifact_key,
                ),
                entry,
            )
        )

    verified: list[_VerifiedArtifactSnapshot] = []
    for plan, entry in plans:
        path = resolve_artifact_descendant(
            run_dir,
            plan.relative_path,
            field=f"artifact_index_path[{plan.artifact_key}]",
        )
        if path.exists() and not path.is_file():
            raise ArtifactStoreMetadataError(
                f"artifact index target is not a regular file: {plan.artifact_key}"
            )
        if not path.is_file():
            raise ArtifactNotFoundError(
                f"artifact file not found: {plan.relative_path}"
            )
        try:
            content_bytes = path.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(
                f"artifact file not found: {plan.relative_path}"
            ) from exc
        verify_sha256_checksum(
            content_bytes,
            plan.checksum,
            artifact_id=plan.artifact_key,
            field="artifact_index.checksum",
            store="strict_workflow",
            operation="strict_read",
        )
        if plan.size_bytes is not None and len(content_bytes) != plan.size_bytes:
            raise ArtifactStoreMetadataError(
                f"artifact index size_bytes does not match content: {plan.artifact_key}"
            )
        actual_content_type = content_type_for_path(plan.relative_path)
        if (
            plan.content_type is not None
            and plan.content_type != actual_content_type
        ):
            raise ArtifactStoreMetadataError(
                f"artifact index content_type does not match path: {plan.artifact_key}"
            )
        verified.append(
            _VerifiedArtifactSnapshot(
                artifact_key=plan.artifact_key,
                relative_path=_posix_artifact_path(plan.relative_path),
                absolute_path=path,
                metadata=MappingProxyType(dict(plan.metadata)),
                content_type=actual_content_type,
                size_bytes=len(content_bytes),
                content_bytes=content_bytes,
            )
        )
    return verified


def _selected_artifact_index_keys(
    artifact_paths: dict[str, str],
    *,
    index_keys: Iterable[str] | None,
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for raw_key in index_keys or DEFAULT_ARTIFACT_INDEX_KEYS:
        key = str(raw_key)
        if key in seen or key not in artifact_paths:
            continue
        seen.add(key)
        selected.append(key)
    return selected


def _canonical_index_entry_projection(
    entry: dict[str, Any],
    *,
    position: int,
) -> dict[str, Any]:
    raw_ref = entry.get("artifact_ref")
    if raw_ref is not None and not isinstance(raw_ref, dict):
        raise ArtifactStoreMetadataError(
            f"artifact index artifact_ref must be an object: entry {position}"
        )
    artifact_ref = dict(raw_ref or {})
    if raw_ref is not None:
        for field_name in ("artifact_id", "run_id", "artifact_type", "path"):
            value = artifact_ref.get(field_name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
            ):
                raise ArtifactStoreMetadataError(
                    "artifact index artifact_ref field must be a non-empty string: "
                    f"{field_name} at entry {position}"
                )
    projected = dict(entry)
    for field_name in ("artifact_id", "run_id", "artifact_type", "path"):
        top_value = entry.get(field_name)
        nested_value = artifact_ref.get(field_name)
        if nested_value is not None:
            if top_value is not None and top_value != nested_value:
                raise ArtifactStoreMetadataError(
                    f"artifact index {field_name} declarations conflict: entry {position}"
                )
            projected[field_name] = nested_value
    for field_name in ("artifact_id", "run_id", "artifact_type", "path"):
        value = projected.get(field_name)
        if value is not None and (
            not isinstance(value, str) or not value.strip() or value != value.strip()
        ):
            raise ArtifactStoreMetadataError(
                f"artifact index {field_name} must be a non-empty string: entry {position}"
            )
    return projected


def _verified_index_entry_plan(
    artifact_key: str,
    entry: dict[str, Any],
    projected_entry: dict[str, Any],
    *,
    run_id: str,
    index_artifact_key: str,
) -> _VerifiedIndexEntryPlan:
    raw_ref = entry.get("artifact_ref")
    artifact_ref = dict(raw_ref) if isinstance(raw_ref, dict) else {}
    relative_path = projected_entry.get("path")
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ArtifactStoreMetadataError(
            f"artifact index path is required: {artifact_key}"
        )
    entry_run_id = projected_entry.get("run_id")
    if entry_run_id is not None and entry_run_id != run_id:
        raise ArtifactStoreMetadataError(
            f"artifact index run_id does not match replay run: {artifact_key}"
        )

    top_checksum = entry.get("checksum")
    nested_checksum = artifact_ref.get("checksum")
    top_checksum_declared = "checksum" in entry
    nested_checksum_declared = "checksum" in artifact_ref
    validated_top = (
        validate_sha256_checksum(
            top_checksum,
            artifact_id=artifact_key,
            field="artifact_index.checksum",
        )
        if top_checksum_declared
        else None
    )
    validated_nested = (
        validate_sha256_checksum(
            nested_checksum,
            artifact_id=artifact_key,
            field="artifact_index.artifact_ref.checksum",
        )
        if nested_checksum_declared
        else None
    )
    if top_checksum_declared and nested_checksum_declared:
        if validated_top != validated_nested:
            raise ArtifactStoreMetadataError(
                f"artifact index checksum declarations conflict: {artifact_key}"
            )
    checksum = validated_top or validated_nested
    if checksum is None:
        raise ArtifactStoreMetadataError(
            f"artifact index checksum is missing: {artifact_key}"
        )

    size_bytes = _canonical_optional_index_field(
        entry,
        artifact_ref,
        "size_bytes",
        artifact_key=artifact_key,
    )
    if size_bytes is not None and (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes < 0
    ):
        raise ArtifactStoreMetadataError(
            f"invalid artifact index size_bytes: {artifact_key}"
        )

    # `source_response_headers.content_type` is a business projection of the
    # upstream HTTP response. Its nested artifact_ref owns persisted MIME.
    if artifact_ref:
        content_type = artifact_ref.get("content_type")
        if projected_entry.get("artifact_type") != "source_response_headers":
            top_content_type = entry.get("content_type")
            if (
                top_content_type is not None
                and content_type is not None
                and top_content_type != content_type
            ):
                raise ArtifactStoreMetadataError(
                    f"artifact index content_type declarations conflict: {artifact_key}"
                )
    else:
        content_type = entry.get("content_type")
    if content_type is not None and (
        not isinstance(content_type, str) or not content_type.strip()
    ):
        raise ArtifactStoreMetadataError(
            f"invalid artifact index content_type: {artifact_key}"
        )

    metadata = {
        **entry,
        "artifact_index": True,
        "index_artifact_key": index_artifact_key,
    }
    return _VerifiedIndexEntryPlan(
        artifact_key=artifact_key,
        relative_path=relative_path,
        checksum=checksum,
        content_type=content_type,
        size_bytes=size_bytes,
        metadata=metadata,
    )


def _canonical_optional_index_field(
    entry: dict[str, Any],
    artifact_ref: dict[str, Any],
    field_name: str,
    *,
    artifact_key: str,
) -> Any:
    top_value = entry.get(field_name)
    nested_value = artifact_ref.get(field_name)
    if nested_value is not None:
        if top_value is not None and top_value != nested_value:
            raise ArtifactStoreMetadataError(
                f"artifact index {field_name} declarations conflict: {artifact_key}"
            )
        return nested_value
    return top_value


def _indexed_content_record_from_snapshot(
    snapshot: _VerifiedArtifactSnapshot,
    *,
    redact: bool,
    max_bytes: int | None,
) -> WorkflowArtifactContentRecord:
    return _content_record_from_snapshot(
        snapshot,
        redact=redact,
        max_bytes=max_bytes,
    )


def _artifact_key_segment(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in value
    ).strip("_") or "unknown"


def _run_list_item_matches(
    item: WorkflowRunListItem,
    *,
    workflow_id: str | None,
    workflow_version: str | None,
    status: str | None,
    profile: str | None,
) -> bool:
    if workflow_id is not None and item.workflow_id != workflow_id:
        return False
    if workflow_version is not None and item.workflow_version != workflow_version:
        return False
    if status is not None and item.status != status:
        return False
    if profile is not None and item.profile != profile:
        return False
    return True


def _run_list_sort_key(item: WorkflowRunListItem) -> tuple[str, str, str]:
    started_at = item.started_at or item.finished_at or ""
    return (started_at, item.finished_at or "", item.run_id)


def _catalog_counts(
    items: Iterable[WorkflowRunListItem],
    field_name: str,
) -> dict[str, int]:
    counts = Counter(
        str(value)
        for value in (_run_list_field(item, field_name) for item in items)
        if value is not None
    )
    return dict(sorted(counts.items()))


def _run_list_field(item: WorkflowRunListItem, field_name: str) -> Any:
    if field_name == "status":
        return item.status
    if field_name == "workflow_id":
        return item.workflow_id
    if field_name == "profile":
        return item.profile
    raise ValueError(f"unsupported run catalog field: {field_name}")


def _latest_started_at(items: Iterable[WorkflowRunListItem]) -> str | None:
    values = sorted(item.started_at for item in items if item.started_at)
    return values[-1] if values else None


def _oldest_started_at(items: Iterable[WorkflowRunListItem]) -> str | None:
    values = sorted(item.started_at for item in items if item.started_at)
    return values[0] if values else None


def _status_value(status: str | WorkflowStatus | None) -> str | None:
    if isinstance(status, WorkflowStatus):
        return status.value
    if status is None:
        return None
    return str(status)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _delta_or_none(
    base_value: float | None,
    target_value: float | None,
) -> float | None:
    if base_value is None or target_value is None:
        return None
    return round(target_value - base_value, 3)


def _first_run_with_status(
    runs: Iterable[WorkflowRunListItem],
    status: str,
) -> WorkflowRunListItem | None:
    for run in runs:
        if run.status == status:
            return run
    return None


def _first_failed_run(
    runs: Iterable[WorkflowRunListItem],
) -> WorkflowRunListItem | None:
    for run in runs:
        if run.failed:
            return run
    return None


def _first_paused_run(
    runs: Iterable[WorkflowRunListItem],
) -> WorkflowRunListItem | None:
    for run in runs:
        if run.paused:
            return run
    return None


def _catalog_health_severity(
    *,
    latest: WorkflowRunListItem | None,
    invalid_count: int,
    failed_count: int,
    paused_count: int,
    running_count: int,
) -> str:
    if invalid_count:
        return "error"
    if latest is not None and latest.failed:
        return "error"
    if failed_count:
        return "warning"
    if paused_count:
        return "paused"
    if running_count:
        return "warning"
    if latest is None:
        return "unknown"
    if latest.succeeded:
        return "ok"
    return "warning"


def _catalog_health_summary(
    *,
    latest: WorkflowRunListItem | None,
    severity: str,
    run_count: int,
    invalid_count: int,
) -> str:
    if latest is None:
        return "no workflow runs found"
    if severity == "ok":
        return f"latest run {latest.run_id} completed successfully"
    if severity == "error" and invalid_count:
        return f"catalog has {invalid_count} invalid run manifest(s)"
    if severity == "error":
        return f"latest run {latest.run_id} ended with status {latest.status}"
    if severity == "paused":
        return "catalog contains paused runs"
    if severity == "warning":
        return f"catalog has warnings across {run_count} run(s)"
    return f"catalog status is {severity}"


def _event_phase(event_type: str) -> str:
    if event_type.startswith("workflow_"):
        return "workflow"
    if event_type.startswith("step_"):
        return "step"
    if event_type.startswith("edge_"):
        return "routing"
    if event_type.startswith("checkpoint_"):
        return "checkpoint"
    if event_type in {"human_review_paused", "human_review_requested"}:
        return "human"
    if event_type in {"policy_violation"}:
        return "policy"
    return "runtime"


def _event_severity(event_type: str, *, status: str | None = None) -> str:
    error_events = {
        "workflow_failed",
        "workflow_budget_exceeded",
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
        "human_review_paused",
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
    if event_type == "workflow_budget_exceeded":
        return WorkflowStatus.BUDGET_EXCEEDED.value
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
    if event_type in {"human_review_paused", "human_review_requested"}:
        return f"human review paused: {step_id}" if step_id else "human review paused"
    if event_type == "policy_violation":
        return _optional_string(payload.get("message")) or "policy violation"
    if event_type == "workflow_succeeded":
        return "workflow succeeded"
    if event_type == "workflow_failed":
        message = error.get("message") or payload.get("message")
        return f"workflow failed: {message}" if message else "workflow failed"
    if event_type == "workflow_budget_exceeded":
        message = error.get("message") or payload.get("message")
        return (
            f"workflow budget exceeded: {message}"
            if message
            else "workflow budget exceeded"
        )
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
        "workflow_budget_exceeded",
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


def _read_jsonl_file_values(path: Path) -> list[Any]:
    values: list[Any] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    values.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    raise WorkflowRunInspectionError(
                        f"invalid JSONL artifact at {path}:{line_number}"
                    ) from exc
    except OSError as exc:
        raise WorkflowRunInspectionError(f"failed to read JSONL artifact: {path}") from exc
    return values


def _read_jsonl_bytes_values(content_bytes: bytes) -> list[Any]:
    values: list[Any] = []
    for line_number, line in enumerate(content_bytes.decode("utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            values.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise WorkflowRunInspectionError(
                f"invalid JSONL artifact at line {line_number}"
            ) from exc
    return values


def _read_event_jsonl_bytes(content_bytes: bytes) -> list[WorkflowEventRecord]:
    records: list[WorkflowEventRecord] = []
    try:
        lines = content_bytes.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise WorkflowRunInspectionError("invalid UTF-8 events artifact") from exc
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise WorkflowRunInspectionError(
                f"invalid event JSON at line {line_number}"
            ) from exc
        if not isinstance(payload, dict):
            raise WorkflowRunInspectionError(
                f"event record must be an object at line {line_number}"
            )
        records.append(_event_from_payload(payload, line_number=line_number))
    return records


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
    artifact_metadata = manifest.get("artifact_metadata")
    if isinstance(artifact_metadata, dict) and isinstance(
        artifact_metadata.get(artifact_key),
        dict,
    ):
        metadata.update(artifact_metadata[artifact_key])
    step_artifact = _step_artifact_payload_for_key(manifest, artifact_key)
    if isinstance(step_artifact, dict):
        metadata.update(
            {
                key: value
                for key, value in step_artifact.items()
                if key in {"checksum", "size_bytes", "content_type"}
            }
        )
    return metadata


def _read_strict_workflow_artifact_bytes(
    run_dir: Path,
    manifest: dict[str, Any],
    artifact_key: str,
) -> tuple[str, Path, bytes, dict[str, Any]]:
    snapshot = _capture_verified_artifact_snapshot(run_dir, manifest, artifact_key)
    return (
        snapshot.relative_path,
        snapshot.absolute_path,
        snapshot.content_bytes,
        dict(snapshot.metadata),
    )


def _capture_and_validate_run_manifest(
    run_dir: Path,
) -> tuple[_VerifiedArtifactSnapshot, dict[str, Any]]:
    path = resolve_artifact_descendant(
        run_dir,
        "manifest.json",
        field="artifact_path[manifest]",
    )
    if path.exists() and not path.is_file():
        raise ArtifactStoreMetadataError(
            "artifact file is not a regular file: manifest.json"
        )
    if not path.is_file():
        raise ArtifactNotFoundError("artifact file not found: manifest.json")
    try:
        content_bytes = path.read_bytes()
    except FileNotFoundError as exc:
        raise ArtifactNotFoundError("artifact file not found: manifest.json") from exc
    try:
        manifest = json.loads(content_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactStoreMetadataError("run manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ArtifactStoreMetadataError("run manifest must be an object")
    _validate_canonical_run_manifest(manifest)
    artifacts = _manifest_artifact_map(manifest)
    if artifacts.get("manifest") != "manifest.json":
        raise ArtifactStoreMetadataError(
            "run manifest artifact must reference manifest.json"
        )
    metadata = _strict_artifact_metadata(manifest, "manifest")
    if metadata.get("checksum") != "pending":
        raise ArtifactStoreMetadataError(
            "artifact metadata checksum must be 'pending': manifest"
        )
    expected_content_type = metadata.get("content_type")
    if expected_content_type != "application/json":
        raise ArtifactStoreMetadataError(
            "artifact metadata content_type does not match path: manifest"
        )
    return (
        _VerifiedArtifactSnapshot(
            artifact_key="manifest",
            relative_path="manifest.json",
            absolute_path=path,
            metadata=MappingProxyType(dict(metadata)),
            content_type="application/json",
            size_bytes=len(content_bytes),
            content_bytes=content_bytes,
        ),
        manifest,
    )


def _validate_canonical_run_manifest(manifest: dict[str, Any]) -> None:
    try:
        validate_run_manifest(manifest, require_terminal_artifact=True)
    except RunManifestError as exc:
        raise ArtifactStoreMetadataError("invalid canonical run manifest") from exc


def _capture_verified_artifact_snapshot(
    run_dir: Path,
    manifest: dict[str, Any],
    artifact_key: str,
) -> _VerifiedArtifactSnapshot:
    artifacts = _manifest_artifact_map(manifest)
    relative_path = artifacts.get(artifact_key)
    if relative_path is None:
        raise ArtifactNotFoundError(f"artifact not found: {artifact_key}")

    path = resolve_artifact_descendant(
        run_dir,
        relative_path,
        field=f"artifact_path[{artifact_key}]",
    )
    if path.exists() and not path.is_file():
        raise ArtifactStoreMetadataError(
            f"artifact file is not a regular file: {relative_path}"
        )
    metadata = _strict_artifact_metadata(manifest, artifact_key)
    expected_content_type = metadata.get("content_type")
    actual_content_type = content_type_for_path(relative_path)
    if expected_content_type is not None and expected_content_type != actual_content_type:
        raise ArtifactStoreMetadataError(
            f"artifact metadata content_type does not match path: {artifact_key}"
        )
    expected_checksum = metadata.get("checksum")
    if artifact_key == "manifest":
        if expected_checksum != "pending":
            raise ArtifactStoreMetadataError(
                "artifact metadata checksum must be 'pending': manifest"
            )
    else:
        expected_checksum = validate_sha256_checksum(
            expected_checksum,
            artifact_id=artifact_key,
            field="artifact_metadata.checksum",
        )

    if not path.is_file():
        raise ArtifactNotFoundError(f"artifact file not found: {relative_path}")
    try:
        content_bytes = path.read_bytes()
    except FileNotFoundError as exc:
        raise ArtifactNotFoundError(f"artifact file not found: {relative_path}") from exc

    if artifact_key != "manifest":
        verify_sha256_checksum(
            content_bytes,
            expected_checksum,
            artifact_id=artifact_key,
            field="artifact_metadata.checksum",
            store="strict_workflow",
            operation="strict_read",
        )
        expected_size = metadata.get("size_bytes")
        if expected_size is not None and len(content_bytes) != expected_size:
            raise ArtifactStoreMetadataError(
                f"artifact metadata size_bytes does not match content: {artifact_key}"
            )
    return _VerifiedArtifactSnapshot(
        artifact_key=artifact_key,
        relative_path=_posix_artifact_path(relative_path),
        absolute_path=path,
        metadata=MappingProxyType(dict(metadata)),
        content_type=actual_content_type,
        size_bytes=len(content_bytes),
        content_bytes=content_bytes,
    )


def _json_payload_from_snapshot(
    snapshot: _VerifiedArtifactSnapshot | None,
    *,
    default: Any,
) -> Any:
    if snapshot is None:
        return default
    try:
        return json.loads(snapshot.content_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkflowRunInspectionError(
            f"invalid JSON artifact: {snapshot.artifact_key}"
        ) from exc


def _event_records_from_snapshot(
    snapshot: _VerifiedArtifactSnapshot | None,
) -> list[WorkflowEventRecord]:
    if snapshot is None:
        return []
    return _read_event_jsonl_bytes(snapshot.content_bytes)


def _strict_snapshot_integrity_report(
    artifact_paths: dict[str, str],
    snapshots: dict[str, _VerifiedArtifactSnapshot],
    *,
    indexed_snapshot_count: int,
) -> dict[str, Any]:
    # Strict snapshot construction is the proof of validity. This projection is
    # intentionally byte-derived and does not invoke tolerant path-based inspection.
    return WorkflowManifestIntegrityReport(
        valid=True,
        artifact_count=len(artifact_paths),
        file_count=len(snapshots) + indexed_snapshot_count,
        total_size_bytes=sum(snapshot.size_bytes for snapshot in snapshots.values()),
    ).to_dict()


def _required_index_run_id(manifest: dict[str, Any]) -> str:
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ArtifactStoreMetadataError("run manifest run_id is required")
    return run_id


def _is_missing_checksum_error(exc: ArtifactStoreMetadataError) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current)
        if (
            "checksum is missing" in message
            or "artifact metadata is missing" in message
            or "checksum is required" in message
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _emit_strict_workflow_metadata_failure(
    exc: ArtifactStoreMetadataError,
) -> None:
    if _is_missing_checksum_error(exc):
        emit_artifact_checksum_missing(store="strict_workflow")
    else:
        emit_artifact_metadata_corrupt(store="strict_workflow")


def _strict_artifact_metadata(
    manifest: dict[str, Any],
    artifact_key: str,
) -> dict[str, Any]:
    raw_metadata = manifest.get("artifact_metadata")
    if raw_metadata is not None and not isinstance(raw_metadata, dict):
        raise ArtifactStoreMetadataError("run manifest artifact_metadata must be an object")
    if isinstance(raw_metadata, dict) and artifact_key in raw_metadata:
        metadata = raw_metadata[artifact_key]
        if not isinstance(metadata, dict):
            raise ArtifactStoreMetadataError(
                f"run manifest artifact metadata must be an object: {artifact_key}"
            )
        return _validate_optional_workflow_artifact_metadata_fields(
            dict(metadata),
            artifact_key,
        )

    step_artifact = _step_artifact_payload_for_key(manifest, artifact_key)
    if isinstance(step_artifact, dict):
        return _validate_optional_workflow_artifact_metadata_fields(
            dict(step_artifact),
            artifact_key,
        )
    raise ArtifactStoreMetadataError(
        f"run manifest artifact metadata is missing: {artifact_key}"
    )


def _validate_optional_workflow_artifact_metadata_fields(
    metadata: dict[str, Any],
    artifact_key: str,
) -> dict[str, Any]:
    if "content_type" in metadata and (
        not isinstance(metadata["content_type"], str)
        or not metadata["content_type"].strip()
    ):
        raise ArtifactStoreMetadataError(
            f"invalid artifact metadata content_type: {artifact_key}"
        )
    if "size_bytes" in metadata and (
        isinstance(metadata["size_bytes"], bool)
        or not isinstance(metadata["size_bytes"], int)
        or metadata["size_bytes"] < 0
    ):
        raise ArtifactStoreMetadataError(
            f"invalid artifact metadata size_bytes: {artifact_key}"
        )
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
        "integrity_valid": bool(bundle.integrity.get("valid")),
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



