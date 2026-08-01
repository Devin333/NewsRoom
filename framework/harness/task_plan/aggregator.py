from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Mapping

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import (
    canonical_payload_checksum,
    checksum,
    exact_keys,
    exact_reference,
    frozen_mapping,
    identifier,
    reference,
    stable_text_tuple,
    thaw_mapping,
)
from framework.harness.task_plan.policy import TaskPlanPolicy
from framework.harness.task_plan.store import TaskResultRecord


AggregatorCallable = Callable[[tuple[TaskResultRecord, ...], TaskPlanPolicy], Mapping[str, str]]


@dataclass(frozen=True, slots=True)
class TaskPlanAggregateResult:
    output_refs_by_role: Mapping[str, str]
    aggregate_ref: str
    aggregate_checksum: str
    result_refs: tuple[str, ...]
    branch_refs: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.output_refs_by_role, Mapping):
            raise HarnessValidationError(
                "aggregate output_refs_by_role must be an object",
                code="task_plan_aggregate_invalid",
            )
        roles = {identifier(key, "output_role"): reference(value, "output_ref") for key, value in self.output_refs_by_role.items()}
        object.__setattr__(self, "output_refs_by_role", frozen_mapping(roles, "output_refs_by_role"))
        object.__setattr__(self, "aggregate_ref", reference(self.aggregate_ref, "aggregate_ref"))
        object.__setattr__(self, "aggregate_checksum", checksum(self.aggregate_checksum, "aggregate_checksum"))
        object.__setattr__(
            self,
            "result_refs",
            stable_text_tuple(self.result_refs, "result_refs", allow_empty=False, item_kind="reference"),
        )
        if isinstance(self.branch_refs, (str, bytes)):
            raise HarnessValidationError(
                "aggregate branch_refs must be an array",
                code="task_plan_aggregate_invalid",
            )
        try:
            frozen_branches = tuple(frozen_mapping(item, "branch_refs.item") for item in self.branch_refs)
        except TypeError as exc:
            raise HarnessValidationError(
                "aggregate branch_refs must be an array",
                code="task_plan_aggregate_invalid",
            ) from exc
        object.__setattr__(self, "branch_refs", frozen_branches)
        expected_checksum = canonical_payload_checksum(
            {
                "roles": thaw_mapping(self.output_refs_by_role),
                "result_refs": list(self.result_refs),
                "branch_refs": [thaw_mapping(item) for item in self.branch_refs],
            }
        )
        if self.aggregate_checksum != expected_checksum:
            raise HarnessValidationError(
                "aggregate checksum is invalid",
                code="task_plan_checksum_mismatch",
                details={"expected": expected_checksum, "actual": self.aggregate_checksum},
            )
        expected_ref = f"task-plan-aggregate:{expected_checksum}"
        if self.aggregate_ref != expected_ref:
            raise HarnessValidationError(
                "aggregate reference is not bound to aggregate checksum",
                code="task_plan_aggregate_ref_mismatch",
                details={"expected": expected_ref, "actual": self.aggregate_ref},
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_refs_by_role": thaw_mapping(self.output_refs_by_role),
            "aggregate_ref": self.aggregate_ref,
            "aggregate_checksum": self.aggregate_checksum,
            "result_refs": list(self.result_refs),
            "branch_refs": [thaw_mapping(item) for item in self.branch_refs],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskPlanAggregateResult":
        payload = exact_keys(
            value,
            required=frozenset({"output_refs_by_role", "aggregate_ref", "aggregate_checksum", "result_refs", "branch_refs"}),
            model=cls.__name__,
        )
        return cls(**payload)


class TaskPlanAggregatorRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._items: dict[str, AggregatorCallable] = {}

    def register(self, aggregator_ref: str, aggregator: AggregatorCallable, *, deterministic: bool = False) -> None:
        ref = exact_reference(aggregator_ref, "aggregator_ref")
        if not callable(aggregator):
            raise TypeError("aggregator must be callable")
        if deterministic is not True:
            raise HarnessValidationError(
                "deterministic aggregator registration requires explicit deterministic=True",
                code="task_plan_aggregator_not_deterministic",
                details={"aggregator_ref": ref},
            )
        with self._lock:
            if ref in self._items:
                raise HarnessValidationError("duplicate aggregator registration", code="task_plan_duplicate_aggregator")
            self._items[ref] = aggregator

    def resolve(self, aggregator_ref: str) -> AggregatorCallable:
        ref = exact_reference(aggregator_ref, "aggregator_ref")
        with self._lock:
            aggregator = self._items.get(ref)
        if aggregator is None:
            raise HarnessValidationError("aggregator is unavailable", code="task_plan_aggregator_unavailable", details={"aggregator_ref": ref})
        return aggregator

    def contains(self, aggregator_ref: str) -> bool:
        try:
            ref = exact_reference(aggregator_ref, "aggregator_ref")
        except HarnessValidationError:
            return False
        with self._lock:
            return ref in self._items

    @property
    def refs(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._items))


class TaskPlanAggregator:
    def __init__(self, registry: TaskPlanAggregatorRegistry | None = None) -> None:
        self.registry = registry or TaskPlanAggregatorRegistry()

    def aggregate(self, results: tuple[TaskResultRecord, ...], policy: TaskPlanPolicy) -> TaskPlanAggregateResult:
        accepted = tuple(sorted((item for item in results if item.status.value == "succeeded"), key=lambda item: (item.task_id, item.result_checksum)))
        if not accepted:
            raise HarnessValidationError("no accepted task results are available", code="task_plan_missing_required_role")
        roles: dict[str, str] = {}
        by_role: dict[str, list[TaskResultRecord]] = {}
        for result in accepted:
            if result.output_schema_ref not in policy.allowed_output_schema_refs:
                raise HarnessValidationError(
                    "task result output schema is not allowed",
                    code="task_plan_output_schema_mismatch",
                    details={"task_id": result.task_id, "schema_ref": result.output_schema_ref},
                )
            for role in result.output_roles:
                by_role.setdefault(role, []).append(result)
        for role, producers in sorted(by_role.items()):
            aggregator_ref = policy.deterministic_aggregator_refs.get(role)
            if len(producers) == 1:
                roles[role] = producers[0].result_ref or producers[0].result_checksum
                continue
            if not aggregator_ref:
                raise HarnessValidationError("output role has multiple producers", code="task_plan_output_conflict", details={"role": role})
            merged = self.registry.resolve(aggregator_ref)(tuple(producers), policy)
            if role not in merged:
                raise HarnessValidationError("aggregator omitted the merged role", code="task_plan_aggregator_invalid", details={"role": role})
            roles[role] = merged[role]
        missing = sorted(set(policy.required_output_roles) - set(roles))
        if missing:
            raise HarnessValidationError("required output roles are missing", code="task_plan_missing_required_role", details={"roles": missing})
        unauthorized = sorted(set(roles) - set(policy.allowed_output_roles))
        if unauthorized:
            raise HarnessValidationError("aggregator returned an unauthorized output role", code="task_plan_role_not_allowed", details={"roles": unauthorized})
        stable_roles = {key: roles[key] for key in sorted(roles)}
        # TaskPlanAggregateResult canonicalizes result refs in stable order;
        # compute the checksum over that same canonical representation so a
        # valid aggregate is not rejected merely because task ids sort
        # differently from their result checksums.
        result_refs = tuple(
            sorted(item.result_ref or item.result_checksum for item in accepted)
        )
        aggregate_checksum = canonical_payload_checksum(
            {
                "roles": stable_roles,
                "result_refs": list(result_refs),
                "branch_refs": [
                    {
                        "role": role,
                        "output_ref": roles[role],
                        "producer_node_id": next(
                            (item.task_id for item in accepted if role in item.output_roles),
                            "",
                        ),
                        "output_key": _output_key_for_role(role),
                    }
                    for role in sorted(roles)
                ],
            }
        )
        aggregate_ref = f"task-plan-aggregate:{aggregate_checksum}"
        branch_refs = tuple(
            {
                "role": role,
                "output_ref": roles[role],
                "producer_node_id": next((item.task_id for item in accepted if role in item.output_roles), ""),
                "output_key": _output_key_for_role(role),
            }
            for role in sorted(roles)
        )
        return TaskPlanAggregateResult(stable_roles, aggregate_ref, aggregate_checksum, result_refs, branch_refs)


def _output_key_for_role(role: str) -> str:
    suffix = role.rsplit(".", 1)[-1]
    return {"structure": "structure_candidate", "contribution": "contribution_candidate", "experiments": "experiment_candidate"}.get(suffix, role)


__all__ = ["TaskPlanAggregateResult", "TaskPlanAggregator", "TaskPlanAggregatorRegistry", "AggregatorCallable"]
