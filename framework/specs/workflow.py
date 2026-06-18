"""Declarative workflow specification models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from framework.specs.edge import EdgeCondition, EdgeSpec
from framework.specs.policy import WorkflowPolicySpec
from framework.specs.step import StepSpec, StepType, normalize_step_payload
from framework.specs.trigger import WorkflowTriggerSpec
from framework.specs.validation import (
    ValidationErrorItem,
    ValidationResult,
    ValidationWarningItem,
    WorkflowSpecError,
)


class WorkflowStatus(str, Enum):
    """Workflow run state; separate from StepStatus and worker TaskStatus."""

    DRAFT = "draft"
    READY = "ready"
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_FOR_HUMAN = "waiting_for_human"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"

    def is_terminal(self) -> bool:
        return self in {
            WorkflowStatus.SUCCEEDED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.BUDGET_EXCEEDED,
        }


@dataclass(frozen=True, init=False)
class WorkflowSpec:
    workflow_id: str
    name: str
    version: str
    start_step_id: str = ""
    steps: list[StepSpec]
    edges: list[EdgeSpec] = field(default_factory=list)
    description: str = ""
    trigger: WorkflowTriggerSpec | None = None
    triggers: list[WorkflowTriggerSpec] = field(default_factory=list)
    terminal_step_ids: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    policies: WorkflowPolicySpec = field(default_factory=WorkflowPolicySpec)
    policy: WorkflowPolicySpec | dict[str, Any] | None = None
    max_step_visits: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        workflow_id: str,
        name: str,
        version: str,
        start_step_id: str | list[StepSpec | dict[str, Any]] = "",
        steps: list[StepSpec | dict[str, Any]] | None = None,
        edges: list[EdgeSpec | dict[str, Any]] | None = None,
        description: str = "",
        trigger: WorkflowTriggerSpec | dict[str, Any] | None = None,
        triggers: list[WorkflowTriggerSpec | dict[str, Any]] | None = None,
        terminal_step_ids: list[str] | None = None,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        policies: WorkflowPolicySpec | dict[str, Any] | None = None,
        max_step_visits: int = 100,
        metadata: dict[str, Any] | None = None,
        *,
        policy: WorkflowPolicySpec | dict[str, Any] | None = None,
    ) -> None:
        if steps is None and isinstance(start_step_id, list):
            steps = start_step_id
            start_step_id = ""
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "start_step_id", start_step_id)
        object.__setattr__(self, "steps", list(steps or []))
        object.__setattr__(self, "edges", list(edges or []))
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "trigger", trigger)
        object.__setattr__(self, "triggers", list(triggers or []))
        object.__setattr__(self, "terminal_step_ids", list(terminal_step_ids or []))
        object.__setattr__(self, "input_schema", dict(input_schema or {}))
        object.__setattr__(self, "output_schema", dict(output_schema or {}))
        object.__setattr__(
            self,
            "policies",
            policies if policies is not None else policy if policy is not None else WorkflowPolicySpec(),
        )
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "max_step_visits", max_step_visits)
        object.__setattr__(self, "metadata", dict(metadata or {}))
        self.__post_init__()

    def __post_init__(self) -> None:
        if self.policy is not None:
            object.__setattr__(self, "policies", self.policy)
        if self.trigger is not None and not isinstance(self.trigger, WorkflowTriggerSpec):
            object.__setattr__(self, "trigger", WorkflowTriggerSpec(**self.trigger))
        actual_triggers = list(self.triggers)
        if self.trigger is not None and not actual_triggers:
            actual_triggers = [self.trigger]
        object.__setattr__(
            self,
            "triggers",
            [
                trigger if isinstance(trigger, WorkflowTriggerSpec) else WorkflowTriggerSpec(**trigger)
                for trigger in actual_triggers
            ],
        )
        if not isinstance(self.policies, WorkflowPolicySpec):
            object.__setattr__(self, "policies", WorkflowPolicySpec(**self.policies))
        object.__setattr__(
            self,
            "steps",
            [
                step if isinstance(step, StepSpec) else StepSpec(**normalize_step_payload(step))
                for step in self.steps
            ],
        )
        object.__setattr__(
            self,
            "edges",
            [edge if isinstance(edge, EdgeSpec) else EdgeSpec(**edge) for edge in self.edges],
        )
        if not isinstance(self.input_schema, dict):
            raise WorkflowSpecError(f"input_schema must be an object for workflow {self.workflow_id}")
        if not isinstance(self.output_schema, dict):
            raise WorkflowSpecError(f"output_schema must be an object for workflow {self.workflow_id}")
        if self.steps and not self.start_step_id:
            object.__setattr__(self, "start_step_id", self.steps[0].step_id)

    def validate(
        self,
        *,
        request_keys: list[str] | None = None,
        registered_step_types: list[StepType | str] | None = None,
        strict: bool = False,
        checkpoint_store_available: bool = False,
        allow_pause_artifact_strategy: bool = False,
    ) -> None:
        result = self.validation_result(
            request_keys=request_keys,
            registered_step_types=registered_step_types,
            strict=strict,
            checkpoint_store_available=checkpoint_store_available,
            allow_pause_artifact_strategy=allow_pause_artifact_strategy,
        )
        if not result.passed:
            raise WorkflowSpecError(result.errors[0].message)

    def validation_result(
        self,
        *,
        request_keys: list[str] | None = None,
        registered_step_types: list[StepType | str] | None = None,
        strict: bool = False,
        checkpoint_store_available: bool = False,
        allow_pause_artifact_strategy: bool = False,
    ) -> ValidationResult:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationWarningItem] = []

        def add_error(
            code: str,
            message: str,
            *,
            step_id: str | None = None,
            edge_id: str | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            errors.append(
                ValidationErrorItem(
                    code=code,
                    message=message,
                    step_id=step_id,
                    edge_id=edge_id,
                    metadata=metadata or {},
                )
            )

        def add_warning(
            code: str,
            message: str,
            *,
            step_id: str | None = None,
            edge_id: str | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            warnings.append(
                ValidationWarningItem(
                    code=code,
                    message=message,
                    step_id=step_id,
                    edge_id=edge_id,
                    metadata=metadata or {},
                )
            )

        if not self.workflow_id:
            add_error("workflow_id_required", "workflow_id is required")
        if not self.version:
            add_error(
                "version_required",
                f"version is required for workflow {self.workflow_id}",
            )
        if not self.steps:
            add_error(
                "steps_required",
                f"workflow {self.workflow_id} must define at least one step",
            )
        if self.max_step_visits <= 0:
            add_error("max_step_visits_invalid", "max_step_visits must be positive")

        step_ids = [step.step_id for step in self.steps]
        duplicate_ids = sorted({step_id for step_id in step_ids if step_ids.count(step_id) > 1})
        if duplicate_ids:
            add_error("duplicate_step_ids", f"duplicate step ids: {', '.join(duplicate_ids)}")

        step_id_set = set(step_ids)
        step_by_id = {step.step_id: step for step in self.steps}
        if step_id_set and self.start_step_id not in step_id_set:
            add_error(
                "start_step_missing",
                f"start step does not exist: {self.start_step_id}",
                step_id=self.start_step_id,
            )

        for terminal_step_id in self.terminal_step_ids:
            if terminal_step_id not in step_id_set:
                add_error(
                    "terminal_step_missing",
                    f"terminal step does not exist: {terminal_step_id}",
                    step_id=terminal_step_id,
                )

        for step in self.steps:
            if step.step_type == StepType.SKILL:
                _validate_skill_step(
                    step,
                    add_error=add_error,
                )
            if strict and step.step_type == StepType.HUMAN_REVIEW:
                has_pause_strategy = (
                    allow_pause_artifact_strategy
                    or _human_review_has_pause_artifact_strategy(step)
                )
                if not checkpoint_store_available and not has_pause_strategy:
                    add_error(
                        "human_review_checkpoint_required",
                        "human_review step requires checkpoint_store or pause artifact strategy "
                        f"in strict mode: {step.step_id}",
                        step_id=step.step_id,
                    )
            undeclared_outputs = sorted(set(step.required_output_keys) - set(step.write_keys))
            if undeclared_outputs:
                add_error(
                    "required_outputs_undeclared",
                    f"required_output_keys must be declared in write_keys for step "
                    f"{step.step_id}: {', '.join(undeclared_outputs)}",
                    step_id=step.step_id,
                )
            fallback_step_id = step.failure_policy.fallback_step_id
            if fallback_step_id is not None and fallback_step_id not in step_id_set:
                add_error(
                    "fallback_step_missing",
                    f"fallback step does not exist for {step.step_id}: {fallback_step_id}",
                    step_id=step.step_id,
                )
            for secret_path in _secret_paths(step.to_dict()):
                add_warning(
                    "secret_like_spec_field",
                    f"secret-like field appears in step spec: {secret_path}",
                    step_id=step.step_id,
                    metadata={"path": secret_path},
                )

        if registered_step_types is not None:
            available = {StepType(step_type) for step_type in registered_step_types}
            for step in self.steps:
                if step.step_type not in available:
                    add_error(
                        "step_runner_missing",
                        f"step runner is not registered: {step.step_type.value}",
                        step_id=step.step_id,
                    )

        edge_ids = [edge.edge_id for edge in self.edges]
        duplicate_edge_ids = sorted({edge_id for edge_id in edge_ids if edge_ids.count(edge_id) > 1})
        if duplicate_edge_ids:
            add_error(
                "duplicate_edge_ids",
                f"duplicate edge ids: {', '.join(duplicate_edge_ids)}",
            )

        for edge in self.edges:
            if edge.source_step_id not in step_id_set:
                add_error(
                    "edge_source_missing",
                    f"edge {edge.edge_id} references missing source step {edge.source_step_id}",
                    edge_id=edge.edge_id,
                )
            if edge.target_step_id not in step_id_set:
                add_error(
                    "edge_target_missing",
                    f"edge {edge.edge_id} references missing target step {edge.target_step_id}",
                    edge_id=edge.edge_id,
                )
            if edge.condition == EdgeCondition.CONDITIONAL and not edge.condition_expr:
                add_error(
                    "conditional_expression_missing",
                    f"conditional edge {edge.edge_id} requires condition_expr",
                    edge_id=edge.edge_id,
                )
            if edge.condition == EdgeCondition.LLM_DECIDE and _llm_decide_is_governance_edge(edge):
                add_error(
                    "llm_decide_governance_forbidden",
                    f"LLM_DECIDE edge {edge.edge_id} cannot control safety, approval, "
                    "quality pass, or publish decisions",
                    edge_id=edge.edge_id,
                    metadata={"target_step_id": edge.target_step_id},
                )
            for secret_path in _secret_paths(edge.to_dict()):
                add_warning(
                    "secret_like_spec_field",
                    f"secret-like field appears in edge spec: {secret_path}",
                    edge_id=edge.edge_id,
                    metadata={"path": secret_path},
                )

        for secret_path in _secret_paths({"metadata": self.metadata}):
            add_warning(
                "secret_like_spec_field",
                f"secret-like field appears in workflow spec: {secret_path}",
                metadata={"path": secret_path},
            )

        if errors:
            return ValidationResult(passed=False, errors=errors, warnings=warnings)

        adjacency = _workflow_adjacency(self)
        reachable_step_ids = _reachable_step_ids(self.start_step_id, adjacency)
        for terminal_step_id in self.terminal_step_ids:
            if terminal_step_id not in reachable_step_ids:
                add_error(
                    "terminal_step_unreachable",
                    f"terminal step is not reachable: {terminal_step_id}",
                    step_id=terminal_step_id,
                )

        reverse_adjacency = _reverse_adjacency(adjacency)
        initial_keys = set(request_keys or ["request"])
        input_properties = self.input_schema.get("properties")
        if isinstance(input_properties, dict):
            initial_keys.update(str(key) for key in input_properties)
        initial_keys.update(str(key) for key in self.metadata.get("initial_keys", []))
        for step in self.steps:
            if step.step_id not in reachable_step_ids:
                add_warning(
                    "step_unreachable",
                    f"step is not reachable from start step: {step.step_id}",
                    step_id=step.step_id,
                )
                continue
            upstream_step_ids = _reachable_step_ids(step.step_id, reverse_adjacency) - {step.step_id}
            available_keys = set(initial_keys)
            for upstream_step_id in upstream_step_ids:
                available_keys.update(step_by_id[upstream_step_id].write_keys)
            missing_reads = sorted(set(step.read_keys) - available_keys)
            if missing_reads:
                add_error(
                    "read_keys_unavailable",
                    f"read_keys are not produced by upstream steps for step "
                    f"{step.step_id}: {', '.join(missing_reads)}",
                    step_id=step.step_id,
                )
            if strict:
                missing_strict_reads = sorted(
                    set(step.read_keys)
                    - _strict_keys_available_before_step(
                        workflow=self,
                        target_step_id=step.step_id,
                        initial_keys=initial_keys,
                    )
                )
                if missing_strict_reads:
                    add_error(
                        "read_keys_not_available_on_all_paths",
                        f"read_keys are not available on every path before step "
                        f"{step.step_id}: {', '.join(missing_strict_reads)}",
                        step_id=step.step_id,
                    )
        _validate_parallel_write_conflicts(
            workflow=self,
            add_error=add_error,
            strict=strict,
        )
        return ValidationResult(passed=not errors, errors=errors, warnings=warnings)

    def step_by_id(self, step_id: str) -> StepSpec:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        raise WorkflowSpecError(f"step does not exist: {step_id}")

    def get_step(self, step_id: str) -> StepSpec | None:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def step_ids(self) -> set[str]:
        return {step.step_id for step in self.steps}

    def entry_steps(self) -> list[StepSpec]:
        targets = {edge.target_step_id for edge in self.edges}
        entries = [step for step in self.steps if step.step_id not in targets]
        if entries:
            return entries
        start_step = self.get_step(self.start_step_id)
        return [start_step] if start_step is not None else []

    def terminal_steps(self) -> list[StepSpec]:
        if self.terminal_step_ids:
            return [
                step
                for terminal_step_id in self.terminal_step_ids
                if (step := self.get_step(terminal_step_id)) is not None
            ]
        sources = {edge.source_step_id for edge in self.edges}
        return [step for step in self.steps if step.step_id not in sources]

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "trigger": self.trigger.to_dict() if self.trigger is not None else None,
            "triggers": [trigger.to_dict() for trigger in self.triggers],
            "start_step_id": self.start_step_id,
            "terminal_step_ids": list(self.terminal_step_ids),
            "steps": [step.to_dict() for step in self.steps],
            "edges": [edge.to_dict() for edge in self.edges],
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "policies": self.policies.to_dict(),
            "max_step_visits": self.max_step_visits,
            "metadata": dict(self.metadata),
        }
        if self.policy is not None:
            payload["policy"] = self.policies.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowSpec":
        return cls(**payload)


_SECRET_FIELD_TOKENS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "password",
    "secret",
    "token",
)


def _secret_paths(value: Any, path: str = "$") -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if any(token in key_text.casefold() for token in _SECRET_FIELD_TOKENS):
                matches.append(child_path)
            matches.extend(_secret_paths(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            matches.extend(_secret_paths(item, f"{path}[{index}]"))
    return matches


def _workflow_adjacency(workflow: WorkflowSpec) -> dict[str, set[str]]:
    adjacency = {step.step_id: set() for step in workflow.steps}
    for edge in workflow.edges:
        adjacency[edge.source_step_id].add(edge.target_step_id)
    for step in workflow.steps:
        fallback_step_id = step.failure_policy.fallback_step_id
        if fallback_step_id is not None:
            adjacency[step.step_id].add(fallback_step_id)
    return adjacency


def _reverse_adjacency(adjacency: dict[str, set[str]]) -> dict[str, set[str]]:
    reverse = {step_id: set() for step_id in adjacency}
    for source_step_id, target_step_ids in adjacency.items():
        for target_step_id in target_step_ids:
            reverse[target_step_id].add(source_step_id)
    return reverse


def _reachable_step_ids(start_step_id: str, adjacency: dict[str, set[str]]) -> set[str]:
    reachable: set[str] = set()
    stack = [start_step_id]
    while stack:
        step_id = stack.pop()
        if step_id in reachable:
            continue
        reachable.add(step_id)
        stack.extend(sorted(adjacency.get(step_id, set()) - reachable, reverse=True))
    return reachable


def _strict_keys_available_before_step(
    *,
    workflow: WorkflowSpec,
    target_step_id: str,
    initial_keys: set[str],
) -> set[str]:
    return _strict_keys_available_before_steps(
        workflow=workflow,
        initial_keys=initial_keys,
    ).get(target_step_id, set(initial_keys))


def _strict_keys_available_before_steps(
    *,
    workflow: WorkflowSpec,
    initial_keys: set[str],
) -> dict[str, set[str]]:
    step_by_id = {step.step_id: step for step in workflow.steps}
    predecessors = _workflow_predecessors(workflow)
    universe = set(initial_keys)
    for step in workflow.steps:
        universe.update(str(key) for key in step.write_keys)

    before: dict[str, set[str]] = {}
    after: dict[str, set[str]] = {}
    for step in workflow.steps:
        if step.step_id == workflow.start_step_id or not predecessors.get(step.step_id):
            before[step.step_id] = set(initial_keys)
        else:
            before[step.step_id] = set(universe)
        after[step.step_id] = before[step.step_id] | set(step.write_keys)

    changed = True
    max_iterations = max(1, len(workflow.steps) * 2)
    iteration = 0
    while changed and iteration < max_iterations:
        changed = False
        iteration += 1
        for step in workflow.steps:
            if step.step_id == workflow.start_step_id:
                next_before = set(initial_keys)
            else:
                incoming_step_ids = predecessors.get(step.step_id, set())
                if not incoming_step_ids:
                    next_before = set(initial_keys)
                else:
                    incoming_after = [
                        after.get(predecessor_step_id, set(initial_keys))
                        for predecessor_step_id in incoming_step_ids
                        if predecessor_step_id in step_by_id
                    ]
                    next_before = set.intersection(*incoming_after) if incoming_after else set(initial_keys)
            next_after = next_before | set(step.write_keys)
            if next_before != before[step.step_id] or next_after != after[step.step_id]:
                before[step.step_id] = next_before
                after[step.step_id] = next_after
                changed = True
    return before


def _workflow_predecessors(workflow: WorkflowSpec) -> dict[str, set[str]]:
    predecessors = {step.step_id: set() for step in workflow.steps}
    for edge in workflow.edges:
        if edge.target_step_id in predecessors:
            predecessors[edge.target_step_id].add(edge.source_step_id)
    for step in workflow.steps:
        fallback_step_id = step.failure_policy.fallback_step_id
        if fallback_step_id in predecessors:
            predecessors[fallback_step_id].add(step.step_id)
    return predecessors


def _validate_parallel_write_conflicts(
    *,
    workflow: WorkflowSpec,
    add_error: Any,
    strict: bool,
) -> None:
    step_by_id = {step.step_id: step for step in workflow.steps}
    for step in workflow.steps:
        if step.step_type == StepType.PARALLEL_GROUP:
            branches = step.metadata.get("branches")
            if not isinstance(branches, list):
                continue
            conflict_strategy = str(step.metadata.get("conflict_strategy") or "error")
            seen: dict[str, str] = {}
            for index, branch in enumerate(branches):
                if not isinstance(branch, dict):
                    add_error(
                        "parallel_branch_invalid",
                        f"parallel_group branch must be an object in step {step.step_id}",
                        step_id=step.step_id,
                        metadata={"branch_index": index},
                    )
                    continue
                branch_id = str(branch.get("branch_id") or branch.get("implementation") or index)
                for key in [str(item) for item in branch.get("write_keys", [])]:
                    if key in seen and conflict_strategy == "error":
                        add_error(
                            "parallel_write_conflict",
                            f"parallel_group step {step.step_id} has write conflict for key {key}",
                            step_id=step.step_id,
                            metadata={
                                "write_key": key,
                                "first_branch_id": seen[key],
                                "second_branch_id": branch_id,
                            },
                        )
                    if conflict_strategy != "namespace":
                        seen.setdefault(key, branch_id)
        if not strict:
            continue
        outgoing = [
            edge.target_step_id
            for edge in workflow.edges
            if edge.source_step_id == step.step_id
        ]
        if len(outgoing) < 2:
            continue
        fanout_writes: dict[str, str] = {}
        for target_step_id in outgoing:
            target = step_by_id.get(target_step_id)
            if target is None:
                continue
            for key in target.write_keys:
                if key in fanout_writes:
                    add_error(
                        "parallel_fanout_write_conflict",
                        f"fan-out targets from {step.step_id} write the same key: {key}",
                        step_id=step.step_id,
                        metadata={
                            "write_key": key,
                            "first_target_step_id": fanout_writes[key],
                            "second_target_step_id": target_step_id,
                        },
                    )
                fanout_writes.setdefault(key, target_step_id)


def _human_review_has_pause_artifact_strategy(step: StepSpec) -> bool:
    if step.metadata.get("pause_artifact_strategy") or step.metadata.get("pause_artifact"):
        return True
    policy = step.artifact_policy
    return bool(policy is not None and policy.write_step_output)


def _validate_skill_step(step: StepSpec, *, add_error: Any) -> None:
    skill_name = step.metadata.get("skill") or step.implementation
    if not isinstance(skill_name, str) or not skill_name.strip():
        add_error(
            "skill_step_missing_skill",
            f"skill step requires skill for step {step.step_id}",
            step_id=step.step_id,
            metadata={"field": "skill"},
        )
    input_spec = step.metadata.get("input", {})
    if not isinstance(input_spec, dict):
        add_error(
            "skill_step_input_invalid",
            f"skill step input must be an object for step {step.step_id}",
            step_id=step.step_id,
            metadata={"field": "input"},
        )
    output_key = step.metadata.get("output_key")
    if output_key is not None and not isinstance(output_key, str):
        add_error(
            "skill_step_output_key_invalid",
            f"skill step output_key must be a string for step {step.step_id}",
            step_id=step.step_id,
            metadata={"field": "output_key"},
        )
    timeout_seconds = step.metadata.get("timeout_seconds")
    if timeout_seconds is not None and (
        type(timeout_seconds) is not int or timeout_seconds <= 0
    ):
        add_error(
            "skill_step_timeout_invalid",
            f"skill step timeout_seconds must be a positive integer for step {step.step_id}",
            step_id=step.step_id,
            metadata={"field": "timeout_seconds"},
        )
    fail_workflow_on_error = step.metadata.get("fail_workflow_on_error", True)
    if not isinstance(fail_workflow_on_error, bool):
        add_error(
            "skill_step_fail_policy_invalid",
            f"skill step fail_workflow_on_error must be a bool for step {step.step_id}",
            step_id=step.step_id,
            metadata={"field": "fail_workflow_on_error"},
        )


def _llm_decide_is_governance_edge(edge: EdgeSpec) -> bool:
    text = " ".join(
        str(value)
        for value in (
            edge.edge_id,
            edge.target_step_id,
            edge.description,
            edge.metadata.get("route_hint"),
            edge.metadata.get("decision"),
            edge.metadata.get("purpose"),
        )
    ).casefold()
    governance_tokens = (
        "approval",
        "approve",
        "approved",
        "human_approved",
        "publish",
        "validation_pass",
        "validation.pass",
        "safety",
        "safe_to_publish",
    )
    return any(token in text for token in governance_tokens)


__all__ = ["WorkflowSpec", "WorkflowStatus"]
