from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkerStatus,
)
from framework.harness.graph import (
    HarnessGraphCompiler,
    HarnessGraphDefinition,
    HarnessWorkerType,
)
from framework.harness.subagents import SubAgentSpec
from framework.shared.graph_identity import GraphExecutionIdentity

from business.research.domain import (
    ReaderIssue,
    ReaderRepairApplicationCandidate,
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairContextPack,
    ReaderRepairPatchCandidate,
    ResearchReaderPayload,
    stable_research_id,
)
from business.research.graphs.reader_repair import (
    READER_REPAIR_SUBAGENT_IDS,
    build_reader_repair_graph_definition,
    build_reader_repair_subagent_specs,
)
from business.research.ports.llm_worker import ResearchCandidateWorkerPort
from business.research.ports.reader_repair_candidate import (
    READER_REPAIR_APPLICATION_OBSERVATION_TASK,
    READER_REPAIR_PATCH_CANDIDATE_TASK,
)
from business.research.reader_repair.application import (
    reader_repair_component_checksum,
)


_PATCH_TARGET_BY_OPERATION = MappingProxyType(
    {
        "replace_document": "document",
        "replace_analysis": "analysis",
        "remove_analysis": "analysis",
        "replace_evidence": "evidence",
        "remove_evidence": "evidence",
        "replace_navigation": "navigation",
        "replace_annotations": "annotations",
        "replace_source_lineage": "source_lineage",
        "replace_quality": "quality",
    }
)
_PATCH_RESERVED_ROOT_FIELDS = frozenset(
    {"candidate_id", "target_region_refs", "metadata"}
)
_PATCH_RESERVED_OPERATION_FIELDS = frozenset(
    {"operation_id", "expected_before_checksum"}
)
_OBSERVATION_RESERVED_ROOT_FIELDS = frozenset(
    {
        "candidate_id",
        "application_id",
        "source_refs",
        "input_bindings",
        "metadata",
    }
)
_MODEL = TypeVar("_MODEL", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class _ReaderRepairSubAgentTask:
    run_id: str
    step_id: str
    inputs: Mapping[str, Any]
    execution_identity: GraphExecutionIdentity | None = None


@dataclass(frozen=True, slots=True)
class _ReaderRepairSubAgentWorker:
    step_id: str
    worker_id: str
    worker_version: str
    graph_id: str
    graph_version: str
    graph_ref: str
    graph_checksum: str
    input_keys: tuple[str, ...]
    spec: SubAgentSpec
    handler: Callable[[_ReaderRepairSubAgentTask], HarnessWorkerResult] = field(
        repr=False
    )
    worker_type: HarnessWorkerType = HarnessWorkerType.SUBAGENT

    def execute(
        self,
        task: dict[str, Any],
        *,
        execution_identity: GraphExecutionIdentity | None = None,
    ) -> HarnessWorkerResult:
        parsed = _parse_task(
            task,
            expected_step_id=self.step_id,
            expected_input_keys=self.input_keys,
            expected_graph_id=self.graph_id,
            expected_graph_version=self.graph_version,
            expected_graph_ref=self.graph_ref,
            expected_graph_checksum=self.graph_checksum,
            execution_identity=execution_identity,
        )
        result = self.handler(parsed)
        if not isinstance(result, HarnessWorkerResult):  # pragma: no cover
            raise _worker_error(
                "Reader Repair SubAgent returned an invalid worker result",
                step_id=self.step_id,
                result_type=type(result).__name__,
            )
        return result


@dataclass(frozen=True, slots=True)
class _ReaderRepairSubAgentWorkerBuilder:
    definition: HarnessGraphDefinition
    candidate_worker: ResearchCandidateWorkerPort
    specs: Mapping[str, SubAgentSpec]
    graph_id: str
    graph_version: str
    graph_ref: str
    graph_checksum: str

    def build(self) -> Mapping[str, object]:
        handlers: dict[
            str,
            Callable[[_ReaderRepairSubAgentTask], HarnessWorkerResult],
        ] = {
            "propose_repair_candidate": self._propose_repair_candidate,
            "collect_repair_application_observation": (
                self._collect_repair_application_observation
            ),
        }
        expected = {
            activity.step_id
            for activity in self.definition.activities
            if activity.worker_type is HarnessWorkerType.SUBAGENT
        }
        if set(handlers) != expected:  # pragma: no cover - declaration invariant
            raise AssertionError("Reader Repair SubAgent handlers do not match Graph")

        workers: dict[str, object] = {}
        for step_id, handler in handlers.items():
            activity = self.definition.activity(step_id)
            leaf = self.definition.leaf_activity_binding(step_id)
            subagent_id = READER_REPAIR_SUBAGENT_IDS[step_id]
            spec = self.specs.get(subagent_id)
            if activity is None or leaf is None or spec is None:  # pragma: no cover
                raise AssertionError("Reader Repair SubAgent lacks an exact binding")
            workers[step_id] = _ReaderRepairSubAgentWorker(
                step_id=step_id,
                worker_id=leaf.worker_ref.contract_id,
                worker_version=leaf.worker_ref.version,
                graph_id=self.graph_id,
                graph_version=self.graph_version,
                graph_ref=self.graph_ref,
                graph_checksum=self.graph_checksum,
                input_keys=activity.input_keys,
                spec=spec,
                handler=handler,
            )
        return MappingProxyType(workers)

    def _propose_repair_candidate(
        self,
        task: _ReaderRepairSubAgentTask,
    ) -> HarnessWorkerResult:
        payload = _model_input(task, "reader_payload", ResearchReaderPayload)
        context_pack = _model_input(
            task,
            "reader_repair_context_pack",
            ReaderRepairContextPack,
        )
        _require_issue_run(context_pack.issue, task)
        if context_pack.issue.paper_id != payload.paper.paper_id:
            raise _worker_error(
                "Reader Repair context belongs to another paper",
                step_id=task.step_id,
            )
        if context_pack.issue.payload_ref != payload.payload_id:
            raise _worker_error(
                "Reader Repair context is not bound to the reader payload",
                step_id=task.step_id,
            )

        proposal = _normalize_patch_proposal(
            _candidate_mapping(
                _generate_candidate(
                    self.candidate_worker,
                    task=READER_REPAIR_PATCH_CANDIDATE_TASK,
                    payload={
                        "reader_payload": payload.to_dict(),
                        "reader_repair_context_pack": context_pack.to_dict(),
                    },
                    execution_identity=task.execution_identity,
                ),
                step_id=task.step_id,
            ),
            step_id=task.step_id,
        )
        _reject_reserved_fields(
            proposal,
            _PATCH_RESERVED_ROOT_FIELDS,
            step_id=task.step_id,
            field_name="candidate",
        )
        raw_operations = proposal.get("patch_operations")
        if isinstance(raw_operations, str | bytes) or not isinstance(
            raw_operations,
            Sequence,
        ):
            raise _worker_error(
                "Reader Repair patch proposal requires patch_operations",
                step_id=task.step_id,
            )

        input_bindings = {
            "reader_payload": checksum_for(payload.to_dict()),
            "reader_repair_context_pack": checksum_for(context_pack.to_dict()),
        }
        try:
            proposal_checksum = checksum_for(
                {"input_bindings": input_bindings, "proposal": proposal}
            )
        except (TypeError, ValueError) as exc:
            raise _worker_error(
                "Reader Repair patch proposal is not serializable",
                step_id=task.step_id,
            ) from exc
        candidate_id = stable_research_id(
            "reader_repair_patch_candidate",
            proposal_checksum,
        )

        operations: list[dict[str, Any]] = []
        target_region_refs: set[str] = set()
        for index, value in enumerate(raw_operations):
            if not isinstance(value, Mapping):
                raise _worker_error(
                    "Reader Repair patch operation must be an object",
                    step_id=task.step_id,
                    operation_index=index,
                )
            operation = dict(value)
            _reject_reserved_fields(
                operation,
                _PATCH_RESERVED_OPERATION_FIELDS,
                step_id=task.step_id,
                field_name=f"patch_operations[{index}]",
            )
            operation_kind = operation.get("op")
            if not isinstance(operation_kind, str):
                raise _worker_error(
                    "Reader Repair patch operation requires an operation kind",
                    step_id=task.step_id,
                    operation_index=index,
                )
            target = _PATCH_TARGET_BY_OPERATION.get(operation_kind)
            if target is None:
                raise _worker_error(
                    "Reader Repair patch operation is unsupported",
                    step_id=task.step_id,
                    operation_index=index,
                )
            source_refs = operation.get("source_refs")
            if isinstance(source_refs, str | bytes) or not isinstance(
                source_refs,
                Sequence,
            ):
                raise _worker_error(
                    "Reader Repair patch operation requires source_refs",
                    step_id=task.step_id,
                    operation_index=index,
                )
            target_region_refs.update(
                ref for ref in source_refs if isinstance(ref, str) and ref
            )
            operation.update(
                {
                    "operation_id": stable_research_id(
                        "reader_repair_patch_operation",
                        candidate_id,
                        str(index),
                        str(operation_kind),
                    ),
                    "expected_before_checksum": (
                        reader_repair_component_checksum(payload, target)
                    ),
                }
            )
            operations.append(operation)

        candidate_payload = {
            **proposal,
            "candidate_id": candidate_id,
            "target_region_refs": sorted(target_region_refs),
            "patch_operations": operations,
            "metadata": {
                "candidate_only": True,
                "input_bindings": input_bindings,
                "subagent_id": READER_REPAIR_SUBAGENT_IDS[task.step_id],
            },
        }
        candidate = _validate_model(
            candidate_payload,
            ReaderRepairPatchCandidate,
            task=task,
        )
        return HarnessWorkerResult(
            status=HarnessWorkerStatus.SUCCEEDED,
            output={"reader_repair_patch_candidate": candidate.to_dict()},
        )

    def _collect_repair_application_observation(
        self,
        task: _ReaderRepairSubAgentTask,
    ) -> HarnessWorkerResult:
        issue = _model_input(task, "reader_issue", ReaderIssue)
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
        _require_issue_run(issue, task)
        if application.candidate_id != candidate.candidate_id:
            raise _worker_error(
                "Reader Repair application is not bound to the patch candidate",
                step_id=task.step_id,
            )
        if set(application.source_refs) != set(candidate.target_region_refs):
            raise _worker_error(
                "Reader Repair application source scope is not bound",
                step_id=task.step_id,
            )

        proposal = _candidate_mapping(
            _generate_candidate(
                self.candidate_worker,
                task=READER_REPAIR_APPLICATION_OBSERVATION_TASK,
                payload={
                    "reader_issue": issue.to_dict(),
                    "reader_repair_patch_candidate": candidate.to_dict(),
                    "reader_repair_application_candidate": application.to_dict(),
                },
                execution_identity=task.execution_identity,
            ),
            step_id=task.step_id,
        )
        _reject_reserved_fields(
            proposal,
            _OBSERVATION_RESERVED_ROOT_FIELDS,
            step_id=task.step_id,
            field_name="observation",
        )
        observation_payload = {
            **proposal,
            "candidate_id": candidate.candidate_id,
            "application_id": application.application_id,
            "source_refs": list(application.source_refs),
            "input_bindings": {
                "reader_repair_patch_candidate": checksum_for(
                    candidate.to_dict()
                ),
                "reader_repair_application_candidate": checksum_for(
                    application.to_dict()
                ),
            },
            "metadata": {
                "candidate_only": True,
                "deterministic_verdict": False,
                "subagent_id": READER_REPAIR_SUBAGENT_IDS[task.step_id],
            },
        }
        observation = _validate_model(
            observation_payload,
            ReaderRepairApplicationObservationCandidate,
            task=task,
        )
        return HarnessWorkerResult(
            status=HarnessWorkerStatus.SUCCEEDED,
            output={
                "reader_repair_application_observation": observation.to_dict()
            },
        )


def build_reader_repair_subagent_worker_implementations(
    *,
    candidate_worker: ResearchCandidateWorkerPort,
) -> Mapping[str, object]:
    """Build the exact two candidate-only Reader Repair SubAgent workers."""

    if not isinstance(candidate_worker, ResearchCandidateWorkerPort):
        raise TypeError(
            "candidate_worker must implement ResearchCandidateWorkerPort"
        )
    definition = build_reader_repair_graph_definition()
    graph = HarnessGraphCompiler().compile(definition).graph
    specs = {
        spec.subagent_id: spec for spec in build_reader_repair_subagent_specs()
    }
    if set(specs) != set(READER_REPAIR_SUBAGENT_IDS.values()):  # pragma: no cover
        raise AssertionError("Reader Repair SubAgent specs do not match Graph")
    return _ReaderRepairSubAgentWorkerBuilder(
        definition=definition,
        candidate_worker=candidate_worker,
        specs=MappingProxyType(specs),
        graph_id=graph.graph_id,
        graph_version=graph.graph_version,
        graph_ref=graph.graph_ref.exact_ref,
        graph_checksum=graph.checksum,
    ).build()


def _parse_task(
    value: Mapping[str, Any],
    *,
    expected_step_id: str,
    expected_input_keys: tuple[str, ...],
    expected_graph_id: str,
    expected_graph_version: str,
    expected_graph_ref: str,
    expected_graph_checksum: str,
    execution_identity: GraphExecutionIdentity | None,
) -> _ReaderRepairSubAgentTask:
    if execution_identity is not None and not isinstance(
        execution_identity,
        GraphExecutionIdentity,
    ):
        raise _worker_error(
            "Reader Repair SubAgent requires a typed Graph execution identity",
            step_id=expected_step_id,
            identity_type=type(execution_identity).__name__,
        )
    if not isinstance(value, Mapping):
        raise _worker_error(
            "Reader Repair SubAgent task must be an object",
            step_id=expected_step_id,
        )
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip() or run_id != run_id.strip():
        raise _worker_error(
            "Reader Repair SubAgent task requires run_id",
            step_id=expected_step_id,
        )
    if execution_identity is not None:
        mismatches = {
            field_name: {
                "expected": expected,
                "actual": getattr(execution_identity, field_name),
            }
            for field_name, expected in (
                ("run_id", run_id),
                ("graph_id", expected_graph_id),
                ("graph_version", expected_graph_version),
                ("graph_ref", expected_graph_ref),
                ("graph_checksum", expected_graph_checksum),
                ("node_id", expected_step_id),
            )
            if getattr(execution_identity, field_name) != expected
        }
        if mismatches:
            raise _worker_error(
                "Reader Repair SubAgent execution identity does not match its Graph activity",
                step_id=expected_step_id,
                identity_mismatches=mismatches,
            )
    if value.get("step_id") != expected_step_id:
        raise _worker_error(
            "Reader Repair SubAgent task step does not match its worker",
            step_id=expected_step_id,
            actual_step_id=value.get("step_id"),
        )
    if value.get("worker_type") != HarnessWorkerType.SUBAGENT.value:
        raise _worker_error(
            "Reader Repair SubAgent task has the wrong worker type",
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
            "Reader Repair SubAgent task inputs do not match its Graph activity",
            step_id=expected_step_id,
            expected_input_keys=sorted(expected_input_keys),
            actual_input_keys=actual_keys,
        )
    if not isinstance(value.get("metadata"), Mapping):
        raise _worker_error(
            "Reader Repair SubAgent task metadata must be an object",
            step_id=expected_step_id,
        )
    return _ReaderRepairSubAgentTask(
        run_id=run_id,
        step_id=expected_step_id,
        inputs=dict(inputs),
        execution_identity=execution_identity,
    )


def _model_input(
    task: _ReaderRepairSubAgentTask,
    key: str,
    model_type: type[_MODEL],
) -> _MODEL:
    return _validate_model(task.inputs[key], model_type, task=task, input_key=key)


def _validate_model(
    value: Any,
    model_type: type[_MODEL],
    *,
    task: _ReaderRepairSubAgentTask,
    input_key: str | None = None,
) -> _MODEL:
    try:
        return model_type.model_validate(value)
    except (TypeError, ValueError, ValidationError) as exc:
        raise _worker_error(
            "Reader Repair SubAgent model is invalid",
            step_id=task.step_id,
            model_type=model_type.__name__,
            input_key=input_key,
            error_type=type(exc).__name__,
        ) from exc


def _candidate_mapping(value: Any, *, step_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _worker_error(
            "Reader Repair candidate worker must return an object",
            step_id=step_id,
        )
    return dict(value)


def _generate_candidate(
    worker: ResearchCandidateWorkerPort,
    *,
    task: str,
    payload: dict[str, Any],
    execution_identity: GraphExecutionIdentity | None,
) -> dict[str, Any]:
    if execution_identity is None:
        return worker.generate_candidate(task=task, payload=payload)
    return worker.generate_candidate(
        task=task,
        payload=payload,
        execution_identity=execution_identity,
    )


def _normalize_patch_proposal(
    proposal: dict[str, Any],
    *,
    step_id: str,
) -> dict[str, Any]:
    """Restore strict provider key/value projections to domain dictionaries."""

    normalized = deepcopy(proposal)
    operations = normalized.get("patch_operations")
    if not isinstance(operations, list):
        return normalized
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            continue
        replacement = operation.get("replacement")
        if operation.get("op") == "replace_document" and isinstance(
            replacement,
            dict,
        ):
            for table in replacement.get("tables", []):
                if not isinstance(table, dict):
                    continue
                rows = table.get("rows")
                if not isinstance(rows, list):
                    continue
                table["rows"] = [
                    _entries_to_mapping(
                        row,
                        step_id=step_id,
                        field_name=(
                            f"patch_operations[{index}].replacement.tables.rows"
                        ),
                    )
                    for row in rows
                ]
        if operation.get("op") == "replace_analysis" and isinstance(
            replacement,
            dict,
        ):
            quality = replacement.get("quality")
            if quality is not None:
                replacement["quality"] = _entries_to_mapping(
                    quality,
                    step_id=step_id,
                    field_name=(
                        f"patch_operations[{index}].replacement.quality"
                    ),
                )
        if operation.get("op") == "replace_evidence" and isinstance(
            replacement,
            dict,
        ):
            coverage = replacement.get("coverage")
            if coverage is not None:
                replacement["coverage"] = _entries_to_mapping(
                    coverage,
                    step_id=step_id,
                    field_name=(
                        f"patch_operations[{index}].replacement.coverage"
                    ),
                )
    return normalized


def _entries_to_mapping(
    value: Any,
    *,
    step_id: str,
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"entries"}:
        raise _worker_error(
            "Reader Repair key/value projection is invalid",
            step_id=step_id,
            field_name=field_name,
        )
    entries = value["entries"]
    if not isinstance(entries, list):
        raise _worker_error(
            "Reader Repair key/value entries must be an array",
            step_id=step_id,
            field_name=field_name,
        )
    result: dict[str, Any] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"key", "value"}:
            raise _worker_error(
                "Reader Repair key/value entry is invalid",
                step_id=step_id,
                field_name=field_name,
            )
        key = entry["key"]
        if not isinstance(key, str) or not key.strip() or key != key.strip():
            raise _worker_error(
                "Reader Repair key/value entry key is invalid",
                step_id=step_id,
                field_name=field_name,
            )
        if key in result:
            raise _worker_error(
                "Reader Repair key/value entry keys must be unique",
                step_id=step_id,
                field_name=field_name,
                duplicate_key=key,
            )
        result[key] = entry["value"]
    return result


def _reject_reserved_fields(
    value: Mapping[str, Any],
    reserved: frozenset[str],
    *,
    step_id: str,
    field_name: str,
) -> None:
    supplied = sorted(set(value).intersection(reserved))
    if supplied:
        raise _worker_error(
            "Reader Repair candidate supplied controller-owned fields",
            step_id=step_id,
            field_name=field_name,
            reserved_fields=supplied,
        )


def _require_issue_run(
    issue: ReaderIssue,
    task: _ReaderRepairSubAgentTask,
) -> None:
    if issue.run_id != task.run_id:
        raise _worker_error(
            "Reader Repair issue belongs to another Harness run",
            step_id=task.step_id,
            issue_run_id=issue.run_id,
        )


def _worker_error(
    message: str,
    *,
    step_id: str,
    **details: Any,
) -> HarnessValidationError:
    return HarnessValidationError(
        message,
        code="reader_repair_subagent_worker_contract_invalid",
        details={"step_id": step_id, **details},
    )


__all__ = [
    "READER_REPAIR_APPLICATION_OBSERVATION_TASK",
    "READER_REPAIR_PATCH_CANDIDATE_TASK",
    "build_reader_repair_subagent_worker_implementations",
]
