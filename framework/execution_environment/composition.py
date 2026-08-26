from __future__ import annotations

"""Process-scoped runtime composition contracts.

This module only binds execution providers and profiles. Application layers
remain responsible for supplying durable stores and other control-plane ports.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import re
from typing import Any

from framework.execution_environment.errors import (
    ExecutionEnvironmentUnavailableError,
    RuntimeCompositionDriftError,
    RuntimeCompositionProfileError,
)
from framework.execution_environment.models import ExecutionMode, ExecutionProfile
from framework.execution_environment.registry import ExecutionEnvironmentRegistry
from framework.shared.json import stable_json_dumps


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}\Z")
_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a bounded identifier")
    return normalized


def _fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        stable_json_dumps(value).encode("utf-8")
    ).hexdigest()


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
    ) -> None:
        if not isinstance(manifest, RuntimeCompositionManifest):
            raise TypeError("manifest must be RuntimeCompositionManifest")
        if not isinstance(profile_registry, ExecutionProfileRegistry):
            raise TypeError("profile_registry must be ExecutionProfileRegistry")
        if not isinstance(execution_registry, ExecutionEnvironmentRegistry):
            raise TypeError("execution_registry must be ExecutionEnvironmentRegistry")
        if not isinstance(require_explicit_execution_profile, bool):
            raise TypeError("require_explicit_execution_profile must be boolean")
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

    @property
    def fingerprint(self) -> str:
        return self.manifest.fingerprint

    def resolve_profile(self, profile_id: str) -> ExecutionProfile:
        self.verify_integrity()
        profile = self.profile_registry.resolve(profile_id)
        if profile.mode is ExecutionMode.SANDBOXED_PROCESS and profile.provider_id not in self.execution_registry.provider_ids():
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
        return {
            "status": "ready",
            "composition_id": self.manifest.composition_id,
            "manifest_fingerprint": self.manifest.fingerprint,
            "policy_fingerprint": self.manifest.policy_fingerprint,
            "provider_fingerprint": self.manifest.provider_fingerprint,
            "profiles": list(self.profile_registry.profile_ids),
            "providers": list(self.execution_registry.provider_ids()),
        }

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
    "RuntimeCompositionManifest",
    "RuntimeExecutionComposition",
    "build_runtime_execution_composition",
]
