from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from framework.artifacts import (
    ArtifactManager,
    resolve_artifact_descendant,
    validate_artifact_path_segment,
)
from framework.events.ports import EventReaderPort, EventRuntimePort
from framework.events.schema import EventSchemaCatalog, default_event_schema_catalog
from framework.specs import (
    WorkflowSpec,
    WorkflowStatus,
)
from framework.workflow.checkpoint.durable import WorkflowCheckpointV2Envelope
from framework.workflow.checkpoint.store import StoredWorkflowCheckpoint
from framework.workflow.runtime.checkpoint_coordinator import CheckpointCoordinator
from framework.workflow.runtime.execution_context import build_execution_context
from framework.workflow.runtime.execution_loop import WorkflowExecutionLoop
from framework.workflow.runtime.artifact_publishers import (
    ArtifactPublishContext,
    ArtifactPublishPhase,
    RuntimeArtifactPublisher,
    WorkflowArtifactPublisher,
    WorkflowArtifactPublisherRegistry,
)
from framework.workflow.governance.budget import restore_global_budget_tracker_usage
from framework.workflow.checkpoint.recovery import (
    inspect_checkpoint_artifacts,
    verified_checkpoint_recovery_cursor,
)
from framework.workflow.checkpoint.resume import (
    ResumeMode,
    WorkflowResumePlanner,
    WorkflowResumeRequest,
    checkpoint_envelope_for_resume,
)
from framework.workflow.runtime.manifest_updater import ManifestUpdater, public_resume_metadata
from framework.workflow.runtime.outcome_finalizer import WorkflowOutcomeFinalizer
from framework.workflow.runtime.result import StepOutcome, WorkflowResult
from framework.workflow.routing import RoutingEngine
from framework.workflow.runtime.runtime_event_bridge import RuntimeEventBridge
from framework.workflow.runtime.state_machine import (
    WorkflowRuntimeEvent,
    WorkflowRuntimeEventType,
    WorkflowStateMachine,
)
from framework.workflow.runtime.step_invoker import (
    StepInvoker,
)
from framework.workflow.runtime.verification import (
    RuntimeVerificationMode,
    WorkflowRuntimeVerifier,
)
from framework.workflow.runners.base import StepExecutionError
from framework.workflow.runners.function import FunctionStepRunner
from framework.workflow.runners.registry import StepRunnerRegistry


def _artifact_publisher_registry(
    artifact_publishers: list[WorkflowArtifactPublisher]
    | WorkflowArtifactPublisherRegistry
    | None,
) -> WorkflowArtifactPublisherRegistry:
    if isinstance(artifact_publishers, WorkflowArtifactPublisherRegistry):
        return artifact_publishers
    return WorkflowArtifactPublisherRegistry(
        [*(artifact_publishers or []), RuntimeArtifactPublisher()]
    )


class WorkflowExecutor:
    def __init__(
        self,
        function_step_runner: FunctionStepRunner | None,
        artifact_manager: ArtifactManager,
        routing_engine: RoutingEngine | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        step_runner_registry: StepRunnerRegistry | None = None,
        checkpoint_store: Any | None = None,
        event_runtime: EventRuntimePort | None = None,
        event_reader: EventReaderPort | None = None,
        event_schema_catalog: EventSchemaCatalog | None = None,
        global_budget_tracker: Any | None = None,
        artifact_publishers: list[WorkflowArtifactPublisher]
        | WorkflowArtifactPublisherRegistry
        | None = None,
        runtime_verification_mode: RuntimeVerificationMode = "off",
    ) -> None:
        if step_runner_registry is None:
            if function_step_runner is None:
                raise ValueError("function_step_runner is required without step_runner_registry")
            step_runner_registry = StepRunnerRegistry.with_function_runner(function_step_runner)
        self._step_runner_registry = step_runner_registry
        self._artifact_manager = artifact_manager
        self._routing_engine = routing_engine or RoutingEngine()
        self._sleep_fn = sleep_fn or time.sleep
        self._checkpoint_store = checkpoint_store
        self._event_runtime = event_runtime
        self._event_reader = event_reader
        self._event_schema_catalog = (
            event_schema_catalog or default_event_schema_catalog()
        )
        self._global_budget_tracker = global_budget_tracker
        self._artifact_publishers = _artifact_publisher_registry(artifact_publishers)
        self._workflow_state_machine = WorkflowStateMachine()
        self._runtime_verifier = WorkflowRuntimeVerifier(runtime_verification_mode)

    def execute(
        self,
        workflow: WorkflowSpec,
        request: dict[str, Any],
        *,
        profile: str,
        run_id: str | None = None,
        _initial_buffer_values: dict[str, Any] | None = None,
        _current_step_ids: list[str] | None = None,
        _initial_path: list[str] | None = None,
        _initial_step_results: dict[str, StepOutcome] | None = None,
        _resumed_checkpoint_id: str | None = None,
        _resume_metadata: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        initial_buffer_values = _initial_buffer_values or {"request": request}
        workflow.validate(
            request_keys=list(initial_buffer_values),
            strict=True,
            checkpoint_store_available=self._checkpoint_store is not None,
            allow_pause_artifact_strategy=True,
        )
        _validate_step_runners(workflow, self._step_runner_registry)

        started_monotonic = time.perf_counter()
        context = build_execution_context(
            workflow=workflow,
            request=request,
            profile=profile,
            artifact_manager=self._artifact_manager,
            step_runner_registry=self._step_runner_registry,
            event_runtime=self._event_runtime,
            event_reader=self._event_reader,
            event_schema_catalog=self._event_schema_catalog,
            started_monotonic=started_monotonic,
            run_id=run_id,
            initial_buffer_values=initial_buffer_values,
            current_step_ids=_current_step_ids,
            initial_path=_initial_path,
            initial_step_results=_initial_step_results,
        )
        _configure_step_runners(
            self._step_runner_registry,
            artifact_manager=self._artifact_manager,
            run_id=context.run_id,
            workflow=workflow,
            event_runtime=self._event_runtime,
            event_reader=self._event_reader,
            event_schema_catalog=self._event_schema_catalog,
            global_budget_tracker=self._global_budget_tracker,
        )
        manifest_updater = ManifestUpdater(
            artifact_manager=self._artifact_manager,
            run_id=context.run_id,
            manifest=context.manifest,
        )
        manifest_updater.apply_resume_metadata(
            checkpoint_id=_resumed_checkpoint_id,
            resume_metadata=_resume_metadata,
        )
        event_bridge = RuntimeEventBridge()
        step_invoker = StepInvoker(
            step_runner_registry=self._step_runner_registry,
            sleep_fn=self._sleep_fn,
        )
        checkpoint_coordinator = CheckpointCoordinator(
            checkpoint_store=self._checkpoint_store,
            global_budget_tracker=self._global_budget_tracker,
        )
        finalizer = WorkflowOutcomeFinalizer(
            artifact_manager=self._artifact_manager,
            artifact_publishers=self._artifact_publishers,
            event_bridge=event_bridge,
            global_budget_tracker=self._global_budget_tracker,
        )

        context.status = self._workflow_state_machine.transition(
            WorkflowStatus.CREATED,
            WorkflowRuntimeEvent(
                event_type=WorkflowRuntimeEventType.START,
                reason=(
                    "workflow_resumed"
                    if _resumed_checkpoint_id is not None
                    else "workflow_execution_started"
                ),
                checkpoint_id=_resumed_checkpoint_id,
            ),
        )

        self._artifact_publishers.publish_all(
            ArtifactPublishContext(
                phase=ArtifactPublishPhase.START,
                run_id=context.run_id,
                workflow=workflow,
                profile=profile,
                status=context.status,
                request=request,
                output={},
                manifest=context.manifest,
                artifact_manager=self._artifact_manager,
                step_results={},
                path=[],
                initial_buffer_snapshot=context.initial_buffer_snapshot,
            )
        )

        if _resumed_checkpoint_id is None:
            event_bridge.emit_workflow_started(
                context.recorder,
                workflow=workflow,
                profile=profile,
                trace_context=context.trace_context,
            )
        else:
            event_bridge.emit_workflow_resumed(
                context.recorder,
                workflow=workflow,
                profile=profile,
                checkpoint_id=_resumed_checkpoint_id,
                resume_metadata=_resume_metadata,
                public_resume_metadata=(
                    public_resume_metadata(_resume_metadata)
                    if _resume_metadata
                    else None
                ),
                trace_context=context.trace_context,
            )

        WorkflowExecutionLoop(
            state_machine=self._workflow_state_machine,
            routing_engine=self._routing_engine,
            step_invoker=step_invoker,
            checkpoint_coordinator=checkpoint_coordinator,
            event_bridge=event_bridge,
            manifest_updater=manifest_updater,
            is_run_cancelled=self._is_run_cancelled,
        ).run(context)
        self._runtime_verifier.apply(context)
        return finalizer.finalize(context)

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
    ) -> WorkflowResult:
        envelope = checkpoint_envelope_for_resume(checkpoint)
        recovery_cursor = None
        if isinstance(envelope, WorkflowCheckpointV2Envelope):
            if self._event_reader is None:
                raise StepExecutionError(
                    "durable event reader is required to verify checkpoint recovery"
                )
            try:
                recovery_cursor = verified_checkpoint_recovery_cursor(
                    checkpoint=envelope,
                    reader=self._event_reader,
                )
            except (TypeError, ValueError) as exc:
                raise StepExecutionError(str(exc)) from exc
        public_resume_metadata = dict(resume_metadata or {})
        actual_resume_metadata = dict(public_resume_metadata)
        recovery_report = inspect_checkpoint_artifacts(
            checkpoint=envelope,
            manifest=_load_checkpoint_manifest(self._artifact_manager.root, checkpoint.run_id),
            artifact_root=self._artifact_manager.root,
            strict=False,
        )
        actual_resume_metadata["partial_artifact_recovery"] = recovery_report.to_dict()
        actual_resume_metadata["_public_resume_metadata"] = (
            public_resume_metadata
            if resume_metadata is not None
            else {"partial_artifact_recovery": recovery_report.to_dict()}
        )
        mode = (
            ResumeMode.FROM_STEP
            if target_step_id
            else ResumeMode.WITH_PATCH
            if buffer_updates
            else ResumeMode.EXACT
        )
        resume_request = WorkflowResumeRequest(
            mode=mode,
            checkpoint=envelope,
            recovery_cursor=recovery_cursor,
            run_id=run_id,
            patch=dict(buffer_updates or {}),
            target_step_id=target_step_id,
            strict=True,
            metadata=actual_resume_metadata,
        )
        try:
            plan = WorkflowResumePlanner().plan(workflow, resume_request)
        except ValueError as exc:
            raise StepExecutionError(str(exc)) from exc
        budget_usage = plan.resume_metadata.get("budget_usage")
        if restore_global_budget_tracker_usage(self._global_budget_tracker, budget_usage):
            plan.resume_metadata["resume_budget_inherited"] = True
        request = plan.initial_buffer_values.get("request")
        if not isinstance(request, dict):
            request = {}
        return self.execute(
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

    def _is_run_cancelled(self, run_id: str) -> bool:
        return (self._artifact_manager.run_dir(run_id) / "cancel.json").exists()


def _step_outcomes_from_checkpoint(payload: dict[str, Any]) -> dict[str, StepOutcome]:
    outcomes: dict[str, StepOutcome] = {}
    for step_id, raw_outcome in payload.items():
        if not isinstance(raw_outcome, dict):
            continue
        outcomes[str(step_id)] = StepOutcome.from_dict(raw_outcome)
    return outcomes


def _load_checkpoint_manifest(artifact_root: Path, run_id: str) -> dict[str, Any] | None:
    validated_run_id = validate_artifact_path_segment(run_id, field="run_id")
    path = resolve_artifact_descendant(
        artifact_root,
        validated_run_id,
        "manifest.json",
        field="checkpoint_manifest_path",
    )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _validate_step_runners(workflow: WorkflowSpec, registry: StepRunnerRegistry) -> None:
    validation = registry.validate_workflow(workflow)
    if validation.passed:
        return
    messages = [
        f"{issue.step_id}:{issue.code}:{issue.message}"
        for issue in validation.errors
    ]
    legacy_messages = []
    for issue in validation.errors:
        step_type = issue.details.get("step_type")
        implementation = issue.details.get("implementation")
        if issue.code == "runner_not_found" and step_type:
            legacy_messages.append(f"step runner is not registered: {step_type}")
        if issue.code == "implementation_not_resolvable" and implementation:
            legacy_messages.append(
                f"step implementation is not registered: {implementation}"
            )
    detail_messages = [*messages, *legacy_messages]
    raise StepExecutionError("step runner validation failed: " + "; ".join(detail_messages))


def _configure_step_runners(
    registry: StepRunnerRegistry,
    *,
    artifact_manager: ArtifactManager,
    run_id: str,
    workflow: WorkflowSpec,
    event_runtime: EventRuntimePort | None,
    event_reader: EventReaderPort | None,
    event_schema_catalog: EventSchemaCatalog,
    global_budget_tracker: Any | None = None,
) -> None:
    configured_runner_ids: set[str] = set()
    for step_type in registry.registered_step_types():
        runner = registry.get(step_type)
        capability = getattr(runner, "capability", None)
        runner_id = getattr(capability, "runner_id", f"{step_type.value}:{id(runner)}")
        if runner_id in configured_runner_ids:
            continue
        configured_runner_ids.add(str(runner_id))
        configure = getattr(runner, "configure_run_context", None)
        if callable(configure):
            configure(artifact_manager=artifact_manager, run_id=run_id)
        configure_workflow = getattr(runner, "configure_workflow_context", None)
        if callable(configure_workflow):
            configure_workflow(workflow=workflow)
        configure_events = getattr(runner, "configure_event_runtime", None)
        if callable(configure_events):
            if event_runtime is None or event_reader is None:
                raise ValueError(
                    "durable event runtime and reader are required for nested workflows"
                )
            configure_events(
                event_runtime=event_runtime,
                event_reader=event_reader,
                event_schema_catalog=event_schema_catalog,
            )
        configure_budget = getattr(runner, "configure_global_budget_tracker", None)
        if callable(configure_budget) and global_budget_tracker is not None:
            configure_budget(global_budget_tracker)
