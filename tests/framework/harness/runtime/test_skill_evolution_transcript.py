from __future__ import annotations

from framework.harness import HarnessEventLogEntry, HarnessReplayReader, HarnessTranscript, HarnessTranscriptEntry


def test_skill_evolution_transcript_replays_candidate_release_and_rollback_refs() -> None:
    transcript = HarnessTranscript("run-skill")
    transcript.append(
        HarnessTranscriptEntry(
            entry_id="entry-candidate",
            run_id="run-skill",
            phase="verify",
            candidate_refs=("candidate://reader-repair/1",),
            eval_refs=("eval://reader-repair/held-out",),
            release_refs=("skill-release://reader-repair/1.1.0",),
            metadata={"promotion_decision": {"status": "promote"}},
        )
    )
    events = (
        HarnessEventLogEntry(
            event_id="event-skill",
            run_id="run-skill",
            event_type="skill_release_published",
            skill_name="reader-repair",
            skill_version="1.1.0",
            skill_candidate_id="candidate://reader-repair/1",
        ),
    )

    report = HarnessReplayReader().replay(run_id="run-skill", events=events, transcript=transcript)

    assert report.skill_candidates == ("candidate://reader-repair/1",)
    assert report.skill_releases == ("skill-release://reader-repair/1.1.0",)
    assert report.side_effects_replayed is False
