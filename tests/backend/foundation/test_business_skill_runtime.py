from __future__ import annotations

import pytest

from framework.skills import SkillFailureReason, SkillResult

from backend.foundation.skills import BusinessSkillRuntime


class SuccessfulSkillRunner:
    def run(self, skill_name, input_data, *, context):
        return SkillResult.success(
            skill_name=skill_name,
            version="test",
            output={"skill_name": skill_name, "input_seen": bool(input_data)},
            trace={"run_id": context.run_id},
        )


class FailingSkillRunner:
    def run(self, skill_name, input_data, *, context):
        return SkillResult.failed(
            skill_name,
            "test",
            SkillFailureReason.EXECUTION_FAILED,
            "mock_failure",
            "mock failure",
        )


def test_business_skill_runtime_fallbacks_are_offline() -> None:
    runtime = BusinessSkillRuntime()

    assert runtime.run_entity_extraction({"title": "OpenAI Agent Memory"}).used_fallback
    assert runtime.run_source_reliability({"publisher_type": "official_blog"}, {"title": "x"}).output["reliability_score"] > 0
    assert runtime.run_event_deduplication([{"item_id": "1", "title": "A"}]).output["event_groups"]
    assert runtime.run_evidence_checking([{"claim_id": "c1", "text": "x"}], [{"source_id": "s1", "text": "x"}]).output["claim_results"]
    assert runtime.run_report_writing({"title": "Report"}, [{"item_id": "i1", "title": "Item"}]).output["markdown_report"]
    assert runtime.run_trend_analysis([{"event_id": "e1", "title": "Trend"}]).output["event_analyses"]


def test_business_skill_runtime_uses_injected_runner() -> None:
    result = BusinessSkillRuntime(SuccessfulSkillRunner()).run_entity_extraction({"title": "OpenAI"})

    assert result.status == "success"
    assert result.output["skill_name"] == "entity-extraction"
    assert result.trace["trace"]["run_id"] == "business-skill-run"
    assert not result.used_fallback


def test_business_skill_runtime_failure_falls_back_or_raises() -> None:
    runtime = BusinessSkillRuntime(FailingSkillRunner())

    result = runtime.run_trend_analysis([{"event_id": "e1"}])
    assert result.used_fallback
    assert result.errors

    with pytest.raises(ValueError):
        runtime.run_trend_analysis([{"event_id": "e1"}], fail_on_skill_error=True)
