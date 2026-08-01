from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import (
    HarnessSideEffectAttemptLease,
    HarnessSideEffectDecision,
    HarnessSideEffectHandlerReference,
    HarnessSideEffectIntent,
    HarnessSideEffectOutcome,
)


@runtime_checkable
class HarnessSideEffectHandler(Protocol):
    """The only object allowed to turn an authorized intent into an effect."""

    def commit(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome: ...


@runtime_checkable
class HarnessSideEffectPreparationHandler(HarnessSideEffectHandler, Protocol):
    def prepare(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome: ...


@runtime_checkable
class HarnessFencedSideEffectHandler(HarnessSideEffectHandler, Protocol):
    def commit_fenced(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        attempt: HarnessSideEffectAttemptLease,
    ) -> HarnessSideEffectOutcome: ...

    def request_cancellation(self, attempt: HarnessSideEffectAttemptLease) -> None: ...

    def confirm_termination(self, attempt: HarnessSideEffectAttemptLease) -> bool: ...

    def reconcile(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        attempt: HarnessSideEffectAttemptLease,
    ) -> HarnessSideEffectOutcome | None: ...


@dataclass(frozen=True, slots=True)
class HarnessSideEffectCapabilities:
    cancellation: bool = False
    termination_confirmation: bool = False
    stable_idempotency: bool = False
    fencing: bool = False
    reconciliation: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "cancellation",
            "termination_confirmation",
            "stable_idempotency",
            "fencing",
            "reconciliation",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise _registry_error(
                    "invalid_side_effect_capability",
                    "side-effect safety capabilities must be booleans",
                    field=field_name,
                )

    def missing_for_physical_concurrency(self) -> tuple[str, ...]:
        return tuple(
            field_name
            for field_name in (
                "cancellation",
                "termination_confirmation",
                "stable_idempotency",
                "fencing",
                "reconciliation",
            )
            if not getattr(self, field_name)
        )

    @property
    def physical_concurrency_safe(self) -> bool:
        return not self.missing_for_physical_concurrency()


@dataclass(frozen=True, slots=True)
class HarnessSideEffectHandlerBinding:
    reference: HarnessSideEffectHandlerReference | str
    kind: str
    handler: HarnessSideEffectHandler
    supports_origins: tuple[str, ...] = ("worker", "controller_terminal")
    capabilities: HarnessSideEffectCapabilities = HarnessSideEffectCapabilities()

    def __post_init__(self) -> None:
        reference = HarnessSideEffectHandlerReference.parse(self.reference)
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise HarnessValidationError("side-effect handler binding kind is required")
        if not isinstance(self.handler, HarnessSideEffectHandler):
            raise HarnessValidationError("side-effect handler must implement commit")
        origins = tuple(str(origin).strip() for origin in self.supports_origins)
        if not origins or any(not origin for origin in origins):
            raise HarnessValidationError(
                "side-effect handler binding origins are invalid"
            )
        if len(set(origins)) != len(origins):
            raise HarnessValidationError(
                "side-effect handler binding origins must be unique"
            )
        if not isinstance(self.capabilities, HarnessSideEffectCapabilities):
            raise _registry_error(
                "invalid_side_effect_capability",
                "side-effect handler binding requires HarnessSideEffectCapabilities",
                reference=str(reference),
            )
        if self.capabilities.physical_concurrency_safe and not isinstance(
            self.handler,
            HarnessFencedSideEffectHandler,
        ):
            raise _registry_error(
                "invalid_fenced_side_effect_handler",
                "parallel-safe side-effect handler must implement fenced execution",
                reference=str(reference),
            )
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "kind", self.kind.strip())
        object.__setattr__(self, "supports_origins", origins)


class HarnessSideEffectRegistry:
    """Instance-scoped exact handler registry; no module-global fallback exists."""

    def __init__(
        self, bindings: Iterable[HarnessSideEffectHandlerBinding] = ()
    ) -> None:
        self._bindings: dict[
            HarnessSideEffectHandlerReference, HarnessSideEffectHandlerBinding
        ] = {}
        for binding in bindings:
            self.register(binding)

    def register(
        self,
        binding: HarnessSideEffectHandlerBinding | None = None,
        *,
        reference: HarnessSideEffectHandlerReference | str | None = None,
        kind: str | None = None,
        handler: HarnessSideEffectHandler | None = None,
        supports_origins: tuple[str, ...] = ("worker", "controller_terminal"),
        capabilities: HarnessSideEffectCapabilities = HarnessSideEffectCapabilities(),
    ) -> HarnessSideEffectHandlerBinding:
        if binding is None:
            if reference is None or kind is None or handler is None:
                raise HarnessValidationError(
                    "register requires binding or reference, kind, and handler"
                )
            binding = HarnessSideEffectHandlerBinding(
                reference=reference,
                kind=kind,
                handler=handler,
                supports_origins=supports_origins,
                capabilities=capabilities,
            )
        if not isinstance(binding, HarnessSideEffectHandlerBinding):
            raise HarnessValidationError("side-effect registry binding is invalid")
        if binding.reference in self._bindings:
            raise _registry_error(
                "duplicate_side_effect_handler",
                "side-effect handler reference is already registered",
                reference=str(binding.reference),
            )
        self._bindings[binding.reference] = binding
        return binding

    def resolve(
        self,
        reference: HarnessSideEffectHandlerReference | str,
        *,
        kind: str | None = None,
        origin: str | None = None,
    ) -> HarnessSideEffectHandlerBinding:
        exact = HarnessSideEffectHandlerReference.parse(reference)
        binding = self._bindings.get(exact)
        if binding is None:
            raise _registry_error(
                "unknown_side_effect_handler",
                "exact side-effect handler reference is not registered",
                reference=str(exact),
            )
        if kind is not None and binding.kind != str(kind):
            raise _registry_error(
                "side_effect_handler_kind_mismatch",
                "side-effect handler kind does not match declaration",
                reference=str(exact),
                expected_kind=str(kind),
                actual_kind=binding.kind,
            )
        if origin is not None and str(origin) not in binding.supports_origins:
            raise _registry_error(
                "side_effect_handler_origin_mismatch",
                "side-effect handler does not support the requested origin",
                reference=str(exact),
                origin=str(origin),
            )
        return binding

    def validate_intent(
        self, intent: HarnessSideEffectIntent
    ) -> HarnessSideEffectHandlerBinding:
        if not isinstance(intent, HarnessSideEffectIntent):
            raise HarnessValidationError("side-effect intent is invalid")
        if intent.handler is None:
            raise _registry_error(
                "missing_side_effect_handler",
                "side-effect intent has no exact handler reference",
                effect_id=intent.effect_id,
            )
        return self.resolve(
            intent.handler, kind=intent.kind, origin=intent.origin.value
        )

    def bindings(self) -> tuple[HarnessSideEffectHandlerBinding, ...]:
        return tuple(self._bindings.values())


def _registry_error(code: str, message: str, **details: Any) -> HarnessValidationError:
    return HarnessValidationError(message, code=code, details={"code": code, **details})


__all__ = [
    "HarnessFencedSideEffectHandler",
    "HarnessSideEffectHandler",
    "HarnessSideEffectHandlerBinding",
    "HarnessSideEffectCapabilities",
    "HarnessSideEffectPreparationHandler",
    "HarnessSideEffectRegistry",
]
