from __future__ import annotations

import inspect
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gate_registry import (
    DeterministicGateRegistry,
    GateBinding,
)
from framework.harness.side_effects.registry import (
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectRegistry,
)
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.graph.activity import HarnessWorkerType


_CONTRACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$")
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class HarnessActivityUsage(StrEnum):
    SERIAL = "serial"
    PARALLEL = "parallel"
    COMPENSATION = "compensation"


@dataclass(frozen=True, slots=True)
class HarnessActivityCapabilities:
    termination_confirmation: bool = False
    stable_idempotency: bool = False
    fencing: bool = False
    reconciliation: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "termination_confirmation",
            "stable_idempotency",
            "fencing",
            "reconciliation",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise _authority_error(
                    "invalid_activity_capability",
                    "activity safety capabilities must be booleans",
                    field=field_name,
                )

    def missing_for(self, usage: HarnessActivityUsage | str) -> tuple[str, ...]:
        required_usage = HarnessActivityUsage(usage)
        if required_usage is HarnessActivityUsage.SERIAL:
            return ()
        return tuple(
            field_name
            for field_name in (
                "termination_confirmation",
                "stable_idempotency",
                "fencing",
                "reconciliation",
            )
            if not getattr(self, field_name)
        )

    @property
    def parallel_safe(self) -> bool:
        return not self.missing_for(HarnessActivityUsage.PARALLEL)

    @property
    def compensation_safe(self) -> bool:
        return not self.missing_for(HarnessActivityUsage.COMPENSATION)


@dataclass(frozen=True, slots=True)
class HarnessWorkerBinding:
    reference: HarnessContractReference | str
    worker_type: HarnessWorkerType | str
    implementation: object

    def __post_init__(self) -> None:
        reference = _coerce_reference(HarnessContractKind.WORKER, self.reference)
        worker_type = _coerce_worker_type(self.worker_type, field="worker_type")
        _require_implementation_identity(
            self.implementation,
            reference,
            id_attribute="worker_id",
            version_attribute="worker_version",
        )
        implementation_type = _coerce_worker_type(
            getattr(self.implementation, "worker_type", None),
            field="implementation.worker_type",
        )
        if implementation_type is not worker_type:
            raise _authority_error(
                "runtime_worker_type_mismatch",
                "worker implementation type does not match its binding",
                reference=reference,
                expected_worker_type=worker_type.value,
                actual_worker_type=implementation_type.value,
            )
        if not callable(getattr(self.implementation, "execute", None)):
            raise _authority_error(
                "invalid_runtime_contract_implementation",
                "worker implementation must expose execute(task)",
                reference=reference,
            )
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "worker_type", worker_type)


@dataclass(frozen=True, slots=True)
class HarnessActivityContractBinding:
    reference: HarnessContractReference | str
    implementation: object

    def __post_init__(self) -> None:
        reference = _coerce_reference(HarnessContractKind.ACTIVITY, self.reference)
        _require_implementation_identity(
            self.implementation,
            reference,
            id_attribute="activity_contract_id",
            version_attribute="activity_contract_version",
        )
        if not callable(getattr(self.implementation, "dispatch", None)):
            raise _authority_error(
                "invalid_runtime_contract_implementation",
                "live activity implementation must expose dispatch(request)",
                reference=reference,
            )
        if not isinstance(
            getattr(self.implementation, "capabilities", None),
            HarnessActivityCapabilities,
        ):
            raise _authority_error(
                "invalid_runtime_contract_implementation",
                "live activity implementation must expose HarnessActivityCapabilities",
                reference=reference,
            )
        object.__setattr__(self, "reference", reference)

    @property
    def capabilities(self) -> HarnessActivityCapabilities:
        return cast(HarnessActivityCapabilities, self.implementation.capabilities)


@dataclass(frozen=True, slots=True)
class HarnessCompensationHandlerBinding:
    reference: HarnessContractReference | str
    implementation: object

    def __post_init__(self) -> None:
        reference = _coerce_reference(HarnessContractKind.COMPENSATION, self.reference)
        _require_implementation_identity(
            self.implementation,
            reference,
            id_attribute="compensation_handler_id",
            version_attribute="compensation_handler_version",
        )
        if not callable(getattr(self.implementation, "compensate", None)):
            raise _authority_error(
                "invalid_runtime_contract_implementation",
                "compensation implementation must expose compensate(request)",
                reference=reference,
            )
        object.__setattr__(self, "reference", reference)


@dataclass(frozen=True, slots=True)
class HarnessDeterministicMergeBinding:
    reference: HarnessContractReference | str
    implementation: object

    def __post_init__(self) -> None:
        reference = _coerce_reference(HarnessContractKind.MERGE, self.reference)
        _require_implementation_identity(
            self.implementation,
            reference,
            id_attribute="merge_id",
            version_attribute="merge_version",
        )
        if getattr(self.implementation, "deterministic", None) is not True:
            raise _authority_error(
                "merge_determinism_unproven",
                "merge implementation must explicitly declare deterministic=True",
                reference=reference,
            )
        if not callable(self.implementation):
            raise _authority_error(
                "invalid_runtime_contract_implementation",
                "merge implementation must be callable",
                reference=reference,
            )
        call = getattr(self.implementation, "__call__", None)
        if inspect.iscoroutinefunction(
            self.implementation
        ) or inspect.iscoroutinefunction(call):
            raise _authority_error(
                "invalid_runtime_contract_implementation",
                "deterministic merge implementation must be synchronous",
                reference=reference,
            )
        object.__setattr__(self, "reference", reference)


class HarnessRuntimeBindingAuthority:
    """Instance-scoped authority for exact runtime bindings.

    Registrations are supplied by the composition root. A graph may request an
    exact reference, but it cannot create a registration or make itself trusted.
    """

    def __init__(
        self,
        *,
        workers: Iterable[HarnessWorkerBinding] = (),
        activities: Iterable[HarnessActivityContractBinding] = (),
        compensations: Iterable[HarnessCompensationHandlerBinding] = (),
        merges: Iterable[HarnessDeterministicMergeBinding] = (),
        gate_registry: DeterministicGateRegistry | None = None,
        side_effect_registry: HarnessSideEffectRegistry | None = None,
    ) -> None:
        if gate_registry is not None and not isinstance(
            gate_registry,
            DeterministicGateRegistry,
        ):
            raise TypeError("gate_registry must be DeterministicGateRegistry")
        if side_effect_registry is not None and not isinstance(
            side_effect_registry,
            HarnessSideEffectRegistry,
        ):
            raise TypeError("side_effect_registry must be HarnessSideEffectRegistry")
        self._workers = _ExactBindingMap(
            HarnessContractKind.WORKER,
            HarnessWorkerBinding,
            workers,
        )
        self._activities = _ExactBindingMap(
            HarnessContractKind.ACTIVITY,
            HarnessActivityContractBinding,
            activities,
        )
        self._compensations = _ExactBindingMap(
            HarnessContractKind.COMPENSATION,
            HarnessCompensationHandlerBinding,
            compensations,
        )
        self._merges = _ExactBindingMap(
            HarnessContractKind.MERGE,
            HarnessDeterministicMergeBinding,
            merges,
        )
        self._gate_registry = gate_registry or DeterministicGateRegistry()
        self._side_effect_registry = side_effect_registry or HarnessSideEffectRegistry()

    @property
    def worker_bindings(self) -> tuple[HarnessWorkerBinding, ...]:
        return cast(tuple[HarnessWorkerBinding, ...], self._workers.bindings)

    @property
    def activity_bindings(self) -> tuple[HarnessActivityContractBinding, ...]:
        return cast(
            tuple[HarnessActivityContractBinding, ...],
            self._activities.bindings,
        )

    @property
    def compensation_bindings(self) -> tuple[HarnessCompensationHandlerBinding, ...]:
        return cast(
            tuple[HarnessCompensationHandlerBinding, ...],
            self._compensations.bindings,
        )

    @property
    def merge_bindings(self) -> tuple[HarnessDeterministicMergeBinding, ...]:
        return cast(
            tuple[HarnessDeterministicMergeBinding, ...],
            self._merges.bindings,
        )

    def resolve_worker(
        self,
        reference: HarnessContractReference | str,
        *,
        expected_worker_type: HarnessWorkerType | str,
    ) -> HarnessWorkerBinding:
        binding = cast(HarnessWorkerBinding, self._workers.resolve(reference))
        expected = _coerce_worker_type(
            expected_worker_type,
            field="expected_worker_type",
        )
        if binding.worker_type is not expected:
            raise _authority_error(
                "runtime_worker_type_mismatch",
                "resolved worker type does not match the graph step",
                reference=binding.reference,
                expected_worker_type=expected.value,
                actual_worker_type=binding.worker_type.value,
            )
        return binding

    def resolve_activity(
        self,
        reference: HarnessContractReference | str,
        *,
        required_usage: HarnessActivityUsage | str = HarnessActivityUsage.SERIAL,
    ) -> HarnessActivityContractBinding:
        try:
            usage = HarnessActivityUsage(required_usage)
        except (TypeError, ValueError) as exc:
            raise _authority_error(
                "invalid_activity_usage",
                "activity usage is not supported",
                usage=str(required_usage),
            ) from exc
        binding = cast(
            HarnessActivityContractBinding,
            self._activities.resolve(reference),
        )
        missing = binding.capabilities.missing_for(usage)
        if missing:
            raise _authority_error(
                "activity_contract_safety_unproven",
                "activity contract lacks required safety capabilities",
                reference=binding.reference,
                usage=usage.value,
                missing_capabilities=missing,
            )
        return binding

    def resolve_compensation(
        self,
        reference: HarnessContractReference | str,
    ) -> HarnessCompensationHandlerBinding:
        return cast(
            HarnessCompensationHandlerBinding,
            self._compensations.resolve(reference),
        )

    def resolve_merge(
        self,
        reference: HarnessContractReference | str,
    ) -> HarnessDeterministicMergeBinding:
        return cast(
            HarnessDeterministicMergeBinding,
            self._merges.resolve(reference),
        )

    def resolve_gate(
        self,
        reference: HarnessContractReference | str,
    ) -> tuple[GateBinding, ...]:
        exact = _coerce_reference(HarnessContractKind.GATE, reference)
        return self._gate_registry.bindings_for(exact.exact_ref)

    def resolve_side_effect(
        self,
        reference: HarnessContractReference | str,
        *,
        kind: str | None = None,
        origin: str | None = None,
    ) -> HarnessSideEffectHandlerBinding:
        exact = _coerce_reference(HarnessContractKind.SIDE_EFFECT, reference)
        return self._side_effect_registry.resolve(
            exact.exact_ref,
            kind=kind,
            origin=origin,
        )


class _ExactBindingMap:
    def __init__(
        self,
        contract_kind: HarnessContractKind,
        binding_type: type[object],
        bindings: Iterable[object],
    ) -> None:
        by_reference: dict[HarnessContractReference, object] = {}
        for binding in tuple(bindings):
            if not isinstance(binding, binding_type):
                raise TypeError(
                    f"{contract_kind.value} bindings must contain {binding_type.__name__} values"
                )
            reference = cast(HarnessContractReference, binding.reference)
            if reference in by_reference:
                raise _authority_error(
                    "duplicate_runtime_contract_binding",
                    "runtime contract reference is registered more than once",
                    reference=reference,
                )
            by_reference[reference] = binding
        self._contract_kind = contract_kind
        self._by_reference = by_reference
        self.bindings = tuple(
            by_reference[reference]
            for reference in sorted(by_reference, key=lambda item: item.exact_ref)
        )

    def resolve(self, reference: HarnessContractReference | str) -> object:
        exact = _coerce_reference(self._contract_kind, reference)
        binding = self._by_reference.get(exact)
        if binding is None:
            raise _authority_error(
                "unknown_runtime_contract_binding",
                "exact runtime contract reference is not registered",
                reference=exact,
            )
        return binding


def _coerce_reference(
    expected_kind: HarnessContractKind,
    value: HarnessContractReference | str,
) -> HarnessContractReference:
    if isinstance(value, HarnessContractReference):
        reference = value
    else:
        if (
            not isinstance(value, str)
            or value != value.strip()
            or value.count("@") != 1
        ):
            raise _authority_error(
                "invalid_runtime_contract_reference",
                "runtime contract reference must use exact '<id>@<version>' form",
                reference=value,
                expected_kind=expected_kind.value,
            )
        contract_id, version = value.rsplit("@", maxsplit=1)
        _validate_reference_component(
            contract_id,
            field="contract_id",
            pattern=_CONTRACT_ID_PATTERN,
        )
        _validate_reference_component(
            version,
            field="version",
            pattern=_VERSION_PATTERN,
        )
        try:
            reference = HarnessContractReference(expected_kind, contract_id, version)
        except (HarnessValidationError, TypeError, ValueError) as exc:
            raise _authority_error(
                "invalid_runtime_contract_reference",
                "runtime contract reference is invalid or uses a moving version",
                reference=value,
                expected_kind=expected_kind.value,
            ) from exc
    if reference.contract_kind is not expected_kind:
        raise _authority_error(
            "runtime_contract_kind_mismatch",
            "runtime contract reference kind does not match the resolver",
            reference=reference,
            expected_kind=expected_kind.value,
            actual_kind=reference.contract_kind.value,
        )
    _validate_reference_component(
        reference.contract_id,
        field="contract_id",
        pattern=_CONTRACT_ID_PATTERN,
    )
    _validate_reference_component(
        reference.version,
        field="version",
        pattern=_VERSION_PATTERN,
    )
    return reference


def _require_implementation_identity(
    implementation: object,
    reference: HarnessContractReference,
    *,
    id_attribute: str,
    version_attribute: str,
) -> None:
    actual_id = _implementation_component(
        implementation,
        id_attribute,
        pattern=_CONTRACT_ID_PATTERN,
        reference=reference,
    )
    actual_version = _implementation_component(
        implementation,
        version_attribute,
        pattern=_VERSION_PATTERN,
        reference=reference,
    )
    if actual_version.casefold() in {"current", "default", "latest", "stable"}:
        raise _authority_error(
            "invalid_runtime_contract_implementation",
            "runtime implementation version must be exact",
            reference=reference,
            implementation_version=actual_version,
        )
    if actual_id != reference.contract_id or actual_version != reference.version:
        raise _authority_error(
            "runtime_contract_implementation_mismatch",
            "runtime implementation identity and version must match its exact reference",
            reference=reference,
            implementation_id=actual_id,
            implementation_version=actual_version,
        )


def _implementation_component(
    implementation: object,
    attribute: str,
    *,
    pattern: re.Pattern[str],
    reference: HarnessContractReference,
) -> str:
    value = getattr(implementation, attribute, None)
    if (
        not isinstance(value, str)
        or value != value.strip()
        or pattern.fullmatch(value) is None
    ):
        raise _authority_error(
            "invalid_runtime_contract_implementation",
            "runtime implementation exact identity is missing or invalid",
            reference=reference,
            attribute=attribute,
        )
    return value


def _validate_reference_component(
    value: str,
    *,
    field: str,
    pattern: re.Pattern[str],
) -> None:
    if not value or value != value.strip() or pattern.fullmatch(value) is None:
        raise _authority_error(
            "invalid_runtime_contract_reference",
            "runtime contract reference component is invalid",
            field=field,
            value=value,
        )


def _coerce_worker_type(value: object, *, field: str) -> HarnessWorkerType:
    try:
        return HarnessWorkerType(value)
    except (TypeError, ValueError) as exc:
        raise _authority_error(
            "invalid_runtime_worker_type",
            "runtime worker type is unsupported",
            field=field,
            value=str(value),
        ) from exc


def _authority_error(
    code: str,
    message: str,
    *,
    reference: object | None = None,
    **details: object,
) -> HarnessValidationError:
    payload: dict[str, object] = {"code": code, **details}
    if reference is not None:
        payload["reference"] = (
            reference.exact_ref
            if isinstance(reference, HarnessContractReference)
            else str(reference)
        )
    return HarnessValidationError(message, code=code, details=payload)


__all__ = [
    "HarnessActivityCapabilities",
    "HarnessActivityContractBinding",
    "HarnessActivityUsage",
    "HarnessCompensationHandlerBinding",
    "HarnessDeterministicMergeBinding",
    "HarnessRuntimeBindingAuthority",
    "HarnessWorkerBinding",
]
