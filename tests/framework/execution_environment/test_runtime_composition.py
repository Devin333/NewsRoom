from __future__ import annotations

import pytest

from framework.execution_environment import (
    ExecutionEnvironmentRegistry,
    ExecutionProfile,
    ExecutionProfileRegistry,
    RuntimeCompositionDriftError,
    RuntimeCompositionManifest,
    RuntimeCompositionProfileError,
    RuntimeExecutionComposition,
)
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
