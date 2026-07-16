from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
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
from framework.events.errors import EventContractError
from framework.events.ports import EventReaderPort, EventRuntimePort
from framework.events.runtime.models import (
    MAX_PAGE_LIMIT,
    EventPage,
    StreamReadRequest,
    StreamSequenceCursor,
)
from framework.events.schema import EventSchemaCatalog, default_event_schema_catalog
from framework.llm import GlobalBudgetPolicy, GlobalBudgetTracker
from framework.shared.hashing import hash_text
from framework.specs import WorkflowSpec
from framework.workflow.runtime.executor import WorkflowExecutor
from framework.workflow.runtime.run_result import RunResult
from framework.workflow.runtime.artifact_publishers import WorkflowArtifactPublisher
from framework.workflow.inspection import (
    WorkflowReplayBundle,
    WorkflowReplayContentBundle,
    WorkflowEventRecord,
    WorkflowRunCatalog,
    WorkflowRunCatalogHealth,
    WorkflowRunComparison,
    WorkflowRunDiagnostics,
    WorkflowRunHealthReport,
    WorkflowRunInspection,
    WorkflowRunListItem,
    WorkflowRunInspector,
)
from framework.workflow.runtime.event_projection import project_workflow_event
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
from framework.workflow.checkpoint.store import StoredWorkflowCheckpoint
from framework.workflow.runners import build_default_step_runner_registry
from framework.workflow.runners.function import FunctionStepRegistry
from framework.workflow.runners.registry import StepRunnerRegistry


ArtifactRefExtractor = Callable[..., list[Any]]
LineageExtractor = Callable[..., list[Any]]


class ArtifactIndexStore(Protocol):
    def index_artifact(self, ref: ArtifactRef) -> Any: ...


class LineageStore(Protocol):
    def record_many(self, refs: list[Any]) -> Any: ...


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
        event_runtime: EventRuntimePort | None = None,
        event_reader: EventReaderPort | None = None,
        event_schema_catalog: EventSchemaCatalog | None = None,
        lineage_store: Any | None = None,
        checkpoint_store: Any | None = None,
        event_bus: EventBus | None = None,
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
        if event_runtime is None:
            raise ValueError("event_runtime is required for durable workflow execution")
        if event_reader is None:
            raise ValueError("event_reader is required for durable workflow execution")
        self._event_runtime = event_runtime
        self._event_reader = event_reader
        self._event_schema_catalog = (
            event_schema_catalog or default_event_schema_catalog()
        )
        self._indexer = WorkflowRunIndexer(
            artifact_index_store=artifact_index_store
            or artifact_index_store_from_env(artifact_root=self._artifact_root),
            lineage_store=lineage_store or lineage_store_from_env(artifact_root=self._artifact_root),
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
            event_runtime=self._event_runtime,
            event_reader=self._event_reader,
            event_schema_catalog=self._event_schema_catalog,
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
            event_runtime=self._event_runtime,
            event_reader=self._event_reader,
            event_schema_catalog=self._event_schema_catalog,
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
            event_runtime=self._event_runtime,
            event_reader=self._event_reader,
            event_schema_catalog=self._event_schema_catalog,
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
        checkpoint: StoredWorkflowCheckpoint,
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
            event_runtime=self._event_runtime,
            event_reader=self._event_reader,
            event_schema_catalog=self._event_schema_catalog,
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

    def _read_inspection_event_records(
        self,
        run_id: str,
    ) -> tuple[WorkflowEventRecord, ...]:
        safe_run_id = validate_artifact_path_segment(run_id, field="run_id")
        run_dir = resolve_artifact_descendant(
            self._artifact_root,
            safe_run_id,
            field="run_id",
        )
        manifest = self._run_inspector.load_manifest(run_dir)
        manifest_run_id = manifest.get("run_id")
        if manifest_run_id is not None and manifest_run_id != safe_run_id:
            raise EventContractError(
                "workflow manifest run_id does not match the durable stream scope"
            )
        tenant_id = _optional_manifest_tenant_id(manifest)
        stream_id = f"run:{safe_run_id}"
        high_watermark = self._event_reader.get_stream_high_watermark(
            stream_id,
            tenant_id=tenant_id,
        )
        if high_watermark is None:
            return ()
        if (
            isinstance(high_watermark, bool)
            or not isinstance(high_watermark, int)
            or high_watermark < 1
        ):
            raise EventContractError(
                "durable run event reader returned an invalid high watermark"
            )

        records: list[WorkflowEventRecord] = []
        cursor: StreamSequenceCursor | None = None
        expected_sequence = 1
        page_count = 0
        while expected_sequence <= high_watermark:
            page_count += 1
            if page_count > high_watermark:
                raise EventContractError(
                    "durable run event pagination exceeded the captured stream bound"
                )
            page = self._event_reader.read_stream(
                StreamReadRequest(
                    stream_id=stream_id,
                    tenant_id=tenant_id,
                    cursor=cursor,
                    limit=MAX_PAGE_LIMIT,
                    through_sequence=high_watermark,
                )
            )
            if not isinstance(page, EventPage):
                raise EventContractError("durable run event reader returned an invalid page")
            if page.stream_id != stream_id or page.tenant_id != tenant_id:
                raise EventContractError(
                    "durable run event reader crossed the requested stream scope"
                )
            if page.high_watermark != high_watermark:
                raise EventContractError(
                    "durable run event reader changed the captured high watermark"
                )
            if not page.events:
                raise EventContractError(
                    "durable run event reader returned an incomplete stream prefix"
                )
            for event in page.events:
                if event.stream_sequence != expected_sequence:
                    raise EventContractError(
                        "durable run event reader returned a non-contiguous stream prefix"
                    )
                projection = project_workflow_event(
                    event,
                    schema_catalog=self._event_schema_catalog,
                )
                records.append(
                    _workflow_event_record_from_durable_projection(
                        projection,
                        run_id=safe_run_id,
                        stream_sequence=expected_sequence,
                    )
                )
                expected_sequence += 1

            if expected_sequence > high_watermark:
                if page.next_cursor is not None:
                    raise EventContractError(
                        "durable run event reader continued beyond the captured high watermark"
                    )
                break
            next_cursor = page.next_cursor
            if next_cursor is None:
                raise EventContractError(
                    "durable run event reader truncated the captured stream prefix"
                )
            if (
                next_cursor.stream_id != stream_id
                or next_cursor.tenant_id != tenant_id
                or next_cursor.high_watermark != high_watermark
                or next_cursor.after_sequence != expected_sequence - 1
                or (
                    cursor is not None
                    and next_cursor.after_sequence <= cursor.after_sequence
                )
            ):
                raise EventContractError(
                    "durable run event reader returned a non-advancing cursor"
                )
            cursor = next_cursor

        if expected_sequence - 1 != high_watermark:
            raise EventContractError(
                "durable run event reader did not return the complete stream prefix"
            )
        return tuple(records)

    def inspect_run(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunInspection:
        event_records = self._read_inspection_event_records(run_id)
        return self._run_inspector.inspect_run(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
            event_records=event_records,
        )

    def build_replay_bundle(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowReplayBundle:
        event_records = self._read_inspection_event_records(run_id)
        return self._run_inspector.build_replay_bundle(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
            event_records=event_records,
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
        event_records = self._read_inspection_event_records(run_id)
        return self._run_inspector.build_replay_content_bundle(
            run_id,
            redact=redact,
            expand_artifact_indexes=expand_artifact_indexes,
            artifact_index_keys=artifact_index_keys,
            expand_source_artifacts=expand_source_artifacts,
            max_artifact_bytes=max_artifact_bytes,
            event_records=event_records,
        )

    def inspect_run_diagnostics(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunDiagnostics:
        event_records = self._read_inspection_event_records(run_id)
        return self._run_inspector.build_diagnostics(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
            event_records=event_records,
        )

    def inspect_run_health(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunHealthReport:
        event_records = self._read_inspection_event_records(run_id)
        return self._run_inspector.build_health_report(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
            event_records=event_records,
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
        base_event_records = self._read_inspection_event_records(base_run_id)
        target_event_records = self._read_inspection_event_records(target_run_id)
        return self._run_inspector.compare_runs(
            base_run_id,
            target_run_id,
            verify_checksums=verify_checksums,
            strict=strict,
            base_event_records=base_event_records,
            target_event_records=target_event_records,
        )


def _optional_manifest_tenant_id(manifest: Mapping[str, Any]) -> str | None:
    tenant_id = manifest.get("tenant_id")
    if tenant_id is None:
        return None
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise EventContractError("workflow manifest tenant_id is invalid")
    return tenant_id.strip()


def _workflow_event_record_from_durable_projection(
    projection: Mapping[str, Any],
    *,
    run_id: str,
    stream_sequence: int,
) -> WorkflowEventRecord:
    if projection.get("run_id") != run_id:
        raise EventContractError(
            "durable run event projection crossed the requested run scope"
        )
    if projection.get("stream_sequence") != stream_sequence:
        raise EventContractError(
            "durable run event projection changed the authoritative sequence"
        )
    event_type = projection.get("event_type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise EventContractError("durable run event projection is missing event_type")
    raw_payload = projection.get("payload")
    payload = dict(raw_payload) if isinstance(raw_payload, Mapping) else {}
    event_id = projection.get("event_id")
    occurred_at = projection.get("occurred_at")
    step_id = projection.get("step_id")
    return WorkflowEventRecord(
        event_id=event_id if isinstance(event_id, str) and event_id else None,
        event_type=event_type,
        run_id=run_id,
        occurred_at=(
            occurred_at
            if isinstance(occurred_at, str) and occurred_at
            else None
        ),
        step_id=step_id if isinstance(step_id, str) and step_id else None,
        payload=payload,
        line_number=stream_sequence,
    )


class WorkflowRunIndexer:
    def __init__(
        self,
        *,
        artifact_index_store: ArtifactIndexStore,
        lineage_store: LineageStore,
        artifact_ref_extractors: Sequence[ArtifactRefExtractor] | None = None,
        lineage_extractors: Sequence[LineageExtractor] | None = None,
    ) -> None:
        self._artifact_index_store = artifact_index_store
        self._lineage_store = lineage_store
        self._artifact_ref_extractors = list(artifact_ref_extractors or [])
        self._lineage_extractors = list(lineage_extractors or [])

    def index(self, result: WorkflowResult) -> None:
        self._index_artifacts(result)
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


def lineage_store_from_env(*, artifact_root: str | Path) -> LineageStore:
    return LocalJsonWorkflowLineageStore(
        resolve_artifact_descendant(
            artifact_root,
            "_records/lineage",
            field="lineage_store_root",
        )
    )


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
