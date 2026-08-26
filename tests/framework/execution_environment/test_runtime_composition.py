from __future__ import annotations

import pytest

from framework.execution_environment import (
    ExecutionCapabilityProfile,
    ExecutionEnvironmentRegistry,
    ExecutionEnvironmentUnavailableError,
    ExecutionProfile,
    ExecutionProfileRegistry,
    RuntimeCompositionDriftError,
    RuntimeCompositionManifest,
    RuntimeCompositionProfileError,
    RuntimeExecutionComposition,
)
from framework.execution_environment.ports import ExecutionEnvironmentPort
from framework.tool import ToolRegistry


def _composition() -> tuple[RuntimeExecutionComposition, ExecutionProfileRegistry, ExecutionEnvironmentRegistry]:
    profiles = ExecutionProfileRegistry()
    profiles.register("trusted", ExecutionProfile.trusted_in_process())
    providers = ExecutionEnvironmentRegistry()
    manifest = RuntimeCompositionManifest.from_registries(
        composition_id="test-process",
        profile_registry=profiles,
        execution_registry=providers,
    )
    return RuntimeExecutionComposition(
        manifest=manifest,
        profile_registry=profiles,
        execution_registry=providers,
    ), profiles, providers


def test_manifest_fingerprint_is_stable_and_round_trips() -> None:
    composition, _profiles, _providers = _composition()
    restored = RuntimeCompositionManifest.from_dict(composition.manifest.to_dict())

    assert restored == composition.manifest
    assert restored.fingerprint == composition.fingerprint
    assert composition.diagnostics()["status"] == "ready"


def test_profile_registry_missing_profile_is_typed_denial() -> None:
    composition, _profiles, _providers = _composition()

    with pytest.raises(RuntimeCompositionProfileError) as error:
        composition.resolve_profile("missing")

    assert error.value.reason_code == "runtime_profile_denied"
    assert error.value.details["profile_id"] == "missing"


def test_composition_detects_registry_drift_before_factory_use() -> None:
    composition, profiles, _providers = _composition()
    profiles.register("trusted-copy", ExecutionProfile.trusted_in_process())

    with pytest.raises(RuntimeCompositionDriftError) as error:
        composition.tool_executor_factory(ToolRegistry())

    assert error.value.reason_code == "runtime_composition_drift"


def test_tool_executor_factory_binds_execution_registry() -> None:
    composition, _profiles, providers = _composition()

    executor = composition.tool_executor_factory(
        ToolRegistry(),
        execution_environment=object(),
        require_explicit_execution_profile=False,
    )

    assert executor._execution_environment is providers
    assert executor._require_explicit_execution_profile is True


def test_required_control_plane_ports_are_typed_and_fail_closed() -> None:
    composition, _profiles, _providers = _composition()
    required = RuntimeExecutionComposition(
        manifest=composition.manifest,
        profile_registry=composition.profile_registry,
        execution_registry=composition.execution_registry,
        required_control_plane_ports=("canonical_event_publisher",),
    )

    diagnostics = required.diagnostics()
    assert diagnostics["status"] == "blocked"
    assert diagnostics["missing_control_plane_ports"] == [
        "canonical_event_publisher"
    ]

    required.bind_control_plane_ports(canonical_event_publisher=object())
    diagnostics = required.diagnostics()
    assert diagnostics["status"] == "ready"
    assert diagnostics["control_plane_contracts"] == {
        "canonical_event_publisher": "newsroom.runtime-event-publisher/v1"
    }
    assert diagnostics["control_plane_fingerprint"].startswith("sha256:")

    with pytest.raises(RuntimeCompositionDriftError):
        required.bind_control_plane_ports(canonical_event_publisher=object())


class _UnavailableProvider:
    @property
    def capabilities(self) -> ExecutionCapabilityProfile:
        return ExecutionCapabilityProfile(
            provider_id="offline",
            available=False,
        )

    def execute(self, request):
        raise AssertionError("unavailable provider must not execute")


def test_required_execution_provider_blocks_readiness_with_stable_denial() -> None:
    profiles = ExecutionProfileRegistry()
    profiles.register(
        "external",
        ExecutionProfile.external_process(
            provider_id="offline",
            allowed_argv_prefixes=(("worker",),),
        ),
    )
    providers = ExecutionEnvironmentRegistry()
    provider: ExecutionEnvironmentPort = _UnavailableProvider()
    providers.register(provider)
    manifest = RuntimeCompositionManifest.from_registries(
        composition_id="offline-process",
        profile_registry=profiles,
        execution_registry=providers,
    )
    composition = RuntimeExecutionComposition(
        manifest=manifest,
        profile_registry=profiles,
        execution_registry=providers,
        required_provider_ids=("offline",),
    )

    diagnostics = composition.diagnostics()
    assert diagnostics["status"] == "blocked"
    assert diagnostics["required_providers"] == ["offline"]
    assert diagnostics["unavailable_providers"] == ["offline"]

    with pytest.raises(ExecutionEnvironmentUnavailableError) as raised:
        composition.require_ready()

    assert raised.value.details["denial_code_version"] == (
        "newsroom.execution-capability-denials/v1"
    )
    assert raised.value.details["denial_code"] == "execution_provider_unavailable"


def test_unregistered_required_provider_is_reported_without_provider_fallback() -> None:
    profiles = ExecutionProfileRegistry()
    profiles.register("trusted", ExecutionProfile.trusted_in_process())
    providers = ExecutionEnvironmentRegistry()
    manifest = RuntimeCompositionManifest.from_registries(
        composition_id="missing-provider-process",
        profile_registry=profiles,
        execution_registry=providers,
    )
    composition = RuntimeExecutionComposition(
        manifest=manifest,
        profile_registry=profiles,
        execution_registry=providers,
        required_provider_ids=("docker",),
    )

    assert composition.diagnostics()["unavailable_providers"] == ["docker"]
    with pytest.raises(ExecutionEnvironmentUnavailableError) as raised:
        composition.require_ready()

    assert raised.value.details["provider_ids"] == ["docker"]
