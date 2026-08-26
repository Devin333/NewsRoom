from __future__ import annotations

from fastapi.testclient import TestClient

from framework.execution_environment import (
    ExecutionEnvironmentRegistry,
    ExecutionProfile,
    ExecutionProfileRegistry,
    RuntimeCompositionManifest,
    RuntimeExecutionComposition,
)
from interfaces.api import create_app


def _composition() -> tuple[RuntimeExecutionComposition, ExecutionProfileRegistry]:
    profiles = ExecutionProfileRegistry()
    profiles.register("trusted", ExecutionProfile.trusted_in_process())
    providers = ExecutionEnvironmentRegistry()
    manifest = RuntimeCompositionManifest.from_registries(
        composition_id="api-process",
        profile_registry=profiles,
        execution_registry=providers,
    )
    return (
        RuntimeExecutionComposition(
            manifest=manifest,
            profile_registry=profiles,
            execution_registry=providers,
        ),
        profiles,
    )


def test_api_readiness_exposes_composition_fingerprint() -> None:
    composition, _profiles = _composition()
    client = TestClient(create_app(runtime_execution_composition=composition, audit_emitter_factory=None))

    response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()["data"]["runtime_composition"]
    assert payload["manifest_fingerprint"] == composition.fingerprint
    assert payload["composition_id"] == "api-process"


def test_api_readiness_fails_closed_after_composition_drift() -> None:
    composition, profiles = _composition()
    client = TestClient(create_app(runtime_execution_composition=composition, audit_emitter_factory=None))
    profiles.register("another-trusted", ExecutionProfile.trusted_in_process())

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "runtime_composition_drift"
