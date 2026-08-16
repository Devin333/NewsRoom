from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gate_registry import (
    DeterministicGateRegistry,
    GateRegistration,
)
from framework.harness.graph.bindings import (
    HarnessActivityContractBinding,
    HarnessActivityUsage,
    HarnessLeafActivityBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.graph.definition import (
    HarnessGraphDefinition,
    HarnessGraphLeafBinding,
)
from framework.harness.graph.model import HarnessContractReference
from framework.harness.side_effects.models import HarnessSideEffectOrigin
from framework.harness.side_effects.registry import (
    HarnessSideEffectCapabilities,
    HarnessSideEffectHandler,
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectPreparationHandler,
    HarnessSideEffectRegistry,
)

from business.research.graphs.reader_repair import (
    READER_REPAIR_GRAPH_ID,
    READER_REPAIR_GRAPH_VERSION,
    build_reader_repair_graph_definition,
)
from business.research.graphs.reader_repair_execution_gates import (
    READER_REPAIR_EXECUTION_GATE_REFERENCES,
    build_reader_repair_execution_gate_registry,
)
from business.research.graphs.reader_repair_gates import (
    READER_REPAIR_GATE_REFERENCES,
    build_reader_repair_gate_registry,
)


READER_REPAIR_RUNTIME_BINDING_SCHEMA = (
    "newsroom.research-reader-repair-runtime-bindings/v1"
)


@dataclass(frozen=True, slots=True)
class ReaderRepairRuntimeBindingBundle:
    """Exact Graph v2 bindings prepared for composition, without installing them."""

    definition: HarnessGraphDefinition
    authority: HarnessRuntimeBindingAuthority

    def __post_init__(self) -> None:
        if not isinstance(self.definition, HarnessGraphDefinition):
            raise TypeError("definition must be HarnessGraphDefinition")
        if not isinstance(self.authority, HarnessRuntimeBindingAuthority):
            raise TypeError("authority must be HarnessRuntimeBindingAuthority")
        _verify_exact_bundle(self.definition, self.authority)

    def to_manifest(self) -> dict[str, Any]:
        workers: dict[str, dict[str, str]] = {}
        activities: dict[str, str] = {}
        gates: dict[str, list[str]] = {}
        for activity in self.definition.activities:
            leaf = _leaf_for(self.definition, activity.step_id)
            resolved = self.authority.resolve_leaf_activity(
                worker_ref=leaf.worker_ref,
                activity_ref=leaf.activity_ref,
                expected_leaf_activity_kind=leaf.leaf_activity_kind,
                required_usage=HarnessActivityUsage.SERIAL,
            )
            workers[activity.step_id] = {
                "reference": resolved.worker.reference.exact_ref,
                "worker_type": resolved.worker.worker_type.value,
            }
            activities[activity.step_id] = resolved.activity.reference.exact_ref
            if activity.quality_gate is None:  # pragma: no cover - invariant
                raise AssertionError("Reader Repair activity lacks a quality gate")
            gates[activity.step_id] = [
                str(binding.reference)
                for binding in self.authority.resolve_gate(activity.quality_gate)
            ]

        terminal = self.definition.terminal_side_effect_policy
        if terminal is None:  # pragma: no cover - invariant
            raise AssertionError("Reader Repair Graph lacks its memory terminal policy")
        side_effect = self.authority.resolve_side_effect(
            str(terminal.handler),
            kind=terminal.kind,
            origin=HarnessSideEffectOrigin.CONTROLLER_TERMINAL.value,
        )
        failure_terminal = self.definition.terminal_failure_side_effect_policy
        if failure_terminal is None:  # pragma: no cover - invariant
            raise AssertionError(
                "Reader Repair Graph lacks its failure diagnostic terminal policy"
            )
        failure_side_effect = self.authority.resolve_side_effect(
            str(failure_terminal.handler),
            kind=failure_terminal.kind,
            origin=HarnessSideEffectOrigin.CONTROLLER_TERMINAL.value,
        )
        return {
            "schema_version": READER_REPAIR_RUNTIME_BINDING_SCHEMA,
            "installs_runtime_authority": False,
            "graph_id": self.definition.graph_id,
            "graph_version": self.definition.graph_version,
            "graph_definition_checksum": self.definition.definition_checksum,
            "workers": workers,
            "activities": activities,
            "gates": gates,
            "terminal_side_effect": {
                "reference": str(side_effect.reference),
                "kind": side_effect.kind,
                "supports_origins": list(side_effect.supports_origins),
            },
            "terminal_failure_side_effect": {
                "reference": str(failure_side_effect.reference),
                "kind": failure_side_effect.kind,
                "supports_origins": list(failure_side_effect.supports_origins),
                "disposition": failure_terminal.disposition.value,
                "failure_record_schema": failure_terminal.failure_record_schema,
            },
        }


def build_reader_repair_runtime_binding_bundle(
    *,
    worker_implementations: Mapping[str, object],
    activity_implementations: Mapping[str, object],
    memory_side_effect_handler: HarnessSideEffectPreparationHandler,
    failure_diagnostic_side_effect_handler: HarnessSideEffectHandler,
) -> ReaderRepairRuntimeBindingBundle:
    """Build exact Reader Repair bindings without installing production authority."""

    if not isinstance(
        memory_side_effect_handler,
        HarnessSideEffectPreparationHandler,
    ):
        raise _registration_error(
            "Reader Repair memory handler must support prepare and terminal commit",
            registration_field="memory_side_effect_handler",
        )
    if not isinstance(
        failure_diagnostic_side_effect_handler,
        HarnessSideEffectHandler,
    ):
        raise _registration_error(
            "Reader Repair failure diagnostic handler must support terminal commit",
            registration_field="failure_diagnostic_side_effect_handler",
        )
    definition = build_reader_repair_graph_definition()
    activity_ids = {activity.step_id for activity in definition.activities}
    _require_exact_implementations(
        worker_implementations,
        activity_ids,
        field="worker_implementations",
    )
    _require_exact_implementations(
        activity_implementations,
        activity_ids,
        field="activity_implementations",
    )

    workers: list[HarnessWorkerBinding] = []
    activities: list[HarnessActivityContractBinding] = []
    leaves: list[HarnessLeafActivityBinding] = []
    for activity in definition.activities:
        leaf = _leaf_for(definition, activity.step_id)
        workers.append(
            HarnessWorkerBinding(
                reference=leaf.worker_ref,
                worker_type=activity.worker_type,
                implementation=worker_implementations[activity.step_id],
            )
        )
        activities.append(
            HarnessActivityContractBinding(
                reference=leaf.activity_ref,
                implementation=activity_implementations[activity.step_id],
            )
        )
        leaves.append(
            HarnessLeafActivityBinding(
                leaf_activity_kind=leaf.leaf_activity_kind,
                worker_ref=leaf.worker_ref,
                activity_ref=leaf.activity_ref,
            )
        )

    terminal = definition.terminal_side_effect_policy
    if terminal is None:  # pragma: no cover - invariant
        raise AssertionError("Reader Repair Graph lacks its memory terminal policy")
    memory_binding = HarnessSideEffectHandlerBinding(
        reference=terminal.handler,
        kind=terminal.kind,
        handler=memory_side_effect_handler,
        supports_origins=(
            HarnessSideEffectOrigin.WORKER.value,
            HarnessSideEffectOrigin.CONTROLLER_TERMINAL.value,
        ),
        capabilities=HarnessSideEffectCapabilities(stable_idempotency=True),
    )
    failure_terminal = definition.terminal_failure_side_effect_policy
    if failure_terminal is None:  # pragma: no cover - invariant
        raise AssertionError(
            "Reader Repair Graph lacks its failure diagnostic terminal policy"
        )
    failure_binding = HarnessSideEffectHandlerBinding(
        reference=failure_terminal.handler,
        kind=failure_terminal.kind,
        handler=failure_diagnostic_side_effect_handler,
        supports_origins=(HarnessSideEffectOrigin.CONTROLLER_TERMINAL.value,),
        capabilities=HarnessSideEffectCapabilities(stable_idempotency=True),
    )
    authority = HarnessRuntimeBindingAuthority(
        workers=workers,
        activities=activities,
        leaf_activities=leaves,
        gate_registry=_build_exact_gate_registry(definition),
        side_effect_registry=HarnessSideEffectRegistry(
            (memory_binding, failure_binding)
        ),
    )
    return ReaderRepairRuntimeBindingBundle(
        definition=definition,
        authority=authority,
    )


def _verify_exact_bundle(
    definition: HarnessGraphDefinition,
    authority: HarnessRuntimeBindingAuthority,
) -> None:
    definition.verify_integrity()
    if (
        definition.graph_id != READER_REPAIR_GRAPH_ID
        or definition.graph_version != READER_REPAIR_GRAPH_VERSION
    ):
        raise _registration_error(
            "runtime bundle must use the current Reader Repair Graph",
            expected_graph_ref=(
                f"{READER_REPAIR_GRAPH_ID}@{READER_REPAIR_GRAPH_VERSION}"
            ),
            actual_graph_ref=f"{definition.graph_id}@{definition.graph_version}",
        )

    expected_workers = set()
    expected_activities = set()
    expected_leaves = set()
    for activity in definition.activities:
        leaf = _leaf_for(definition, activity.step_id)
        expected_workers.add(leaf.worker_ref)
        expected_activities.add(leaf.activity_ref)
        expected_leaves.add(
            HarnessLeafActivityBinding(
                leaf_activity_kind=leaf.leaf_activity_kind,
                worker_ref=leaf.worker_ref,
                activity_ref=leaf.activity_ref,
            )
        )
        authority.resolve_leaf_activity(
            worker_ref=leaf.worker_ref,
            activity_ref=leaf.activity_ref,
            expected_leaf_activity_kind=leaf.leaf_activity_kind,
            required_usage=HarnessActivityUsage.SERIAL,
        )
        if activity.quality_gate is None:  # pragma: no cover - invariant
            raise AssertionError("Reader Repair activity lacks a quality gate")
        authority.resolve_gate(activity.quality_gate)
        if activity.side_effect_handler is not None:
            authority.resolve_side_effect(
                str(activity.side_effect_handler),
                origin=HarnessSideEffectOrigin.WORKER.value,
            )

    _require_exact_references(
        expected_workers,
        {binding.reference for binding in authority.worker_bindings},
        field="workers",
    )
    _require_exact_references(
        expected_activities,
        {binding.reference for binding in authority.activity_bindings},
        field="activities",
    )
    if set(authority.leaf_activity_bindings) != expected_leaves:
        raise _registration_error(
            "runtime bundle leaf registrations do not exactly match Graph v2",
            registration_field="leaf_activities",
        )

    terminal = definition.terminal_side_effect_policy
    if terminal is None:  # pragma: no cover - invariant
        raise AssertionError("Reader Repair Graph lacks its memory terminal policy")
    authority.resolve_side_effect(
        str(terminal.handler),
        kind=terminal.kind,
        origin=HarnessSideEffectOrigin.CONTROLLER_TERMINAL.value,
    )
    failure_terminal = definition.terminal_failure_side_effect_policy
    if failure_terminal is None:  # pragma: no cover - invariant
        raise AssertionError(
            "Reader Repair Graph lacks its failure diagnostic terminal policy"
        )
    authority.resolve_side_effect(
        str(failure_terminal.handler),
        kind=failure_terminal.kind,
        origin=HarnessSideEffectOrigin.CONTROLLER_TERMINAL.value,
    )


def _build_exact_gate_registry(
    definition: HarnessGraphDefinition,
) -> DeterministicGateRegistry:
    if definition.definition_checksum is None:  # pragma: no cover - invariant
        raise AssertionError("Reader Repair Graph checksum was not materialized")
    legacy_registry = build_reader_repair_gate_registry()
    execution_registry = build_reader_repair_execution_gate_registry(
        graph_definition_checksum=definition.definition_checksum,
    )
    legacy_refs = set(READER_REPAIR_GATE_REFERENCES)
    execution_refs = set(READER_REPAIR_EXECUTION_GATE_REFERENCES)
    declared_refs = {
        activity.quality_gate
        for activity in definition.activities
        if activity.quality_gate is not None
    }
    terminal = definition.terminal_side_effect_policy
    if terminal is not None:
        declared_refs.update(terminal.inherited_gate_refs)

    registrations: list[GateRegistration] = []
    for reference in sorted(declared_refs):
        if reference in execution_refs:
            binding = execution_registry.resolve(reference)
        elif reference in legacy_refs:
            binding = legacy_registry.resolve(reference)
        else:
            raise _registration_error(
                "Reader Repair Graph declares an unowned gate",
                gate_reference=reference,
            )
        registrations.append(
            GateRegistration(
                reference=binding.reference,
                gate=binding.gate,
                dependencies=binding.dependencies,
            )
        )
    return DeterministicGateRegistry(registrations)


def _leaf_for(
    definition: HarnessGraphDefinition,
    activity_id: str,
) -> HarnessGraphLeafBinding:
    leaf = definition.leaf_activity_binding(activity_id)
    if leaf is None:  # pragma: no cover - GraphDefinition invariant
        raise AssertionError("Reader Repair activity lacks a leaf binding")
    return leaf


def _require_exact_implementations(
    implementations: Mapping[str, object],
    expected: set[str],
    *,
    field: str,
) -> None:
    if not isinstance(implementations, Mapping):
        raise TypeError(f"{field} must be a mapping")
    actual = set(implementations)
    if any(not isinstance(key, str) or not key for key in actual):
        raise TypeError(f"{field} keys must be non-empty strings")
    if actual != expected:
        raise _registration_error(
            "Reader Repair runtime registrations must exactly cover Graph v2",
            registration_field=field,
            missing_activity_ids=sorted(expected - actual),
            unexpected_activity_ids=sorted(actual - expected),
        )


def _require_exact_references(
    expected: set[HarnessContractReference],
    actual: set[HarnessContractReference],
    *,
    field: str,
) -> None:
    if actual == expected:
        return
    raise _registration_error(
        "Reader Repair runtime references do not exactly match Graph v2",
        registration_field=field,
        missing_references=sorted(
            item.exact_ref for item in expected - actual
        ),
        unexpected_references=sorted(
            item.exact_ref for item in actual - expected
        ),
    )


def _registration_error(message: str, **details: object) -> HarnessValidationError:
    return HarnessValidationError(
        message,
        code="reader_repair_runtime_registration_mismatch",
        details={
            "code": "reader_repair_runtime_registration_mismatch",
            **details,
        },
    )


__all__ = [
    "READER_REPAIR_RUNTIME_BINDING_SCHEMA",
    "ReaderRepairRuntimeBindingBundle",
    "build_reader_repair_runtime_binding_bundle",
]
