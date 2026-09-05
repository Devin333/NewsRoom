"""Deterministic, all-or-nothing capacity packing for task waves."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import canonical_payload_checksum, frozen_mapping, identifier, thaw_mapping
from framework.harness.task_plan.parallel_lifecycle import SideEffectClass


@dataclass(frozen=True, slots=True)
class CapacityPool:
    pool_id: str
    capacity: int
    reserved: int = 0
    policy_version: str = "1"
    policy_checksum: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "pool_id", identifier(self.pool_id, "pool_id"))
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (self.capacity, self.reserved)):
            raise HarnessValidationError("capacity pool values must be non-negative", code="CAPACITY_POLICY_INVALID")
        if self.reserved > self.capacity:
            raise HarnessValidationError("capacity pool is over-reserved", code="CAPACITY_POLICY_INVALID")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise HarnessValidationError("capacity policy version is required", code="CAPACITY_POLICY_INVALID")
        expected = canonical_payload_checksum({"pool_id": self.pool_id, "capacity": self.capacity, "policy_version": self.policy_version})
        if self.policy_checksum and self.policy_checksum != expected:
            raise HarnessValidationError("capacity policy checksum mismatch", code="CAPACITY_POLICY_CHECKSUM_MISMATCH")
        object.__setattr__(self, "policy_checksum", expected)

    @property
    def available(self) -> int:
        return self.capacity - self.reserved


@dataclass(frozen=True, slots=True)
class TaskCapacityDemand:
    task_id: str
    quantities: Mapping[str, int]
    side_effect_class: SideEffectClass | str = SideEffectClass.READ_ONLY
    resource_conflict_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", identifier(self.task_id, "task_id"))
        if not isinstance(self.quantities, Mapping) or not self.quantities:
            raise HarnessValidationError("task capacity demand must name at least one pool", code="CAPACITY_DEMAND_INVALID")
        normalized = {}
        for pool_id, quantity in self.quantities.items():
            pool = identifier(str(pool_id), "pool_id")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
                raise HarnessValidationError("task capacity quantity must be positive", code="CAPACITY_DEMAND_INVALID")
            normalized[pool] = quantity
        object.__setattr__(self, "quantities", frozen_mapping(normalized, "capacity_demand.quantities"))
        object.__setattr__(self, "side_effect_class", SideEffectClass(self.side_effect_class))
        if self.resource_conflict_key is not None and (not isinstance(self.resource_conflict_key, str) or not self.resource_conflict_key.strip()):
            raise HarnessValidationError("resource conflict key must be non-empty", code="CAPACITY_DEMAND_INVALID")

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "quantities": thaw_mapping(self.quantities), "side_effect_class": self.side_effect_class.value, "resource_conflict_key": self.resource_conflict_key}


@dataclass(frozen=True, slots=True)
class PoolReservation:
    task_id: str
    allocations: Mapping[str, int]
    policy_checksums: Mapping[str, str]
    reservation_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", identifier(self.task_id, "task_id"))
        allocations = {identifier(str(key), "pool_id"): value for key, value in self.allocations.items()}
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in allocations.values()):
            raise HarnessValidationError("pool allocation must be positive", code="CAPACITY_RESERVATION_INVALID")
        object.__setattr__(self, "allocations", frozen_mapping(allocations, "pool_reservation.allocations"))
        object.__setattr__(self, "policy_checksums", frozen_mapping(dict(self.policy_checksums), "pool_reservation.policy_checksums"))
        object.__setattr__(self, "reservation_checksum", canonical_payload_checksum(self.to_dict(include_checksum=False)))

    def to_dict(self, *, include_checksum: bool = True) -> dict[str, Any]:
        result = {"task_id": self.task_id, "allocations": thaw_mapping(self.allocations), "policy_checksums": thaw_mapping(self.policy_checksums)}
        if include_checksum:
            result["reservation_checksum"] = self.reservation_checksum
        return result


@dataclass(frozen=True, slots=True)
class FirstFitPacking:
    selected: tuple[str, ...]
    overflow: tuple[str, ...]
    reservations: tuple[PoolReservation, ...]
    reasons: Mapping[str, str]
    packing_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected", tuple(self.selected))
        object.__setattr__(self, "overflow", tuple(self.overflow))
        object.__setattr__(self, "reasons", frozen_mapping(dict(self.reasons), "packing.reasons"))
        object.__setattr__(self, "packing_checksum", canonical_payload_checksum(self.to_dict(include_checksum=False)))

    def to_dict(self, *, include_checksum: bool = True) -> dict[str, Any]:
        value = {"selected": list(self.selected), "overflow": list(self.overflow), "reservations": [item.to_dict() for item in self.reservations], "reasons": thaw_mapping(self.reasons)}
        if include_checksum:
            value["packing_checksum"] = self.packing_checksum
        return value


def pack_first_fit(
    task_ids: Sequence[str],
    demands: Mapping[str, TaskCapacityDemand],
    pools: Mapping[str, CapacityPool],
    *,
    max_tasks: int,
    occupied_resource_keys: frozenset[str] = frozenset(),
) -> FirstFitPacking:
    """Select tasks in supplied stable order; failed tasks never reserve partially."""
    if isinstance(max_tasks, bool) or not isinstance(max_tasks, int) or max_tasks < 1:
        raise HarnessValidationError("max_tasks must be positive", code="CAPACITY_POLICY_INVALID")
    remaining = {pool_id: pool.available for pool_id, pool in pools.items()}
    selected, overflow, reservations, reasons = [], [], [], {}
    occupied = set(occupied_resource_keys)
    seen = set()
    for raw_task_id in task_ids:
        task_id = identifier(raw_task_id, "task_id")
        if task_id in seen:
            raise HarnessValidationError("duplicate task in capacity packing", code="CAPACITY_DEMAND_INVALID")
        seen.add(task_id)
        demand = demands.get(task_id)
        reason = None
        if demand is None:
            reason = "CAPACITY_POLICY_MISSING"
        elif len(selected) >= max_tasks:
            reason = "CAPACITY_NOT_AVAILABLE"
        elif any(pool_id not in pools or remaining.get(pool_id, 0) < quantity for pool_id, quantity in demand.quantities.items()):
            reason = "CAPACITY_NOT_AVAILABLE"
        elif demand.side_effect_class is not SideEffectClass.READ_ONLY and demand.resource_conflict_key in occupied:
            reason = "RESOURCE_CONFLICT"
        if reason:
            overflow.append(task_id)
            reasons[task_id] = reason
            continue
        allocations = dict(demand.quantities)
        for pool_id, quantity in allocations.items():
            remaining[pool_id] -= quantity
        if demand.resource_conflict_key:
            occupied.add(demand.resource_conflict_key)
        selected.append(task_id)
        reservations.append(PoolReservation(task_id, allocations, {pool_id: pools[pool_id].policy_checksum for pool_id in allocations}))
    return FirstFitPacking(tuple(selected), tuple(overflow), tuple(reservations), reasons)
