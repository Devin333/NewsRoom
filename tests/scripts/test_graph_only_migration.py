from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
from typing import Any

import pytest

from scripts.graph_only_migration import (
    ConversionStatus,
    GraphMigrationPlanner,
    LegacyRecordKind,
    LegacySourceDescriptor,
    QuarantineReasonCode,
    RunGraphMapping,
    ZERO_LIVE_SIDE_EFFECT_COUNTS,
    checksum_bytes,
)
from scripts.graph_only_migration.contracts import checksum_for, thaw_json


_FIXTURE_ROOT = Path("tests/fixtures/graph_only_migration")


def test_known_history_matches_equivalence_snapshot_and_is_deterministic() -> None:
    run_mapping = _run_mapping()
    sources = _sources(_FIXTURE_ROOT)
    planner = GraphMigrationPlanner()

    first = planner.build_plan(sources, {run_mapping.run_id: run_mapping})
    second = planner.build_plan(reversed(sources), {run_mapping.run_id: run_mapping})

    assert first.to_dict() == second.to_dict()
    assert first.counts == {
        "inventory": 8,
        "converted": 8,
        "quarantined": 0,
        "skipped_idempotent": 0,
    }
    assert first.to_dict()["side_effect_counts"] == dict(
        ZERO_LIVE_SIDE_EFFECT_COUNTS
    )
    assert first.plan_checksum.startswith("sha256:")

    targets = _targets_by_kind(first)
    manifest = targets[LegacyRecordKind.RUN_MANIFEST][0].payload
    events = sorted(
        targets[LegacyRecordKind.WORKFLOW_EVENT],
        key=lambda item: item.stream_sequence or 0,
    )
    checkpoint = targets[LegacyRecordKind.WORKFLOW_CHECKPOINT][0].payload
    replay = targets[LegacyRecordKind.REPLAY_BUNDLE][0].payload
    artifact = next(
        item
        for item in manifest["artifacts"]
        if item["artifact_id"] == "report-artifact"
    )
    actual = {
        "schema_version": "newsroom.graph-history-equivalence-snapshot/v1",
        "run_id": manifest["run_id"],
        "graph_id": manifest["graph_id"],
        "graph_version": manifest["graph_version"],
        "event_sequences": [item.stream_sequence for item in events],
        "terminal_status": manifest["status"],
        "terminal_node_ids": manifest["terminal_node_ids"],
        "gate_evidence_refs": manifest["gate_evidence_refs"],
        "artifact": {
            "artifact_id": artifact["artifact_id"],
            "relative_path": artifact["relative_path"],
            "content_checksum": artifact["content_checksum"],
            "node_id": artifact["node_id"],
            "node_instance_id": artifact["metadata"]["node_instance_id"],
        },
        "checkpoint": {
            "checkpoint_ref": checkpoint["checkpoint_ref"],
            "last_event_sequence": checkpoint["last_event_sequence"],
            "last_event_id": checkpoint["last_event_id"],
            "active_node_instance_ids": checkpoint["active_node_instance_ids"],
            "history_only": checkpoint["history_only"],
            "resume_allowed": checkpoint["resume_allowed"],
            "replay_validation_allowed": checkpoint[
                "replay_validation_allowed"
            ],
            "replay_execution_allowed": checkpoint[
                "replay_execution_allowed"
            ],
            "publication_allowed": checkpoint["publication_allowed"],
        },
        "replay": {
            "selected_node_ids": replay["decision_projection"][
                "selected_node_ids"
            ],
            "terminal_status": replay["decision_projection"]["terminal_status"],
            "live_worker_calls": replay["replay_policy"]["live_worker_calls"],
            "live_side_effect_calls": replay["replay_policy"][
                "live_side_effect_calls"
            ],
            "legacy_executor_calls": replay["replay_policy"][
                "legacy_executor_calls"
            ],
            "offline_validation_allowed": replay["replay_policy"][
                "offline_validation_allowed"
            ],
            "replay_execution_allowed": replay["replay_policy"][
                "replay_execution_allowed"
            ],
            "publication_allowed": replay["replay_policy"][
                "publication_allowed"
            ],
        },
        "inventory_count": first.counts["inventory"],
    }
    expected = json.loads(
        (_FIXTURE_ROOT / "expected_equivalence.json").read_text(encoding="utf-8")
    )
    assert thaw_json(actual) == expected
    for target_group in targets.values():
        for target in target_group:
            assert target.authority_mode == "staging_only"
            assert not _contains_retired_identity_key(target.payload)


def test_converted_terminal_manifest_matches_artifact_owner_wire_contract() -> None:
    from framework.harness.artifacts.terminal_manifest import GraphTerminalManifest

    mapping = _run_mapping()
    plan = GraphMigrationPlanner().build_plan(
        (
            _source_for_kind(LegacyRecordKind.RUN_MANIFEST),
            _source_for_kind(LegacyRecordKind.WORKFLOW_EVENT),
            _source_for_kind(LegacyRecordKind.WORKFLOW_CHECKPOINT),
        ),
        {mapping.run_id: mapping},
    )
    target = next(
        item.target
        for item in plan.items
        if item.inventory.record_kind is LegacyRecordKind.RUN_MANIFEST
    )
    assert target is not None

    parsed = GraphTerminalManifest.from_dict(thaw_json(target.payload))

    assert parsed.run_id == "run-001"
    assert parsed.manifest_hash == target.target_checksum


def test_production_shaped_legacy_manifest_uses_owner_metadata_contract(
    tmp_path: Path,
) -> None:
    from framework.harness.artifacts.terminal_manifest import GraphTerminalManifest
    from framework.workflow.runtime.manifest import validate_run_manifest
    from scripts.graph_only_migration.reader import BoundedLegacySourceReader
    from scripts.graph_only_migration.transformer import GraphHistoryTransformer
    from tests.fixtures.workflow_runs import write_canonical_terminal_run

    fixture = write_canonical_terminal_run(
        tmp_path / "run-manifests",
        run_id="run-001",
        workflow_id="legacy-paper-analysis",
        workflow_version="1.4.0",
    )
    manifest = dict(fixture.manifest)
    manifest["checkpoint_ref"] = "cp-001"
    manifest["latest_checkpoint_id"] = "cp-001"
    validate_run_manifest(manifest, require_terminal_artifact=True)
    fixture.manifest_path.write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    source = _descriptor(
        tmp_path,
        LegacyRecordKind.RUN_MANIFEST,
        "run-manifests",
        "run-001/manifest.json",
        "newsroom.workflow_run_manifest.v1",
    )
    record = BoundedLegacySourceReader().read(source)[0]

    target = GraphHistoryTransformer().transform(record, _run_mapping())
    parsed = GraphTerminalManifest.from_dict(thaw_json(target.payload))

    assert len(parsed.artifacts) >= 12
    assert "manifest" not in {item.artifact_key for item in parsed.artifacts}
    assert all(item.required_for_replay for item in parsed.artifacts)
    assert all(not item.required_for_publication for item in parsed.artifacts)


def test_fixture_sources_remain_valid_for_legacy_and_migration_readers() -> None:
    from framework.agent.artifacts.models import ArtifactRef
    from framework.events.canonical import StoredEvent
    from framework.workflow.checkpoint.durable import (
        durable_envelope_from_payload,
        verify_durable_checkpoint_checksum,
    )
    from framework.workflow.runtime.manifest import validate_run_manifest

    event_rows = [
        json.loads(line)
        for line in (_FIXTURE_ROOT / "events/run-001.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    stored_events = tuple(StoredEvent.from_dict(row) for row in event_rows)
    manifest_payload = json.loads(
        (_FIXTURE_ROOT / "run-manifests/run-001/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    checkpoint_payload = json.loads(
        (_FIXTURE_ROOT / "checkpoints/run-001/cp-001.json").read_text(
            encoding="utf-8"
        )
    )
    artifact_payload = json.loads(
        (_FIXTURE_ROOT / "artifact-index/run-001/report-artifact.json")
        .read_text(encoding="utf-8")
    )
    with pytest.raises(ValueError, match="fields are invalid"):
        ArtifactRef.from_dict(artifact_payload)
    cursor = json.loads(
        (_FIXTURE_ROOT / "cursors/conversation-001/cursor.json").read_text(
            encoding="utf-8"
        )
    )
    iteration = json.loads(
        (
            _FIXTURE_ROOT
            / "cursors/conversation-001/iteration_checkpoint.json"
        ).read_text(encoding="utf-8")
    )

    assert [item.stream_sequence for item in stored_events] == [1, 2]
    validate_run_manifest(manifest_payload, require_terminal_artifact=True)
    assert verify_durable_checkpoint_checksum(checkpoint)
    assert artifact_payload["artifact_id"] == "report-artifact"
    assert cursor["workflow_checkpoint_id"] == "cp-001"
    assert iteration["workflow_checkpoint_id"] == "cp-001"


@pytest.mark.parametrize(
    ("record_kind", "model"),
    (
        (LegacyRecordKind.CONVERSATION_CURSOR, "cursor"),
        (LegacyRecordKind.ITERATION_CHECKPOINT, "iteration"),
    ),
)
def test_history_only_conversation_state_cannot_enter_live_v2_reader(
    record_kind: LegacyRecordKind,
    model: str,
) -> None:
    from infrastructure.storage.conversation.models import (
        AgentIterationCheckpoint,
        ConversationCursor,
    )
    from scripts.graph_only_migration.reader import BoundedLegacySourceReader
    from scripts.graph_only_migration.transformer import GraphHistoryTransformer

    mapping = _run_mapping()
    record = BoundedLegacySourceReader().read(_source_for_kind(record_kind))[0]
    target = GraphHistoryTransformer().transform(
        record,
        mapping,
    )
    assert target.payload["history_only"] is True
    live_model = (
        ConversationCursor if model == "cursor" else AgentIterationCheckpoint
    )

    with pytest.raises(ValueError, match="fields are invalid"):
        live_model.from_dict(thaw_json(target.payload))


def test_history_only_checkpoint_cannot_claim_live_recovery_authority() -> None:
    mapping = _run_mapping()
    plan = GraphMigrationPlanner().build_plan(
        (
            _source_for_kind(LegacyRecordKind.WORKFLOW_EVENT),
            _source_for_kind(LegacyRecordKind.WORKFLOW_CHECKPOINT),
        ),
        {mapping.run_id: mapping},
    )
    target = next(
        item.target
        for item in plan.items
        if item.inventory.record_kind is LegacyRecordKind.WORKFLOW_CHECKPOINT
    )
    assert target is not None
    payload = target.payload

    assert payload["record_role"] == "migration_history_evidence"
    assert payload["history_only"] is True
    assert payload["resume_allowed"] is False
    assert payload["replay_validation_allowed"] is True
    assert payload["replay_execution_allowed"] is False
    assert payload["publication_allowed"] is False
    assert target.target_schema_version == "newsroom.graph-history-checkpoint/v1"


def test_checkpoint_without_converted_boundary_event_is_quarantined() -> None:
    mapping = _run_mapping()
    plan = GraphMigrationPlanner().build_plan(
        (_source_for_kind(LegacyRecordKind.WORKFLOW_CHECKPOINT),),
        {mapping.run_id: mapping},
    )

    assert plan.counts == {
        "inventory": 1,
        "converted": 0,
        "quarantined": 1,
        "skipped_idempotent": 0,
    }
    assert (
        plan.items[0].inventory.quarantine_reason
        is QuarantineReasonCode.INCOMPATIBLE_CHECKPOINT
    )


@pytest.mark.parametrize(
    ("kind", "expected_reason"),
    [
        (
            LegacyRecordKind.RUN_MANIFEST,
            QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
        ),
        (
            LegacyRecordKind.REPLAY_BUNDLE,
            QuarantineReasonCode.MISSING_TERMINAL_EVIDENCE,
        ),
        (
            LegacyRecordKind.CONVERSATION_CURSOR,
            QuarantineReasonCode.INCOMPATIBLE_CHECKPOINT,
        ),
        (
            LegacyRecordKind.ITERATION_CHECKPOINT,
            QuarantineReasonCode.INCOMPATIBLE_CHECKPOINT,
        ),
    ],
)
def test_missing_staging_references_are_quarantined(
    kind: LegacyRecordKind,
    expected_reason: QuarantineReasonCode,
) -> None:
    mapping = _run_mapping()
    plan = GraphMigrationPlanner().build_plan(
        (_source_for_kind(kind),),
        {mapping.run_id: mapping},
    )

    assert plan.counts["quarantined"] == 1
    assert plan.items[0].inventory.quarantine_reason is expected_reason


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("unknown_schema", QuarantineReasonCode.UNKNOWN_SCHEMA),
        ("checksum", QuarantineReasonCode.CHECKSUM_MISMATCH),
        ("unsafe_path", QuarantineReasonCode.ILLEGAL_SOURCE_PATH),
    ],
)
def test_reader_failures_become_stable_quarantine(
    mutation: str,
    expected_reason: QuarantineReasonCode,
) -> None:
    source = _sources(_FIXTURE_ROOT)[0]
    if mutation == "unknown_schema":
        source = replace(source, source_schema_version="unknown-source/v99")
    elif mutation == "checksum":
        source = replace(source, source_checksum=f"sha256:{'0' * 64}")
    elif mutation == "unsafe_path":
        source = replace(source, relative_path="../run-001/manifest.json")
    plan = GraphMigrationPlanner().build_plan(
        (source,),
        {"run-001": _run_mapping()},
    )

    assert plan.counts["quarantined"] == 1
    item = plan.items[0]
    assert item.inventory.quarantine_reason is expected_reason
    assert item.quarantine is not None
    assert item.quarantine.disposition == "read_only_no_execution"
    assert item.quarantine.to_dict()["resume_allowed"] is False
    assert item.quarantine.to_dict()["replay_execution_allowed"] is False
    assert item.quarantine.to_dict()["publication_allowed"] is False


def test_missing_graph_mapping_and_gate_evidence_are_not_guessed() -> None:
    manifest_source = _source_for_kind(LegacyRecordKind.RUN_MANIFEST)
    planner = GraphMigrationPlanner()

    missing_mapping = planner.build_plan((manifest_source,), {})
    assert (
        missing_mapping.items[0].inventory.quarantine_reason
        is QuarantineReasonCode.MISSING_GRAPH_IDENTITY
    )

    mapping_without_gates = replace(_run_mapping(), gate_evidence_refs=())
    missing_gates = planner.build_plan(
        (manifest_source,),
        {"run-001": mapping_without_gates},
    )
    assert (
        missing_gates.items[0].inventory.quarantine_reason
        is QuarantineReasonCode.MISSING_GATE_EVIDENCE
    )


def test_conflicting_workflow_identity_is_ambiguous_not_remapped(
    tmp_path: Path,
) -> None:
    snapshot = _copy_fixture(tmp_path)
    manifest_path = snapshot / "run-manifests/run-001/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["workflow_id"] = "different-legacy-workflow"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    source = _source_for_kind(LegacyRecordKind.RUN_MANIFEST, root=snapshot)

    plan = GraphMigrationPlanner().build_plan(
        (source,),
        {"run-001": _run_mapping(snapshot)},
    )

    assert (
        plan.items[0].inventory.quarantine_reason
        is QuarantineReasonCode.AMBIGUOUS_RECORD
    )


def test_event_sequence_gap_quarantines_the_entire_stream(tmp_path: Path) -> None:
    snapshot = _copy_fixture(tmp_path)
    event_path = snapshot / "events/run-001.jsonl"
    rows = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    rows[1]["stream_sequence"] = 3
    rows[1]["record_checksum"] = checksum_for(
        {key: value for key, value in rows[1].items() if key != "record_checksum"}
    )
    event_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    source = _source_for_kind(LegacyRecordKind.WORKFLOW_EVENT, root=snapshot)

    plan = GraphMigrationPlanner().build_plan(
        (source,),
        {"run-001": _run_mapping(snapshot)},
    )

    assert plan.counts["quarantined"] == 2
    assert {
        item.inventory.quarantine_reason for item in plan.items
    } == {QuarantineReasonCode.EVENT_SEQUENCE_GAP}


def test_canonical_event_checksum_tamper_is_quarantined(tmp_path: Path) -> None:
    snapshot = _copy_fixture(tmp_path)
    event_path = snapshot / "events/run-001.jsonl"
    first = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
    first["payload"]["status"] = "tampered"
    event_path.write_text(json.dumps(first) + "\n", encoding="utf-8")

    plan = GraphMigrationPlanner().build_plan(
        (_source_for_kind(LegacyRecordKind.WORKFLOW_EVENT, root=snapshot),),
        {"run-001": _run_mapping(snapshot)},
    )

    assert plan.counts["quarantined"] == 1
    assert (
        plan.items[0].inventory.quarantine_reason
        is QuarantineReasonCode.CHECKSUM_MISMATCH
    )


def test_artifact_traversal_and_checkpoint_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    snapshot = _copy_fixture(tmp_path)
    artifact_path = snapshot / "artifact-index/run-001/report-artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["path"] = "../outside.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    checkpoint_path = snapshot / "checkpoints/run-001/cp-001.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["data_buffer_snapshot"]["report"]["status"] = "tampered"
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    sources = (
        _source_for_kind(LegacyRecordKind.ARTIFACT_INDEX, root=snapshot),
        _source_for_kind(LegacyRecordKind.WORKFLOW_CHECKPOINT, root=snapshot),
    )

    plan = GraphMigrationPlanner().build_plan(
        sources,
        {"run-001": _run_mapping(snapshot)},
    )

    assert {
        item.inventory.record_kind: item.inventory.quarantine_reason
        for item in plan.items
    } == {
        LegacyRecordKind.ARTIFACT_INDEX: QuarantineReasonCode.ILLEGAL_ARTIFACT_PATH,
        LegacyRecordKind.WORKFLOW_CHECKPOINT: QuarantineReasonCode.CHECKSUM_MISMATCH,
    }


def test_existing_target_exact_body_is_idempotent_and_conflict_is_quarantined() -> None:
    source = _source_for_kind(LegacyRecordKind.ARTIFACT_INDEX)
    mapping = _run_mapping()
    planner = GraphMigrationPlanner()
    initial = planner.build_plan((source,), {"run-001": mapping})
    target = initial.items[0].target
    assert target is not None

    rerun = planner.build_plan(
        (source,),
        {"run-001": mapping},
        existing_targets={target.target_ref: target.target_checksum},
    )
    assert (
        rerun.items[0].inventory.conversion_status
        is ConversionStatus.SKIPPED_IDEMPOTENT
    )
    assert rerun.items[0].target == target

    conflict = planner.build_plan(
        (source,),
        {"run-001": mapping},
        existing_targets={target.target_ref: f"sha256:{'f' * 64}"},
    )
    assert (
        conflict.items[0].inventory.quarantine_reason
        is QuarantineReasonCode.TARGET_CONFLICT
    )


def test_planner_calls_no_live_worker_or_side_effect_module() -> None:
    forbidden_prefixes = (
        "business.",
        "framework.agent.loop",
        "framework.llm",
        "framework.memory",
        "framework.tool",
        "framework.workflow",
        "interfaces.",
        "infrastructure.",
    )
    calls: list[str] = []

    def profile(frame: Any, event: str, arg: Any) -> None:
        del arg
        if event != "call":
            return
        module_name = str(frame.f_globals.get("__name__", ""))
        if module_name.startswith(forbidden_prefixes):
            calls.append(module_name)

    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        mapping = _run_mapping()
        plan = GraphMigrationPlanner().build_plan(
            _sources(_FIXTURE_ROOT),
            {mapping.run_id: mapping},
        )
    finally:
        sys.setprofile(previous)

    assert calls == []
    assert plan.to_dict()["side_effect_counts"] == dict(
        ZERO_LIVE_SIDE_EFFECT_COUNTS
    )


def _run_mapping(root: Path = _FIXTURE_ROOT) -> RunGraphMapping:
    payload = json.loads((root / "run_mapping.json").read_text(encoding="utf-8"))
    return RunGraphMapping.from_dict(payload)


def _sources(root: Path) -> tuple[LegacySourceDescriptor, ...]:
    return (
        _descriptor(
            root,
            LegacyRecordKind.RUN_MANIFEST,
            "run-manifests",
            "run-001/manifest.json",
            "newsroom.workflow_run_manifest.v1",
        ),
        _descriptor(
            root,
            LegacyRecordKind.WORKFLOW_EVENT,
            "events",
            "run-001.jsonl",
            "newsroom.workflow-event/v1",
        ),
        _descriptor(
            root,
            LegacyRecordKind.WORKFLOW_CHECKPOINT,
            "checkpoints",
            "run-001/cp-001.json",
            "workflow-checkpoint/v2",
        ),
        _descriptor(
            root,
            LegacyRecordKind.REPLAY_BUNDLE,
            "replay",
            "run-001/replay_bundle.json",
            "newsroom.workflow-replay-bundle/unversioned-1",
        ),
        _descriptor(
            root,
            LegacyRecordKind.ARTIFACT_INDEX,
            "artifact-index",
            "run-001/report-artifact.json",
            "newsroom.artifact-ref/unversioned-1",
        ),
        _descriptor(
            root,
            LegacyRecordKind.CONVERSATION_CURSOR,
            "cursors",
            "conversation-001/cursor.json",
            "newsroom.conversation-cursor/unversioned-1",
        ),
        _descriptor(
            root,
            LegacyRecordKind.ITERATION_CHECKPOINT,
            "cursors",
            "conversation-001/iteration_checkpoint.json",
            "newsroom.agent-iteration-checkpoint/unversioned-1",
        ),
    )


def _descriptor(
    root: Path,
    kind: LegacyRecordKind,
    directory: str,
    relative_path: str,
    schema_version: str,
) -> LegacySourceDescriptor:
    source_root = root / directory
    path = source_root.joinpath(*relative_path.split("/"))
    return LegacySourceDescriptor(
        environment="fixture",
        source_store=directory,
        owner="migration-test-owner",
        record_kind=kind,
        source_root=source_root,
        relative_path=relative_path,
        source_schema_version=schema_version,
        source_checksum=checksum_bytes(path.read_bytes()),
    )


def _source_for_kind(
    kind: LegacyRecordKind,
    *,
    root: Path = _FIXTURE_ROOT,
) -> LegacySourceDescriptor:
    return next(source for source in _sources(root) if source.record_kind is kind)


def _copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "graph-only-migration"
    shutil.copytree(_FIXTURE_ROOT, target)
    return target


def _targets_by_kind(plan: Any) -> dict[LegacyRecordKind, list[Any]]:
    result: dict[LegacyRecordKind, list[Any]] = {}
    for item in plan.items:
        if item.target is not None:
            result.setdefault(item.target.record_kind, []).append(item.target)
    return result


def _contains_retired_identity_key(value: Any) -> bool:
    if isinstance(value, dict):
        if any(str(key).startswith("workflow_") for key in value):
            return True
        return any(_contains_retired_identity_key(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_retired_identity_key(item) for item in value)
    return False
