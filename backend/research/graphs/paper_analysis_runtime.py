from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gate_registry import DeterministicGateRegistry
from framework.harness.graph.activity import HarnessWorkerType
from framework.harness.graph.bindings import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessLeafActivityBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.graph.definition import HarnessGraphDefinition
from framework.harness.graph.model import HarnessContractReference
from framework.harness.side_effects.registry import HarnessSideEffectRegistry
from framework.harness.workers.result import HarnessWorkerResult


@dataclass(frozen=True, slots=True)
class ResearchPaperAnalysisWorkerImplementation:
    worker_id: str
    worker_version: str
    worker_type: HarnessWorkerType
    delegate: Callable[[dict[str, Any]], HarnessWorkerResult]

    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        result = self.delegate(task)
        if not isinstance(result, HarnessWorkerResult):
            raise HarnessValidationError(
                "Research Graph worker returned an invalid result contract",
                code="research_graph_worker_result_invalid",
                details={"worker_ref": f"{self.worker_id}@{self.worker_version}"},
            )
        return result


@dataclass(frozen=True, slots=True)
class ResearchPaperAnalysisActivityImplementation:
    activity_contract_id: str
    activity_contract_version: str
    capabilities: HarnessActivityCapabilities = HarnessActivityCapabilities(
        stable_idempotency=True,
    )

    def dispatch(self, request: dict[str, Any]) -> object:
        raise HarnessValidationError(
            "Research Graph activity contracts are executed by the physical Graph dispatcher",
            code="graph_activity_dispatcher_required",
        )


def build_paper_analysis_runtime_binding_authority(
    *,
    definition: HarnessGraphDefinition,
    worker_implementations: Mapping[
        str,
        Callable[[dict[str, Any]], HarnessWorkerResult],
    ],
    gate_registry: DeterministicGateRegistry,
    side_effect_registry: HarnessSideEffectRegistry,
) -> HarnessRuntimeBindingAuthority:
    """Bind one exact Research Graph definition at the composition root."""

    if not isinstance(definition, HarnessGraphDefinition):
        raise TypeError("definition must be HarnessGraphDefinition")
    if not isinstance(gate_registry, DeterministicGateRegistry):
        raise TypeError("gate_registry must be DeterministicGateRegistry")
    if not isinstance(side_effect_registry, HarnessSideEffectRegistry):
        raise TypeError("side_effect_registry must be HarnessSideEffectRegistry")
    expected_activity_ids = set(definition.activity_ids)
    actual_activity_ids = set(worker_implementations)
    if actual_activity_ids != expected_activity_ids:
        raise HarnessValidationError(
            "Research runtime registrations must exactly cover the Graph definition",
            code="research_graph_runtime_registration_mismatch",
            details={
                "missing_activity_ids": sorted(
                    expected_activity_ids - actual_activity_ids
                ),
                "unexpected_activity_ids": sorted(
                    actual_activity_ids - expected_activity_ids
                ),
            },
        )

    workers: list[HarnessWorkerBinding] = []
    activities: list[HarnessActivityContractBinding] = []
    leaves: list[HarnessLeafActivityBinding] = []
    for activity in definition.activities:
        worker_ref, activity_ref = _activity_references(
            definition,
            activity.step_id,
        )
        delegate = worker_implementations[activity.step_id]
        if not callable(delegate):
            raise TypeError(
                f"worker implementation for {activity.step_id} must be callable"
            )
        workers.append(
            HarnessWorkerBinding(
                reference=worker_ref,
                worker_type=activity.worker_type,
                implementation=ResearchPaperAnalysisWorkerImplementation(
                    worker_id=worker_ref.contract_id,
                    worker_version=worker_ref.version,
                    worker_type=activity.worker_type,
                    delegate=delegate,
                ),
            )
        )
        activities.append(
            HarnessActivityContractBinding(
                reference=activity_ref,
                implementation=ResearchPaperAnalysisActivityImplementation(
                    activity_contract_id=activity_ref.contract_id,
                    activity_contract_version=activity_ref.version,
                ),
            )
        )
        leaf = definition.leaf_activity_binding(activity.step_id)
        if leaf is not None:
            leaves.append(
                HarnessLeafActivityBinding(
                    leaf_activity_kind=leaf.leaf_activity_kind,
                    worker_ref=leaf.worker_ref,
                    activity_ref=leaf.activity_ref,
                )
            )
        else:
            task_plan = definition.task_plan_stage_binding(activity.step_id)
            if task_plan is not None:
                leaves.append(
                    HarnessLeafActivityBinding(
                        leaf_activity_kind="task_plan",
                        worker_ref=task_plan.worker_ref,
                        activity_ref=task_plan.activity_ref,
                    )
                )

    return HarnessRuntimeBindingAuthority(
        workers=workers,
        activities=activities,
        leaf_activities=leaves,
        gate_registry=gate_registry,
        side_effect_registry=side_effect_registry,
    )


def _activity_references(
    definition: HarnessGraphDefinition,
    activity_id: str,
) -> tuple[HarnessContractReference, HarnessContractReference]:
    leaf = definition.leaf_activity_binding(activity_id)
    if leaf is not None:
        return leaf.worker_ref, leaf.activity_ref
    task_plan = definition.task_plan_stage_binding(activity_id)
    if task_plan is not None:
        return task_plan.worker_ref, task_plan.activity_ref
    raise HarnessValidationError(
        "Research Graph activity has no exact runtime binding declaration",
        code="research_graph_activity_binding_missing",
        details={"activity_id": activity_id},
    )


__all__ = [
    "ResearchPaperAnalysisActivityImplementation",
    "ResearchPaperAnalysisWorkerImplementation",
    "build_paper_analysis_runtime_binding_authority",
]
