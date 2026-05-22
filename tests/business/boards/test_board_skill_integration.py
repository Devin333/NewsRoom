from __future__ import annotations

from framework.skills import SkillFailureReason, SkillResult

from business.boards.ai_news.runner import AINewsRunner
from business.evaluation.fixtures import sample_signal


class FailingSkillRunner:
    def run(self, skill_name, input_data, *, context):
        return SkillResult.failed(skill_name, "test", SkillFailureReason.EXECUTION_FAILED, "fail", "fail")


def test_board_workflow_records_skill_traces_and_falls_back(tmp_path) -> None:
    result = AINewsRunner(artifact_root=tmp_path, skill_runner=FailingSkillRunner()).run(
        signals=[sample_signal("ai_news")],
        topic="Agent Memory",
        run_id="skill-fallback-board",
    )

    traces = result.output["quality_summary"]["skill_trace_metadata"]
    assert traces
    assert any(trace["used_fallback"] for trace in traces)
    assert result.output["cards"]
