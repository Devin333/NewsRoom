from __future__ import annotations

from collections.abc import Mapping

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_state import (
    HarnessCompensationEntry,
    HarnessCompensationStatus,
    HarnessGraphState,
    HarnessNodeInstanceState,
    HarnessNodeInstanceStatus,
)
from framework.harness.graph.canonical import thaw_json
from framework.harness.graph.model import HarnessExecutableNode


def compensation_entry_for_node(
    state: HarnessGraphState,
    node: HarnessNodeInstanceState,
    *,
    require_running: bool = True,
) -> HarnessCompensationEntry:
    """Resolve the one durable compensation entry owned by a node instance."""
    matches = tuple(
        item
        for item in state.compensation_stack
        if item.compensation_node_instance_id == node.instance_id
    )
    if len(matches) != 1:
        raise HarnessValidationError(
            "compensation node must have exactly one durable entry",
            code="graph_compensation_binding_mismatch",
            details={
                "node_instance_id": node.instance_id,
                "entry_count": len(matches),
            },
        )
    entry = matches[0]
    if require_running and entry.status is not HarnessCompensationStatus.RUNNING:
        raise HarnessValidationError(
            "compensation phase requires a running durable entry",
            code="graph_compensation_entry_state_mismatch",
            details={
                "node_instance_id": node.instance_id,
                "status": entry.status.value,
            },
        )
    if require_running and node.status is not HarnessNodeInstanceStatus.COMPENSATING:
        raise HarnessValidationError(
            "running compensation entry requires a compensating node",
            code="compensation_node_state_mismatch",
        )
    if entry.compensation_node_instance_id != node.instance_id:
        raise HarnessValidationError(
            "compensation entry points to another node instance",
            code="cross_node_compensation_rejected",
        )
    if require_running:
        _validate_runtime_metadata(entry, node)
    return entry


def compensation_binding_versions(
    definition: HarnessExecutableNode,
    *,
    state: HarnessGraphState | None = None,
    node: HarnessNodeInstanceState | None = None,
) -> dict[str, str]:
    """Return exact Step bindings, replacing activity with compensation activity."""
    bindings = {
        "step": definition.step_ref.exact_ref,
        "worker": definition.worker_ref.exact_ref,
        "activity": definition.activity_ref.exact_ref,
    }
    bindings.update(
        {
            f"gate:{index:04d}": reference.exact_ref
            for index, reference in enumerate(definition.gate_refs)
        }
    )
    is_compensation = (
        state is not None
        and node is not None
        and node.status is HarnessNodeInstanceStatus.COMPENSATING
    )
    if is_compensation:
        entry = compensation_entry_for_node(state, node)
        bindings["activity"] = entry.activity_ref.exact_ref
        bindings["compensation"] = entry.handler_ref.exact_ref
    elif definition.side_effect_ref is not None:
        bindings["side_effect"] = definition.side_effect_ref.exact_ref
    return bindings


def _validate_runtime_metadata(
    entry: HarnessCompensationEntry,
    node: HarnessNodeInstanceState,
) -> None:
    metadata = thaw_json(node.metadata)
    if not isinstance(metadata, Mapping):  # pragma: no cover - frozen-state invariant
        raise HarnessValidationError(
            "compensation node metadata is not an object",
            code="graph_compensation_binding_mismatch",
        )
    expected = {
        "compensation_entry_id": entry.entry_id,
        "origin_node_instance_id": entry.origin_node_instance_id,
        "effect_outcome_ref": entry.effect_outcome_ref,
        "compensation_handler_ref": entry.handler_ref.exact_ref,
        "compensation_activity_ref": entry.activity_ref.exact_ref,
        "compensation_idempotency_key": entry.idempotency_key,
        "compensation_fencing_generation": entry.fencing_generation,
    }
    mismatches = [
        key
        for key, value in expected.items()
        if metadata.get(key) != value
    ]
    if mismatches:
        raise HarnessValidationError(
            "compensation node metadata does not match its durable entry",
            code="graph_compensation_binding_mismatch",
            details={"mismatches": mismatches},
        )


__all__ = [
    "compensation_binding_versions",
    "compensation_entry_for_node",
]
