from __future__ import annotations

from pathlib import Path

from framework.skills import MockSkillExecutor, SkillEvaluator, SkillPackageLoader, SkillRegistry, SkillRunner


FIXTURES = Path("tests/fixtures/skills")


def test_skill_evaluator_runs_examples_and_calculates_rates() -> None:
    registry = SkillRegistry()
    registry.register_package(SkillPackageLoader().load(FIXTURES / "runnable-skill"))
    runner = SkillRunner(
        registry=registry,
        executor=MockSkillExecutor(outputs={"runnable-skill": {"result": "ok", "evidence": [{"source_id": "fx"}]}}),
    )
    evaluator = SkillEvaluator(registry=registry, runner=runner)

    result = evaluator.evaluate("runnable-skill")

    assert result.passed()
    assert result.total_cases == 1
    assert result.passed_cases == 1
    assert result.schema_pass_rate == 1.0
    assert result.quality_gate_pass_rate == 1.0
    assert result.example_pass_rate == 1.0
    assert result.case_results[0].case_id == "case_001"
