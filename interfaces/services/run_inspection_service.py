from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.framework.serialization import to_json_safe
from core.framework.workflow.inspection import (
    WorkflowArtifactContentRecord,
    WorkflowReplayContentBundle,
    WorkflowRunInspectionError,
    WorkflowRunInspector,
    WorkflowRunListItem,
    redact_sensitive_values,
    resolve_run_dir,
)
from core.framework.workflow.manifest import normalize_legacy_run_manifest


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    workflow_id: str | None = None
    workflow_version: str | None = None
    profile: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    report_id: str | None = None
    artifact_dir: str | None = None
    quality_score: float | None = None
    step_count: int | None = None
    event_count: int | None = None
    manifest_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "profile": self.profile,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "report_id": self.report_id,
            "artifact_dir": self.artifact_dir,
            "quality_score": self.quality_score,
            "step_count": self.step_count,
            "event_count": self.event_count,
            "manifest_path": self.manifest_path,
        }


@dataclass(frozen=True)
class RunListResult:
    runs: list[RunSummary]

    def to_dict(self) -> dict[str, Any]:
        return {"run_count": len(self.runs), "runs": [run.to_dict() for run in self.runs]}


@dataclass(frozen=True)
class RunDetail:
    run_id: str
    manifest: dict[str, Any]
    manifest_path: str
    artifact_dir: str | None = None
    output_preview: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.manifest.get("workflow_id"),
            "workflow_version": self.manifest.get("workflow_version"),
            "profile": self.manifest.get("profile"),
            "status": self.manifest.get("status"),
            "started_at": self.manifest.get("started_at"),
            "finished_at": self.manifest.get("finished_at"),
            "report_id": _manifest_report_id(self.manifest),
            "artifact_dir": self.artifact_dir,
            "output_preview": to_json_safe(self.output_preview or {}),
            "error": to_json_safe(self.error),
            "metrics": to_json_safe(self.metrics or {}),
            "manifest": dict(self.manifest),
            "manifest_path": self.manifest_path,
        }


@dataclass(frozen=True)
class RunEventsResult:
    run_id: str
    events: list[dict[str, Any]]
    events_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event_count": len(self.events),
            "events": [dict(event) for event in self.events],
            "events_path": self.events_path,
        }


@dataclass(frozen=True)
class RunStepsResult:
    run_id: str
    steps: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "step_count": len(self.steps),
            "steps": [to_json_safe(step) for step in self.steps],
        }


@dataclass(frozen=True)
class RunReplayArtifact:
    artifact_key: str
    relative_path: str
    content_type: str
    size_bytes: int | None
    content: Any = None
    read_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "content": self.content,
            "read_error": self.read_error,
        }


@dataclass(frozen=True)
class RunReplayResult:
    run_id: str
    manifest: dict[str, Any]
    manifest_path: str
    events: list[dict[str, Any]]
    events_path: str | None
    artifacts: list[RunReplayArtifact]
    step_results: dict[str, Any]
    integrity: dict[str, Any]
    events_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "manifest": dict(self.manifest),
            "manifest_path": self.manifest_path,
            "event_count": len(self.events),
            "events": [dict(event) for event in self.events],
            "events_path": self.events_path,
            "events_error": self.events_error,
            "artifact_count": len(self.artifacts),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "step_result_count": len(self.step_results),
            "step_results": to_json_safe(self.step_results),
            "integrity": to_json_safe(self.integrity),
        }


@dataclass(frozen=True)
class RunDiagnosticsResult:
    run_id: str
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "diagnostics": to_json_safe(self.diagnostics),
        }


@dataclass(frozen=True)
class RunHealthResult:
    run_id: str
    health: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "health": to_json_safe(self.health),
        }


@dataclass(frozen=True)
class RunCatalogHealthResult:
    health: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"health": to_json_safe(self.health)}


@dataclass(frozen=True)
class RunComparisonResult:
    base_run_id: str
    target_run_id: str
    comparison: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_run_id": self.base_run_id,
            "target_run_id": self.target_run_id,
            "comparison": to_json_safe(self.comparison),
        }


class RunInspectionService:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)
        self._inspector = WorkflowRunInspector(self.artifact_root)

    def list_runs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        workflow_id: str | None = None,
        profile: str | None = None,
    ) -> RunListResult:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be greater than or equal to zero")
        catalog = self._inspector.list_runs(
            limit=limit,
            offset=offset,
            status=status,
            workflow_id=workflow_id,
            profile=profile,
            include_invalid=True,
        )
        return RunListResult(
            [
                _summary_from_run_item(item)
                for item in catalog.runs
                if not _is_unreadable_manifest(item)
            ]
        )

    def get_run(self, run_id: str) -> RunDetail:
        run_dir = _resolve_run_dir_for_service(self.artifact_root, run_id)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"run not found: {run_id}")
        manifest = normalize_legacy_run_manifest(self._inspector.load_manifest(run_dir))
        return RunDetail(
            run_id=str(manifest.get("run_id") or run_id),
            manifest=manifest,
            manifest_path=str(manifest_path),
            artifact_dir=str(run_dir),
            output_preview=_manifest_output_preview(manifest),
            error=_manifest_error(manifest),
            metrics=_manifest_metrics(manifest),
        )

    def get_run_events(
        self,
        run_id: str,
        *,
        event_type: str | None = None,
        step_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> RunEventsResult:
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be greater than or equal to zero")
        detail = self.get_run(run_id)
        artifacts = detail.manifest.get("artifacts") or {}
        if "events" not in artifacts:
            raise FileNotFoundError(f"events artifact not found for run: {run_id}")
        run_dir = _resolve_run_dir_for_service(self.artifact_root, run_id)
        try:
            event_records = self._inspector.read_events(run_dir, manifest=detail.manifest)
            events = [redact_sensitive_values(event.to_dict()) for event in event_records]
            events_path = self._inspector.artifact_path(
                run_dir,
                "events",
                manifest=detail.manifest,
            )
        except WorkflowRunInspectionError as exc:
            if "not found" in str(exc):
                raise FileNotFoundError(str(exc)) from exc
            raise ValueError(str(exc)) from exc
        events = [
            event
            for event in events
            if _event_matches(event, event_type=event_type, step_id=step_id)
        ]
        if offset:
            events = events[offset:]
        if limit is not None:
            events = events[:limit]
        return RunEventsResult(
            run_id=detail.run_id,
            events=events,
            events_path=str(events_path),
        )

    def get_run_steps(self, run_id: str) -> RunStepsResult:
        detail = self.get_run(run_id)
        manifest_steps = detail.manifest.get("steps") or {}
        if not isinstance(manifest_steps, dict):
            raise ValueError(f"invalid steps manifest for run: {run_id}")
        path = [str(step_id) for step_id in detail.manifest.get("path", [])]
        steps = [
            _step_view(step_id, payload, sequence=path.index(step_id) if step_id in path else None)
            for step_id, payload in sorted(manifest_steps.items())
        ]
        steps.sort(key=lambda step: (step["sequence"] is None, step["sequence"] or 0, step["step_id"]))
        return RunStepsResult(run_id=detail.run_id, steps=steps)

    def replay_run(self, run_id: str) -> RunReplayResult:
        run_dir = _resolve_run_dir_for_service(self.artifact_root, run_id)
        if not (run_dir / "manifest.json").exists():
            raise FileNotFoundError(f"run not found: {run_id}")
        bundle = self._inspector.build_replay_content_bundle(run_dir=run_dir, redact=True)
        return _replay_result_from_content_bundle(bundle)

    def get_run_diagnostics(self, run_id: str) -> RunDiagnosticsResult:
        run_dir = _existing_run_dir(self.artifact_root, run_id)
        try:
            diagnostics = self._inspector.build_diagnostics(run_dir=run_dir)
        except WorkflowRunInspectionError as exc:
            raise ValueError(str(exc)) from exc
        return RunDiagnosticsResult(
            run_id=str(diagnostics.inspection.run_id or run_id),
            diagnostics=diagnostics.to_dict(),
        )

    def get_run_health(self, run_id: str) -> RunHealthResult:
        run_dir = _existing_run_dir(self.artifact_root, run_id)
        try:
            health = self._inspector.build_health_report(run_dir=run_dir)
        except WorkflowRunInspectionError as exc:
            raise ValueError(str(exc)) from exc
        return RunHealthResult(
            run_id=str(health.run_id or run_id),
            health=health.to_dict(),
        )

    def get_catalog_health(self) -> RunCatalogHealthResult:
        return RunCatalogHealthResult(self._inspector.catalog_health().to_dict())

    def compare_runs(self, base_run_id: str, target_run_id: str) -> RunComparisonResult:
        _existing_run_dir(self.artifact_root, base_run_id)
        _existing_run_dir(self.artifact_root, target_run_id)
        try:
            comparison = self._inspector.compare_runs(base_run_id, target_run_id)
        except WorkflowRunInspectionError as exc:
            raise ValueError(str(exc)) from exc
        return RunComparisonResult(
            base_run_id=base_run_id,
            target_run_id=target_run_id,
            comparison=comparison.to_dict(),
        )


def _summary_from_run_item(item: WorkflowRunListItem) -> RunSummary:
    return RunSummary(
        run_id=item.run_id,
        status=str(item.status or "unknown"),
        workflow_id=item.workflow_id,
        workflow_version=item.workflow_version,
        profile=item.profile,
        started_at=item.started_at,
        finished_at=item.finished_at,
        report_id=None,
        artifact_dir=item.run_dir,
        step_count=item.step_count,
        event_count=item.event_count,
        manifest_path=item.manifest_path,
    )


def _is_unreadable_manifest(item: WorkflowRunListItem) -> bool:
    return bool(item.invalid_reason and "invalid JSON artifact" in item.invalid_reason)


def _replay_result_from_content_bundle(bundle: WorkflowReplayContentBundle) -> RunReplayResult:
    return RunReplayResult(
        run_id=str(bundle.run_id or "unknown"),
        manifest=dict(bundle.manifest),
        manifest_path=bundle.manifest_path,
        events=[dict(event) for event in bundle.events],
        events_path=bundle.events_path,
        events_error=bundle.events_error,
        artifacts=[
            _replay_artifact_from_content_record(artifact)
            for artifact in bundle.artifacts
        ],
        step_results=dict(bundle.step_results),
        integrity=dict(bundle.integrity),
    )


def _replay_artifact_from_content_record(
    artifact: WorkflowArtifactContentRecord,
) -> RunReplayArtifact:
    return RunReplayArtifact(
        artifact_key=artifact.artifact_key,
        relative_path=artifact.relative_path,
        content_type=artifact.content_type,
        size_bytes=artifact.size_bytes,
        content=artifact.content,
        read_error=artifact.read_error,
    )


def _resolve_run_dir_for_service(artifact_root: Path, run_id: str) -> Path:
    try:
        return resolve_run_dir(artifact_root, run_id)
    except WorkflowRunInspectionError as exc:
        raise ValueError(f"invalid run id: {run_id}") from exc


def _existing_run_dir(artifact_root: Path, run_id: str) -> Path:
    run_dir = _resolve_run_dir_for_service(artifact_root, run_id)
    if not (run_dir / "manifest.json").exists():
        raise FileNotFoundError(f"run not found: {run_id}")
    return run_dir


def _manifest_report_id(manifest: dict[str, Any]) -> str | None:
    report_id = manifest.get("report_id")
    if report_id is not None:
        return str(report_id)
    output = manifest.get("output")
    if isinstance(output, dict) and output.get("report_id") is not None:
        return str(output["report_id"])
    return None


def _manifest_output_preview(manifest: dict[str, Any]) -> dict[str, Any]:
    output = manifest.get("output")
    preview: dict[str, Any] = {}
    if isinstance(output, dict):
        for key, value in output.items():
            if len(preview) >= 12:
                break
            preview[str(key)] = _preview_value(value)
        quality_result = output.get("quality_result") if isinstance(output.get("quality_result"), dict) else {}
        citation_check = output.get("citation_check_result") if isinstance(output.get("citation_check_result"), dict) else {}
        support_matrix = output.get("support_matrix") if isinstance(output.get("support_matrix"), dict) else {}
        quality_lineage = _quality_lineage_preview(output)
        if quality_result or citation_check or support_matrix or quality_lineage:
            preview["quality_trace"] = {
                "decision": quality_result.get("decision"),
                "route": quality_result.get("route") or output.get("quality_route"),
                "citation_failure_categories": quality_result.get("metadata", {}).get(
                    "citation_failure_categories", []
                ),
                "unsupported_claims": citation_check.get("unsupported_claims", []),
                "rejected_claim_usage": citation_check.get("rejected_claim_usage", []),
                "unsupported_sections": support_matrix.get("unsupported_sections", []),
                "quality_lineage": quality_lineage,
            }
        llm_route_manifest = output.get("llm_route_manifest") if isinstance(output.get("llm_route_manifest"), dict) else {}
        llm_router_events = output.get("llm_router_events") if isinstance(output.get("llm_router_events"), list) else []
        if llm_route_manifest or llm_router_events:
            preview["llm_trace"] = {
                "selected_deployment_id": llm_route_manifest.get("selected_deployment_id"),
                "fallback_used": llm_route_manifest.get("fallback_used"),
                "fallback_count": llm_route_manifest.get("fallback_count"),
                "provider_error_count": (llm_route_manifest.get("metrics") or {}).get("provider_error_count"),
                "cooldown_skip_count": (llm_route_manifest.get("metrics") or {}).get("cooldown_skip_count"),
                "router_event_count": len(llm_router_events),
                "budget_check": llm_route_manifest.get("budget_check"),
                "global_budget_check": llm_route_manifest.get("global_budget_check"),
            }
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    if artifacts and "partial_artifacts" not in preview:
        preview["partial_artifacts"] = {
            "artifact_keys": sorted(str(key) for key in artifacts)[:20],
            "required_artifact_keys": [
                key for key in ("request", "events", "step_results", "manifest") if key in artifacts
            ],
        }
    return preview


def _quality_lineage_preview(output: dict[str, Any]) -> dict[str, Any]:
    evidence_bundle = output.get("evidence_bundle") if isinstance(output.get("evidence_bundle"), dict) else {}
    candidate_claims = output.get("candidate_claims") if isinstance(output.get("candidate_claims"), list) else []
    verified_findings = output.get("verified_findings") if isinstance(output.get("verified_findings"), dict) else {}
    report = output.get("final_report") if isinstance(output.get("final_report"), dict) else output.get("blocked_report") if isinstance(output.get("blocked_report"), dict) else {}
    supporting_evidence_ids = sorted(
        {
            str(evidence_id)
            for claim in candidate_claims
            if isinstance(claim, dict)
            for evidence_id in claim.get("source_evidence_ids", [])
            if evidence_id
        }
    )
    return {
        "report_id": str(output.get("report_id") or report.get("report_id") or output.get("run_id") or ""),
        "evidence_bundle_id": evidence_bundle.get("bundle_id"),
        "candidate_claim_count": len(candidate_claims),
        "accepted_claim_count": len(verified_findings.get("accepted_claims", [])),
        "rejected_claim_count": len(verified_findings.get("rejected_claims", [])),
        "uncertain_claim_count": len(verified_findings.get("uncertain_claims", [])),
        "supporting_evidence_ids": supporting_evidence_ids,
    }


def _manifest_error(manifest: dict[str, Any]) -> dict[str, Any] | None:
    error = manifest.get("error")
    if isinstance(error, dict):
        return error
    if error is None:
        return None
    return {"message": str(error)}


def _manifest_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    metrics = manifest.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    return {
        key: value
        for key, value in {
            "step_count": manifest.get("step_count"),
            "event_count": manifest.get("event_count"),
            "checkpoint_count": manifest.get("checkpoint_count"),
            "operation_count": manifest.get("operation_count"),
        }.items()
        if value is not None
    }


def _event_matches(
    event: dict[str, Any],
    *,
    event_type: str | None,
    step_id: str | None,
) -> bool:
    if event_type is not None and event.get("event_type") != event_type:
        return False
    if step_id is None:
        return True
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return event.get("step_id") == step_id or payload.get("step_id") == step_id


def _step_view(
    step_id: Any,
    payload: Any,
    *,
    sequence: int | None,
) -> dict[str, Any]:
    data = dict(payload) if isinstance(payload, dict) else {"value": payload}
    outputs = data.get("outputs") if isinstance(data.get("outputs"), dict) else {}
    error = data.get("error") if isinstance(data.get("error"), dict) else None
    return {
        "step_id": str(step_id),
        "sequence": sequence,
        "status": str(data.get("status") or "unknown"),
        "started_at": data.get("started_at"),
        "finished_at": data.get("finished_at"),
        "output_keys": sorted(str(key) for key in outputs),
        "error": to_json_safe(error),
        "metrics": to_json_safe(data.get("metrics") if isinstance(data.get("metrics"), dict) else {}),
        "artifact_refs": to_json_safe(
            data.get("artifact_refs") if isinstance(data.get("artifact_refs"), list) else []
        ),
        "raw": to_json_safe(data),
    }


def _preview_value(value: Any) -> Any:
    safe = to_json_safe(value)
    if isinstance(safe, dict):
        return {"type": "object", "keys": sorted(str(key) for key in safe)[:12]}
    if isinstance(safe, list):
        return {"type": "array", "count": len(safe)}
    text = str(safe)
    return text[:240] + ("..." if len(text) > 240 else "")
