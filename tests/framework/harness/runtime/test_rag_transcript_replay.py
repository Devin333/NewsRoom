from __future__ import annotations

from framework.harness import HarnessEventLogEntry, HarnessReplayReader, HarnessTranscript, HarnessTranscriptEntry


def test_rag_transcript_replay_explains_query_source_memory_and_halt() -> None:
    transcript = HarnessTranscript("run-rag")
    transcript.append(
        HarnessTranscriptEntry(
            entry_id="entry-rag",
            run_id="run-rag",
            phase="verify",
            rag_session_refs=("rag-session://reader-repair",),
            retrieval_plan_refs=("rag-plan://reader-repair/1",),
            context_pack_refs=("rag-context://reader-repair",),
            evidence_refs=("evidence://method",),
            gate_results=({"gate": "rag_evidence_coverage", "passed": False, "reason": "missing limitation"},),
            budget_snapshot={"queries_used": 2, "max_queries": 2},
            metadata={"memory_hit_refs": ["memory://reader-repair/success"]},
        )
    )
    events = (
        HarnessEventLogEntry(
            event_id="event-rag-round",
            run_id="run-rag",
            event_type="rag_step_executed",
            rag_session_id="rag-session://reader-repair",
            retrieval_round=1,
            metadata={"query": "reader repair method evidence", "accepted_evidence_refs": ["evidence://method"]},
        ),
    )

    report = HarnessReplayReader().replay(run_id="run-rag", events=events, transcript=transcript)

    assert report.rag_sessions == ("rag-session://reader-repair",)
    assert report.retrieval_rounds[0]["round"] == 1
    assert report.context_packs == ("rag-context://reader-repair",)
    assert report.side_effects_replayed is False
