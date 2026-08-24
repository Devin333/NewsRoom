from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework.events.canonical import checksum_for
from framework.harness.control_plane.state import HarnessRunSpec, run_spec_checksum
from interfaces.models.actor import ActorContext
from interfaces.services.harness_wait_runtime import (
    DurableHarnessWaitApprovalResolver,
    HarnessWaitRuntimeRegistry,
    HarnessWaitRuntimeStoreError,
    HarnessWaitRuntimeUnavailableError,
)
from interfaces.services.harness_wait_service import (
    HarnessWaitActorScope,
    HarnessWaitApplicationService,
    HarnessWaitNotFoundError,
    HarnessWaitRequestError,
)

from tests.interfaces.services.test_harness_wait_service import (
    _ActorScopeResolver,
    _waiting_service,
)


def _actor() -> ActorContext:
    return ActorContext(
        actor_id="actor-1",
        actor_type="user",
        roles=["admin"],
        request_id="runtime-registry-test",
    )


def test_run_spec_round_trip_preserves_full_checksum() -> None:
    service, _registration, resolver = _waiting_service("registry-round-trip")
    binding = resolver.binding

    restored = HarnessRunSpec.from_dict(binding.run_spec.to_dict())

    assert run_spec_checksum(restored) == run_spec_checksum(binding.run_spec)
    assert restored == binding.run_spec


def test_runtime_registry_persists_immutable_identity_and_rehydrates_binding(
    tmp_path: Path,
) -> None:
    _service, _registration, resolver = _waiting_service("registry-persist")
    binding = resolver.binding
    tenant_scope_ref = binding.run_spec.metadata["tenant_scope_ref"]
    identity_scope_ref = binding.run_spec.metadata["identity_scope_ref"]

    registry = HarnessWaitRuntimeRegistry(tmp_path)
    registry.register(
        binding.run_spec,
        binding.control_plane,
        tenant_scope_ref=tenant_scope_ref,
        identity_scope_ref=identity_scope_ref,
    )

    restarted = HarnessWaitRuntimeRegistry(
        tmp_path,
        rehydrator=lambda registration, _actor: binding,
    )
    resolved = restarted.resolve(binding.run_spec.run_id, actor=_actor())

    assert resolved.run_spec == binding.run_spec
    assert restarted.registration(binding.run_spec.run_id) is not None
    payload = (tmp_path / "runtime-bindings.json").read_text(encoding="utf-8")
    assert "run_spec_checksum" in payload
    assert binding.run_spec.graph.definition_checksum in payload


def test_runtime_registry_fails_closed_without_live_rehydrator(tmp_path: Path) -> None:
    _service, _registration, resolver = _waiting_service("registry-restart")
    binding = resolver.binding
    registry = HarnessWaitRuntimeRegistry(tmp_path)
    registry.register(
        binding.run_spec,
        binding.control_plane,
        tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
        identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
    )

    restarted = HarnessWaitRuntimeRegistry(tmp_path)
    with pytest.raises(HarnessWaitRuntimeUnavailableError):
        restarted.resolve(binding.run_spec.run_id, actor=_actor())


def test_runtime_registry_rejects_tampered_persisted_graph(tmp_path: Path) -> None:
    _service, _registration, resolver = _waiting_service("registry-tamper")
    binding = resolver.binding
    registry = HarnessWaitRuntimeRegistry(tmp_path)
    registry.register(
        binding.run_spec,
        binding.control_plane,
        tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
        identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
    )
    path = tmp_path / "runtime-bindings.json"
    payload = path.read_text(encoding="utf-8").replace(
        binding.run_spec.graph.definition_checksum,
        checksum_for({"tampered": True}),
        1,
    )
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(HarnessWaitRuntimeStoreError):
        HarnessWaitRuntimeRegistry(tmp_path)


def test_runtime_registry_merges_registrations_from_stale_process_snapshots(
    tmp_path: Path,
) -> None:
    _service_one, _registration_one, resolver_one = _waiting_service("registry-merge-1")
    _service_two, _registration_two, resolver_two = _waiting_service("registry-merge-2")
    binding_one = resolver_one.binding
    binding_two = resolver_two.binding
    first = HarnessWaitRuntimeRegistry(tmp_path)
    second = HarnessWaitRuntimeRegistry(tmp_path)

    first.register(
        binding_one.run_spec,
        binding_one.control_plane,
        tenant_scope_ref=binding_one.run_spec.metadata["tenant_scope_ref"],
        identity_scope_ref=binding_one.run_spec.metadata["identity_scope_ref"],
    )
    second.register(
        binding_two.run_spec,
        binding_two.control_plane,
        tenant_scope_ref=binding_two.run_spec.metadata["tenant_scope_ref"],
        identity_scope_ref=binding_two.run_spec.metadata["identity_scope_ref"],
    )

    persisted = HarnessWaitRuntimeRegistry(tmp_path)
    assert persisted.registration(binding_one.run_spec.run_id) is not None
    assert persisted.registration(binding_two.run_spec.run_id) is not None


def test_durable_approval_resolver_binds_decision_and_reuses_identical_retry(
    tmp_path: Path,
) -> None:
    _service, registration, resolver = _waiting_service(
        "registry-approval",
        wait_kind="approval",
    )
    binding = resolver.binding
    registry = HarnessWaitRuntimeRegistry(tmp_path)
    registry.register(
        binding.run_spec,
        binding.control_plane,
        tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
        identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
    )
    actor = _actor()
    actor_scope_resolver = _ActorScopeResolver(
        HarnessWaitActorScope(
            tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
            identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
            actor_identity_scope_ref=checksum_for({"actor": "actor-1"}),
        )
    )
    approval_resolver = DurableHarnessWaitApprovalResolver(
        runtime_resolver=registry,
        actor_scope_resolver=actor_scope_resolver,
        root=tmp_path,
    )
    service = HarnessWaitApplicationService(
        actor=actor,
        runtime_resolver=registry,
        actor_scope_resolver=actor_scope_resolver,
        approval_resolver=approval_resolver,
    )

    first = service.decide_approval(
        binding.run_spec.run_id,
        registration.node_instance_id,
        approval_id="approval-1",
        approved=True,
    )
    retry = service.decide_approval(
        binding.run_spec.run_id,
        registration.node_instance_id,
        approval_id="approval-1",
        approved=True,
    )

    assert first.wait.outcome == "succeeded"
    assert retry.wait.last_event_sequence == first.wait.last_event_sequence
    assert (tmp_path / "approval-decisions.json").exists()


def test_durable_approval_resolver_rejects_actor_scope_mismatch(tmp_path: Path) -> None:
    _service, registration, resolver = _waiting_service(
        "registry-approval-scope",
        wait_kind="approval",
    )
    binding = resolver.binding
    registry = HarnessWaitRuntimeRegistry(tmp_path)
    registry.register(
        binding.run_spec,
        binding.control_plane,
        tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
        identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
    )
    wrong_scope = HarnessWaitActorScope(
        tenant_scope_ref=checksum_for({"tenant": "other"}),
        identity_scope_ref=checksum_for({"identity": "other"}),
        actor_identity_scope_ref=checksum_for({"actor": "actor-1"}),
    )
    resolver_service = HarnessWaitApplicationService(
        actor=_actor(),
        runtime_resolver=registry,
        actor_scope_resolver=_ActorScopeResolver(wrong_scope),
        approval_resolver=DurableHarnessWaitApprovalResolver(
            runtime_resolver=registry,
            actor_scope_resolver=_ActorScopeResolver(wrong_scope),
            root=tmp_path,
        ),
    )

    with pytest.raises(HarnessWaitNotFoundError) as exc_info:
        resolver_service.decide_approval(
            binding.run_spec.run_id,
            registration.node_instance_id,
            approval_id="approval-1",
            approved=True,
        )
    assert exc_info.value.code == "wait_not_found"


def test_durable_approval_resolver_rejects_conflicting_retry(tmp_path: Path) -> None:
    _service, registration, resolver = _waiting_service(
        "registry-approval-conflict",
        wait_kind="approval",
    )
    binding = resolver.binding
    registry = HarnessWaitRuntimeRegistry(tmp_path)
    registry.register(
        binding.run_spec,
        binding.control_plane,
        tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
        identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
    )
    scope_resolver = _ActorScopeResolver(
        HarnessWaitActorScope(
            tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
            identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
            actor_identity_scope_ref=checksum_for({"actor": "actor-1"}),
        )
    )
    approval_resolver = DurableHarnessWaitApprovalResolver(
        runtime_resolver=registry,
        actor_scope_resolver=scope_resolver,
        root=tmp_path,
    )
    service = HarnessWaitApplicationService(
        actor=_actor(),
        runtime_resolver=registry,
        actor_scope_resolver=scope_resolver,
        approval_resolver=approval_resolver,
    )
    service.decide_approval(
        binding.run_spec.run_id,
        registration.node_instance_id,
        approval_id="approval-1",
        approved=True,
    )

    with pytest.raises(HarnessWaitRequestError) as exc_info:
        service.decide_approval(
            binding.run_spec.run_id,
            registration.node_instance_id,
            approval_id="approval-1",
            approved=False,
        )
    assert exc_info.value.code == "wait_approval_decision_conflict"


def test_durable_approval_resolver_rejects_new_decision_after_wait_is_resolved(
    tmp_path: Path,
) -> None:
    _service, registration, resolver = _waiting_service(
        "registry-approval-stale",
        wait_kind="approval",
    )
    binding = resolver.binding
    registry = HarnessWaitRuntimeRegistry(tmp_path)
    registry.register(
        binding.run_spec,
        binding.control_plane,
        tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
        identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
    )
    scope_resolver = _ActorScopeResolver(
        HarnessWaitActorScope(
            tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
            identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
            actor_identity_scope_ref=checksum_for({"actor": "actor-1"}),
        )
    )
    service = HarnessWaitApplicationService(
        actor=_actor(),
        runtime_resolver=registry,
        actor_scope_resolver=scope_resolver,
        approval_resolver=DurableHarnessWaitApprovalResolver(
            runtime_resolver=registry,
            actor_scope_resolver=scope_resolver,
            root=tmp_path,
        ),
    )
    service.decide_approval(
        binding.run_spec.run_id,
        registration.node_instance_id,
        approval_id="approval-1",
        approved=True,
    )

    with pytest.raises(HarnessWaitRequestError) as exc_info:
        service.decide_approval(
            binding.run_spec.run_id,
            registration.node_instance_id,
            approval_id="another-approval",
            approved=True,
        )
    assert exc_info.value.code == "wait_approval_stale"


def test_durable_approval_resolver_rejects_same_approval_id_on_another_graph(
    tmp_path: Path,
) -> None:
    _service_one, registration_one, resolver_one = _waiting_service(
        "registry-approval-cross-graph-1",
        wait_kind="approval",
    )
    _service_two, registration_two, resolver_two = _waiting_service(
        "registry-approval-cross-graph-2",
        wait_kind="approval",
    )
    binding_one = resolver_one.binding
    binding_two = resolver_two.binding
    registry = HarnessWaitRuntimeRegistry(tmp_path)
    for binding in (binding_one, binding_two):
        registry.register(
            binding.run_spec,
            binding.control_plane,
            tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
            identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
        )
    scope_one = _ActorScopeResolver(
        HarnessWaitActorScope(
            tenant_scope_ref=binding_one.run_spec.metadata["tenant_scope_ref"],
            identity_scope_ref=binding_one.run_spec.metadata["identity_scope_ref"],
            actor_identity_scope_ref=checksum_for({"actor": "actor-1"}),
        )
    )
    approval_resolver = DurableHarnessWaitApprovalResolver(
        runtime_resolver=registry,
        actor_scope_resolver=scope_one,
        root=tmp_path,
    )
    service_one = HarnessWaitApplicationService(
        actor=_actor(),
        runtime_resolver=registry,
        actor_scope_resolver=scope_one,
        approval_resolver=approval_resolver,
    )
    service_one.decide_approval(
        binding_one.run_spec.run_id,
        registration_one.node_instance_id,
        approval_id="approval-1",
        approved=True,
    )

    scope_two = _ActorScopeResolver(
        HarnessWaitActorScope(
            tenant_scope_ref=binding_two.run_spec.metadata["tenant_scope_ref"],
            identity_scope_ref=binding_two.run_spec.metadata["identity_scope_ref"],
            actor_identity_scope_ref=checksum_for({"actor": "actor-1"}),
        )
    )
    service_two = HarnessWaitApplicationService(
        actor=_actor(),
        runtime_resolver=registry,
        actor_scope_resolver=scope_two,
        approval_resolver=DurableHarnessWaitApprovalResolver(
            runtime_resolver=registry,
            actor_scope_resolver=scope_two,
            root=tmp_path,
        ),
    )
    with pytest.raises(HarnessWaitRequestError) as exc_info:
        service_two.decide_approval(
            binding_two.run_spec.run_id,
            registration_two.node_instance_id,
            approval_id="approval-1",
            approved=True,
        )
    assert exc_info.value.code == "wait_approval_decision_conflict"


def test_durable_approval_resolver_rejects_tampered_event_reference(
    tmp_path: Path,
) -> None:
    _service, registration, resolver = _waiting_service(
        "registry-approval-tamper",
        wait_kind="approval",
    )
    binding = resolver.binding
    registry = HarnessWaitRuntimeRegistry(tmp_path)
    registry.register(
        binding.run_spec,
        binding.control_plane,
        tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
        identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
    )
    scope_resolver = _ActorScopeResolver(
        HarnessWaitActorScope(
            tenant_scope_ref=binding.run_spec.metadata["tenant_scope_ref"],
            identity_scope_ref=binding.run_spec.metadata["identity_scope_ref"],
            actor_identity_scope_ref=checksum_for({"actor": "actor-1"}),
        )
    )
    service = HarnessWaitApplicationService(
        actor=_actor(),
        runtime_resolver=registry,
        actor_scope_resolver=scope_resolver,
        approval_resolver=DurableHarnessWaitApprovalResolver(
            runtime_resolver=registry,
            actor_scope_resolver=scope_resolver,
            root=tmp_path,
        ),
    )
    service.decide_approval(
        binding.run_spec.run_id,
        registration.node_instance_id,
        approval_id="approval-1",
        approved=True,
    )
    path = tmp_path / "approval-decisions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["decisions"][0]["approval_event_ref"] = checksum_for({"forged": True})
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(HarnessWaitRequestError) as exc_info:
        service.decide_approval(
            binding.run_spec.run_id,
            registration.node_instance_id,
            approval_id="approval-1",
            approved=True,
        )
    assert exc_info.value.code == "wait_approval_decision_conflict"
