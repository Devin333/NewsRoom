"""Authorized application boundary for Harness graph inspection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from framework.harness.control_plane.graph_inspection import HarnessGraphInspection
from framework.harness.control_plane.graph_observability import (
    HarnessGraphHealthReport,
    graph_health_report,
)
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.workflow.canonical import required_text
from interfaces.models.actor import READ_REPORTS_PERMISSION, ActorContext


_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class HarnessGraphApplicationError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        self.code = required_text(code, "code")
        super().__init__(message)


class HarnessGraphAuthorizationError(HarnessGraphApplicationError):
    pass


class HarnessGraphNotFoundError(HarnessGraphApplicationError):
    pass


@runtime_checkable
class HarnessGraphControlPlanePort(Protocol):
    def recover_graph(self, run_spec: HarnessRunSpec): ...

    def inspect_graph(
        self,
        run_spec: HarnessRunSpec,
        *,
        verify_history: bool = False,
    ) -> HarnessGraphInspection: ...


@dataclass(frozen=True, slots=True)
class HarnessGraphRuntimeBinding:
    run_spec: HarnessRunSpec
    control_plane: HarnessGraphControlPlanePort

    def __post_init__(self) -> None:
        if not isinstance(self.run_spec, HarnessRunSpec):
            raise TypeError("run_spec must be HarnessRunSpec")
        if not isinstance(self.control_plane, HarnessGraphControlPlanePort):
            raise TypeError("control_plane must implement HarnessGraphControlPlanePort")


@runtime_checkable
class HarnessGraphRuntimeResolverPort(Protocol):
    def resolve(
        self,
        run_id: str,
        *,
        actor: ActorContext,
    ) -> HarnessGraphRuntimeBinding: ...


@dataclass(frozen=True, slots=True)
class HarnessGraphActorScope:
    tenant_scope_ref: str
    identity_scope_ref: str

    def __post_init__(self) -> None:
        for field_name in ("tenant_scope_ref", "identity_scope_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not _CHECKSUM_PATTERN.fullmatch(value):
                raise ValueError(f"{field_name} must be a sha256 reference")


@runtime_checkable
class HarnessGraphActorScopeResolverPort(Protocol):
    def resolve(self, actor: ActorContext) -> HarnessGraphActorScope: ...


class HarnessGraphApplicationService:
    """Expose safe graph state without leaking Control Plane or store access."""

    def __init__(
        self,
        *,
        actor: ActorContext,
        runtime_resolver: HarnessGraphRuntimeResolverPort,
        actor_scope_resolver: HarnessGraphActorScopeResolverPort,
    ) -> None:
        if not isinstance(actor, ActorContext):
            raise TypeError("actor must be ActorContext")
        if not isinstance(runtime_resolver, HarnessGraphRuntimeResolverPort):
            raise TypeError(
                "runtime_resolver must implement HarnessGraphRuntimeResolverPort"
            )
        if not isinstance(actor_scope_resolver, HarnessGraphActorScopeResolverPort):
            raise TypeError(
                "actor_scope_resolver must implement HarnessGraphActorScopeResolverPort"
            )
        self._actor = actor
        self._runtime_resolver = runtime_resolver
        self._actor_scope_resolver = actor_scope_resolver

    def inspect_run(
        self,
        run_id: str,
        *,
        verify_history: bool = False,
    ) -> HarnessGraphInspection:
        binding = self._authorized_binding(run_id)
        return binding.control_plane.inspect_graph(
            binding.run_spec,
            verify_history=verify_history,
        )

    def inspect_health(
        self,
        run_id: str,
        *,
        canonical_high_watermark: int | None = None,
        incompatible_history: bool = False,
    ) -> HarnessGraphHealthReport:
        binding = self._authorized_binding(run_id)
        state = binding.control_plane.recover_graph(binding.run_spec)
        return graph_health_report(
            state,
            canonical_high_watermark=canonical_high_watermark,
            incompatible_history=incompatible_history,
        )

    def _authorized_binding(self, run_id: str) -> HarnessGraphRuntimeBinding:
        if not self._actor.has_permission(READ_REPORTS_PERMISSION):
            raise HarnessGraphAuthorizationError(
                "actor lacks graph inspection permission",
                code="graph_inspection_permission_denied",
            )
        run_id = required_text(run_id, "run_id")
        binding = self._runtime_resolver.resolve(run_id, actor=self._actor)
        if not isinstance(binding, HarnessGraphRuntimeBinding):
            raise TypeError("runtime resolver returned an invalid binding")
        if binding.run_spec.run_id != run_id:
            raise HarnessGraphNotFoundError(
                "run was not found in the authorized scope",
                code="graph_run_not_found",
            )
        state = binding.control_plane.recover_graph(binding.run_spec)
        actor_scope = self._actor_scope_resolver.resolve(self._actor)
        if (
            state.metadata.get("tenant_scope_ref") != actor_scope.tenant_scope_ref
            or state.metadata.get("identity_scope_ref")
            != actor_scope.identity_scope_ref
        ):
            raise HarnessGraphNotFoundError(
                "run was not found in the authorized scope",
                code="graph_run_not_found",
            )
        return binding


__all__ = [
    "HarnessGraphActorScope",
    "HarnessGraphActorScopeResolverPort",
    "HarnessGraphApplicationError",
    "HarnessGraphApplicationService",
    "HarnessGraphAuthorizationError",
    "HarnessGraphControlPlanePort",
    "HarnessGraphNotFoundError",
    "HarnessGraphRuntimeBinding",
    "HarnessGraphRuntimeResolverPort",
]
