from __future__ import annotations

from framework.harness import (
    HarnessTranscript,
    HarnessTranscriptEntry,
    InMemoryHarnessTranscriptStore,
)


def test_transcript_records_plan_execute_verify_phase_entries() -> None:
    store = InMemoryHarnessTranscriptStore()
    for phase in ("plan", "execute", "verify"):
        store.append(
            HarnessTranscriptEntry(
                entry_id=f"entry-{phase}",
                run_id="run-transcript",
                step_id="collect",
                phase=phase,
                gate_results=({"gate": f"{phase}-gate", "passed": True},) if phase == "verify" else (),
                budget_snapshot={"turns_used": 1},
            )
        )

    entries = store.entries_for_run("run-transcript")

    assert [entry.phase for entry in entries] == ["plan", "execute", "verify"]
    assert entries[-1].gate_results[0]["gate"] == "verify-gate"


def test_transcript_round_trips_all_persisted_reference_fields() -> None:
    entry = HarnessTranscriptEntry(
        entry_id="entry-persist",
        run_id="run-persist",
        step_id="verify",
        phase="VERIFY",
        decision={"decision": "complete"},
        input_refs=("input://1",),
        output_refs=("output://1",),
        gate_results=({"gate": "quality", "passed": True},),
        budget_snapshot={"turns_used": 1},
        worker_call_ref="worker-call://1",
        artifact_refs=("artifact://run-persist/report",),
        skill_refs=("skill://research",),
        candidate_refs=("candidate://1",),
        rag_session_refs=("rag-session://1",),
        retrieval_plan_refs=("rag-plan://1",),
        context_pack_refs=("rag-context://1",),
        context_envelope_ref="context://1",
        context_snapshot_ref="context-snapshot://1",
        compression_record_refs=("compression://1",),
        evidence_refs=("evidence://1",),
        eval_refs=("eval://1",),
        release_refs=("release://1",),
        metadata={"phase_index": 1},
    )
    transcript = HarnessTranscript("run-persist", (entry,))

    payload = transcript.to_dict()
    restored = HarnessTranscript.from_dict(payload)

    assert restored.to_dict() == payload
