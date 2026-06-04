from __future__ import annotations

from framework.harness import (
    HarnessEventLogEntry,
    HarnessReplayReader,
    HarnessTranscript,
    HarnessTranscriptEntry,
)


def test_replay_reads_transcript_and_event_log_without_side_effects() -> None:
    transcript = HarnessTranscript("run-replay")
    transcript.append(
        HarnessTranscriptEntry(
            entry_id="entry-plan",
            run_id="run-replay",
            step_id="collect",
            phase="plan",
            gate_results=({"gate": "budget", "passed": True},),
            budget_snapshot={"turns_used": 1},
            artifact_refs=("artifact://worker-output",),
        )
    )
    events = (
        HarnessEventLogEntry(
            event_id="event-halt",
            run_id="run-replay",
            step_id="collect",
            event_type="run_state_changed",
            status_after="halted",
            error="budget exhausted",
        ),
    )

    report = HarnessReplayReader().replay(run_id="run-replay", events=events, transcript=transcript)

    assert report.status == "halted"
    assert report.side_effects_replayed is False
    assert report.gate_results[0]["gate"] == "budget"
    assert report.artifacts == ("artifact://worker-output",)
