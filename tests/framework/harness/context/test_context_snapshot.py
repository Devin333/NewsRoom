from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness import ContextAssembler, ContextReplayGate, HarnessValidationError


def test_context_snapshot_supports_replay_from_refs() -> None:
    assembler = ContextAssembler()
    envelope = assembler.assemble({"run_id": "run-replay", "step_id": "verify"})
    snapshot = assembler.snapshot_store.load(envelope.snapshot_ref or "")
    replayed = assembler.snapshot_store.replay(envelope.snapshot_ref or "")

    assert ContextReplayGate().evaluate(snapshot).passed is True
    assert replayed.envelope_id == envelope.envelope_id
    assert snapshot.assembled_prompt_ref.startswith("artifact://assembled-context/")
    assert snapshot.metadata["payload_saved"] is False


def test_context_replay_rejects_checksum_mismatch() -> None:
    assembler = ContextAssembler()
    envelope = assembler.assemble({"run_id": "run-replay", "step_id": "verify"})
    assembler.snapshot_store.envelopes[envelope.envelope_id] = replace(envelope, token_estimate=envelope.token_estimate + 1)

    with pytest.raises(HarnessValidationError):
        assembler.snapshot_store.replay(envelope.snapshot_ref or "")
