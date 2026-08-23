from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

from framework.events.canonical import checksum_for
from framework.harness import (
    HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY,
    HarnessCommittedNodeOutputReceipt,
    HarnessGraphActivityTaskContext,
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkerStatus,
)
from framework.harness.graph import HarnessGraphDefinition, HarnessWorkerType
from framework.shared.time import ensure_utc

from business.research.domain import (
    ReaderIssue,
    ReaderRepairApplicationCandidate,
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairApplicationVerificationRecord,
    ReaderRepairCase,
    ReaderRepairContextPack,
    ReaderRepairMemoryQuery,
    ReaderRepairPatchCandidate,
    ReaderRepairRAGPolicy,
    ReaderRepairResult,
    ReaderRepairStrategy,
    ResearchReaderPayload,
    research_subject_scope_ref,
    stable_research_id,
)
from business.research.graphs.reader_repair import (
    READER_REPAIR_GRAPH_ID,
    build_reader_repair_graph_definition,
)
from business.research.graphs.reader_repair_execution_workers import (
    build_reader_repair_application_verification_worker_result,
    build_reader_repair_application_worker_result,
    build_reader_repair_result_worker_result,
)
from business.research.graphs.reader_repair_workers import (
    build_reader_repair_memory_worker_result,
)
from business.research.ports.repair_memory import ReaderRepairMemoryRecallPort
from business.research.reader_repair.consolidation import ReaderRepairConsolidator
from business.research.reader_repair.issue_detector import ReaderRepairIssueDetector
from business.research.reader_repair.repair_context import ReaderRepairContextBuilder


_CHECKSUM_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MODEL = TypeVar("_MODEL", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ReaderRepairRunAuthorityContext:
    """Composition-owned authority projected for one admitted repair run."""

    run_id: str
    paper_id: str
    created_at: datetime
    identity_scope_ref: str
    subject_scope_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _required_text(self.run_id, "run_id"))
        object.__setattr__(
            self,
            "paper_id",
            _required_text(self.paper_id, "paper_id"),
        )
        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be datetime")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        for field_name in ("identity_scope_ref", "subject_scope_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or _CHECKSUM_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{field_name} must be a sha256 reference")
        if self.subject_scope_ref != research_subject_scope_ref(self.paper_id):
            raise ValueError("subject_scope_ref does not match paper_id")


@runtime_checkable
class ReaderRepairRunAuthorityResolver(Protocol):
    def resolve(self, *, run_id: str) -> ReaderRepairRunAuthorityContext:
        ...


@runtime_checkable
class ReaderRepairCommittedOutputResolver(Protocol):
    """Resolve a current durable application receipt for the consumer worker."""

    def resolve(
        self,
        *,
        definition: HarnessGraphDefinition,
        run_id: str,
        application: ReaderRepairApplicationCandidate,
    ) -> HarnessCommittedNodeOutputReceipt:
        ...


@dataclass(frozen=True, slots=True)
class _ReaderRepairFunctionTask:
    run_id: str
    step_id: str
    inputs: Mapping[str, Any]
    activity_attempt: int | None
    graph_id: str | None = None
    graph_version: str | None = None
    graph_ref: str | None = None
    graph_checksum: str | None = None
    node_id: str | None = None
    node_instance_id: str | None = None
    activity_id: str | None = None


@dataclass(frozen=True, slots=True)
class _ReaderRepairFunctionWorker:
    step_id: str
    worker_id: str
    worker_version: str
    input_keys: tuple[str, ...]
    handler: Callable[[_ReaderRepairFunctionTask], HarnessWorkerResult] = field(
        repr=False
    )
    worker_type: HarnessWorkerType = HarnessWorkerType.FUNCTION

    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        parsed = _parse_task(
            task,
            expected_step_id=self.step_id,
            expected_input_keys=self.input_keys,
        )
        result = self.handler(parsed)
        if not isinstance(result, HarnessWorkerResult):
            raise _worker_error(
                "Reader Repair Function returned an invalid worker result",
                step_id=self.step_id,
                result_type=type(result).__name__,
            )
        return result


@dataclass(frozen=True, slots=True)
class _ReaderRepairFunctionWorkerBuilder:
    definition: HarnessGraphDefinition
    memory: ReaderRepairMemoryRecallPort
    run_authority_resolver: ReaderRepairRunAuthorityResolver
    committed_output_resolver: ReaderRepairCommittedOutputResolver
    issue_detector: ReaderRepairIssueDetector
    context_builder: ReaderRepairContextBuilder
    consolidator: ReaderRepairConsolidator

    def build(self) -> Mapping[str, object]:
        handlers: dict[
            str,
            Callable[[_ReaderRepairFunctionTask], HarnessWorkerResult],
        ] = {
            "detect_reader_issue": self._detect_reader_issue,
            "assemble_repair_context": self._assemble_repair_context,
            "apply_repair_candidate": self._apply_repair_candidate,
            "verify_repair_application": self._verify_repair_application,
            "build_repair_result": self._build_repair_result,
            "build_repair_case": self._build_repair_case,
            "prepare_skill_candidate_bundle": self._prepare_skill_candidate_bundle,
            "prepare_memory_write": self._prepare_memory_write,
        }
        expected = {
            activity.step_id
            for activity in self.definition.activities
            if activity.worker_type is HarnessWorkerType.FUNCTION
        }
        if set(handlers) != expected:  # pragma: no cover - declaration invariant
            raise AssertionError("Reader Repair Function handlers do not match Graph")

        workers: dict[str, object] = {}
        for step_id, handler in handlers.items():
            activity = self.definition.activity(step_id)
            leaf = self.definition.leaf_activity_binding(step_id)
            if activity is None or leaf is None:  # pragma: no cover - invariant
                raise AssertionError("Reader Repair Function lacks a Graph binding")
            workers[step_id] = _ReaderRepairFunctionWorker(
                step_id=step_id,
                worker_id=leaf.worker_ref.contract_id,
                worker_version=leaf.worker_ref.version,
                input_keys=activity.input_keys,
                handler=handler,
            )
        return MappingProxyType(workers)

    def _detect_reader_issue(
        self,
        task: _ReaderRepairFunctionTask,
    ) -> HarnessWorkerResult:
        payload = _model_input(task, "reader_payload", ResearchReaderPayload)
        input_run_id = _text_input(task, "run_id")
        if input_run_id != task.run_id:
            raise _worker_error(
                "Reader Repair run input does not match the Harness run",
                step_id=task.step_id,
            )
        source_format = _optional_text_input(task, "source_format")
        authority = self._run_authority(
            task.run_id,
            payload.paper.paper_id,
            step_id=task.step_id,
        )
        issues = self.issue_detector.detect(
            payload,
            run_id=task.run_id,
            source_format=source_format,
            created_at=authority.created_at,
        )
        if not issues:
            raise HarnessValidationError(
                "reader repair requires a detected reader issue",
                code="reader_repair_issue_not_detected",
                details={"step_id": task.step_id},
            )
        return _succeeded(reader_issue=issues[0].to_dict())

    def _assemble_repair_context(
        self,
        task: _ReaderRepairFunctionTask,
    ) -> HarnessWorkerResult:
        issue = _model_input(task, "reader_issue", ReaderIssue)
        _require_issue_run(issue, task)
        query = ReaderRepairMemoryQuery.from_issue(
            issue,
            source_format=issue.metadata.get("source_format"),
        )
        recalled_cases = sorted(
            _model_sequence(
                self.memory.recall_cases(query),
                ReaderRepairCase,
                step_id=task.step_id,
                field_name="recalled_cases",
            ),
            key=lambda item: item.repair_case_id,
        )
        recalled_strategies = sorted(
            _model_sequence(
                self.memory.recall_strategies(
                    query.issue_type,
                    namespace=query.namespace,
                ),
                ReaderRepairStrategy,
                step_id=task.step_id,
                field_name="recalled_strategies",
            ),
            key=lambda item: item.strategy_id,
        )
        successful_cases = [case for case in recalled_cases if case.successful][
            : query.max_successful_cases
        ]
        failed_cases = [case for case in recalled_cases if not case.successful][
            : query.max_failed_cases
        ]
        policy = ReaderRepairRAGPolicy(
            policy_id=stable_research_id(
                "repair_rag_policy",
                issue.error_signature,
            )
        )
        context_pack = self.context_builder.build_pack(
            issue=issue,
            query=query,
            successful_cases=successful_cases,
            failed_cases=failed_cases,
            strategies=list(recalled_strategies[: query.max_strategies]),
            policy=policy,
        )
        return _succeeded(reader_repair_context_pack=context_pack.to_dict())

    def _apply_repair_candidate(
        self,
        task: _ReaderRepairFunctionTask,
    ) -> HarnessWorkerResult:
        return build_reader_repair_application_worker_result(
            payload=_model_input(task, "reader_payload", ResearchReaderPayload),
            candidate=_model_input(
                task,
                "reader_repair_patch_candidate",
                ReaderRepairPatchCandidate,
            ),
        )

    def _verify_repair_application(
        self,
        task: _ReaderRepairFunctionTask,
    ) -> HarnessWorkerResult:
        return build_reader_repair_application_verification_worker_result(
            payload=_model_input(task, "reader_payload", ResearchReaderPayload),
            issue=_current_issue_input(task),
            candidate=_model_input(
                task,
                "reader_repair_patch_candidate",
                ReaderRepairPatchCandidate,
            ),
            application=_model_input(
                task,
                "reader_repair_application_candidate",
                ReaderRepairApplicationCandidate,
            ),
            observation=_model_input(
                task,
                "reader_repair_application_observation",
                ReaderRepairApplicationObservationCandidate,
            ),
        )

    def _build_repair_result(
        self,
        task: _ReaderRepairFunctionTask,
    ) -> HarnessWorkerResult:
        payload = _model_input(task, "reader_payload", ResearchReaderPayload)
        issue = _model_input(task, "reader_issue", ReaderIssue)
        _require_issue_run(issue, task)
        candidate = _model_input(
            task,
            "reader_repair_patch_candidate",
            ReaderRepairPatchCandidate,
        )
        application = _model_input(
            task,
            "reader_repair_application_candidate",
            ReaderRepairApplicationCandidate,
        )
        observation = _model_input(
            task,
            "reader_repair_application_observation",
            ReaderRepairApplicationObservationCandidate,
        )
        verification = _model_input(
            task,
            "reader_repair_application_verification",
            ReaderRepairApplicationVerificationRecord,
        )
        receipt = self.committed_output_resolver.resolve(
            definition=self.definition,
            run_id=task.run_id,
            application=application,
        )
        if not isinstance(receipt, HarnessCommittedNodeOutputReceipt):
            raise _worker_error(
                "Reader Repair committed-output resolver returned an invalid receipt",
                step_id=task.step_id,
                receipt_type=type(receipt).__name__,
            )
        if receipt.resource.run_id != task.run_id:
            raise _worker_error(
                "Reader Repair committed-output receipt belongs to another run",
                step_id=task.step_id,
            )
        if self.definition.definition_checksum is None:  # pragma: no cover
            raise AssertionError("Reader Repair Graph checksum is missing")
        return build_reader_repair_result_worker_result(
            payload=payload,
            issue=issue,
            candidate=candidate,
            application=application,
            observation=observation,
            verification=verification,
            receipt=receipt,
            graph_definition_checksum=self.definition.definition_checksum,
        )

    def _build_repair_case(
        self,
        task: _ReaderRepairFunctionTask,
    ) -> HarnessWorkerResult:
        context_pack = _model_input(
            task,
            "reader_repair_context_pack",
            ReaderRepairContextPack,
        )
        result = _model_input(task, "reader_repair_result", ReaderRepairResult)
        _require_issue_run(context_pack.issue, task)
        repair_summary = result.metadata.get("repair_summary")
        if not isinstance(repair_summary, str) or not repair_summary.strip():
            raise _worker_error(
                "Reader Repair result lacks its verified repair summary",
                step_id=task.step_id,
            )
        repair_case = ReaderRepairCase(
            repair_case_id=stable_research_id(
                "repair_case",
                context_pack.issue.issue_id,
                result.attempt_id,
            ),
            issue=context_pack.issue,
            memory_kind="episodic",
            repair_strategy=repair_summary,
            repair_attempt_refs=[result.attempt_id],
            successful=result.successful,
            verification_results=result.verification_results,
            payload_before_ref=result.payload_before_ref,
            payload_after_ref=result.payload_after_ref,
            source_refs=result.source_refs,
            constraints=context_pack.repair_constraints,
            failure_reason=result.failure_reason,
            created_at=context_pack.issue.created_at,
            tags=[
                context_pack.issue.issue_type,
                context_pack.issue.error_signature,
            ],
            metadata={
                "active_skill_mutation": False,
                "input_bindings": {
                    "reader_repair_context_pack": checksum_for(
                        context_pack.to_dict()
                    ),
                    "reader_repair_result": checksum_for(result.to_dict()),
                },
            },
        )
        return _succeeded(reader_repair_case=repair_case.to_dict())

    def _prepare_skill_candidate_bundle(
        self,
        task: _ReaderRepairFunctionTask,
    ) -> HarnessWorkerResult:
        context_pack = _model_input(
            task,
            "reader_repair_context_pack",
            ReaderRepairContextPack,
        )
        repair_case = _model_input(
            task,
            "reader_repair_case",
            ReaderRepairCase,
        )
        _require_issue_run(repair_case.issue, task)
        if repair_case.issue != context_pack.issue:
            raise _worker_error(
                "Reader Repair case does not match its verified context",
                step_id=task.step_id,
            )
        cases_by_id = {
            case.repair_case_id: case for case in context_pack.recalled_cases
        }
        existing = cases_by_id.get(repair_case.repair_case_id)
        if existing is not None and existing != repair_case:
            raise _worker_error(
                "Reader Repair memory returned a conflicting case identity",
                step_id=task.step_id,
                repair_case_id=repair_case.repair_case_id,
            )
        cases_by_id[repair_case.repair_case_id] = repair_case
        strategies = self.consolidator.consolidate(
            sorted(cases_by_id.values(), key=lambda item: item.repair_case_id)
        )
        strategies = sorted(
            (
                strategy.model_copy(
                    update={"created_at": repair_case.created_at},
                    deep=True,
                )
                for strategy in strategies
            ),
            key=lambda item: item.strategy_id,
        )
        seeds = [
            seed
            for strategy in strategies
            if (seed := self.consolidator.skill_candidate_seed(strategy)) is not None
        ]
        bundle = {
            "input_bindings": {
                "reader_repair_context_pack": checksum_for(
                    context_pack.to_dict()
                ),
                "reader_repair_case": checksum_for(repair_case.to_dict()),
            },
            "strategies": [strategy.to_dict() for strategy in strategies],
            "skill_candidate_seeds": [seed.to_dict() for seed in seeds],
        }
        return _succeeded(strategy_candidate_bundle=bundle)

    def _prepare_memory_write(
        self,
        task: _ReaderRepairFunctionTask,
    ) -> HarnessWorkerResult:
        repair_case = _model_input(
            task,
            "reader_repair_case",
            ReaderRepairCase,
        )
        strategy_bundle = _mapping_input(task, "strategy_candidate_bundle")
        _require_issue_run(repair_case.issue, task)
        authority = self._run_authority(
            task.run_id,
            repair_case.issue.paper_id,
            step_id=task.step_id,
        )
        if task.activity_attempt is None:
            raise _worker_error(
                "Reader Repair memory worker requires a Harness activity attempt",
                step_id=task.step_id,
            )
        return build_reader_repair_memory_worker_result(
            run_id=task.run_id,
            repair_case=repair_case,
            strategy_candidate_bundle=strategy_bundle,
            identity_scope_ref=authority.identity_scope_ref,
            subject_scope_ref=authority.subject_scope_ref,
            attempt=task.activity_attempt,
            graph_id=task.graph_id,
            graph_version=task.graph_version,
            graph_ref=task.graph_ref,
            graph_checksum=task.graph_checksum,
            node_id=task.node_id,
            node_instance_id=task.node_instance_id,
            activity_id=task.activity_id,
        )

    def _run_authority(
        self,
        run_id: str,
        paper_id: str,
        *,
        step_id: str,
    ) -> ReaderRepairRunAuthorityContext:
        authority = self.run_authority_resolver.resolve(run_id=run_id)
        if not isinstance(authority, ReaderRepairRunAuthorityContext):
            raise _worker_error(
                "Reader Repair run authority resolver returned an invalid context",
                step_id=step_id,
                context_type=type(authority).__name__,
            )
        if authority.run_id != run_id or authority.paper_id != paper_id:
            raise _worker_error(
                "Reader Repair run authority does not match the worker subject",
                step_id=step_id,
            )
        return authority


def build_reader_repair_function_worker_implementations(
    *,
    memory: ReaderRepairMemoryRecallPort,
    run_authority_resolver: ReaderRepairRunAuthorityResolver,
    committed_output_resolver: ReaderRepairCommittedOutputResolver,
    issue_detector: ReaderRepairIssueDetector | None = None,
    context_builder: ReaderRepairContextBuilder | None = None,
    consolidator: ReaderRepairConsolidator | None = None,
) -> Mapping[str, object]:
    """Build the exact eight deterministic Graph v2 Function workers."""

    if not isinstance(memory, ReaderRepairMemoryRecallPort):
        raise TypeError("memory must implement ReaderRepairMemoryRecallPort")
    if not isinstance(run_authority_resolver, ReaderRepairRunAuthorityResolver):
        raise TypeError(
            "run_authority_resolver must implement ReaderRepairRunAuthorityResolver"
        )
    if not isinstance(committed_output_resolver, ReaderRepairCommittedOutputResolver):
        raise TypeError(
            "committed_output_resolver must implement "
            "ReaderRepairCommittedOutputResolver"
        )
    definition = build_reader_repair_graph_definition()
    return _ReaderRepairFunctionWorkerBuilder(
        definition=definition,
        memory=memory,
        run_authority_resolver=run_authority_resolver,
        committed_output_resolver=committed_output_resolver,
        issue_detector=issue_detector or ReaderRepairIssueDetector(),
        context_builder=context_builder or ReaderRepairContextBuilder(),
        consolidator=consolidator or ReaderRepairConsolidator(),
    ).build()


def _parse_task(
    value: Mapping[str, Any],
    *,
    expected_step_id: str,
    expected_input_keys: tuple[str, ...],
) -> _ReaderRepairFunctionTask:
    if not isinstance(value, Mapping):
        raise _worker_error(
            "Reader Repair Function task must be an object",
            step_id=expected_step_id,
        )
    run_id = _required_text(value.get("run_id"), "run_id")
    if value.get("step_id") != expected_step_id:
        raise _worker_error(
            "Reader Repair Function task step does not match its worker",
            step_id=expected_step_id,
            actual_step_id=value.get("step_id"),
        )
    if value.get("worker_type") != HarnessWorkerType.FUNCTION.value:
        raise _worker_error(
            "Reader Repair Function task has the wrong worker type",
            step_id=expected_step_id,
            actual_worker_type=value.get("worker_type"),
        )
    inputs = value.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != set(expected_input_keys):
        actual_keys = (
            sorted(str(key) for key in inputs)
            if isinstance(inputs, Mapping)
            else []
        )
        raise _worker_error(
            "Reader Repair Function task inputs do not match its Graph activity",
            step_id=expected_step_id,
            expected_input_keys=sorted(expected_input_keys),
            actual_input_keys=actual_keys,
        )
    metadata = value.get("metadata")
    if not isinstance(metadata, Mapping):
        raise _worker_error(
            "Reader Repair Function task metadata must be an object",
            step_id=expected_step_id,
        )
    context = _task_activity_context(value, run_id=run_id, step_id=expected_step_id)
    return _ReaderRepairFunctionTask(
        run_id=run_id,
        step_id=expected_step_id,
        inputs=dict(inputs),
        activity_attempt=_activity_attempt(
            value,
            run_id=run_id,
            step_id=expected_step_id,
        ),
        graph_id=None if context is None else context.activity.graph_ref.graph_id,
        graph_version=None if context is None else context.activity.graph_ref.identity_version,
        graph_ref=None if context is None else context.activity.graph_ref.identity_ref.exact_ref,
        graph_checksum=None if context is None else context.activity.graph_ref.checksum,
        node_id=None if context is None else context.activity.node_id,
        node_instance_id=None if context is None else context.activity.node_instance_id,
        activity_id=None if context is None else context.activity.activity_id,
    )


def _task_activity_context(
    value: Mapping[str, Any],
    *,
    run_id: str,
    step_id: str,
) -> HarnessGraphActivityTaskContext | None:
    raw_context = value.get(HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY)
    if raw_context is None:
        return None
    if not isinstance(raw_context, Mapping):
        raise _worker_error(
            "Reader Repair Harness activity identity must be an object",
            step_id=step_id,
        )
    try:
        context = HarnessGraphActivityTaskContext.from_dict(raw_context)
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise _worker_error(
            "Reader Repair Harness activity context is invalid",
            step_id=step_id,
            error_code=getattr(exc, "code", None),
        ) from exc
    activity = context.activity
    if activity.run_id != run_id or activity.node_id != step_id:
        raise _worker_error(
            "Reader Repair Harness activity context does not match the task",
            step_id=step_id,
        )
    return context


def _activity_attempt(
    value: Mapping[str, Any],
    *,
    run_id: str,
    step_id: str,
) -> int | None:
    raw_context = value.get(HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY)
    if raw_context is None:
        return None
    if not isinstance(raw_context, Mapping):
        raise _worker_error(
            "Reader Repair Harness activity identity must be an object",
            step_id=step_id,
        )
    try:
        task_context = HarnessGraphActivityTaskContext.from_dict(raw_context)
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise _worker_error(
            "Reader Repair Harness activity context is invalid",
            step_id=step_id,
            error_code=getattr(exc, "code", None),
        ) from exc
    activity = task_context.activity
    mismatches = tuple(
        field_name
        for field_name, expected, actual in (
            ("run_id", run_id, activity.run_id),
            ("graph_id", READER_REPAIR_GRAPH_ID, activity.graph_ref.graph_id),
            ("node_id", step_id, activity.node_id),
        )
        if expected != actual
    )
    if mismatches:
        raise _worker_error(
            "Reader Repair Harness activity context does not match the task",
            step_id=step_id,
            mismatches=list(mismatches),
        )
    return activity.attempt


def _model_input(
    task: _ReaderRepairFunctionTask,
    key: str,
    model_type: type[_MODEL],
) -> _MODEL:
    value = task.inputs[key]
    try:
        return model_type.model_validate(value)
    except (TypeError, ValueError, ValidationError) as exc:
        raise _worker_error(
            "Reader Repair Function input model is invalid",
            step_id=task.step_id,
            input_key=key,
            model_type=model_type.__name__,
            error_type=type(exc).__name__,
        ) from exc


def _model_sequence(
    value: Sequence[Any],
    model_type: type[_MODEL],
    *,
    step_id: str,
    field_name: str,
) -> tuple[_MODEL, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise _worker_error(
            "Reader Repair recall result must be an array",
            step_id=step_id,
            field_name=field_name,
        )
    result: list[_MODEL] = []
    for item in value:
        try:
            result.append(model_type.model_validate(item))
        except (TypeError, ValueError, ValidationError) as exc:
            raise _worker_error(
                "Reader Repair recall result contains an invalid model",
                step_id=step_id,
                field_name=field_name,
                error_type=type(exc).__name__,
            ) from exc
    return tuple(result)


def _current_issue_input(task: _ReaderRepairFunctionTask) -> ReaderIssue:
    issue = _model_input(task, "reader_issue", ReaderIssue)
    _require_issue_run(issue, task)
    return issue


def _require_issue_run(
    issue: ReaderIssue,
    task: _ReaderRepairFunctionTask,
) -> None:
    if issue.run_id != task.run_id:
        raise _worker_error(
            "Reader Repair issue belongs to another Harness run",
            step_id=task.step_id,
            issue_run_id=issue.run_id,
        )


def _mapping_input(
    task: _ReaderRepairFunctionTask,
    key: str,
) -> dict[str, Any]:
    value = task.inputs[key]
    if not isinstance(value, Mapping):
        raise _worker_error(
            "Reader Repair Function mapping input is invalid",
            step_id=task.step_id,
            input_key=key,
        )
    return dict(value)


def _text_input(task: _ReaderRepairFunctionTask, key: str) -> str:
    return _required_text(task.inputs[key], key)


def _optional_text_input(
    task: _ReaderRepairFunctionTask,
    key: str,
) -> str | None:
    value = task.inputs[key]
    if value is None:
        return None
    return _required_text(value, key)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise HarnessValidationError(
            f"{field_name} must be a non-blank string",
            code="reader_repair_function_worker_contract_invalid",
            details={"field_name": field_name},
        )
    return value


def _succeeded(**output: Any) -> HarnessWorkerResult:
    return HarnessWorkerResult(
        status=HarnessWorkerStatus.SUCCEEDED,
        output=output,
    )


def _worker_error(
    message: str,
    *,
    step_id: str,
    **details: Any,
) -> HarnessValidationError:
    return HarnessValidationError(
        message,
        code="reader_repair_function_worker_contract_invalid",
        details={"step_id": step_id, **details},
    )


__all__ = [
    "ReaderRepairCommittedOutputResolver",
    "ReaderRepairRunAuthorityContext",
    "ReaderRepairRunAuthorityResolver",
    "build_reader_repair_function_worker_implementations",
]
