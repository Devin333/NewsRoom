from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from business.research.graphs.reader_repair import (
    READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF,
    READER_REPAIR_MEMORY_HANDLER_REF,
    READER_REPAIR_SUBAGENT_IDS,
    build_reader_repair_graph_definition,
)
from business.research.graphs.reader_repair_runtime import (
    READER_REPAIR_RUNTIME_BINDING_SCHEMA,
    build_reader_repair_runtime_binding_bundle,
)
from framework.harness import HarnessValidationError, HarnessWorkerResult
from framework.harness.graph.activity import HarnessWorkerType
from framework.harness.graph.bindings import HarnessActivityCapabilities


@dataclass(frozen=True, slots=True)
class _Worker:
    worker_id: str
    worker_version: str
    worker_type: HarnessWorkerType

    def execute(self, _task: dict[str, Any]) -> HarnessWorkerResult:
        return HarnessWorkerResult(status="succeeded", output={})


@dataclass(frozen=True, slots=True)
class _Activity:
    activity_contract_id: str
    activity_contract_version: str
    capabilities: HarnessActivityCapabilities = HarnessActivityCapabilities(
        stable_idempotency=True,
    )

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        return dict(request)


class _MemorySideEffectHandler:
    def prepare(self, intent: object, authorization: object) -> tuple[object, object]:
        return intent, authorization

    def commit(self, intent: object, authorization: object) -> tuple[object, object]:
        return intent, authorization


class _FailureDiagnosticSideEffectHandler:
    def commit(self, intent: object, authorization: object) -> tuple[object, object]:
        return intent, authorization


def test_reader_repair_runtime_bundle_closes_graph_v2_exactly_without_activation() -> None:
    workers, activities = _implementations()

    bundle = build_reader_repair_runtime_binding_bundle(
        worker_implementations=workers,
        activity_implementations=activities,
        memory_side_effect_handler=_MemorySideEffectHandler(),
        failure_diagnostic_side_effect_handler=(
            _FailureDiagnosticSideEffectHandler()
        ),
    )
    manifest = bundle.to_manifest()

    assert manifest["schema_version"] == READER_REPAIR_RUNTIME_BINDING_SCHEMA
    assert manifest["installs_runtime_authority"] is False
    assert manifest["graph_id"] == "research.reader_repair.graph"
    assert manifest["graph_version"] == "2"
    assert manifest["graph_definition_checksum"] == (
        "sha256:fadbddd1dfb4e0880745f23e0be136a449ae23cd92d2b855c43be17f1a5d9307"
    )
    assert set(manifest["workers"]) == set(workers)
    assert set(manifest["activities"]) == set(activities)
    assert set(manifest["gates"]) == set(workers)
    for activity in bundle.definition.activities:
        assert manifest["gates"][activity.step_id][-1] == activity.quality_gate
    assert {
        activity_id
        for activity_id, worker in manifest["workers"].items()
        if worker["worker_type"] == HarnessWorkerType.SUBAGENT.value
    } == set(READER_REPAIR_SUBAGENT_IDS)
    assert manifest["terminal_side_effect"] == {
        "reference": READER_REPAIR_MEMORY_HANDLER_REF,
        "kind": "memory_write",
        "supports_origins": ["worker", "controller_terminal"],
    }
    assert manifest["terminal_failure_side_effect"] == {
        "reference": READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF,
        "kind": "memory_write_failure_diagnostic",
        "supports_origins": ["controller_terminal"],
        "disposition": "quarantine",
        "failure_record_schema": (
            "newsroom.harness-graph-terminal-failure-record/v1"
        ),
    }
    assert "artifact" not in json.dumps(manifest, sort_keys=True).casefold()


@pytest.mark.parametrize(
    "implementation_kind",
    ("worker", "activity"),
)
@pytest.mark.parametrize("mutation", ("missing", "unexpected"))
def test_reader_repair_runtime_bundle_rejects_inexact_implementation_sets(
    implementation_kind: str,
    mutation: str,
) -> None:
    workers, activities = _implementations()
    target = workers if implementation_kind == "worker" else activities
    if mutation == "missing":
        target.pop("build_repair_case")
    else:
        target["unexpected_step"] = next(iter(target.values()))

    with pytest.raises(HarnessValidationError) as captured:
        build_reader_repair_runtime_binding_bundle(
            worker_implementations=workers,
            activity_implementations=activities,
            memory_side_effect_handler=_MemorySideEffectHandler(),
            failure_diagnostic_side_effect_handler=(
                _FailureDiagnosticSideEffectHandler()
            ),
        )

    assert captured.value.code == "reader_repair_runtime_registration_mismatch"
    assert captured.value.details["registration_field"] == (
        "worker_implementations"
        if implementation_kind == "worker"
        else "activity_implementations"
    )
    expected_detail = (
        "missing_activity_ids" if mutation == "missing" else "unexpected_activity_ids"
    )
    assert captured.value.details[expected_detail]


def test_reader_repair_runtime_bundle_rejects_substituted_exact_worker_identity() -> None:
    workers, activities = _implementations()
    original = workers["apply_repair_candidate"]
    workers["apply_repair_candidate"] = _Worker(
        worker_id=original.worker_id,
        worker_version="2",
        worker_type=original.worker_type,
    )

    with pytest.raises(HarnessValidationError) as captured:
        build_reader_repair_runtime_binding_bundle(
            worker_implementations=workers,
            activity_implementations=activities,
            memory_side_effect_handler=_MemorySideEffectHandler(),
            failure_diagnostic_side_effect_handler=(
                _FailureDiagnosticSideEffectHandler()
            ),
        )

    assert captured.value.code == "runtime_contract_implementation_mismatch"
    assert captured.value.details["reference"] == (
        "research.reader_repair.apply_repair_candidate@1"
    )


def test_reader_repair_runtime_bundle_requires_a_real_memory_handler_contract() -> None:
    workers, activities = _implementations()

    with pytest.raises(HarnessValidationError) as captured:
        build_reader_repair_runtime_binding_bundle(
            worker_implementations=workers,
            activity_implementations=activities,
            memory_side_effect_handler=object(),  # type: ignore[arg-type]
            failure_diagnostic_side_effect_handler=(
                _FailureDiagnosticSideEffectHandler()
            ),
        )

    assert captured.value.code == "reader_repair_runtime_registration_mismatch"
    assert captured.value.details["registration_field"] == (
        "memory_side_effect_handler"
    )


def test_reader_repair_runtime_bundle_requires_a_distinct_failure_handler_contract() -> None:
    workers, activities = _implementations()

    with pytest.raises(HarnessValidationError) as captured:
        build_reader_repair_runtime_binding_bundle(
            worker_implementations=workers,
            activity_implementations=activities,
            memory_side_effect_handler=_MemorySideEffectHandler(),
            failure_diagnostic_side_effect_handler=object(),  # type: ignore[arg-type]
        )

    assert captured.value.code == "reader_repair_runtime_registration_mismatch"
    assert captured.value.details["registration_field"] == (
        "failure_diagnostic_side_effect_handler"
    )


def _implementations() -> tuple[dict[str, _Worker], dict[str, _Activity]]:
    definition = build_reader_repair_graph_definition()
    workers: dict[str, _Worker] = {}
    activities: dict[str, _Activity] = {}
    for activity in definition.activities:
        leaf = definition.leaf_activity_binding(activity.step_id)
        assert leaf is not None
        workers[activity.step_id] = _Worker(
            worker_id=leaf.worker_ref.contract_id,
            worker_version=leaf.worker_ref.version,
            worker_type=activity.worker_type,
        )
        activities[activity.step_id] = _Activity(
            activity_contract_id=leaf.activity_ref.contract_id,
            activity_contract_version=leaf.activity_ref.version,
        )
    return workers, activities
