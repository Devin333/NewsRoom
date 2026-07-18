from __future__ import annotations

import pytest

from framework.events.canonical import checksum_for
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
    assert report.gate_results[0]["verification_status"] == "legacy_unverified"
    assert report.artifacts == ("artifact://worker-output",)


def test_replay_identifies_versioned_gate_evidence_without_reexecuting_it() -> None:
    raw_result = {
        "gate": "candidate_quality",
        "passed": True,
        "reason": None,
        "details": {},
    }
    transcript = HarnessTranscript("run-versioned-replay")
    transcript.append(
        HarnessTranscriptEntry(
            entry_id="entry-verify",
            run_id="run-versioned-replay",
            step_id="collect",
            phase="verify",
            gate_results=(
                {
                    "gate": "candidate_quality",
                    "passed": True,
                    "details": {
                        "harness_gate": {
                            "reference": "candidate_quality@1",
                            "input_ref": "sha256:" + "1" * 64,
                            "result_ref": checksum_for(raw_result),
                            "reason_code": "gate_passed",
                        }
                    },
                },
            ),
        )
    )

    report = HarnessReplayReader().replay(
        run_id="run-versioned-replay",
        transcript=transcript,
    )

    assert report.side_effects_replayed is False
    assert report.gate_results[0]["verification_status"] == "versioned_evidence"


@pytest.mark.parametrize(
    ("reference", "input_ref", "result_ref"),
    (
        ("candidate_quality@latest", "sha256:" + "1" * 64, "sha256:" + "2" * 64),
        ("candidate_quality@1", "not-a-checksum", "sha256:" + "2" * 64),
        ("candidate_quality@1", "sha256:" + "1" * 64, "not-a-checksum"),
        ("candidate_quality@1", "sha256:" + "1" * 64, "sha256:" + "2" * 64),
    ),
)
def test_replay_marks_malformed_gate_evidence_unverified(
    reference: str,
    input_ref: str,
    result_ref: str,
) -> None:
    transcript = HarnessTranscript("run-malformed-gate-replay")
    transcript.append(
        HarnessTranscriptEntry(
            entry_id="entry-verify",
            run_id="run-malformed-gate-replay",
            step_id="collect",
            phase="verify",
            gate_results=(
                {
                    "gate": "candidate_quality",
                    "passed": True,
                    "details": {
                        "harness_gate": {
                            "reference": reference,
                            "input_ref": input_ref,
                            "result_ref": result_ref,
                            "reason_code": "gate_passed",
                        }
                    },
                },
            ),
        )
    )

    report = HarnessReplayReader().replay(
        run_id="run-malformed-gate-replay",
        transcript=transcript,
    )

    assert report.gate_results[0]["verification_status"] == "malformed_unverified"
