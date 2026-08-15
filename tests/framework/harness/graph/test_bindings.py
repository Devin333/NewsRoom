from __future__ import annotations

from dataclasses import dataclass

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gate_registry import (
    DeterministicGateRegistry,
    GateReference,
    GateRegistration,
)
from framework.harness.control_plane.gates import DeterministicGate
from framework.harness.side_effects.registry import (
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectRegistry,
)
from framework.harness.graph.bindings import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessActivityUsage,
    HarnessCompensationHandlerBinding,
    HarnessDeterministicMergeBinding,
    HarnessLeafActivityBinding,
    HarnessResolvedLeafActivityBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.graph.activity import HarnessLeafActivityKind
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.workers.result import HarnessWorkerResult


def test_authority_resolves_pre_registered_exact_runtime_bindings() -> None:
    worker = _Worker()
    activity = _Activity(capabilities=_safe_capabilities())
    compensation = _Compensation()
    merge = _Merge()
    gate = _Gate("candidate.schema", "1")
    side_effect = _SideEffectHandler()
    authority = HarnessRuntimeBindingAuthority(
        workers=(HarnessWorkerBinding("research.collect@1", "script", worker),),
        activities=(
            HarnessActivityContractBinding(
                "newsroom.harness-worker-activity@v1",
                activity,
            ),
        ),
        compensations=(
            HarnessCompensationHandlerBinding("research.undo@1", compensation),
        ),
        merges=(HarnessDeterministicMergeBinding("research.merge@1", merge),),
        gate_registry=DeterministicGateRegistry(
            (
                GateRegistration(
                    reference=GateReference("candidate.schema", "1"),
                    gate=gate,
                ),
            )
        ),
        side_effect_registry=HarnessSideEffectRegistry(
            (
                HarnessSideEffectHandlerBinding(
                    "research.publish@1",
                    "artifact",
                    side_effect,
                    supports_origins=("worker",),
                ),
            )
        ),
    )

    assert (
        authority.resolve_worker(
            "research.collect@1",
            expected_worker_type="script",
        ).implementation
        is worker
    )
    assert (
        authority.resolve_activity(
            "newsroom.harness-worker-activity@v1",
            required_usage=HarnessActivityUsage.PARALLEL,
        ).implementation
        is activity
    )
    assert (
        authority.resolve_compensation("research.undo@1").implementation
        is compensation
    )
    assert authority.resolve_merge("research.merge@1").implementation is merge
    assert [
        str(binding.reference)
        for binding in authority.resolve_gate("candidate.schema@1")
    ] == ["candidate.schema@1"]
    assert (
        authority.resolve_side_effect(
            "research.publish@1",
            kind="artifact",
            origin="worker",
        ).handler
        is side_effect
    )


@pytest.mark.parametrize("kind", tuple(HarnessLeafActivityKind))
def test_authority_resolves_exact_typed_leaf_activity_pair(
    kind: HarnessLeafActivityKind,
) -> None:
    worker_ref = f"worker.{kind.value}@1"
    activity_ref = f"activity.{kind.value}@v1"
    registration = HarnessLeafActivityBinding(
        leaf_activity_kind=kind,
        worker_ref=worker_ref,
        activity_ref=activity_ref,
    )
    authority = HarnessRuntimeBindingAuthority(
        workers=(
            HarnessWorkerBinding(
                worker_ref,
                kind.value,
                _Worker(
                    worker_id=f"worker.{kind.value}",
                    worker_type=kind.value,
                ),
            ),
        ),
        activities=(
            HarnessActivityContractBinding(
                activity_ref,
                _Activity(activity_contract_id=f"activity.{kind.value}"),
            ),
        ),
        leaf_activities=(registration,),
    )

    resolved = authority.resolve_leaf_activity(
        worker_ref=worker_ref,
        activity_ref=activity_ref,
        expected_leaf_activity_kind=kind,
    )

    assert isinstance(resolved, HarnessResolvedLeafActivityBinding)
    assert resolved.leaf_activity_kind is kind
    assert resolved.worker.reference.exact_ref == worker_ref
    assert resolved.activity.reference.exact_ref == activity_ref
    assert authority.leaf_activity_bindings == (registration,)
    assert HarnessLeafActivityBinding.from_dict(registration.to_dict()) == registration


@pytest.mark.parametrize(
    ("kind", "legacy_worker_type"),
    (
        (HarnessLeafActivityKind.FUNCTION, "script"),
        (HarnessLeafActivityKind.TOOL, "mcp"),
    ),
)
def test_leaf_registration_rejects_legacy_worker_type_aliases(
    kind: HarnessLeafActivityKind,
    legacy_worker_type: str,
) -> None:
    worker_ref = f"worker.{kind.value}@1"
    activity_ref = f"activity.{kind.value}@v1"

    with pytest.raises(HarnessValidationError) as captured:
        HarnessRuntimeBindingAuthority(
            workers=(
                HarnessWorkerBinding(
                    worker_ref,
                    legacy_worker_type,
                    _Worker(
                        worker_id=f"worker.{kind.value}",
                        worker_type=legacy_worker_type,
                    ),
                ),
            ),
            activities=(
                HarnessActivityContractBinding(
                    activity_ref,
                    _Activity(activity_contract_id=f"activity.{kind.value}"),
                ),
            ),
            leaf_activities=(
                HarnessLeafActivityBinding(kind, worker_ref, activity_ref),
            ),
        )

    assert captured.value.code == "leaf_activity_worker_type_mismatch"
    assert captured.value.details["expected_worker_type"] == kind.value
    assert captured.value.details["actual_worker_type"] == legacy_worker_type


def test_leaf_resolution_rejects_kind_mismatch_and_unregistered_pair() -> None:
    worker_ref = "worker.skill@1"
    activity_ref = "activity.skill@v1"
    authority = HarnessRuntimeBindingAuthority(
        workers=(
            HarnessWorkerBinding(
                worker_ref,
                "skill",
                _Worker(worker_id="worker.skill", worker_type="skill"),
            ),
        ),
        activities=(
            HarnessActivityContractBinding(
                activity_ref,
                _Activity(activity_contract_id="activity.skill"),
            ),
        ),
        leaf_activities=(
            HarnessLeafActivityBinding("skill", worker_ref, activity_ref),
        ),
    )

    with pytest.raises(HarnessValidationError) as mismatch:
        authority.resolve_leaf_activity(
            worker_ref=worker_ref,
            activity_ref=activity_ref,
            expected_leaf_activity_kind="subagent",
        )
    with pytest.raises(HarnessValidationError) as unregistered:
        authority.resolve_leaf_activity(
            worker_ref=worker_ref,
            activity_ref="activity.other@v1",
            expected_leaf_activity_kind="skill",
        )

    assert mismatch.value.code == "runtime_leaf_activity_kind_mismatch"
    assert mismatch.value.details["actual_leaf_activity_kind"] == "skill"
    assert unregistered.value.code == "unknown_leaf_activity_binding"


@pytest.mark.parametrize(
    "binding_factory",
    (
        lambda: HarnessWorkerBinding(
            "research.collect@1",
            "script",
            _Worker(worker_version="2"),
        ),
        lambda: HarnessActivityContractBinding(
            "newsroom.harness-worker-activity@v1",
            _Activity(activity_contract_version="v2"),
        ),
        lambda: HarnessCompensationHandlerBinding(
            "research.undo@1",
            _Compensation(compensation_handler_version="2"),
        ),
        lambda: HarnessDeterministicMergeBinding(
            "research.merge@1",
            _Merge(merge_version="2"),
        ),
    ),
)
def test_registration_rejects_implementation_identity_or_version_mismatch(
    binding_factory,
) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        binding_factory()

    assert captured.value.code == "runtime_contract_implementation_mismatch"


@pytest.mark.parametrize(
    "binding_factory",
    (
        lambda: HarnessWorkerBinding(
            "research.collect@1",
            "script",
            _Worker(worker_version="latest"),
        ),
        lambda: HarnessActivityContractBinding(
            "newsroom.harness-worker-activity@v1",
            _Activity(activity_contract_version="current"),
        ),
        lambda: HarnessCompensationHandlerBinding(
            "research.undo@1",
            _Compensation(compensation_handler_version="stable"),
        ),
        lambda: HarnessDeterministicMergeBinding(
            "research.merge@1",
            _Merge(merge_version="default"),
        ),
    ),
)
def test_registration_rejects_moving_implementation_versions(binding_factory) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        binding_factory()

    assert captured.value.code == "invalid_runtime_contract_implementation"


def test_graph_reference_cannot_create_or_complete_an_authority_registration() -> None:
    graph_reference = HarnessContractReference(
        HarnessContractKind.WORKER,
        "research.collect",
        "1",
    )
    authority = HarnessRuntimeBindingAuthority()

    with pytest.raises(HarnessValidationError) as captured:
        authority.resolve_worker(
            graph_reference,
            expected_worker_type="script",
        )

    assert captured.value.code == "unknown_runtime_contract_binding"
    assert captured.value.details["reference"] == "research.collect@1"


@pytest.mark.parametrize(
    "resolver",
    (
        lambda authority: authority.resolve_worker(
            "research.collect@2",
            expected_worker_type="script",
        ),
        lambda authority: authority.resolve_activity(
            "newsroom.harness-worker-activity@v2"
        ),
        lambda authority: authority.resolve_compensation("research.undo@2"),
        lambda authority: authority.resolve_merge("research.merge@2"),
    ),
)
def test_unknown_exact_versions_fail_closed(resolver) -> None:
    authority = _runtime_authority()

    with pytest.raises(HarnessValidationError) as captured:
        resolver(authority)

    assert captured.value.code == "unknown_runtime_contract_binding"


@pytest.mark.parametrize(
    "reference",
    (
        "research.collect",
        "research.collect@latest",
        " research.collect@1",
        "research.collect@1 ",
    ),
)
def test_invalid_or_moving_runtime_references_fail_closed(reference: str) -> None:
    authority = _runtime_authority()

    with pytest.raises(HarnessValidationError) as captured:
        authority.resolve_worker(reference, expected_worker_type="script")

    assert captured.value.code == "invalid_runtime_contract_reference"


def test_resolver_rejects_contract_kind_mismatch() -> None:
    authority = _runtime_authority()
    gate_reference = HarnessContractReference(
        HarnessContractKind.GATE,
        "research.collect",
        "1",
    )

    with pytest.raises(HarnessValidationError) as captured:
        authority.resolve_worker(gate_reference, expected_worker_type="script")

    assert captured.value.code == "runtime_contract_kind_mismatch"
    assert captured.value.details["expected_kind"] == "worker"
    assert captured.value.details["actual_kind"] == "gate"


def test_worker_binding_requires_matching_graph_worker_type() -> None:
    authority = _runtime_authority()

    with pytest.raises(HarnessValidationError) as captured:
        authority.resolve_worker(
            "research.collect@1",
            expected_worker_type="llm",
        )

    assert captured.value.code == "runtime_worker_type_mismatch"
    assert captured.value.details["actual_worker_type"] == "script"


def test_worker_registration_requires_normalized_execute_port() -> None:
    class WorkerWithoutExecute:
        worker_id = "research.collect"
        worker_version = "1"
        worker_type = "script"

    with pytest.raises(HarnessValidationError) as captured:
        HarnessWorkerBinding(
            "research.collect@1",
            "script",
            WorkerWithoutExecute(),
        )

    assert captured.value.code == "invalid_runtime_contract_implementation"


def test_serial_activity_does_not_invent_parallel_or_compensation_safety() -> None:
    activity = _Activity(
        capabilities=HarnessActivityCapabilities(stable_idempotency=True)
    )
    authority = HarnessRuntimeBindingAuthority(
        activities=(
            HarnessActivityContractBinding(
                "newsroom.harness-worker-activity@v1",
                activity,
            ),
        )
    )

    assert (
        authority.resolve_activity(
            "newsroom.harness-worker-activity@v1",
            required_usage="serial",
        ).implementation
        is activity
    )
    for usage in (HarnessActivityUsage.PARALLEL, HarnessActivityUsage.COMPENSATION):
        with pytest.raises(HarnessValidationError) as captured:
            authority.resolve_activity(
                "newsroom.harness-worker-activity@v1",
                required_usage=usage,
            )
        assert captured.value.code == "activity_contract_safety_unproven"
        assert captured.value.details["usage"] == usage.value
        assert captured.value.details["missing_capabilities"] == (
            "termination_confirmation",
            "fencing",
            "reconciliation",
        )


def test_fully_qualified_activity_is_explicitly_safe_for_bounded_reexecution() -> None:
    capabilities = _safe_capabilities()
    authority = HarnessRuntimeBindingAuthority(
        activities=(
            HarnessActivityContractBinding(
                "newsroom.harness-worker-activity@v1",
                _Activity(capabilities=capabilities),
            ),
        )
    )

    assert capabilities.parallel_safe
    assert capabilities.compensation_safe
    assert (
        authority.resolve_activity(
            "newsroom.harness-worker-activity@v1",
            required_usage="parallel",
        ).capabilities
        is capabilities
    )
    assert (
        authority.resolve_activity(
            "newsroom.harness-worker-activity@v1",
            required_usage="compensation",
        ).capabilities
        is capabilities
    )


def test_merge_registration_requires_explicit_determinism_and_sync_callable() -> None:
    with pytest.raises(HarnessValidationError) as non_deterministic:
        HarnessDeterministicMergeBinding(
            "research.merge@1",
            _Merge(deterministic=False),
        )

    with pytest.raises(HarnessValidationError) as asynchronous:
        HarnessDeterministicMergeBinding(
            "research.merge@1",
            _AsyncMerge(),
        )

    assert non_deterministic.value.code == "merge_determinism_unproven"
    assert asynchronous.value.code == "invalid_runtime_contract_implementation"


def test_duplicate_exact_bindings_are_rejected_without_last_writer_wins() -> None:
    first = HarnessWorkerBinding("research.collect@1", "script", _Worker())
    second = HarnessWorkerBinding("research.collect@1", "script", _Worker())

    with pytest.raises(HarnessValidationError) as captured:
        HarnessRuntimeBindingAuthority(workers=(first, second))

    assert captured.value.code == "duplicate_runtime_contract_binding"


def test_binding_views_are_stable_and_do_not_expose_mutation() -> None:
    authority = HarnessRuntimeBindingAuthority(
        workers=(
            HarnessWorkerBinding(
                "research.report@2",
                "llm",
                _Worker(
                    worker_id="research.report",
                    worker_version="2",
                    worker_type="llm",
                ),
            ),
            HarnessWorkerBinding("research.collect@1", "script", _Worker()),
        )
    )

    assert [binding.reference.exact_ref for binding in authority.worker_bindings] == [
        "research.collect@1",
        "research.report@2",
    ]
    assert isinstance(authority.worker_bindings, tuple)


def test_gate_resolution_reuses_exact_registry_and_dependency_closure() -> None:
    dependency = _Gate("dependency.schema", "1")
    root = _Gate("candidate.schema", "2")
    registry = DeterministicGateRegistry(
        (
            GateRegistration(GateReference("dependency.schema", "1"), dependency),
            GateRegistration(
                GateReference("candidate.schema", "2"),
                root,
                dependencies=(GateReference("dependency.schema", "1"),),
            ),
        )
    )
    authority = HarnessRuntimeBindingAuthority(gate_registry=registry)

    assert [
        str(binding.reference)
        for binding in authority.resolve_gate("candidate.schema@2")
    ] == [
        "dependency.schema@1",
        "candidate.schema@2",
    ]

    with pytest.raises(HarnessValidationError) as missing:
        authority.resolve_gate("candidate.schema@3")
    assert missing.value.code == "unknown_gate_reference"


def test_side_effect_resolution_reuses_kind_and_origin_checks() -> None:
    registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding(
                "research.publish@1",
                "artifact",
                _SideEffectHandler(),
                supports_origins=("controller_terminal",),
            ),
        )
    )
    authority = HarnessRuntimeBindingAuthority(side_effect_registry=registry)

    with pytest.raises(HarnessValidationError) as kind_mismatch:
        authority.resolve_side_effect("research.publish@1", kind="email")
    with pytest.raises(HarnessValidationError) as origin_mismatch:
        authority.resolve_side_effect("research.publish@1", origin="worker")

    assert kind_mismatch.value.code == "side_effect_handler_kind_mismatch"
    assert origin_mismatch.value.code == "side_effect_handler_origin_mismatch"


def _runtime_authority() -> HarnessRuntimeBindingAuthority:
    return HarnessRuntimeBindingAuthority(
        workers=(
            HarnessWorkerBinding(
                "research.collect@1",
                "script",
                _Worker(),
            ),
        ),
        activities=(
            HarnessActivityContractBinding(
                "newsroom.harness-worker-activity@v1",
                _Activity(),
            ),
        ),
        compensations=(
            HarnessCompensationHandlerBinding(
                "research.undo@1",
                _Compensation(),
            ),
        ),
        merges=(
            HarnessDeterministicMergeBinding(
                "research.merge@1",
                _Merge(),
            ),
        ),
    )


def _safe_capabilities() -> HarnessActivityCapabilities:
    return HarnessActivityCapabilities(
        termination_confirmation=True,
        stable_idempotency=True,
        fencing=True,
        reconciliation=True,
    )


@dataclass
class _Worker:
    worker_id: str = "research.collect"
    worker_version: str = "1"
    worker_type: str = "script"

    def execute(self, task: dict) -> HarnessWorkerResult:
        return HarnessWorkerResult("succeeded", output=dict(task))


@dataclass
class _Activity:
    activity_contract_id: str = "newsroom.harness-worker-activity"
    activity_contract_version: str = "v1"
    capabilities: HarnessActivityCapabilities = HarnessActivityCapabilities()

    def dispatch(self, request: dict) -> HarnessWorkerResult:
        return HarnessWorkerResult("succeeded", output=dict(request))


@dataclass
class _Compensation:
    compensation_handler_id: str = "research.undo"
    compensation_handler_version: str = "1"

    def compensate(self, request: dict) -> HarnessWorkerResult:
        return HarnessWorkerResult("succeeded", output=dict(request))


@dataclass
class _Merge:
    merge_id: str = "research.merge"
    merge_version: str = "1"
    deterministic: bool = True

    def __call__(self, branch_outputs: dict) -> dict:
        return dict(branch_outputs)


class _AsyncMerge:
    merge_id = "research.merge"
    merge_version = "1"
    deterministic = True

    async def __call__(self, branch_outputs: dict) -> dict:
        return dict(branch_outputs)


class _Gate(DeterministicGate):
    def __init__(self, gate_name: str, gate_version: str) -> None:
        self.gate_name = gate_name
        self.gate_version = gate_version


class _SideEffectHandler:
    def commit(self, intent, authorization):
        raise AssertionError("binding tests must not execute side effects")
