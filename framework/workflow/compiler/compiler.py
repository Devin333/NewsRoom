from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from typing import Any

from framework.specs import EdgeCondition, EdgeSpec, StepSpec, StepType, WorkflowSpec
from framework.specs.policy import GATE_POLICY_DIMENSIONS, GATE_POLICY_MODES, TRACE_POLICY_LEVELS
from framework.workflow.runtime.manifest import WorkflowRunnerManifest, build_runner_manifest
from framework.workflow.runners.registry import StepRunnerRegistry


class WorkflowCompileSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class WorkflowCompileIssueCode(StrEnum):
    MISSING_START_STEP = "missing_start_step"
    DUPLICATE_STEP_ID = "duplicate_step_id"
    UNKNOWN_EDGE_SOURCE = "unknown_edge_source"
    UNKNOWN_EDGE_TARGET = "unknown_edge_target"
    UNKNOWN_TERMINAL_STEP = "unknown_terminal_step"
    UNREACHABLE_STEP = "unreachable_step"
    NO_TERMINAL_STEP = "no_terminal_step"
    TERMINAL_HAS_OUTGOING_EDGE = "terminal_has_outgoing_edge"
    CYCLE_REQUIRES_MAX_VISITS = "cycle_requires_max_visits"
    CONDITIONAL_EDGE_MISSING_EXPR = "conditional_edge_missing_expr"
    LLM_DECIDE_FOR_GOVERNANCE = "llm_decide_for_governance"
    READ_KEY_UNAVAILABLE = "read_key_unavailable"
    WRITE_KEY_CONFLICT = "write_key_conflict"
    WRITE_KEY_OVERLAPS_REQUEST = "write_key_overlaps_request"
    WRITE_KEY_RESERVED = "write_key_reserved"
    REQUIRED_OUTPUT_KEY_UNSATISFIED = "required_output_key_unsatisfied"
    RUNNER_NOT_FOUND = "runner_not_found"
    RUNNER_IMPLEMENTATION_NOT_FOUND = "runner_implementation_not_found"
    RUNNER_MISSING_DEPENDENCY = "runner_missing_dependency"
    RUNNER_STEP_VALIDATION_FAILED = "runner_step_validation_failed"
    RUNNER_VALIDATION_WARNING = "runner_validation_warning"
    SPEC_VALIDATION_FAILED = "spec_validation_failed"
    RUNTIME_QUALITY_POLICY_INVALID = "runtime_quality_policy_invalid"


@dataclass(frozen=True)
class WorkflowCompileError:
    code: WorkflowCompileIssueCode
    message: str
    step_id: str | None = None
    edge_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowCompileWarning:
    code: WorkflowCompileIssueCode
    message: str
    step_id: str | None = None
    edge_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompiledWorkflowGraph:
    step_ids: list[str]
    adjacency: dict[str, list[str]]
    reverse_adjacency: dict[str, list[str]]
    reachable_step_ids: set[str]
    terminal_step_ids: set[str]
    has_cycle: bool


@dataclass(frozen=True)
class StepReadWritePlan:
    step_id: str
    read_keys: set[str]
    optional_read_keys: set[str]
    write_keys: set[str]
    unavailable_read_keys: set[str]
    upstream_write_keys: set[str]


@dataclass(frozen=True)
class WorkflowReadWritePlan:
    request_keys: set[str]
    resume_buffer_keys: set[str]
    reserved_keys: set[str]
    step_plans: dict[str, StepReadWritePlan]
    final_available_keys: set[str]
    terminal_required_output_keys: set[str]


@dataclass
class WorkflowCompileResult:
    passed: bool
    errors: list[WorkflowCompileError]
    warnings: list[WorkflowCompileWarning]
    graph: CompiledWorkflowGraph | None
    required_step_types: list[StepType]
    required_implementations: list[str]
    read_write_plan: WorkflowReadWritePlan
    runner_manifest: WorkflowRunnerManifest | None = None

    def has_error(self, code: WorkflowCompileIssueCode) -> bool:
        return any(error.code == code for error in self.errors)

    def has_warning(self, code: WorkflowCompileIssueCode) -> bool:
        return any(warning.code == code for warning in self.warnings)


@dataclass
class WorkflowCompileOptions:
    strict: bool = False
    request_keys: set[str] = field(default_factory=set)
    resume_buffer_keys: set[str] = field(default_factory=set)
    reserved_keys: set[str] = field(
        default_factory=lambda: {
            "workflow",
            "workflow_id",
            "run_id",
            "state",
            "context",
            "events",
            "errors",
            "metadata",
        }
    )
    max_step_visits_required_for_cycles: bool = True


class WorkflowCompiler:
    def __init__(
        self,
        *,
        runner_registry: StepRunnerRegistry | None = None,
        options: WorkflowCompileOptions | None = None,
    ) -> None:
        self.runner_registry = runner_registry
        self.options = options or WorkflowCompileOptions()

    def compile(self, spec: WorkflowSpec) -> WorkflowCompileResult:
        errors: list[WorkflowCompileError] = []
        warnings: list[WorkflowCompileWarning] = []

        self._validate_basic_fields(spec, errors)
        step_by_id = self._validate_unique_step_ids(spec, errors)
        edge_graph = self._validate_edge_endpoints(spec, step_by_id, errors)
        self._validate_start_and_terminals(spec, step_by_id, errors)
        self._check_runtime_quality_policy(spec, errors)

        graph = self._build_compiled_graph(spec, step_by_id, edge_graph)
        if graph is not None:
            self._check_reachability(graph, errors, warnings)
            self._check_graph_policy(spec, graph, errors, warnings)

        read_write_plan = self._check_dataflow(spec, graph, step_by_id, errors, warnings)
        self._check_required_output_keys(spec, step_by_id, read_write_plan, errors)
        self._check_runner_registry_validation(spec, errors, warnings)

        required_step_types = self._collect_required_step_types(spec)
        required_implementations = self._collect_required_implementations(spec)
        runner_manifest = (
            build_runner_manifest(spec, self.runner_registry)
            if self.runner_registry is not None
            else None
        )
        return WorkflowCompileResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            graph=graph,
            required_step_types=required_step_types,
            required_implementations=required_implementations,
            read_write_plan=read_write_plan,
            runner_manifest=runner_manifest,
        )

    def _validate_basic_fields(
        self,
        spec: WorkflowSpec,
        errors: list[WorkflowCompileError],
    ) -> None:
        result = spec.validation_result()
        if result.passed:
            return
        for error in result.errors:
            code = _SPEC_ERROR_CODE_MAP.get(str(error.code), WorkflowCompileIssueCode.SPEC_VALIDATION_FAILED)
            if str(error.code) in _COMPILER_OWNED_VALIDATION_CODES:
                continue
            errors.append(
                WorkflowCompileError(
                    code=code,
                    message=f"WorkflowSpec validation failed: {error.message}",
                    step_id=error.step_id,
                    edge_id=error.edge_id,
                    details={"validation_code": error.code, **dict(error.metadata)},
                )
            )

    def _validate_unique_step_ids(
        self,
        spec: WorkflowSpec,
        errors: list[WorkflowCompileError],
    ) -> dict[str, StepSpec]:
        seen: set[str] = set()
        step_by_id: dict[str, StepSpec] = {}
        for step in spec.steps:
            if step.step_id in seen:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.DUPLICATE_STEP_ID,
                        message=f"Duplicate step_id: {step.step_id}",
                        step_id=step.step_id,
                    )
                )
                continue
            seen.add(step.step_id)
            step_by_id[step.step_id] = step
        return step_by_id

    def _validate_edge_endpoints(
        self,
        spec: WorkflowSpec,
        step_by_id: dict[str, StepSpec],
        errors: list[WorkflowCompileError],
    ) -> dict[str, list[str]]:
        adjacency = {step_id: [] for step_id in step_by_id}
        for edge in spec.edges:
            source_exists = edge.source_step_id in step_by_id
            target_exists = edge.target_step_id in step_by_id
            if not source_exists:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.UNKNOWN_EDGE_SOURCE,
                        message=f"Edge source does not exist: {edge.source_step_id}",
                        edge_id=edge.edge_id,
                        details={"source_step_id": edge.source_step_id},
                    )
                )
            if not target_exists:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.UNKNOWN_EDGE_TARGET,
                        message=f"Edge target does not exist: {edge.target_step_id}",
                        edge_id=edge.edge_id,
                        details={"target_step_id": edge.target_step_id},
                    )
                )
            if source_exists and target_exists:
                adjacency[edge.source_step_id].append(edge.target_step_id)
        return {step_id: sorted(targets) for step_id, targets in adjacency.items()}

    def _validate_start_and_terminals(
        self,
        spec: WorkflowSpec,
        step_by_id: dict[str, StepSpec],
        errors: list[WorkflowCompileError],
    ) -> None:
        if not spec.start_step_id:
            errors.append(
                WorkflowCompileError(
                    code=WorkflowCompileIssueCode.MISSING_START_STEP,
                    message="WorkflowSpec.start_step_id is required.",
                )
            )
        elif spec.start_step_id not in step_by_id:
            errors.append(
                WorkflowCompileError(
                    code=WorkflowCompileIssueCode.MISSING_START_STEP,
                    message=f"start_step_id does not exist: {spec.start_step_id}",
                    step_id=spec.start_step_id,
                )
            )
        if not spec.terminal_step_ids:
            errors.append(
                WorkflowCompileError(
                    code=WorkflowCompileIssueCode.NO_TERMINAL_STEP,
                    message="WorkflowSpec must define at least one terminal step.",
                )
            )
        for terminal_step_id in spec.terminal_step_ids:
            if terminal_step_id not in step_by_id:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.UNKNOWN_TERMINAL_STEP,
                        message=f"terminal_step_id does not exist: {terminal_step_id}",
                        step_id=terminal_step_id,
                    )
                )

    def _build_compiled_graph(
        self,
        spec: WorkflowSpec,
        step_by_id: dict[str, StepSpec],
        adjacency: dict[str, list[str]],
    ) -> CompiledWorkflowGraph | None:
        if not step_by_id:
            return None
        reverse = {step_id: [] for step_id in step_by_id}
        for source_step_id, target_step_ids in adjacency.items():
            for target_step_id in target_step_ids:
                reverse.setdefault(target_step_id, []).append(source_step_id)
        reverse = {step_id: sorted(sources) for step_id, sources in reverse.items()}
        reachable = (
            _reachable_step_ids(spec.start_step_id, adjacency)
            if spec.start_step_id in step_by_id
            else set()
        )
        return CompiledWorkflowGraph(
            step_ids=list(step_by_id),
            adjacency=adjacency,
            reverse_adjacency=reverse,
            reachable_step_ids=reachable,
            terminal_step_ids=set(spec.terminal_step_ids),
            has_cycle=_has_cycle(adjacency),
        )

    def _check_reachability(
        self,
        graph: CompiledWorkflowGraph,
        errors: list[WorkflowCompileError],
        warnings: list[WorkflowCompileWarning],
    ) -> None:
        for step_id in sorted(set(graph.step_ids) - graph.reachable_step_ids):
            message = f"Step is unreachable from start_step_id: {step_id}"
            if self.options.strict:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.UNREACHABLE_STEP,
                        message=message,
                        step_id=step_id,
                    )
                )
            else:
                warnings.append(
                    WorkflowCompileWarning(
                        code=WorkflowCompileIssueCode.UNREACHABLE_STEP,
                        message=message,
                        step_id=step_id,
                    )
                )

    def _check_graph_policy(
        self,
        spec: WorkflowSpec,
        graph: CompiledWorkflowGraph,
        errors: list[WorkflowCompileError],
        warnings: list[WorkflowCompileWarning],
    ) -> None:
        for terminal_step_id in spec.terminal_step_ids:
            outgoing = graph.adjacency.get(terminal_step_id, [])
            if outgoing:
                warnings.append(
                    WorkflowCompileWarning(
                        code=WorkflowCompileIssueCode.TERMINAL_HAS_OUTGOING_EDGE,
                        message=f"Terminal step has outgoing edges: {terminal_step_id}",
                        step_id=terminal_step_id,
                        details={"outgoing": list(outgoing)},
                    )
                )
        for edge in spec.edges:
            if edge.condition == EdgeCondition.CONDITIONAL and not edge.condition_expr:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.CONDITIONAL_EDGE_MISSING_EXPR,
                        message="Conditional edge requires condition_expr.",
                        edge_id=edge.edge_id,
                    )
                )
            if edge.condition == EdgeCondition.LLM_DECIDE and _is_governance_decision_edge(edge):
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.LLM_DECIDE_FOR_GOVERNANCE,
                        message=(
                            "LLM_DECIDE edge cannot be used for safety, approval, "
                            "quality pass, publish, or release decisions."
                        ),
                        edge_id=edge.edge_id,
                        details={"metadata": dict(edge.metadata)},
                    )
                )
        if (
            graph.has_cycle
            and self.options.max_step_visits_required_for_cycles
            and spec.max_step_visits <= 0
        ):
            errors.append(
                WorkflowCompileError(
                    code=WorkflowCompileIssueCode.CYCLE_REQUIRES_MAX_VISITS,
                    message="Workflow graph contains cycle, but max_step_visits is not set.",
                )
            )

    def _check_dataflow(
        self,
        spec: WorkflowSpec,
        graph: CompiledWorkflowGraph | None,
        step_by_id: dict[str, StepSpec],
        errors: list[WorkflowCompileError],
        warnings: list[WorkflowCompileWarning],
    ) -> WorkflowReadWritePlan:
        request_keys = _request_keys(spec, self.options.request_keys)
        resume_buffer_keys = {str(key) for key in self.options.resume_buffer_keys}
        reserved_keys = {str(key) for key in self.options.reserved_keys}
        step_plans: dict[str, StepReadWritePlan] = {}
        final_available_keys = set(request_keys) | set(resume_buffer_keys)
        terminal_required_output_keys: set[str] = set()

        for step in spec.steps:
            optional_read_keys = _optional_read_keys(step)
            upstream_write_keys = (
                _upstream_write_keys(graph, step.step_id, step_by_id)
                if graph is not None
                else set()
            )
            available = set(request_keys) | set(resume_buffer_keys) | upstream_write_keys | optional_read_keys
            unavailable = set(step.read_keys) - available
            if unavailable:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.READ_KEY_UNAVAILABLE,
                        message=f"Step reads unavailable keys: {sorted(unavailable)}",
                        step_id=step.step_id,
                        details={
                            "read_keys": sorted(step.read_keys),
                            "available_keys": sorted(available),
                            "missing_keys": sorted(unavailable),
                        },
                    )
                )

            request_overlaps = set(step.write_keys) & request_keys
            if request_overlaps:
                warnings.append(
                    WorkflowCompileWarning(
                        code=WorkflowCompileIssueCode.WRITE_KEY_OVERLAPS_REQUEST,
                        message=f"Step write_keys overlaps request keys: {sorted(request_overlaps)}",
                        step_id=step.step_id,
                        details={"overlaps": sorted(request_overlaps)},
                    )
                )
            reserved_overlaps = set(step.write_keys) & reserved_keys
            if reserved_overlaps:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.WRITE_KEY_RESERVED,
                        message=f"Step writes reserved keys: {sorted(reserved_overlaps)}",
                        step_id=step.step_id,
                        details={"reserved_keys": sorted(reserved_overlaps)},
                    )
                )

            write_keys = set(step.write_keys)
            final_available_keys.update(write_keys)
            step_plans[step.step_id] = StepReadWritePlan(
                step_id=step.step_id,
                read_keys=set(step.read_keys),
                optional_read_keys=optional_read_keys,
                write_keys=write_keys,
                unavailable_read_keys=unavailable,
                upstream_write_keys=upstream_write_keys,
            )
        for terminal_step_id in spec.terminal_step_ids:
            terminal_step = step_by_id.get(terminal_step_id)
            if terminal_step is not None:
                terminal_required_output_keys.update(terminal_step.required_output_keys)

        if graph is not None:
            self._check_parallel_write_conflicts(graph, step_by_id, errors, warnings)

        return WorkflowReadWritePlan(
            request_keys=request_keys,
            resume_buffer_keys=resume_buffer_keys,
            reserved_keys=reserved_keys,
            step_plans=step_plans,
            final_available_keys=final_available_keys,
            terminal_required_output_keys=terminal_required_output_keys,
        )

    def _check_parallel_write_conflicts(
        self,
        graph: CompiledWorkflowGraph,
        step_by_id: dict[str, StepSpec],
        errors: list[WorkflowCompileError],
        warnings: list[WorkflowCompileWarning],
    ) -> None:
        for source_step_id, targets in graph.adjacency.items():
            if len(targets) < 2:
                continue
            for left, right in combinations(targets, 2):
                left_step = step_by_id.get(left)
                right_step = step_by_id.get(right)
                if left_step is None or right_step is None:
                    continue
                conflicts = set(left_step.write_keys) & set(right_step.write_keys)
                if not conflicts:
                    continue
                message = (
                    f"Possible parallel write_keys conflict between {left} and {right}: "
                    f"{sorted(conflicts)}"
                )
                details = {
                    "source_step_id": source_step_id,
                    "left_step_id": left,
                    "right_step_id": right,
                    "conflicts": sorted(conflicts),
                }
                if self.options.strict:
                    errors.append(
                        WorkflowCompileError(
                            code=WorkflowCompileIssueCode.WRITE_KEY_CONFLICT,
                            message=message,
                            step_id=source_step_id,
                            details=details,
                        )
                    )
                else:
                    warnings.append(
                        WorkflowCompileWarning(
                            code=WorkflowCompileIssueCode.WRITE_KEY_CONFLICT,
                            message=message,
                            step_id=source_step_id,
                            details=details,
                        )
                    )

    def _check_required_output_keys(
        self,
        spec: WorkflowSpec,
        step_by_id: dict[str, StepSpec],
        read_write_plan: WorkflowReadWritePlan,
        errors: list[WorkflowCompileError],
    ) -> None:
        for step in spec.steps:
            missing_declared_outputs = set(step.required_output_keys) - set(step.write_keys)
            if missing_declared_outputs:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.REQUIRED_OUTPUT_KEY_UNSATISFIED,
                        message=(
                            "required_output_keys must be declared in write_keys: "
                            f"{sorted(missing_declared_outputs)}"
                        ),
                        step_id=step.step_id,
                        details={
                            "required_output_keys": sorted(step.required_output_keys),
                            "write_keys": sorted(step.write_keys),
                            "missing_keys": sorted(missing_declared_outputs),
                        },
                    )
                )
        for terminal_step_id in spec.terminal_step_ids:
            terminal_step = step_by_id.get(terminal_step_id)
            plan = read_write_plan.step_plans.get(terminal_step_id)
            if terminal_step is None or plan is None:
                continue
            available = (
                read_write_plan.request_keys
                | read_write_plan.resume_buffer_keys
                | plan.upstream_write_keys
                | set(terminal_step.write_keys)
                | plan.optional_read_keys
            )
            missing = set(terminal_step.required_output_keys) - available
            if missing:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.REQUIRED_OUTPUT_KEY_UNSATISFIED,
                        message=f"Terminal required_output_keys are unavailable: {sorted(missing)}",
                        step_id=terminal_step_id,
                        details={
                            "required_output_keys": sorted(terminal_step.required_output_keys),
                            "missing_keys": sorted(missing),
                        },
                    )
                )

    def _check_runtime_quality_policy(
        self,
        spec: WorkflowSpec,
        errors: list[WorkflowCompileError],
    ) -> None:
        for owner, policy, step in [
            ("workflow", spec.policies.runtime_quality, None),
            *[
                ("step", step.runtime_quality, step)
                for step in spec.steps
                if step.runtime_quality is not None
            ],
        ]:
            if policy is None:
                continue
            prefix = f"{owner} runtime_quality"
            step_id = step.step_id if step is not None else None
            if policy.trace.level not in TRACE_POLICY_LEVELS:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.RUNTIME_QUALITY_POLICY_INVALID,
                        message=f"{prefix}.trace.level is invalid: {policy.trace.level}",
                        step_id=step_id,
                        details={"allowed": sorted(TRACE_POLICY_LEVELS)},
                    )
                )
            if policy.trace.max_payload_bytes <= 0:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.RUNTIME_QUALITY_POLICY_INVALID,
                        message=f"{prefix}.trace.max_payload_bytes must be positive.",
                        step_id=step_id,
                    )
                )
            if policy.gate.mode not in GATE_POLICY_MODES:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.RUNTIME_QUALITY_POLICY_INVALID,
                        message=f"{prefix}.gate.mode is invalid: {policy.gate.mode}",
                        step_id=step_id,
                        details={"allowed": sorted(GATE_POLICY_MODES)},
                    )
                )
            invalid_dimensions = sorted(set(policy.gate.dimensions) - GATE_POLICY_DIMENSIONS)
            if invalid_dimensions:
                errors.append(
                    WorkflowCompileError(
                        code=WorkflowCompileIssueCode.RUNTIME_QUALITY_POLICY_INVALID,
                        message=f"{prefix}.gate.dimensions contains unsupported dimensions: {invalid_dimensions}",
                        step_id=step_id,
                        details={"allowed": sorted(GATE_POLICY_DIMENSIONS)},
                    )
                )
            if step is not None:
                missing_outputs = set(policy.evaluation.required_output_keys) - set(step.write_keys)
                if missing_outputs:
                    errors.append(
                        WorkflowCompileError(
                            code=WorkflowCompileIssueCode.RUNTIME_QUALITY_POLICY_INVALID,
                            message=(
                                "runtime_quality.evaluation.required_output_keys must be "
                                f"declared in write_keys: {sorted(missing_outputs)}"
                            ),
                            step_id=step.step_id,
                            details={
                                "required_output_keys": sorted(policy.evaluation.required_output_keys),
                                "write_keys": sorted(step.write_keys),
                                "missing_keys": sorted(missing_outputs),
                            },
                        )
                    )
    def _check_runner_registry_validation(
        self,
        spec: WorkflowSpec,
        errors: list[WorkflowCompileError],
        warnings: list[WorkflowCompileWarning],
    ) -> None:
        if self.runner_registry is None:
            return
        validation = self.runner_registry.validate_workflow(spec)
        for item in validation.errors:
            code = _RUNNER_VALIDATION_CODE_TO_COMPILE_CODE.get(
                item.code,
                WorkflowCompileIssueCode.RUNNER_STEP_VALIDATION_FAILED,
            )
            errors.append(
                WorkflowCompileError(
                    code=code,
                    message=item.message,
                    step_id=item.step_id,
                    details={
                        "runner_id": item.runner_id,
                        "validation_code": item.code,
                        **dict(item.details),
                    },
                )
            )
        for item in validation.warnings:
            warnings.append(
                WorkflowCompileWarning(
                    code=WorkflowCompileIssueCode.RUNNER_VALIDATION_WARNING,
                    message=item.message,
                    step_id=item.step_id,
                    details={
                        "runner_id": item.runner_id,
                        "validation_code": item.code,
                        **dict(item.details),
                    },
                )
            )

    def _collect_required_step_types(self, spec: WorkflowSpec) -> list[StepType]:
        return sorted({step.step_type for step in spec.steps}, key=lambda item: item.value)

    def _collect_required_implementations(self, spec: WorkflowSpec) -> list[str]:
        return sorted({step.implementation for step in spec.steps})


def _request_keys(spec: WorkflowSpec, option_keys: set[str]) -> set[str]:
    keys = {str(key) for key in option_keys}
    if not keys:
        keys.add("request")
    input_properties = spec.input_schema.get("properties")
    if isinstance(input_properties, dict):
        keys.update(str(key) for key in input_properties)
    keys.update(str(key) for key in spec.metadata.get("initial_keys", []))
    return keys


def _optional_read_keys(step: StepSpec) -> set[str]:
    keys = step.metadata.get("optional_read_keys", [])
    if keys is None:
        return set()
    return {str(key) for key in keys}


def _upstream_write_keys(
    graph: CompiledWorkflowGraph,
    step_id: str,
    step_by_id: dict[str, StepSpec],
) -> set[str]:
    keys: set[str] = set()
    for upstream_step_id in _collect_upstream_step_ids(graph, step_id):
        upstream = step_by_id.get(upstream_step_id)
        if upstream is not None:
            keys.update(upstream.write_keys)
    return keys


def _collect_upstream_step_ids(graph: CompiledWorkflowGraph, step_id: str) -> set[str]:
    visited: set[str] = set()
    stack = list(graph.reverse_adjacency.get(step_id, []))
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        stack.extend(graph.reverse_adjacency.get(current, []))
    return visited


def _reachable_step_ids(start_step_id: str, adjacency: dict[str, list[str]]) -> set[str]:
    reachable: set[str] = set()
    stack = [start_step_id]
    while stack:
        step_id = stack.pop()
        if step_id in reachable:
            continue
        reachable.add(step_id)
        stack.extend(reversed([item for item in adjacency.get(step_id, []) if item not in reachable]))
    return reachable


def _has_cycle(adjacency: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> bool:
        if step_id in visiting:
            return True
        if step_id in visited:
            return False
        visiting.add(step_id)
        try:
            return any(visit(target_step_id) for target_step_id in adjacency.get(step_id, []))
        finally:
            visiting.remove(step_id)
            visited.add(step_id)

    return any(visit(step_id) for step_id in adjacency)


def _is_governance_decision_edge(edge: EdgeSpec) -> bool:
    categories = {
        "publish",
        "approval",
        "validation_pass",
        "safety",
        "release",
    }
    for key in ("decision_category", "purpose"):
        value = edge.metadata.get(key)
        if isinstance(value, str) and value.casefold() in categories:
            return True
    return False


_SPEC_ERROR_CODE_MAP = {
    "start_step_missing": WorkflowCompileIssueCode.MISSING_START_STEP,
    "duplicate_step_ids": WorkflowCompileIssueCode.DUPLICATE_STEP_ID,
    "edge_source_missing": WorkflowCompileIssueCode.UNKNOWN_EDGE_SOURCE,
    "edge_target_missing": WorkflowCompileIssueCode.UNKNOWN_EDGE_TARGET,
    "terminal_step_missing": WorkflowCompileIssueCode.UNKNOWN_TERMINAL_STEP,
    "conditional_expression_missing": WorkflowCompileIssueCode.CONDITIONAL_EDGE_MISSING_EXPR,
    "read_keys_unavailable": WorkflowCompileIssueCode.READ_KEY_UNAVAILABLE,
    "required_outputs_undeclared": WorkflowCompileIssueCode.REQUIRED_OUTPUT_KEY_UNSATISFIED,
}

_RUNNER_VALIDATION_CODE_TO_COMPILE_CODE = {
    "runner_not_found": WorkflowCompileIssueCode.RUNNER_NOT_FOUND,
    "implementation_not_resolvable": WorkflowCompileIssueCode.RUNNER_IMPLEMENTATION_NOT_FOUND,
    "runner_missing_dependencies": WorkflowCompileIssueCode.RUNNER_MISSING_DEPENDENCY,
}

_COMPILER_OWNED_VALIDATION_CODES = {
    "duplicate_step_ids",
    "start_step_missing",
    "terminal_step_missing",
    "edge_source_missing",
    "edge_target_missing",
    "conditional_expression_missing",
    "llm_decide_governance_forbidden",
    "read_keys_unavailable",
    "read_keys_not_available_on_all_paths",
    "required_outputs_undeclared",
    "parallel_write_conflict",
    "parallel_fanout_write_conflict",
    "terminal_step_unreachable",
}



