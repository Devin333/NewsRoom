from __future__ import annotations

"""Process-scoped runtime composition contracts.

The composition owns the provider/profile policy and records any durable
control-plane ports supplied by the application root.  ``required_provider_ids``
is deliberately explicit: a profile may be present in the shared catalog for
another process role without making that provider a startup dependency here.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import re
from typing import Any

from framework.execution_environment.errors import (
    ExecutionEnvironmentUnavailableError,
    RuntimeCompositionDriftError,
    RuntimeCompositionProfileError,
)
from framework.execution_environment.models import (
    CAPABILITY_DENIAL_CODE_VERSION,
    ExecutionMode,
    ExecutionProfile,
    capability_denial_code,
)
from framework.execution_environment.registry import ExecutionEnvironmentRegistry
from framework.shared.json import stable_json_dumps


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}\Z")
_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}\Z")

RUNTIME_CONTROL_PLANE_PORT_CONTRACTS: Mapping[str, str] = {
    "durable_intent_repository": "newsroom.runtime-intent/v1",
    "execution_receipt_repository": "newsroom.execution-receipt/v1",
    "child_lease_repository": "newsroom.child-lease/v1",
    "idempotency_reconciliation_port": "newsroom.idempotency-reconciliation/v1",
    "canonical_event_publisher": "newsroom.runtime-event-publisher/v1",
    "durable_event_storage": "newsroom.runtime-event-store/v1",
    "projection_checkpoint_reader": "newsroom.runtime-projection-checkpoint/v1",
    "operator_authorizer": "newsroom.operator-authorizer/v1",
    "operator_service": "newsroom.operator-service/v1",
}


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a bounded identifier")
    return normalized


def _fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        stable_json_dumps(value).encode("utf-8")
    ).hexdigest()


def _port_identity(port: Any) -> str:
    for attribute in ("composition_fingerprint", "fingerprint", "checksum"):
        value = getattr(port, attribute, None)
        if callable(value):
            try:
                value = value()
            except TypeError:
                value = None
        if isinstance(value, str) and value.strip():
            return value.strip()
    port_type = type(port)
    return f"{port_type.__module__}.{port_type.__qualname__}"


@dataclass(frozen=True, slots=True)
class RuntimeCompositionManifest:
    """Immutable identity shared by all instances of one process role."""

    composition_id: str
    version: str = "1"
    policy_fingerprint: str = "sha256:" + "0" * 64
    provider_fingerprint: str = "sha256:" + "0" * 64
    event_schema_version: str = "newsroom.runtime-events/v1"
    durable_store_contract: str = "newsroom.durable-store/v1"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "composition_id", _identifier(self.composition_id, "composition_id"))
        object.__setattr__(self, "version", _identifier(self.version, "version"))
        for name in ("policy_fingerprint", "provider_fingerprint"):
            value = str(getattr(self, name)).strip().lower()
            if _CHECKSUM.fullmatch(value) is None:
                raise ValueError(f"{name} must be a sha256 checksum")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "event_schema_version", _identifier(self.event_schema_version, "event_schema_version"))
        object.__setattr__(self, "durable_store_contract", _identifier(self.durable_store_contract, "durable_store_contract"))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())

    @classmethod
    def from_registries(
        cls,
        *,
        composition_id: str,
        profile_registry: "ExecutionProfileRegistry",
        execution_registry: ExecutionEnvironmentRegistry,
        **kwargs: Any,
    ) -> "RuntimeCompositionManifest":
        return cls(
            composition_id=composition_id,
            policy_fingerprint=profile_registry.fingerprint,
            provider_fingerprint=execution_registry.fingerprint,
            **kwargs,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuntimeCompositionManifest":
        if not isinstance(value, Mapping):
            raise TypeError("runtime composition manifest must be an object")
        expected = {
            "composition_id", "version", "policy_fingerprint", "provider_fingerprint",
            "event_schema_version", "durable_store_contract", "metadata",
        }
        unknown = sorted(set(value) - expected)
        if unknown:
            raise ValueError(f"runtime composition manifest contains unknown fields: {unknown}")
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "composition_id": self.composition_id,
            "version": self.version,
            "policy_fingerprint": self.policy_fingerprint,
            "provider_fingerprint": self.provider_fingerprint,
            "event_schema_version": self.event_schema_version,
            "durable_store_contract": self.durable_store_contract,
            "metadata": dict(self.metadata),
        }


class ExecutionProfileRegistry:
    """Explicit, immutable-by-fingerprint registry of named execution profiles."""

    def __init__(self) -> None:
        self._profiles: dict[str, ExecutionProfile] = {}

    def register(self, profile_id: str, profile: ExecutionProfile) -> None:
        normalized = _identifier(profile_id, "profile_id")
        if not isinstance(profile, ExecutionProfile):
            raise TypeError("profile must be ExecutionProfile")
        if normalized in self._profiles:
            raise ValueError(f"execution profile is already registered: {normalized}")
        self._profiles[normalized] = profile

    def resolve(self, profile_id: str) -> ExecutionProfile:
        normalized = _identifier(profile_id, "profile_id")
        profile = self._profiles.get(normalized)
        if profile is None:
            raise RuntimeCompositionProfileError(
                "requested execution profile is not registered",
                details={"profile_id": normalized},
            )
        return profile

    @property
    def profile_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            [
                {"profile_id": profile_id, "profile": self._profiles[profile_id].to_dict()}
                for profile_id in self.profile_ids
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            profile_id: self._profiles[profile_id].to_dict()
            for profile_id in self.profile_ids
        }


class RuntimeExecutionComposition:
    """Validated process-local binding for execution and tool construction."""

    def __init__(
        self,
        *,
        manifest: RuntimeCompositionManifest,
        profile_registry: ExecutionProfileRegistry,
        execution_registry: ExecutionEnvironmentRegistry,
        expected_manifest_fingerprint: str | None = None,
        require_explicit_execution_profile: bool = True,
        control_plane_ports: Mapping[str, Any] | None = None,
        required_control_plane_ports: Sequence[str] = (),
        required_provider_ids: Sequence[str] = (),
    ) -> None:
        if not isinstance(manifest, RuntimeCompositionManifest):
            raise TypeError("manifest must be RuntimeCompositionManifest")
        if not isinstance(profile_registry, ExecutionProfileRegistry):
            raise TypeError("profile_registry must be ExecutionProfileRegistry")
        if not isinstance(execution_registry, ExecutionEnvironmentRegistry):
            raise TypeError("execution_registry must be ExecutionEnvironmentRegistry")
        if not isinstance(require_explicit_execution_profile, bool):
            raise TypeError("require_explicit_execution_profile must be boolean")
        required_ports = tuple(str(name).strip() for name in required_control_plane_ports)
        unknown_required_ports = sorted(
            set(required_ports) - set(RUNTIME_CONTROL_PLANE_PORT_CONTRACTS)
        )
        if unknown_required_ports:
            raise ValueError(
                "unknown required runtime control-plane ports: "
                f"{unknown_required_ports}"
            )
        if len(set(required_ports)) != len(required_ports):
            raise ValueError("required runtime control-plane ports must be unique")
        required_providers = tuple(
            _identifier(value, "required_provider_id")
            for value in required_provider_ids
        )
        if len(set(required_providers)) != len(required_providers):
            raise ValueError("required execution providers must be unique")
        if expected_manifest_fingerprint is not None:
            expected_manifest_fingerprint = str(expected_manifest_fingerprint).strip().lower()
            if _CHECKSUM.fullmatch(expected_manifest_fingerprint) is None:
                raise RuntimeCompositionDriftError(
                    "expected runtime composition fingerprint is invalid",
                    details={
                        "expected_manifest_fingerprint": expected_manifest_fingerprint,
                        "actual_manifest_fingerprint": manifest.fingerprint,
                    },
                )
        if expected_manifest_fingerprint is not None and expected_manifest_fingerprint != manifest.fingerprint:
            raise RuntimeCompositionDriftError(
                details={
                    "expected_manifest_fingerprint": expected_manifest_fingerprint,
                    "actual_manifest_fingerprint": manifest.fingerprint,
                }
            )
        if manifest.policy_fingerprint != profile_registry.fingerprint:
            raise RuntimeCompositionDriftError(
                "runtime policy fingerprint does not match profile registry",
                details={"expected": manifest.policy_fingerprint, "actual": profile_registry.fingerprint},
            )
        if manifest.provider_fingerprint != execution_registry.fingerprint:
            raise RuntimeCompositionDriftError(
                "runtime provider fingerprint does not match execution registry",
                details={"expected": manifest.provider_fingerprint, "actual": execution_registry.fingerprint},
            )
        self.manifest = manifest
        self.profile_registry = profile_registry
        self.execution_registry = execution_registry
        self.require_explicit_execution_profile = require_explicit_execution_profile
        self._required_control_plane_ports = required_ports
        self._required_provider_ids = required_providers
        self._control_plane_ports = dict(control_plane_ports or {})
        self._validate_control_plane_port_names(self._control_plane_ports)

    @property
    def fingerprint(self) -> str:
        return self.manifest.fingerprint

    def resolve_profile(self, profile_id: str) -> ExecutionProfile:
        self.verify_integrity()
        profile = self.profile_registry.resolve(profile_id)
        if profile.mode in {
            ExecutionMode.SANDBOXED_PROCESS,
            ExecutionMode.EXTERNAL_PROCESS,
        } and profile.provider_id not in self.execution_registry.provider_ids():
            raise ExecutionEnvironmentUnavailableError(
                "execution profile provider is not registered",
                details={"profile_id": profile_id, "provider_id": profile.provider_id},
            )
        return profile

    def verify_integrity(self) -> None:
        """Fail closed if mutable registries drift after composition startup."""

        if self.manifest.policy_fingerprint != self.profile_registry.fingerprint:
            raise RuntimeCompositionDriftError(
                "runtime policy fingerprint drift detected",
                details={
                    "expected": self.manifest.policy_fingerprint,
                    "actual": self.profile_registry.fingerprint,
                },
            )
        if self.manifest.provider_fingerprint != self.execution_registry.fingerprint:
            raise RuntimeCompositionDriftError(
                "runtime provider fingerprint drift detected",
                details={
                    "expected": self.manifest.provider_fingerprint,
                    "actual": self.execution_registry.fingerprint,
                },
            )

    def diagnostics(self) -> dict[str, Any]:
        self.verify_integrity()
        provider_capabilities = {
            provider_id: self.execution_registry.resolve_capabilities(provider_id).to_dict()
            for provider_id in self.execution_registry.provider_ids()
        }
        profiles = {
            profile_id: self.profile_registry.resolve(profile_id).to_dict()
            for profile_id in self.profile_registry.profile_ids
        }
        missing_control_plane_ports = self.missing_control_plane_ports
        unavailable_providers = self.unavailable_provider_ids
        return {
            "status": (
                "blocked"
                if missing_control_plane_ports or unavailable_providers
                else "ready"
            ),
            "composition_id": self.manifest.composition_id,
            "manifest_fingerprint": self.manifest.fingerprint,
            "policy_fingerprint": self.manifest.policy_fingerprint,
            "provider_fingerprint": self.manifest.provider_fingerprint,
            "profiles": list(self.profile_registry.profile_ids),
            "profile_catalog": profiles,
            "providers": list(self.execution_registry.provider_ids()),
            "required_providers": list(self.required_provider_ids),
            "unavailable_providers": list(unavailable_providers),
            "provider_capabilities": provider_capabilities,
            "control_plane_ports": sorted(self._control_plane_ports),
            "required_control_plane_ports": list(self._required_control_plane_ports),
            "missing_control_plane_ports": list(missing_control_plane_ports),
            "control_plane_contracts": {
                name: RUNTIME_CONTROL_PLANE_PORT_CONTRACTS[name]
                for name in sorted(self._control_plane_ports)
            },
            "control_plane_fingerprint": self.control_plane_fingerprint,
        }

    @property
    def control_plane_ports(self) -> Mapping[str, Any]:
        return dict(self._control_plane_ports)

    @property
    def required_control_plane_ports(self) -> tuple[str, ...]:
        return self._required_control_plane_ports

    @property
    def missing_control_plane_ports(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in self._required_control_plane_ports
            if name not in self._control_plane_ports
        )

    @property
    def required_provider_ids(self) -> tuple[str, ...]:
        return self._required_provider_ids

    @property
    def unavailable_provider_ids(self) -> tuple[str, ...]:
        registered = set(self.execution_registry.provider_ids())
        return tuple(
            provider_id
            for provider_id in self.required_provider_ids
            if provider_id not in registered
            or not self.execution_registry.resolve_capabilities(provider_id).available
        )

    @property
    def control_plane_fingerprint(self) -> str:
        return _fingerprint(
            [
                {
                    "name": name,
                    "contract": RUNTIME_CONTROL_PLANE_PORT_CONTRACTS[name],
                    "port": _port_identity(self._control_plane_ports[name]),
                }
                for name in sorted(self._control_plane_ports)
            ]
        )

    def require_control_plane_ports(self) -> None:
        missing = self.missing_control_plane_ports
        if missing:
            raise RuntimeCompositionDriftError(
                "required runtime control-plane ports are not bound",
                details={"missing_control_plane_ports": list(missing)},
            )

    def require_ready(self) -> None:
        """Fail closed unless every role-required provider and port is available.

        Catalogued providers that are not listed in ``required_provider_ids``
        remain admission-gated when an activity requests them, but do not make
        an otherwise trusted-only process report itself unavailable.
        """

        self.verify_integrity()
        unavailable = self.unavailable_provider_ids
        if unavailable:
            raise ExecutionEnvironmentUnavailableError(
                "required runtime execution providers are unavailable",
                details={
                    "provider_ids": list(unavailable),
                    "missing": ["provider_unavailable"],
                    "denial_code_version": CAPABILITY_DENIAL_CODE_VERSION,
                    "denial_code": capability_denial_code("provider_unavailable"),
                    "denials": [
                        {
                            "provider_id": provider_id,
                            "capability": "provider_unavailable",
                            "denial_code": capability_denial_code(
                                "provider_unavailable"
                            ),
                        }
                        for provider_id in unavailable
                    ],
                },
            )
        self.require_control_plane_ports()

    @staticmethod
    def _validate_control_plane_port_names(ports: Mapping[str, Any]) -> None:
        unknown = sorted(set(ports) - set(RUNTIME_CONTROL_PLANE_PORT_CONTRACTS))
        if unknown:
            raise ValueError(f"unknown runtime control-plane ports: {unknown}")

    def bind_control_plane_ports(self, **ports: Any) -> None:
        """Bind durable/control-plane ports exactly once during startup."""

        self._validate_control_plane_port_names(ports)
        duplicate = sorted(set(ports).intersection(self._control_plane_ports))
        if duplicate:
            raise RuntimeCompositionDriftError(
                "runtime control-plane port was bound more than once",
                details={"ports": duplicate},
            )
        for name, port in ports.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("control-plane port names must be non-empty strings")
            if port is None:
                raise RuntimeCompositionDriftError(
                    "required runtime control-plane port is unavailable",
                    details={"port": name},
                )
        self._control_plane_ports.update(ports)

    def tool_executor_factory(self, registry: Any, **kwargs: Any) -> Any:
        self.verify_integrity()
        from framework.tool.runtime.executor import ToolExecutor

        kwargs["execution_environment"] = self.execution_registry
        kwargs["require_explicit_execution_profile"] = (
            self.require_explicit_execution_profile
        )
        return ToolExecutor(registry, **kwargs)


def build_runtime_execution_composition(
    *,
    manifest: RuntimeCompositionManifest,
    profile_registry: ExecutionProfileRegistry,
    execution_registry: ExecutionEnvironmentRegistry,
    **kwargs: Any,
) -> RuntimeExecutionComposition:
    return RuntimeExecutionComposition(
        manifest=manifest,
        profile_registry=profile_registry,
        execution_registry=execution_registry,
        **kwargs,
    )


__all__ = [
    "ExecutionProfileRegistry",
    "RUNTIME_CONTROL_PLANE_PORT_CONTRACTS",
    "RuntimeCompositionManifest",
    "RuntimeExecutionComposition",
    "build_runtime_execution_composition",
]
