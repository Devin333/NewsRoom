from __future__ import annotations

from framework.harness import HarnessTranscriptEntry, InMemoryHarnessTranscriptStore


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
