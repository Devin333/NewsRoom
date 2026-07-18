from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gates import DeterministicGate


_GATE_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]*$")
_GATE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_AMBIGUOUS_VERSION_ALIASES = frozenset({"current", "default", "latest", "stable"})


@dataclass(frozen=True, slots=True, order=True)
class GateReference:
    gate_id: str
    version: str

    def __post_init__(self) -> None:
        gate_id = _validate_component(self.gate_id, pattern=_GATE_ID_PATTERN)
        version = _validate_component(self.version, pattern=_GATE_VERSION_PATTERN)
        if version.casefold() in _AMBIGUOUS_VERSION_ALIASES:
            raise _registry_error(
                "invalid_gate_reference",
                "gate version must be exact and cannot use a moving alias",
                reference=self,
            )
        object.__setattr__(self, "gate_id", gate_id)
        object.__setattr__(self, "version", version)

    @classmethod
    def parse(cls, value: str) -> GateReference:
        if not isinstance(value, str) or value.count("@") != 1:
            raise _registry_error(
                "invalid_gate_reference",
                "gate reference must use the exact '<gate-id>@<version>' form",
                reference=value,
            )
        gate_id, version = value.split("@", maxsplit=1)
        try:
            return cls(gate_id=gate_id, version=version)
        except HarnessValidationError as exc:
            raise _registry_error(
                "invalid_gate_reference",
                "gate reference must use the exact '<gate-id>@<version>' form",
                reference=value,
            ) from exc

    def __str__(self) -> str:
        return f"{self.gate_id}@{self.version}"


@dataclass(frozen=True, slots=True)
class GateRegistration:
    reference: GateReference
    gate: DeterministicGate
    dependencies: tuple[GateReference, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.reference, GateReference):
            raise _registry_error(
                "invalid_gate_registration",
                "gate registration reference must be a GateReference",
                reference=self.reference,
            )
        if not isinstance(self.gate, DeterministicGate):
            raise _registry_error(
                "invalid_gate_registration",
                "gate registration implementation must be a DeterministicGate",
                reference=self.reference,
            )
        implementation_id = str(getattr(self.gate, "gate_name", "")).strip()
        implementation_version = str(
            getattr(self.gate, "gate_version", "")
        ).strip()
        if (
            implementation_id != self.reference.gate_id
            or implementation_version != self.reference.version
        ):
            raise _registry_error(
                "incompatible_gate_implementation",
                "gate implementation identity and version must match its exact reference",
                reference=self.reference,
                implementation_id=implementation_id,
                implementation_version=implementation_version,
            )
        dependencies = tuple(self.dependencies)
        if any(not isinstance(dependency, GateReference) for dependency in dependencies):
            raise _registry_error(
                "invalid_gate_registration",
                "gate dependencies must be GateReference values",
                reference=self.reference,
            )
        object.__setattr__(self, "dependencies", dependencies)


@dataclass(frozen=True, slots=True)
class GateBinding:
    reference: GateReference
    gate: DeterministicGate
    dependencies: tuple[GateReference, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.reference, GateReference):
            raise _registry_error(
                "invalid_gate_binding",
                "gate binding reference must be a GateReference",
                reference=self.reference,
            )
        if not isinstance(self.gate, DeterministicGate):
            raise _registry_error(
                "invalid_gate_binding",
                "gate binding implementation must be a DeterministicGate",
                reference=self.reference,
            )
        dependencies = tuple(self.dependencies)
        if any(not isinstance(dependency, GateReference) for dependency in dependencies):
            raise _registry_error(
                "invalid_gate_binding",
                "gate binding dependencies must be GateReference values",
                reference=self.reference,
            )
        object.__setattr__(self, "dependencies", dependencies)

    @property
    def gate_id(self) -> str:
        return self.reference.gate_id

    @property
    def version(self) -> str:
        return self.reference.version


class DeterministicGateRegistry:
    """Instance-scoped registry that resolves only exact, versioned gate references."""

    def __init__(self, registrations: Iterable[GateRegistration] = ()) -> None:
        self._bindings: dict[GateReference, GateBinding] = {}
        for registration in registrations:
            self.register(registration)

    def register(self, registration: GateRegistration) -> None:
        if not isinstance(registration, GateRegistration):
            raise _registry_error(
                "invalid_gate_registration",
                "registration must be a GateRegistration",
                reference=getattr(registration, "reference", registration),
            )
        reference = registration.reference
        if reference in self._bindings:
            raise _registry_error(
                "duplicate_gate_registration",
                "gate reference is already registered",
                reference=reference,
            )
        self._bindings[reference] = GateBinding(
            reference=reference,
            gate=registration.gate,
            dependencies=registration.dependencies,
        )

    def resolve(self, reference: str | GateReference) -> GateBinding:
        exact_reference = _coerce_reference(reference)
        binding = self._bindings.get(exact_reference)
        if binding is None:
            raise _registry_error(
                "unknown_gate_reference",
                "exact gate reference is not registered",
                reference=exact_reference,
            )
        return binding

    def bindings_for(self, reference: str | GateReference) -> tuple[GateBinding, ...]:
        root = _coerce_reference(reference)
        ordered: list[GateBinding] = []
        completed: set[GateReference] = set()
        active: list[GateReference] = []

        def visit(current: GateReference, *, required_by: GateReference | None) -> None:
            if current in completed:
                return
            if current in active:
                cycle_start = active.index(current)
                cycle = (*active[cycle_start:], current)
                raise _registry_error(
                    "gate_dependency_cycle",
                    "gate dependency cycle detected",
                    reference=current,
                    cycle=[str(item) for item in cycle],
                )

            binding = self._bindings.get(current)
            if binding is None:
                raise _registry_error(
                    "missing_gate_dependency" if required_by is not None else "unknown_gate_reference",
                    "registered gate dependency is missing"
                    if required_by is not None
                    else "exact gate reference is not registered",
                    reference=current,
                    required_by=required_by,
                )

            active.append(current)
            for dependency in binding.dependencies:
                visit(dependency, required_by=current)
            active.pop()
            completed.add(current)
            ordered.append(binding)

        visit(root, required_by=None)
        return tuple(ordered)


def _coerce_reference(value: str | GateReference) -> GateReference:
    if isinstance(value, GateReference):
        return value
    return GateReference.parse(value)


def _validate_component(value: str, *, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or pattern.fullmatch(value) is None:
        raise _registry_error(
            "invalid_gate_reference",
            "gate reference component is invalid",
            reference=value,
        )
    return value


def _registry_error(
    code: str,
    message: str,
    *,
    reference: object,
    **details: object,
) -> HarnessValidationError:
    payload = {
        "code": code,
        "reference": str(reference),
        **{key: str(value) if isinstance(value, GateReference) else value for key, value in details.items()},
    }
    return HarnessValidationError(message, code=code, details=payload)


__all__ = [
    "DeterministicGateRegistry",
    "GateBinding",
    "GateReference",
    "GateRegistration",
]
