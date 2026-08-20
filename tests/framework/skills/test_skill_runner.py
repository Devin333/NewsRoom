from __future__ import annotations

from pathlib import Path

import pytest

from framework.skills import (
    MockSkillExecutor,
    SkillFailureReason,
    SkillOutput,
    SkillPackageLoader,
    SkillRegistry,
    SkillRunContext,
    SkillRunStatus,
    SkillRunner,
)


FIXTURES = Path("tests/fixtures/skills")


class ExplodingExecutor:
    def execute(self, package, input_data, prompt_bundle, context):
        raise RuntimeError("boom")


def _registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register_package(SkillPackageLoader().load(FIXTURES / "runnable-skill"))
    return registry


def test_skill_runner_success() -> None:
    runner = SkillRunner(
        registry=_registry(),
        executor=MockSkillExecutor(outputs={"runnable-skill": {"result": "ok", "evidence": [{"source_id": "fx"}]}}),
    )

    result = runner.run("runnable-skill", {"text": "hello"}, SkillRunContext.for_test("runnable-skill"))

    assert result.is_success()
    assert result.output["result"] == "ok"
    assert result.quality_gate_results
    assert result.trace["events"]


def test_skill_runner_requires_explicit_context() -> None:
    runner = SkillRunner(registry=_registry())

    with pytest.raises(TypeError, match="SkillRunContext is required"):
        runner.run("runnable-skill", {"text": "hello"}, None)  # type: ignore[arg-type]


def test_skill_runner_rejects_context_for_another_skill() -> None:
    runner = SkillRunner(registry=_registry())

    with pytest.raises(ValueError, match="skill_name does not match"):
        runner.run(
            "runnable-skill",
            {"text": "hello"},
            SkillRunContext.for_standalone("other-skill", "test-mismatch"),
        )


def test_skill_runner_skill_not_found_failure() -> None:
    result = SkillRunner(registry=_registry()).run(
        "missing-skill", {"text": "hello"}, SkillRunContext.for_standalone("missing-skill", "test-missing")
    )

    assert result.status == SkillRunStatus.FAILED
    assert result.failure_reason == SkillFailureReason.SKILL_NOT_FOUND


def test_skill_runner_input_schema_failure() -> None:
    result = SkillRunner(registry=_registry()).run(
        "runnable-skill", {"missing": "hello"}, SkillRunContext.for_standalone("runnable-skill", "test-input")
    )

    assert result.status == SkillRunStatus.FAILED
    assert result.failure_reason == SkillFailureReason.INPUT_SCHEMA_INVALID


def test_skill_runner_output_schema_failure() -> None:
    result = SkillRunner(
        registry=_registry(),
        executor=MockSkillExecutor(outputs={"runnable-skill": {"evidence": []}}),
    ).run("runnable-skill", {"text": "hello"}, SkillRunContext.for_standalone("runnable-skill", "test-output"))

    assert result.status == SkillRunStatus.FAILED
    assert result.failure_reason == SkillFailureReason.OUTPUT_SCHEMA_INVALID


def test_skill_runner_executor_exception_failure() -> None:
    result = SkillRunner(registry=_registry(), executor=ExplodingExecutor()).run(
        "runnable-skill", {"text": "hello"}, SkillRunContext.for_standalone("runnable-skill", "test-exception")
    )

    assert result.status == SkillRunStatus.FAILED
    assert result.failure_reason == SkillFailureReason.EXECUTION_FAILED


def test_skill_runner_quality_gate_failure_is_partial() -> None:
    registry = _registry()
    package = registry.get_package("runnable-skill")
    assert package is not None
    package.metadata.quality_gates = ["evidence_required"]
    result = SkillRunner(
        registry=registry,
        executor=MockSkillExecutor(outputs={"runnable-skill": {"result": "ok"}}),
    ).run("runnable-skill", {"text": "hello"}, SkillRunContext.for_standalone("runnable-skill", "test-quality"))

    assert result.status == SkillRunStatus.PARTIAL
    assert result.failure_reason == SkillFailureReason.QUALITY_GATE_FAILED


def test_skill_runner_accepts_direct_skill_output_from_custom_executor() -> None:
    class DirectExecutor:
        def execute(self, package, input_data, prompt_bundle, context):
            return SkillOutput.from_dict({"result": "ok"})

    result = SkillRunner(registry=_registry(), executor=DirectExecutor()).run(
        "runnable-skill", {"text": "hello"}, SkillRunContext.for_standalone("runnable-skill", "test-direct")
    )

    assert result.is_success()
