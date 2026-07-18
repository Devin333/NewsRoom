from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gate_registry import (
    DeterministicGateRegistry,
    GateBinding,
    GateReference,
    GateRegistration,
)
from framework.harness.control_plane.gates import DeterministicGate


class _Gate(DeterministicGate):
    def __init__(self, name: str, version: str = "1") -> None:
        self.gate_name = name
        self.gate_version = version


def test_gate_reference_parses_exact_version_and_is_immutable() -> None:
    reference = GateReference.parse("ClaimEvidenceGate@2")

    assert reference == GateReference(gate_id="ClaimEvidenceGate", version="2")
    assert str(reference) == "ClaimEvidenceGate@2"
    with pytest.raises(FrozenInstanceError):
        reference.version = "3"  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    (
        "",
        "ClaimEvidenceGate",
        "ClaimEvidenceGate@",
        "@2",
        "ClaimEvidenceGate@2@latest",
        "ClaimEvidenceGate@latest",
        "ClaimEvidenceGate@default",
        " ClaimEvidenceGate@2",
        "ClaimEvidenceGate@2 ",
        "Claim Evidence Gate@2",
    ),
)
def test_gate_reference_rejects_unversioned_or_ambiguous_values(value: str) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        GateReference.parse(value)

    assert captured.value.code == "invalid_gate_reference"
    assert captured.value.details == {"code": "invalid_gate_reference", "reference": value}


def test_registry_resolves_only_the_exact_registered_version() -> None:
    version_one = _registration("ClaimEvidenceGate@1")
    version_two = _registration("ClaimEvidenceGate@2")
    registry = DeterministicGateRegistry((version_one, version_two))

    binding = registry.resolve("ClaimEvidenceGate@2")

    assert binding.reference == GateReference.parse("ClaimEvidenceGate@2")
    assert binding.gate is version_two.gate
    assert binding.version == "2"
    with pytest.raises(HarnessValidationError) as captured:
        registry.resolve("ClaimEvidenceGate@3")
    assert captured.value.code == "unknown_gate_reference"
    assert captured.value.details["reference"] == "ClaimEvidenceGate@3"


def test_registry_rejects_duplicate_exact_registration() -> None:
    registry = DeterministicGateRegistry()
    registry.register(_registration("ClaimEvidenceGate@2"))

    with pytest.raises(HarnessValidationError) as captured:
        registry.register(_registration("ClaimEvidenceGate@2"))

    assert captured.value.code == "duplicate_gate_registration"
    assert captured.value.details["reference"] == "ClaimEvidenceGate@2"


@pytest.mark.parametrize(
    ("reference", "implementation_name", "implementation_version"),
    (
        ("ClaimEvidenceGate@2", "DifferentGate", "2"),
        ("ClaimEvidenceGate@2", "ClaimEvidenceGate", "1"),
    ),
)
def test_registration_rejects_incompatible_implementation_identity_or_version(
    reference: str,
    implementation_name: str,
    implementation_version: str,
) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        GateRegistration(
            reference=GateReference.parse(reference),
            gate=_Gate(implementation_name, implementation_version),
        )

    assert captured.value.code == "incompatible_gate_implementation"
    assert captured.value.details == {
        "code": "incompatible_gate_implementation",
        "reference": reference,
        "implementation_id": implementation_name,
        "implementation_version": implementation_version,
    }


def test_bindings_for_rejects_a_missing_dependency() -> None:
    registry = DeterministicGateRegistry(
        (
            _registration(
                "ReportQualityGate@1",
                dependencies=("EvidenceCoverageGate@1",),
            ),
        )
    )

    with pytest.raises(HarnessValidationError) as captured:
        registry.bindings_for("ReportQualityGate@1")

    assert captured.value.code == "missing_gate_dependency"
    assert captured.value.details == {
        "code": "missing_gate_dependency",
        "reference": "EvidenceCoverageGate@1",
        "required_by": "ReportQualityGate@1",
    }


def test_bindings_for_rejects_a_dependency_cycle() -> None:
    registry = DeterministicGateRegistry(
        (
            _registration("GateA@1", dependencies=("GateB@1",)),
            _registration("GateB@1", dependencies=("GateC@1",)),
            _registration("GateC@1", dependencies=("GateA@1",)),
        )
    )

    with pytest.raises(HarnessValidationError) as captured:
        registry.bindings_for("GateA@1")

    assert captured.value.code == "gate_dependency_cycle"
    assert captured.value.details["reference"] == "GateA@1"
    assert captured.value.details["cycle"] == ["GateA@1", "GateB@1", "GateC@1", "GateA@1"]


def test_bindings_for_returns_stable_dependency_first_deduplicated_order() -> None:
    registry = DeterministicGateRegistry(
        (
            _registration("ReportGate@1", dependencies=("SchemaGate@1", "EvidenceGate@1")),
            _registration("EvidenceGate@1", dependencies=("LineageGate@1",)),
            _registration("SchemaGate@1", dependencies=("LineageGate@1",)),
            _registration("LineageGate@1"),
        )
    )

    bindings = registry.bindings_for(GateReference.parse("ReportGate@1"))

    assert tuple(str(binding.reference) for binding in bindings) == (
        "LineageGate@1",
        "SchemaGate@1",
        "EvidenceGate@1",
        "ReportGate@1",
    )
    assert all(isinstance(binding, GateBinding) for binding in bindings)


def test_registrations_and_bindings_are_immutable() -> None:
    registration = _registration("ReportGate@1", dependencies=("SchemaGate@1",))
    registry = DeterministicGateRegistry(
        (registration, _registration("SchemaGate@1"))
    )
    binding = registry.resolve("ReportGate@1")

    assert isinstance(registration.dependencies, tuple)
    assert isinstance(binding.dependencies, tuple)
    with pytest.raises(FrozenInstanceError):
        registration.dependencies = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        binding.dependencies = ()  # type: ignore[misc]


def test_registry_instances_do_not_share_registrations() -> None:
    first = DeterministicGateRegistry((_registration("ReportGate@1"),))
    second = DeterministicGateRegistry()

    assert first.resolve("ReportGate@1").gate_id == "ReportGate"
    with pytest.raises(HarnessValidationError) as captured:
        second.resolve("ReportGate@1")
    assert captured.value.code == "unknown_gate_reference"


def _registration(
    reference: str,
    *,
    dependencies: tuple[str, ...] = (),
) -> GateRegistration:
    parsed = GateReference.parse(reference)
    return GateRegistration(
        reference=parsed,
        gate=_Gate(parsed.gate_id, parsed.version),
        dependencies=tuple(GateReference.parse(item) for item in dependencies),
    )
