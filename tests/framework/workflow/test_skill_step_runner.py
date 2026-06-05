from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.runners.skill import SkillStepRunner, resolve_skill_input
from framework.specs.skill_step import SkillStepSpec


@dataclass
class FakeSkillError:
    code: str
    message: str


@dataclass
class FakeSkillWarning:
    code: str
    message: str


@dataclass
class FakeSkillResult:
    status: str
    output: dict[str, Any]
    skill_name: str = "entity-extraction"
    version: str = "1.0"
    errors: list[FakeSkillError] = field(default_factory=list)
    warnings: list[FakeSkillWarning] = field(default_factory=list)


class FakeSkillRunner:
    def __init__(self, result: FakeSkillResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def run(self, skill_name: str, input_data: dict[str, Any], context=None) -> FakeSkillResult:
        self.calls.append(
            {
                "skill_name": skill_name,
                "input_data": input_data,
                "context": context,
            }
        )
        return self.result


def test_skill_step_runner_can_resolve_skill_step() -> None:
    runner = SkillStepRunner(FakeSkillRunner(_success_result()))
    step = SkillStepSpec(id="extract_entities", skill="entity-extraction")

    assert runner.can_resolve(step) is True


def test_skill_step_runner_describes_actual_capability() -> None:
    runner = SkillStepRunner(FakeSkillRunner(_success_result()))

    assert runner.capability.supports_timeout is False
    assert runner.capability.supports_retry is False
    assert runner.describe_capability() == runner.capability.to_dict()


def test_skill_step_runner_validate_step_finds_missing_skill() -> None:
    runner = SkillStepRunner(FakeSkillRunner(_success_result()))
    step = StepSpec(step_id="extract_entities", step_type=StepType.SKILL)

    issues = runner.validate_step(step)

    assert [issue.code for issue in issues] == ["skill_step_missing_skill"]


def test_skill_step_runner_run_calls_skill_runner() -> None:
    fake = FakeSkillRunner(_success_result())
    runner = SkillStepRunner(fake)
    step = SkillStepSpec(
        id="extract_entities",
        skill="entity-extraction",
        input={"item": "{{ collected_item }}"},
    )

    runner.run(step, {"collected_item": {"title": "News"}})

    assert fake.calls[0]["skill_name"] == "entity-extraction"
    assert fake.calls[0]["input_data"] == {"item": {"title": "News"}}
    assert fake.calls[0]["context"].metadata["workflow_step_id"] == "extract_entities"


def test_skill_step_runner_writes_full_result() -> None:
    result = _success_result()
    runner = SkillStepRunner(FakeSkillRunner(result))
    buffer: dict[str, Any] = {}

    runner.run(SkillStepSpec(id="extract_entities", skill="entity-extraction"), buffer)

    assert buffer["extract_entities.result"] is result


def test_skill_step_runner_writes_step_output() -> None:
    result = _success_result(output={"entities": ["OpenAI"]})
    runner = SkillStepRunner(FakeSkillRunner(result))
    buffer: dict[str, Any] = {}

    runner.run(SkillStepSpec(id="extract_entities", skill="entity-extraction"), buffer)

    assert buffer["extract_entities.output"] == {"entities": ["OpenAI"]}


def test_skill_step_runner_writes_output_key() -> None:
    result = _success_result(output={"entities": ["OpenAI"]})
    runner = SkillStepRunner(FakeSkillRunner(result))
    buffer: dict[str, Any] = {}

    runner.run(
        SkillStepSpec(
            id="extract_entities",
            skill="entity-extraction",
            output_key="extracted_entities",
        ),
        buffer,
    )

    assert buffer["extracted_entities"] == {"entities": ["OpenAI"]}


def test_skill_step_runner_failed_result_returns_failed_outcome() -> None:
    result = FakeSkillResult(
        status="failed",
        output={"entities": []},
        errors=[FakeSkillError(code="execution_failed", message="boom")],
    )
    runner = SkillStepRunner(FakeSkillRunner(result))

    outcome = runner.run(SkillStepSpec(id="extract_entities", skill="entity-extraction"), {})

    assert outcome.status == StepStatus.FAILED
    assert (
        outcome.error_message
        == "Skill step 'extract_entities' failed running skill 'entity-extraction': boom"
    )


def test_skill_step_runner_failed_result_can_warn_without_failing_workflow() -> None:
    result = FakeSkillResult(
        status="failed",
        output={"entities": []},
        errors=[FakeSkillError(code="execution_failed", message="boom")],
    )
    runner = SkillStepRunner(FakeSkillRunner(result))

    outcome = runner.run(
        SkillStepSpec(
            id="extract_entities",
            skill="entity-extraction",
            fail_workflow_on_error=False,
        ),
        {},
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.warnings == [
        "Skill step 'extract_entities' failed running skill 'entity-extraction': boom"
    ]


def test_resolve_skill_input_recursively_resolves_exact_templates() -> None:
    buffer = {
        "collected_items": [{"title": "A"}],
        "source_info": {"name": "source"},
    }

    resolved = resolve_skill_input(
        {
            "items": "{{ collected_items }}",
            "policy": {
                "mode": "strict",
                "source": "{{ source_info }}",
            },
        },
        buffer,
    )

    assert resolved == {
        "items": [{"title": "A"}],
        "policy": {
            "mode": "strict",
            "source": {"name": "source"},
        },
    }


def _success_result(output: dict[str, Any] | None = None) -> FakeSkillResult:
    return FakeSkillResult(status="success", output=output or {"entities": ["OpenAI"]})
