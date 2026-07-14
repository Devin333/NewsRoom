from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from framework.artifacts import (
    ArtifactManager,
    ArtifactPathError,
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.artifacts.models import ArtifactRef
from framework.events import EventBus
from framework.llm import GlobalBudgetPolicy, GlobalBudgetTracker
from framework.shared.hashing import hash_text
from framework.shared.time import ensure_utc
from framework.specs import WorkflowSpec
from framework.workflow.runtime.executor import WorkflowExecutor
from framework.workflow.runtime.run_result import RunResult
from framework.workflow.runtime.artifact_publishers import WorkflowArtifactPublisher
from framework.workflow.inspection import (
    WorkflowReplayBundle,
    WorkflowReplayContentBundle,
    WorkflowRunCatalog,
    WorkflowRunCatalogHealth,
    WorkflowRunComparison,
    WorkflowRunDiagnostics,
    WorkflowRunHealthReport,
    WorkflowRunInspection,
    WorkflowRunListItem,
    WorkflowRunInspector,
)
from framework.workflow.runtime.manifest import manifest_schema_version
from framework.workflow.operations import (
    LocalWorkflowRunOperationService,
    OperationActor,
    OperationResult,
    WorkflowRunOperationService,
    checkpoint_from_run_artifacts,
)
from framework.workflow.runtime.result import WorkflowResult
from framework.workflow.routing import RoutingEngine
from framework.workflow.checkpoint.resume import WorkflowResumePlan
from framework.workflow.checkpoint.model import WorkflowCheckpoint
from framework.workflow.runners import build_default_step_runner_registry
from framework.workflow.runners.function import FunctionStepRegistry
from framework.workflow.runners.registry import StepRunnerRegistry


ArtifactRefExtractor = Callable[..., list[Any]]
LineageExtractor = Callable[..., list[Any]]


class ArtifactIndexStore(Protocol):
    def index_artifact(self, ref: ArtifactRef) -> Any: ...


class EventStore(Protocol):
    def append_event(self, event: Any) -> Any: ...


class LineageStore(Protocol):
    def record_many(self, refs: list[Any]) -> Any: ...


class PayloadRedactor(Protocol):
    def redact(self, value: Any, *, run_id: str, artifact_id: str) -> Any: ...


class WorkflowRunner:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        function_registry: FunctionStepRegistry | None = None,
        step_runner_registry: StepRunnerRegistry | None = None,
        tool_registry: Any | None = None,
        memory_runtime: Any | None = None,
        agent_runner: Any | None = None,
        agent_registry: dict[str, Any] | None = None,
        workflow_registry: dict[str, WorkflowSpec] | None = None,
        approval_store: Any | None = None,
        secret_provider: Any | None = None,
        max_parallel_workers: int = 4,
        max_tool_batch_workers: int = 4,
        artifact_index_store: Any | None = None,
        event_store: Any | None = None,
        lineage_store: Any | None = None,
        checkpoint_store: Any | None = None,
        event_bus: EventBus | None = None,
        redactor: PayloadRedactor | None = None,
        global_budget_policy: GlobalBudgetPolicy | None = None,
        global_budget_tracker: GlobalBudgetTracker | None = None,
        artifact_publishers: Sequence[WorkflowArtifactPublisher] | None = None,
        artifact_ref_extractors: Sequence[ArtifactRefExtractor] | None = None,
        lineage_extractors: Sequence[LineageExtractor] | None = None,
        operation_service: WorkflowRunOperationService | None = None,
        routing_engine: RoutingEngine | None = None,
    ) -> None:
        self._artifact_root = Path(artifact_root)
        self._artifact_manager = ArtifactManager(self._artifact_root)
        if step_runner_registry is None:
            if function_registry is None:
                raise ValueError("function_registry is required without step_runner_registry")
            step_runner_registry = build_default_step_runner_registry(
                function_registry,
                tool_registry=tool_registry,
                memory_runtime=memory_runtime,
                agent_runner=agent_runner,
                agent_registry=agent_registry,
                workflow_registry=workflow_registry,
                artifact_manager=self._artifact_manager,
                approval_store=approval_store,
                secret_provider=secret_provider,
                max_parallel_workers=max_parallel_workers,
                max_tool_batch_workers=max_tool_batch_workers,
            )
        self._step_runner_registry = step_runner_registry
        self._indexer = WorkflowRunIndexer(
            artifact_index_store=artifact_index_store
            or artifact_index_store_from_env(artifact_root=self._artifact_root),
            event_store=event_store or event_store_from_env(artifact_root=self._artifact_root),
            lineage_store=lineage_store or lineage_store_from_env(artifact_root=self._artifact_root),
            redactor=redactor or WorkflowEventRedactor(),
            artifact_ref_extractors=artifact_ref_extractors,
            lineage_extractors=lineage_extractors,
        )
        self._checkpoint_store = checkpoint_store
        self._event_bus = event_bus
        self._run_inspector = WorkflowRunInspector(self._artifact_root)
        self._global_budget_policy = global_budget_policy
        self._global_budget_tracker = global_budget_tracker
        self._artifact_publishers = list(artifact_publishers or [])
        self._routing_engine = routing_engine
        self._operation_service = operation_service or LocalWorkflowRunOperationService(
            artifact_root=self._artifact_root,
            runner=self,
            checkpoint_store=self._checkpoint_store,
        )

    def run(
        self,
        workflow: WorkflowSpec,
        request: dict[str, Any],
        *,
        profile: str,
        run_id: str | None = None,
    ) -> RunResult:
        executor = WorkflowExecutor(
            function_step_runner=None,
            step_runner_registry=self._step_runner_registry,
            artifact_manager=self._artifact_manager,
            checkpoint_store=self._checkpoint_store,
            event_bus=self._event_bus,
            global_budget_tracker=self._budget_tracker_for_run(),
            artifact_publishers=self._artifact_publishers,
            routing_engine=self._routing_engine,
        )
        result = executor.execute(workflow, request, profile=profile, run_id=run_id)
        self._persist_storage_indexes(result)
        return RunResult.from_workflow_result(result)

    def execute_resume_plan(
        self,
        workflow: WorkflowSpec,
        plan: WorkflowResumePlan,
        *,
        profile: str,
    ) -> RunResult:
        executor = WorkflowExecutor(
            function_step_runner=None,
            step_runner_registry=self._step_runner_registry,
            artifact_manager=self._artifact_manager,
            checkpoint_store=self._checkpoint_store,
            event_bus=self._event_bus,
            global_budget_tracker=self._budget_tracker_for_run(),
            artifact_publishers=self._artifact_publishers,
            routing_engine=self._routing_engine,
        )
        request = plan.initial_buffer_values.get("request")
        if not isinstance(request, dict):
            request = {}
        result = executor.execute(
            workflow,
            request,
            profile=profile,
            run_id=plan.run_id,
            _initial_buffer_values=plan.initial_buffer_values,
            _current_step_ids=plan.current_step_ids,
            _initial_path=plan.initial_path,
            _initial_step_results=plan.initial_step_results,
            _resumed_checkpoint_id=plan.resumed_from_checkpoint_id,
            _resume_metadata=plan.resume_metadata,
        )
        self._persist_storage_indexes(result)
        return RunResult.from_workflow_result(result)

    def resume_from_checkpoint(
        self,
        workflow: WorkflowSpec,
        checkpoint: WorkflowCheckpoint,
        *,
        profile: str,
        run_id: str | None = None,
        buffer_updates: dict[str, Any] | None = None,
        resume_metadata: dict[str, Any] | None = None,
        target_step_id: str | None = None,
    ) -> RunResult:
        executor = WorkflowExecutor(
            function_step_runner=None,
            step_runner_registry=self._step_runner_registry,
            artifact_manager=self._artifact_manager,
            checkpoint_store=self._checkpoint_store,
            event_bus=self._event_bus,
            global_budget_tracker=self._budget_tracker_for_run(),
            artifact_publishers=self._artifact_publishers,
            routing_engine=self._routing_engine,
        )
        result = executor.resume_from_checkpoint(
            workflow,
            checkpoint,
            profile=profile,
            run_id=run_id,
            buffer_updates=buffer_updates,
            resume_metadata=resume_metadata,
            target_step_id=target_step_id,
        )
        self._persist_storage_indexes(result)
        return RunResult.from_workflow_result(result)

    def resume_from_approval_context(
        self,
        workflow: WorkflowSpec,
        approval_context: Any,
        *,
        profile: str,
        run_id: str | None = None,
    ) -> RunResult:
        if self._checkpoint_store is None:
            raise ValueError("checkpoint_store is required to resume from approval context")
        context = _approval_context_payload(approval_context)
        approval_run_id = _approval_context_run_id(context)
        if not approval_run_id:
            raise ValueError("approval resume context does not include an original run id")
        checkpoint = self._checkpoint_store.get_latest_checkpoint(approval_run_id)
        if checkpoint is None:
            checkpoint = checkpoint_from_run_artifacts(self._artifact_root, run_id=approval_run_id)
        if checkpoint is None:
            raise ValueError(f"checkpoint not found for approval run id: {approval_run_id}")
        resume_metadata = dict(context.get("resume_metadata") or {})
        return self.resume_from_checkpoint(
            workflow,
            checkpoint,
            profile=profile,
            run_id=run_id,
            buffer_updates=dict(context.get("buffer_updates") or {}),
            resume_metadata=resume_metadata,
            target_step_id=_approval_context_target_step_id(resume_metadata),
        )

    def cancel_run(
        self,
        run_id: str,
        reason: str,
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        return self._operation_service.cancel_run(run_id, reason, actor=actor)

    def rerun_from_step(
        self,
        run_id: str,
        step_id: str,
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        return self._operation_service.rerun_from_step(run_id, step_id, actor=actor)

    def resume_with_patch(
        self,
        run_id: str,
        patch: dict[str, Any],
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        return self._operation_service.resume_with_patch(run_id, patch, actor=actor)

    def skip_step(
        self,
        run_id: str,
        step_id: str,
        reason: str,
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        return self._operation_service.skip_step(run_id, step_id, reason, actor=actor)

    def mark_blocked_resolved(
        self,
        run_id: str,
        resolution: dict[str, Any],
        *,
        actor: OperationActor | None = None,
    ) -> OperationResult:
        return self._operation_service.mark_blocked_resolved(
            run_id,
            resolution,
            actor=actor,
        )

    def _budget_tracker_for_run(self) -> GlobalBudgetTracker | None:
        if self._global_budget_tracker is not None:
            return self._global_budget_tracker
        if self._global_budget_policy is not None:
            return GlobalBudgetTracker(self._global_budget_policy)
        return None

    def _persist_storage_indexes(self, result: WorkflowResult) -> None:
        self._indexer.index(result)

    def inspect_run(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunInspection:
        return self._run_inspector.inspect_run(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )

    def build_replay_bundle(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowReplayBundle:
        return self._run_inspector.build_replay_bundle(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )

    def build_replay_content_bundle(
        self,
        run_id: str,
        *,
        redact: bool = True,
        expand_artifact_indexes: bool = True,
        artifact_index_keys: list[str] | None = None,
        expand_source_artifacts: bool = True,
        max_artifact_bytes: int | None = None,
    ) -> WorkflowReplayContentBundle:
        return self._run_inspector.build_replay_content_bundle(
            run_id,
            redact=redact,
            expand_artifact_indexes=expand_artifact_indexes,
            artifact_index_keys=artifact_index_keys,
            expand_source_artifacts=expand_source_artifacts,
            max_artifact_bytes=max_artifact_bytes,
        )

    def inspect_run_diagnostics(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunDiagnostics:
        return self._run_inspector.build_diagnostics(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )

    def inspect_run_health(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunHealthReport:
        return self._run_inspector.build_health_report(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )

    def list_runs(
        self,
        *,
        limit: int | None = 50,
        offset: int = 0,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        status: str | None = None,
        profile: str | None = None,
        include_invalid: bool = False,
    ) -> WorkflowRunCatalog:
        return self._run_inspector.list_runs(
            limit=limit,
            offset=offset,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            status=status,
            profile=profile,
            include_invalid=include_invalid,
        )

    def latest_run(
        self,
        *,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        status: str | None = None,
        profile: str | None = None,
        include_invalid: bool = False,
    ) -> WorkflowRunListItem | None:
        return self._run_inspector.latest_run(
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            status=status,
            profile=profile,
            include_invalid=include_invalid,
        )

    def catalog_health(
        self,
        *,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        profile: str | None = None,
        include_invalid: bool = True,
    ) -> WorkflowRunCatalogHealth:
        return self._run_inspector.catalog_health(
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            profile=profile,
            include_invalid=include_invalid,
        )

    def compare_runs(
        self,
        base_run_id: str,
        target_run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunComparison:
        return self._run_inspector.compare_runs(
            base_run_id,
            target_run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )


class WorkflowRunIndexer:
    def __init__(
        self,
        *,
        artifact_index_store: ArtifactIndexStore,
        event_store: EventStore,
        lineage_store: LineageStore,
        redactor: PayloadRedactor,
        artifact_ref_extractors: Sequence[ArtifactRefExtractor] | None = None,
        lineage_extractors: Sequence[LineageExtractor] | None = None,
    ) -> None:
        self._artifact_index_store = artifact_index_store
        self._event_store = event_store
        self._lineage_store = lineage_store
        self._redactor = redactor
        self._artifact_ref_extractors = list(artifact_ref_extractors or [])
        self._lineage_extractors = list(lineage_extractors or [])

    def index(self, result: WorkflowResult) -> None:
        self._index_artifacts(result)
        self._index_events(result)
        self._index_lineage(result)

    def _index_artifacts(self, result: WorkflowResult) -> None:
        if result.artifact_dir is None:
            return
        run_dir = Path(result.artifact_dir)
        created_at = _parse_datetime(result.manifest.get("finished_at")) or datetime.now(UTC)
        for artifact_key, relative_path in sorted((result.manifest.get("artifacts") or {}).items()):
            if not isinstance(relative_path, str):
                continue
            normalized_relative_path = validate_relative_artifact_path(
                relative_path,
                field=f"manifest_artifact_path[{artifact_key}]",
            )
            path = _artifact_path(run_dir, relative_path)
            data = path.read_bytes()
            self._artifact_index_store.index_artifact(
                ArtifactRef(
                    artifact_id=_artifact_id_from_key(artifact_key),
                    run_id=result.run_id,
                    artifact_type=str(artifact_key),
                    path=normalized_relative_path,
                    content_type=_content_type(path),
                    size_bytes=len(data),
                    checksum=sha256(data).hexdigest(),
                    redacted=True,
                    created_at=created_at,
                    metadata={
                        "artifact_key": str(artifact_key),
                        "workflow_id": result.workflow_id,
                        "workflow_version": result.workflow_version,
                        "manifest_schema_version": manifest_schema_version(result.manifest),
                    },
                )
            )
        for extractor in self._artifact_ref_extractors:
            for artifact_ref in extractor(
                run_dir=run_dir,
                manifest=result.manifest,
                output=result.output,
            ):
                self._artifact_index_store.index_artifact(artifact_ref)

    def _index_events(self, result: WorkflowResult) -> None:
        if result.events_path is None or result.artifact_dir is None:
            return
        artifacts = result.manifest.get("artifacts") or {}
        relative_path = artifacts.get("events") if isinstance(artifacts, dict) else None
        if not isinstance(relative_path, str):
            return
        try:
            events_path = _artifact_path(Path(result.artifact_dir), relative_path)
        except FileNotFoundError:
            return
        with events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                event = WorkflowEventRecord.from_dict(json.loads(stripped))
                payload_step_id = event.payload.get("step_id")
                redaction = self._redactor.redact(
                    event.payload,
                    run_id=result.run_id,
                    artifact_id="events",
                )
                metadata = {
                    **event.metadata,
                    "workflow_version": result.workflow_version,
                }
                if redaction.redacted:
                    metadata["redaction_report"] = redaction.report.to_dict()
                event = replace(
                    event,
                    workflow_id=event.workflow_id or result.workflow_id,
                    step_id=event.step_id or (str(payload_step_id) if payload_step_id else None),
                    payload=redaction.value,
                    redacted=True,
                    metadata=metadata,
                )
                self._event_store.append_event(event)

    def _index_lineage(self, result: WorkflowResult) -> None:
        for extractor in self._lineage_extractors:
            refs = extractor(
                output=result.output,
                run_id=result.run_id,
                workflow_id=result.workflow_id,
            )
            if refs:
                self._lineage_store.record_many(refs)


class LocalJsonWorkflowArtifactIndexStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def index_artifact(self, ref: ArtifactRef) -> Path:
        validated_run_id = _validate_id(ref.run_id, "run_id")
        validated_artifact_id = _require_artifact_id(ref.artifact_id)
        if ref.step_id is not None:
            _validate_id(ref.step_id, "step_id")
        _validate_relative_path(ref.path)
        path = resolve_artifact_descendant(
            self.root,
            hash_text(validated_run_id)[:12],
            _artifact_record_file_name(validated_artifact_id),
            field="artifact_index_path",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(ref.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path


@dataclass(frozen=True)
class WorkflowEventRecord:
    event_id: str
    run_id: str
    event_type: str
    timestamp: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    workflow_id: str | None = None
    step_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    tool_call_id: str | None = None
    request_id: str | None = None
    severity: str = "info"
    trace_id: str | None = None
    redacted: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def occurred_at(self) -> datetime:
        return self.timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "tool_call_id": self.tool_call_id,
            "request_id": self.request_id,
            "payload": self.payload,
            "severity": self.severity,
            "trace_id": self.trace_id,
            "redacted": self.redacted,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkflowEventRecord:
        timestamp = payload.get("timestamp", payload.get("occurred_at"))
        if timestamp is None:
            raise KeyError("timestamp")
        return cls(
            event_id=str(payload["event_id"]),
            run_id=str(payload["run_id"]),
            event_type=str(payload["event_type"]),
            timestamp=_parse_datetime(timestamp) or datetime.now(UTC),
            workflow_id=_optional_str(payload.get("workflow_id")),
            step_id=_optional_str(payload.get("step_id")),
            task_id=_optional_str(payload.get("task_id")),
            agent_id=_optional_str(payload.get("agent_id")),
            tool_call_id=_optional_str(payload.get("tool_call_id")),
            request_id=_optional_str(payload.get("request_id")),
            payload=dict(payload.get("payload") or {}),
            severity=str(payload.get("severity") or "info"),
            trace_id=_optional_str(payload.get("trace_id")),
            redacted=bool(payload.get("redacted", True)),
            metadata=dict(payload.get("metadata") or {}),
        )


class LocalJsonWorkflowEventStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def append_event(self, event: WorkflowEventRecord) -> int:
        validated_run_id = _validate_id(event.run_id, "run_id")
        path = resolve_artifact_descendant(
            self.root,
            f"{validated_run_id}.jsonl",
            field="event_store_path",
        )
        offset = _line_count(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return offset


class LocalJsonWorkflowLineageStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def record_many(self, refs: list[Any]) -> list[Path]:
        return [self._record(ref) for ref in refs]

    def _record(self, ref: Any) -> Path:
        run_id = str(getattr(ref, "run_id"))
        validated_run_id = _validate_id(run_id, "run_id")
        path = resolve_artifact_descendant(
            self.root,
            f"{validated_run_id}.jsonl",
            field="lineage_store_path",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        to_dict = getattr(ref, "to_dict", None)
        payload = to_dict() if callable(to_dict) else dict(ref)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
            handle.write("\n")
        return path


def artifact_index_store_from_env(*, artifact_root: str | Path) -> ArtifactIndexStore:
    return LocalJsonWorkflowArtifactIndexStore(
        resolve_artifact_descendant(
            artifact_root,
            "_records/artifact_index",
            field="artifact_index_root",
        )
    )


def event_store_from_env(*, artifact_root: str | Path) -> EventStore:
    return LocalJsonWorkflowEventStore(
        resolve_artifact_descendant(
            artifact_root,
            "_records/events",
            field="event_store_root",
        )
    )


def lineage_store_from_env(*, artifact_root: str | Path) -> LineageStore:
    return LocalJsonWorkflowLineageStore(
        resolve_artifact_descendant(
            artifact_root,
            "_records/lineage",
            field="lineage_store_root",
        )
    )


class WorkflowEventRedactor:
    def redact(self, value: Any, *, run_id: str, artifact_id: str) -> RedactionResult:
        fields: set[str] = set()
        rules: set[str] = set()
        redacted_value = self._redact(value, path="$", fields=fields, rules=rules)
        return RedactionResult(
            value=redacted_value,
            report=RedactionReport(
                run_id=run_id,
                artifact_id=artifact_id,
                redacted_fields=sorted(fields),
                redaction_rules_applied=sorted(rules),
            ),
        )

    def _redact(self, value: Any, *, path: str, fields: set[str], rules: set[str]) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                child_path = f"{path}.{key}"
                if _is_sensitive_key(key):
                    redacted[str(key)] = "[redacted]"
                    fields.add(child_path)
                    rules.add("sensitive_key")
                else:
                    redacted[str(key)] = self._redact(item, path=child_path, fields=fields, rules=rules)
            return redacted
        if isinstance(value, list):
            return [
                self._redact(item, path=f"{path}[{index}]", fields=fields, rules=rules)
                for index, item in enumerate(value)
            ]
        if isinstance(value, str):
            return _redact_string(value, path=path, fields=fields, rules=rules)
        return value


class RedactionReport:
    def __init__(
        self,
        *,
        run_id: str,
        artifact_id: str,
        redacted_fields: list[str],
        redaction_rules_applied: list[str],
    ) -> None:
        self.run_id = run_id
        self.artifact_id = artifact_id
        self.redacted_fields = redacted_fields
        self.redaction_rules_applied = redaction_rules_applied
        self.created_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "redacted_fields": list(self.redacted_fields),
            "redaction_rules_applied": list(self.redaction_rules_applied),
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
        }


class RedactionResult:
    def __init__(self, *, value: Any, report: RedactionReport) -> None:
        self.value = value
        self.report = report

    @property
    def redacted(self) -> bool:
        return bool(self.report.redacted_fields)


def _artifact_path(run_dir: Path, relative_path: str) -> Path:
    normalized_relative_path = _validate_relative_path(relative_path)
    path = resolve_artifact_descendant(
        run_dir,
        normalized_relative_path,
        field="artifact_path",
    )
    if not path.exists():
        raise FileNotFoundError(f"artifact file not found: {relative_path}")
    return path


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".jsonl":
        return "application/x-ndjson"
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".txt":
        return "text/plain"
    return "application/octet-stream"


def _artifact_id_from_key(key: str) -> str:
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(key)).strip("._") or "artifact"
    if safe_key == key:
        return safe_key
    digest = sha256(str(key).encode("utf-8")).hexdigest()[:8]
    return f"{safe_key}-{digest}"


def _approval_context_payload(approval_context: Any) -> dict[str, Any]:
    if isinstance(approval_context, dict):
        return dict(approval_context)
    to_dict = getattr(approval_context, "to_dict", None)
    if callable(to_dict):
        raw_payload: Any = to_dict()
        if isinstance(raw_payload, dict):
            return dict(raw_payload)
    payload: dict[str, Any] = {}
    for key in ("buffer_updates", "resume_metadata", "decision_payload", "approval_id"):
        if hasattr(approval_context, key):
            payload[key] = getattr(approval_context, key)
    approval = getattr(approval_context, "approval", None)
    if approval is not None:
        payload["approval"] = approval.to_dict() if hasattr(approval, "to_dict") else approval
    return payload


def _approval_context_run_id(context: dict[str, Any]) -> str | None:
    for value in (
        _nested_value(context.get("resume_metadata"), "approval_run_id"),
        _nested_value(context.get("decision_payload"), "run_id"),
        _nested_value(context.get("approval"), "run_id"),
    ):
        if value:
            return str(value)
    return None


def _approval_context_target_step_id(resume_metadata: dict[str, Any]) -> str | None:
    target_step_id = _nested_value(resume_metadata, "resume_next_step_id")
    if not target_step_id:
        return None
    target_step_id = str(target_step_id)
    return target_step_id


def _nested_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    if hasattr(value, key):
        return getattr(value, key)
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _validate_id(value: str, label: str) -> str:
    try:
        return validate_artifact_path_segment(value, field=label)
    except ArtifactPathError as exc:
        raise ArtifactPathError(f"invalid {label}: {value}") from exc


def _validate_relative_path(value: str) -> str:
    try:
        return validate_relative_artifact_path(value, field="artifact_path")
    except ArtifactPathError as exc:
        raise ArtifactPathError(f"invalid artifact path: {value}") from exc


def _artifact_record_file_name(artifact_id: str) -> str:
    return f"a-{hash_text(artifact_id)[:16]}.json"


def _require_artifact_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("artifact_id is required")
    return value


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).replace("-", "_").casefold()
    return any(
        part in normalized
        for part in (
            "authorization",
            "cookie",
            "api_key",
            "apikey",
            "access_token",
            "refresh_token",
            "token",
            "secret",
            "password",
            "signature",
            "database_url",
            "dsn",
        )
    )


def _redact_string(value: str, *, path: str, fields: set[str], rules: set[str]) -> str:
    redacted = value
    redacted, bearer_count = re.subn(r"(?i)(bearer\s+)[^\s,;]+", r"\1[redacted]", redacted)
    if bearer_count:
        fields.add(path)
        rules.add("bearer_token")
    redacted, secret_count = re.subn(r"(?i)sk-[A-Za-z0-9_-]{8,}", "[redacted]", redacted)
    if secret_count:
        fields.add(path)
        rules.add("secret_like_string")
    return redacted
