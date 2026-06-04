from __future__ import annotations

from framework.harness import HarnessReplayReport, HarnessTraceExporter


def test_trace_export_projects_replay_report_for_review() -> None:
    report = HarnessReplayReport(
        run_id="run-trace",
        status="succeeded",
        phase_transitions=({"step_id": "collect", "phase": "verify", "decision": {"decision_type": "complete_step"}},),
        gate_results=({"gate": "schema", "passed": True},),
        budget_summary={"turns_used": 3},
        artifacts=("artifact://report",),
        skill_candidates=("candidate://skill/1",),
        rag_sessions=("rag-session://1",),
        context_snapshots=("context-snapshot://1",),
    )

    trace = HarnessTraceExporter().export(report)

    assert trace["run_id"] == "run-trace"
    assert trace["steps"] == [{"step_id": "collect", "phase": "verify"}]
    assert trace["rag_sessions"] == ["rag-session://1"]
    assert trace["metrics"]["side_effects_replayed"] is False
