from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from framework.harness import (
    FakeSubAgentRuntime,
    FakeSubAgentWorker,
    HarnessValidationError,
    HarnessWorkerResult,
    SubAgentRuntime,
    SubAgentTranscriptObservation,
    SubAgentTranscript,
    SubAgentTranscriptCorruptError,
    SubAgentTranscriptGate,
    SubAgentTranscriptStoreError,
    fake_subagent_spec,
)
from framework.harness.subagents.transcript import FakeSubAgentTranscriptStore


def test_transcript_rejects_nested_private_keys_and_secret_like_values() -> None:
    runtime = FakeSubAgentRuntime(fake_subagent_spec())
    invocation = runtime.build_invocation()
    # Build a valid identity through the already-created invocation and use the
    # runtime once to obtain the canonical attempt shape.
    result = runtime.invoke(invocation)
    transcript = runtime.transcript_store.read(result.transcript_ref or "")

    with pytest.raises(HarnessValidationError) as private_error:
        SubAgentTranscript(
            identity=transcript.identity,
            context_envelope_ref=transcript.context_envelope_ref,
            input_refs=transcript.input_refs,
            gate_results=(
                {
                    "gate_id": "test_gate",
                    "gate_version": "1",
                    "input_checksum": "sha256:" + "1" * 64,
                    "passed": True,
                    "reason_code": "test_gate_passed",
                    "evidence_checksum": "sha256:" + "2" * 64,
                    "nested": {"hidden_prompt": "private"},
                },
            ),
        )
    assert private_error.value.code in {
        "subagent_transcript_private_content_rejected",
        "subagent_transcript_gate_evidence_invalid",
    }

    with pytest.raises(HarnessValidationError) as secret_error:
        SubAgentTranscript(
            identity=transcript.identity,
            context_envelope_ref=transcript.context_envelope_ref,
            input_refs=transcript.input_refs,
            redaction_report={"note": "sk-test-secret-value"},
        )
    assert secret_error.value.code == "subagent_transcript_secret_content_rejected"


def test_transcript_gate_rejects_fabricated_receipt() -> None:
    runtime = FakeSubAgentRuntime(fake_subagent_spec())
    result = runtime.invoke(runtime.build_invocation())
    assert result.transcript_receipt is not None
    stale = replace(
        result.transcript_receipt,
        output_checksum="sha256:" + "f" * 64,
    )
    fabricated = replace(result, transcript_receipt=stale)

    gate = SubAgentTranscriptGate().evaluate(
        fabricated,
        store=runtime.transcript_store,
    )

    assert gate.passed is False
    assert gate.reason_code in {
        "subagent_transcript_corrupt",
        "subagent_transcript_checksum_mismatch",
    }


def test_store_failure_never_returns_worker_result_as_acceptable() -> None:
    source = FakeSubAgentRuntime(fake_subagent_spec())
    invocation = source.build_invocation()

    class FailingStore(FakeSubAgentTranscriptStore):
        def write(self, context, output, transcript):
            raise SubAgentTranscriptStoreError(
                "transcript storage is unavailable",
                code="subagent_transcript_store_unavailable",
            )

    runtime = SubAgentRuntime(
        workers={
            source.spec.subagent_id: FakeSubAgentWorker(
                (HarnessWorkerResult(status="succeeded", output={"result": "ok"}),)
            )
        },
        transcript_store=FailingStore(),
    )

    with pytest.raises(SubAgentTranscriptStoreError) as captured:
        runtime.invoke(invocation)

    assert captured.value.code == "subagent_transcript_store_unavailable"


def test_committed_receipt_recovery_does_not_call_worker() -> None:
    source_worker = FakeSubAgentWorker(
        (HarnessWorkerResult(status="succeeded", output={"result": "ok"}),)
    )
    source = FakeSubAgentRuntime(fake_subagent_spec(), source_worker)
    invocation = source.build_invocation()
    first = source.invoke(invocation)
    assert first.transcript_receipt is not None
    assert len(source_worker.calls) == 1

    class ExplodingWorker:
        calls = 0

        def execute(self, task):
            self.calls += 1
            raise AssertionError("recovery must not invoke a live worker")

    worker = ExplodingWorker()
    recovered_runtime = SubAgentRuntime(
        workers={source.spec.subagent_id: worker},
        transcript_store=source.transcript_store,
    )
    recovered = recovered_runtime.invoke(invocation)

    assert recovered.invocation_id == first.invocation_id
    assert recovered.child_run_id == first.child_run_id
    assert recovered.subagent_id == first.subagent_id
    assert recovered.status == first.status
    assert recovered.output == first.output
    assert recovered.artifact_refs == first.artifact_refs
    assert recovered.transcript_receipt == first.transcript_receipt
    assert recovered.metadata["recovered"] is True
    assert worker.calls == 0


def test_memory_write_candidates_are_sanitized_but_not_persisted_as_authority() -> None:
    worker = FakeSubAgentWorker(
        (
            HarnessWorkerResult(
                status="succeeded",
                output={
                    "result": "ok",
                    "memory_write_candidates": (
                        {
                            "candidate_id": "memory-candidate-1",
                            "namespace": "research.public",
                            "content_ref": "artifact://research/memory-candidate-1",
                        },
                    ),
                },
            ),
        )
    )
    runtime = FakeSubAgentRuntime(fake_subagent_spec(), worker)

    result = runtime.invoke(runtime.build_invocation())
    receipt = result.transcript_receipt

    assert result.memory_write_candidates == (
        {
            "candidate_id": "memory-candidate-1",
            "namespace": "research.public",
            "content_ref": "artifact://research/memory-candidate-1",
        },
    )
    assert receipt is not None
    output = runtime.transcript_store.read_output(receipt.output_ref)
    transcript = runtime.transcript_store.read(receipt.transcript_ref)
    assert "memory_write_candidates" not in output.output
    assert "memory_write_candidates" not in transcript.to_dict()


def test_private_memory_write_candidate_halts_without_persisting_candidate_body() -> None:
    worker = FakeSubAgentWorker(
        (
            HarnessWorkerResult(
                status="succeeded",
                output={
                    "result": "ok",
                    "memory_write_candidates": (
                        {"candidate_id": "memory-candidate-1", "secret": "private"},
                    ),
                },
            ),
        )
    )
    runtime = FakeSubAgentRuntime(fake_subagent_spec(), worker)

    result = runtime.invoke(runtime.build_invocation())

    assert result.status.value == "halted"
    assert result.errors == ("subagent_worker_output_invalid",)
    assert result.memory_write_candidates == ()
    assert result.transcript_receipt is not None
    transcript = runtime.transcript_store.read(result.transcript_receipt.transcript_ref)
    assert transcript.errors == ("subagent_worker_output_invalid",)


def test_recovery_observation_is_payload_free_and_sink_failure_is_non_authoritative() -> None:
    source = FakeSubAgentRuntime(fake_subagent_spec())
    invocation = source.build_invocation()
    first = source.invoke(invocation)
    observations: list[SubAgentTranscriptObservation] = []

    class CollectingSink:
        def record(self, observation: SubAgentTranscriptObservation) -> None:
            observations.append(observation)

    recovered_runtime = SubAgentRuntime(
        workers={},
        transcript_store=source.transcript_store,
        observation_sink=CollectingSink(),
    )
    recovered = recovered_runtime.invoke(invocation)

    assert recovered.transcript_receipt == first.transcript_receipt
    assert len(observations) == 1
    observation = observations[0]
    assert observation.name == "subagent_transcript_recovery_reused_total"
    assert observation.value == 1.0
    assert set(observation.to_dict()) == {
        "name",
        "transcript_id",
        "invocation_id",
        "parent_run_id",
        "child_run_id",
        "workflow_id",
        "stage_id",
        "task_id",
        "task_instance_id",
        "attempt",
        "subagent_id",
        "transcript_ref",
        "transcript_checksum",
        "output_ref",
        "output_checksum",
        "reason_code",
        "value",
    }
    assert not any(
        key in observation.to_dict()
        for key in ("output", "transcript", "context", "memory_write_candidates")
    )

    class FailingSink:
        def record(self, observation: SubAgentTranscriptObservation) -> None:
            raise RuntimeError("telemetry unavailable")

    recovered_with_failed_telemetry = SubAgentRuntime(
        workers={},
        transcript_store=source.transcript_store,
        observation_sink=FailingSink(),
    ).invoke(invocation)
    assert recovered_with_failed_telemetry.transcript_receipt == first.transcript_receipt


@pytest.mark.parametrize("value", (float("nan"), float("inf"), -1.0))
def test_observation_rejects_non_finite_or_negative_values(value: float) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        SubAgentTranscriptObservation(
            name="subagent_transcript_bytes",
            value=value,
        )

    assert captured.value.code == "subagent_transcript_observation_invalid"


def test_fake_store_identity_lookup_fails_closed_on_dangling_receipt() -> None:
    runtime = FakeSubAgentRuntime(fake_subagent_spec())
    invocation = runtime.build_invocation()
    result = runtime.invoke(invocation)
    receipt = result.transcript_receipt
    assert receipt is not None
    transcript = runtime.transcript_store.read(receipt.transcript_ref)
    del runtime.transcript_store.transcripts[receipt.transcript_ref]

    with pytest.raises(SubAgentTranscriptCorruptError) as captured:
        runtime.transcript_store.find_by_identity(transcript.identity)

    assert captured.value.code == "subagent_transcript_corrupt"
