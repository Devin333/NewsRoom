from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from framework.harness import (
    SubAgentAttemptIdentity,
    SubAgentContextEvidence,
    SubAgentOutputDocument,
    SubAgentTranscript,
    SubAgentTranscriptConflictError,
    SubAgentTranscriptStoreError,
    SubAgentTranscriptObservation,
)
from framework.shared.json import stable_json_dumps
from infrastructure.storage.harness import FilesystemSubAgentTranscriptStore


FIXED_TIME = datetime(2026, 8, 13, 1, 2, 3, tzinfo=UTC)


def _identity(*, parent_run_id: str = "run-1", attempt: int = 1) -> SubAgentAttemptIdentity:
    return SubAgentAttemptIdentity(
        invocation_id=f"invocation://{parent_run_id}/task-1/{attempt}",
        parent_run_id=parent_run_id,
        child_run_id=f"{parent_run_id}:stage-1:task-instance-{attempt}",
        workflow_id="research-paper-analysis",
        stage_id="analysis",
        task_id="structure",
        task_instance_id=f"task-instance-{attempt}",
        attempt=attempt,
        subagent_id="research-structure-analyst",
    )


def _documents(
    *,
    identity: SubAgentAttemptIdentity | None = None,
    result: str = "ok",
) -> tuple[SubAgentContextEvidence, SubAgentOutputDocument, SubAgentTranscript]:
    resolved = identity or _identity()
    context_ref = f"subagent-context://v1/{resolved.parent_run_id}/{resolved.transcript_id}"
    context = SubAgentContextEvidence(
        identity=resolved,
        context_envelope_ref=context_ref,
        input_refs=("artifact://input/source",),
        memory_context_refs=(),
        redaction_report={
            "raw_parent_messages_included": False,
            "sibling_history_included": False,
        },
    )
    output = SubAgentOutputDocument(
        identity=resolved,
        status="succeeded",
        output={"result": result},
        artifact_refs=("artifact://analysis/structure",),
    )
    gate_projection = {
        "gate_id": "subagent_output_schema",
        "gate_version": "1",
        "input_checksum": "sha256:" + "1" * 64,
        "passed": True,
        "reason_code": "subagent_output_schema_passed",
    }
    from framework.events.canonical import checksum_for

    transcript = SubAgentTranscript(
        identity=resolved,
        context_envelope_ref=context_ref,
        input_refs=context.input_refs,
        output_ref=output.ref,
        output_checksum=output.output_checksum,
        artifact_refs=output.artifact_refs,
        gate_results=({**gate_projection, "evidence_checksum": checksum_for(gate_projection)},),
        budget_snapshot={"max_turns": 3},
        redaction_report=context.redaction_report,
        events=({"event_type": "subagent_completed"},),
        observed_at=FIXED_TIME,
    )
    return context, output, transcript


def test_store_reopens_and_resolves_every_typed_section(tmp_path: Path) -> None:
    context, output, transcript = _documents()
    first = FilesystemSubAgentTranscriptStore(tmp_path, clock=lambda: FIXED_TIME)

    receipt = first.write(context, output, transcript)
    reopened = FilesystemSubAgentTranscriptStore(tmp_path)

    assert reopened.verify(receipt) == receipt
    assert reopened.read(receipt.transcript_ref) == transcript
    assert reopened.read_context(receipt.context_ref) == context
    assert reopened.read_output(receipt.output_ref) == output
    assert reopened.find_by_identity(transcript.identity) == receipt
    files = tuple(tmp_path.rglob("*.json"))
    assert len(files) == 1
    assert not tuple(tmp_path.rglob("*.tmp"))


def test_store_emits_stable_payload_free_commit_observations(tmp_path: Path) -> None:
    observations: list[SubAgentTranscriptObservation] = []

    class CollectingSink:
        def record(self, observation: SubAgentTranscriptObservation) -> None:
            observations.append(observation)

    monotonic_values = iter((10.0, 10.025))
    store = FilesystemSubAgentTranscriptStore(
        tmp_path,
        clock=lambda: FIXED_TIME,
        monotonic=lambda: next(monotonic_values),
        observation_sink=CollectingSink(),
    )

    receipt = store.write(*_documents())

    assert {observation.name for observation in observations} == {
        "subagent_transcript_commit_succeeded",
        "subagent_transcript_bytes",
        "subagent_transcript_commit_latency_ms",
    }
    for observation in observations:
        payload = observation.to_dict()
        assert payload["transcript_ref"] == receipt.transcript_ref
        assert payload["transcript_checksum"] == receipt.transcript_checksum
        assert payload["output_ref"] == receipt.output_ref
        assert payload["output_checksum"] == receipt.output_checksum
        assert not any(
            key in payload
            for key in ("output", "transcript", "context", "gate_results")
        )
    values = {observation.name: observation.value for observation in observations}
    assert values["subagent_transcript_commit_succeeded"] == 1.0
    assert values["subagent_transcript_bytes"] is not None
    assert values["subagent_transcript_bytes"] > 0
    assert values["subagent_transcript_commit_latency_ms"] == pytest.approx(25.0)


def test_observation_sink_failure_does_not_change_commit_result(tmp_path: Path) -> None:
    class FailingSink:
        def record(self, observation: SubAgentTranscriptObservation) -> None:
            raise RuntimeError("telemetry unavailable")

    store = FilesystemSubAgentTranscriptStore(
        tmp_path,
        clock=lambda: FIXED_TIME,
        observation_sink=FailingSink(),
    )

    receipt = store.write(*_documents())

    assert store.verify(receipt) == receipt


def test_same_identity_same_documents_are_idempotent_across_instances(tmp_path: Path) -> None:
    documents = _documents()
    first = FilesystemSubAgentTranscriptStore(tmp_path, clock=lambda: FIXED_TIME)
    second = FilesystemSubAgentTranscriptStore(
        tmp_path,
        clock=lambda: datetime(2026, 8, 13, 2, 0, tzinfo=UTC),
    )

    original = first.write(*documents)
    retried = second.write(*documents)

    assert retried == original
    assert retried.committed_at == FIXED_TIME
    assert second.refs_for_parent("run-1") == (original.transcript_ref,)


def test_same_identity_different_documents_conflict_without_overwrite(tmp_path: Path) -> None:
    store = FilesystemSubAgentTranscriptStore(tmp_path, clock=lambda: FIXED_TIME)
    original_documents = _documents(result="first")
    conflicting_documents = _documents(result="different")
    original = store.write(*original_documents)

    with pytest.raises(SubAgentTranscriptConflictError) as captured:
        store.write(*conflicting_documents)

    assert captured.value.code == "subagent_transcript_conflict"
    assert store.verify(original) == original
    assert dict(store.read_output(original.output_ref).output) == {"result": "first"}


def test_two_store_instances_commit_same_attempt_once_under_thread_race(tmp_path: Path) -> None:
    documents = _documents()
    stores = (
        FilesystemSubAgentTranscriptStore(tmp_path, clock=lambda: FIXED_TIME),
        FilesystemSubAgentTranscriptStore(tmp_path, clock=lambda: FIXED_TIME),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = tuple(pool.map(lambda store: store.write(*documents), stores))

    assert receipts[0] == receipts[1]
    assert stores[0].refs_for_parent("run-1") == (receipts[0].transcript_ref,)
    assert len(tuple(tmp_path.rglob("*.json"))) == 1


def test_two_processes_commit_same_attempt_once(tmp_path: Path) -> None:
    context, output, transcript = _documents()
    payload_path = tmp_path / "attempt-input.json"
    payload_path.write_text(
        stable_json_dumps(
            {
                "context": context.to_dict(),
                "output": output.to_dict(),
                "transcript": transcript.to_dict(),
            }
        ),
        encoding="utf-8",
    )
    start_path = tmp_path / "start.signal"
    helper = Path(__file__).with_name("subagent_transcript_process_worker.py")
    receipt_paths = (tmp_path / "receipt-1.json", tmp_path / "receipt-2.json")
    processes = [
        subprocess.Popen(
            (
                sys.executable,
                str(helper),
                str(tmp_path / "store"),
                str(payload_path),
                str(start_path),
                str(receipt_path),
            ),
            cwd=Path(__file__).parents[4],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for receipt_path in receipt_paths
    ]
    start_path.write_text("start", encoding="utf-8")
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, (stdout, stderr)

    outcomes = tuple(json.loads(path.read_text(encoding="utf-8")) for path in receipt_paths)
    assert outcomes[0] == outcomes[1]
    reopened = FilesystemSubAgentTranscriptStore(tmp_path / "store")
    assert len(reopened.refs_for_parent("run-1")) == 1
    assert len(tuple((tmp_path / "store").rglob("*.json"))) == 1


def test_tampered_bundle_fails_closed(tmp_path: Path) -> None:
    observations: list[SubAgentTranscriptObservation] = []

    class CollectingSink:
        def record(self, observation: SubAgentTranscriptObservation) -> None:
            observations.append(observation)

    store = FilesystemSubAgentTranscriptStore(
        tmp_path,
        clock=lambda: FIXED_TIME,
        observation_sink=CollectingSink(),
    )
    receipt = store.write(*_documents())
    path = next(tmp_path.rglob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["output"]["output"]["result"] = "tampered"
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(SubAgentTranscriptStoreError) as captured:
        store.verify(receipt)

    assert captured.value.code == "subagent_transcript_corrupt"
    assert [observation.name for observation in observations[-2:]] == [
        "subagent_transcript_verify_failed",
        "subagent_transcript_corrupt",
    ]
    assert all(
        observation.reason_code == "subagent_transcript_corrupt"
        for observation in observations[-2:]
    )


def test_missing_bundle_and_storage_unavailability_have_stable_codes(tmp_path: Path) -> None:
    store = FilesystemSubAgentTranscriptStore(tmp_path)
    identity = _identity()
    assert store.find_by_identity(identity) is None

    with pytest.raises(SubAgentTranscriptStoreError) as missing:
        store.read(f"subagent-transcript://v1/run-1/{identity.transcript_id}")
    assert missing.value.code == "subagent_transcript_not_found"

    unavailable_root = tmp_path / "not-a-directory"
    unavailable_root.write_text("occupied", encoding="utf-8")
    with pytest.raises(SubAgentTranscriptStoreError) as unavailable:
        FilesystemSubAgentTranscriptStore(unavailable_root)
    assert unavailable.value.code == "subagent_transcript_store_unavailable"


def test_size_limit_rejects_before_publication(tmp_path: Path) -> None:
    store = FilesystemSubAgentTranscriptStore(
        tmp_path,
        max_transcript_bytes=4096,
        max_output_bytes=1024,
        max_bundle_bytes=8192,
    )
    context, _, _ = _documents()
    output = SubAgentOutputDocument(
        identity=context.identity,
        status="succeeded",
        output={"result": "x" * 1500},
    )
    _, _, template = _documents()
    transcript = SubAgentTranscript(
        identity=context.identity,
        context_envelope_ref=context.context_envelope_ref,
        input_refs=context.input_refs,
        output_ref=output.ref,
        output_checksum=output.output_checksum,
        budget_snapshot=template.budget_snapshot,
        redaction_report=template.redaction_report,
        observed_at=FIXED_TIME,
    )

    with pytest.raises(SubAgentTranscriptStoreError) as captured:
        store.write(context, output, transcript)

    assert captured.value.code == "subagent_transcript_size_exceeded"
    assert not tuple(tmp_path.rglob("*.json"))


def test_parent_query_is_bounded_sorted_deduplicated_and_scoped(tmp_path: Path) -> None:
    store = FilesystemSubAgentTranscriptStore(tmp_path, clock=lambda: FIXED_TIME)
    run_one = [store.write(*_documents(identity=_identity(attempt=attempt))) for attempt in (3, 1, 2)]
    run_two = store.write(*_documents(identity=_identity(parent_run_id="run-2")))

    refs = store.refs_for_parent("run-1", limit=2)

    assert refs == tuple(sorted(receipt.transcript_ref for receipt in run_one))[:2]
    assert len(refs) == len(set(refs))
    assert all("/run-1/" in ref for ref in refs)
    assert run_two.transcript_ref not in refs


@pytest.mark.parametrize(
    "ref",
    (
        "subagent-transcript://v1/../sat_" + "0" * 64,
        "subagent-transcript://v1/run-1/../../escape",
        "https://example.invalid/transcript",
    ),
)
def test_malformed_or_escaping_refs_are_rejected(ref: str, tmp_path: Path) -> None:
    store = FilesystemSubAgentTranscriptStore(tmp_path)

    with pytest.raises(SubAgentTranscriptStoreError) as captured:
        store.read(ref)

    assert captured.value.code == "subagent_transcript_identity_mismatch"
