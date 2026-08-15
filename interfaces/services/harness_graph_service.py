"""Authorized application boundary for Harness graph inspection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Protocol, runtime_checkable

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_checkpoint import (
    HarnessGraphReplayReadResult,
)
from framework.harness.control_plane.graph_inspection import HarnessGraphInspection
from framework.harness.control_plane.graph_operations import (
    HarnessGraphRunOperation,
    HarnessGraphRunOperationType,
)
from framework.harness.control_plane.graph_observability import (
    HarnessGraphHealthReport,
    graph_health_report,
)
from framework.harness.control_plane.harness import HarnessRunResult
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.workflow.canonical import required_text
from interfaces.models.actor import (
    READ_REPORTS_PERMISSION,
    WRITE_RUNS_PERMISSION,
    ActorContext,
)


_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class HarnessGraphApplicationError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        self.code = required_text(code, "code")
        super().__init__(message)


class HarnessGraphAuthorizationError(HarnessGraphApplicationError):
    pass


class HarnessGraphNotFoundError(HarnessGraphApplicationError):
    pass


class HarnessGraphRequestError(HarnessGraphApplicationError):
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

    def accept_graph_run_operation(
        self,
        run_spec: HarnessRunSpec,
        operation: HarnessGraphRunOperation,
        *,
        occurred_at: datetime,
    ) -> HarnessGraphRunOperation: ...

    def recover_and_run(self, run_spec: HarnessRunSpec) -> HarnessRunResult: ...

    def verify_graph_history_or_quarantine(
        self,
        run_spec: HarnessRunSpec,
        *,
        through_sequence: int | None = None,
    ) -> HarnessGraphReplayReadResult: ...


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
    actor_identity_scope_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("tenant_scope_ref", "identity_scope_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not _CHECKSUM_PATTERN.fullmatch(value):
                raise ValueError(f"{field_name} must be a sha256 reference")
        if self.actor_identity_scope_ref is not None and (
            not isinstance(self.actor_identity_scope_ref, str)
            or not _CHECKSUM_PATTERN.fullmatch(self.actor_identity_scope_ref)
        ):
            raise ValueError("actor_identity_scope_ref must be a sha256 reference")


@runtime_checkable
class HarnessGraphActorScopeResolverPort(Protocol):
    def resolve(self, actor: ActorContext) -> HarnessGraphActorScope: ...


@dataclass(frozen=True, slots=True)
class HarnessGraphRunOperationResult:
    operation: str
    operation_id: str
    operation_ref: str
    run: HarnessGraphInspection

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "operation_id": self.operation_id,
            "operation_ref": self.operation_ref,
            "run": self.run.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class HarnessGraphReplayResult:
    run_id: str
    status: str
    through_sequence: int | None = None
    projection_checksum: str | None = None
    verified_decision_checksums: tuple[str, ...] = ()
    pending_cause_count: int = 0
    quarantine_reason: str | None = None
    sequence: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "through_sequence": self.through_sequence,
            "projection_checksum": self.projection_checksum,
            "verified_decision_checksums": list(
                self.verified_decision_checksums
            ),
            "pending_cause_count": self.pending_cause_count,
            "quarantine_reason": self.quarantine_reason,
            "sequence": self.sequence,
        }


class HarnessGraphApplicationService:
    """Expose safe graph state without leaking Control Plane or store access."""

    def __init__(
        self,
        *,
        actor: ActorContext,
        runtime_resolver: HarnessGraphRuntimeResolverPort,
        actor_scope_resolver: HarnessGraphActorScopeResolverPort,
        clock: Callable[[], datetime] | None = None,
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
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._clock = clock or _utc_now

    def inspect_run(
        self,
        run_id: str,
        *,
        verify_history: bool = False,
    ) -> HarnessGraphInspection:
        binding, _ = self._authorized_binding(run_id)
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
        binding, _ = self._authorized_binding(run_id)
        state = binding.control_plane.recover_graph(binding.run_spec)
        return graph_health_report(
            state,
            canonical_high_watermark=canonical_high_watermark,
            incompatible_history=incompatible_history,
        )

    def cancel_run(
        self,
        run_id: str,
        *,
        cancellation_id: str,
        reason_code: str,
    ) -> HarnessGraphRunOperationResult:
        binding, actor_scope = self._authorized_binding(
            run_id,
            permission=WRITE_RUNS_PERMISSION,
        )
        if actor_scope.actor_identity_scope_ref is None:
            raise HarnessGraphAuthorizationError(
                "actor identity scope is required for Graph run mutation",
                code="graph_actor_identity_scope_missing",
            )
        operation = HarnessGraphRunOperation(
            HarnessGraphRunOperationType.CANCEL,
            _request_text(
                cancellation_id,
                "cancellation_id",
                code="graph_cancellation_id_invalid",
            ),
            binding.run_spec.run_id,
            actor_scope.actor_identity_scope_ref,
            _request_text(
                reason_code,
                "reason_code",
                code="graph_cancellation_reason_invalid",
            ),
            0,
        )
        try:
            accepted = binding.control_plane.accept_graph_run_operation(
                binding.run_spec,
                operation,
                occurred_at=self._clock(),
            )
        except HarnessValidationError as exc:
            if exc.code not in {
                "graph_run_operation_identity_conflict",
                "graph_run_operation_terminal",
                "graph_run_operation_conflict",
            }:
                raise
            raise HarnessGraphRequestError(str(exc), code=exc.code) from exc
        driven = binding.control_plane.recover_and_run(binding.run_spec)
        state = driven.graph_state or binding.control_plane.recover_graph(
            binding.run_spec
        )
        return HarnessGraphRunOperationResult(
            operation=accepted.operation_type.value,
            operation_id=accepted.operation_id,
            operation_ref=accepted.operation_ref,
            run=HarnessGraphInspection.from_state(state),
        )

    def replay_run(
        self,
        run_id: str,
        *,
        through_sequence: int | None = None,
    ) -> HarnessGraphReplayResult:
        binding, _ = self._authorized_binding(run_id)
        if through_sequence is not None and (
            not isinstance(through_sequence, int)
            or isinstance(through_sequence, bool)
            or through_sequence < 1
        ):
            raise HarnessGraphRequestError(
                "through_sequence must be a positive integer",
                code="graph_replay_sequence_invalid",
            )
        result = binding.control_plane.verify_graph_history_or_quarantine(
            binding.run_spec,
            through_sequence=through_sequence,
        )
        if not isinstance(result, HarnessGraphReplayReadResult):
            raise HarnessGraphApplicationError(
                "control plane returned an invalid replay result",
                code="graph_replay_result_invalid",
            )
        if result.report is None:
            return HarnessGraphReplayResult(
                run_id=binding.run_spec.run_id,
                status="quarantined",
                quarantine_reason=result.quarantine_reason,
                sequence=result.sequence,
            )
        if result.report.run_id != binding.run_spec.run_id:
            raise HarnessGraphApplicationError(
                "control plane returned replay for another run",
                code="graph_replay_result_invalid",
            )
        return HarnessGraphReplayResult(
            run_id=result.report.run_id,
            status="verified",
            through_sequence=result.report.through_sequence,
            projection_checksum=result.report.projection_checksum,
            verified_decision_checksums=(
                result.report.verified_decision_checksums
            ),
            pending_cause_count=len(result.report.pending_cause_checksums),
        )

    def _authorized_binding(
        self,
        run_id: str,
        *,
        permission: str = READ_REPORTS_PERMISSION,
    ) -> tuple[HarnessGraphRuntimeBinding, HarnessGraphActorScope]:
        if not self._actor.has_permission(permission):
            raise HarnessGraphAuthorizationError(
                "actor lacks Graph run operation permission",
                code=(
                    "graph_inspection_permission_denied"
                    if permission == READ_REPORTS_PERMISSION
                    else "graph_run_operation_permission_denied"
                ),
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
        if not isinstance(actor_scope, HarnessGraphActorScope):
            raise HarnessGraphApplicationError(
                "actor scope resolver returned an invalid scope",
                code="graph_actor_scope_resolver_invalid",
            )
        if (
            state.metadata.get("tenant_scope_ref") != actor_scope.tenant_scope_ref
            or state.metadata.get("identity_scope_ref")
            != actor_scope.identity_scope_ref
        ):
            raise HarnessGraphNotFoundError(
                "run was not found in the authorized scope",
                code="graph_run_not_found",
            )
        return binding, actor_scope


def _request_text(value: object, field_name: str, *, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HarnessGraphRequestError(f"{field_name} is invalid", code=code)
    try:
        return required_text(value, field_name)
    except HarnessValidationError as exc:
        raise HarnessGraphRequestError(f"{field_name} is invalid", code=code) from exc


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "HarnessGraphActorScope",
    "HarnessGraphActorScopeResolverPort",
    "HarnessGraphApplicationError",
    "HarnessGraphApplicationService",
    "HarnessGraphAuthorizationError",
    "HarnessGraphControlPlanePort",
    "HarnessGraphNotFoundError",
    "HarnessGraphReplayResult",
    "HarnessGraphRequestError",
    "HarnessGraphRunOperationResult",
    "HarnessGraphRuntimeBinding",
    "HarnessGraphRuntimeResolverPort",
]
