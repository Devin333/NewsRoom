from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
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
        events = self.read_events(actual_run_dir, manifest=manifest, missing_ok=True)
        steps = summarize_steps(step_results, manifest=manifest)
        event_summary = summarize_events(events)
        return WorkflowRunInspection(
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
