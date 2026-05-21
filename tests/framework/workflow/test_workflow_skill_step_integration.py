from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.specs import EdgeSpec, StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from framework.workflow.compiler import WorkflowCompiler
from framework.workflow.runtime.artifacts import ArtifactManager
from framework.workflow.runtime.executor import WorkflowExecutor
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners import FunctionStepRegistry, build_default_step_runner_registry
from framework.workflow.runners.skill_step_runner import SkillStepRunner


@dataclass
class FakeSkillError:
    code: str
    message: str


@dataclass
class FakeSkillResult:
    status: str
    output: dict[str, Any]
    skill_name: str = "entity-extraction"
    version: str = "1.0"
    errors: list[FakeSkillError] = field(default_factory=list)
    warnings: list[Any] = field(default_factory=list)


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


def test_minimal_workflow_can_contain_skill_step() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf-skill",
        name="Skill Workflow",
        version="1.0",
        steps=[
            {
                "id": "extract_entities",
                "type": "skill",
                "skill": "entity-extraction",
                "input": {},
                "output_key": "extracted_entities",
            }
        ],
        terminal_step_ids=["extract_entities"],
    )

    step = workflow.step_by_id("extract_entities")

    assert step.step_type == StepType.SKILL
    assert step.implementation == "entity-extraction"
    assert step.metadata["skill"] == "entity-extraction"
    assert step.write_keys == [
        "extract_entities.output",
        "extract_entities.result",
        "extracted_entities",
    ]


def test_workflow_skill_step_passes_upstream_output_to_skill(tmp_path: Path) -> None:
    skill_runner = FakeSkillRunner(
        FakeSkillResult(status="success", output={"entities": ["OpenAI"]})
    )
    registry = _registry(skill_runner)
    workflow = _workflow()

    result = WorkflowExecutor(
        function_step_runner=None,
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=registry,
    ).execute(workflow, {}, profile="test", run_id="run-skill-upstream")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert skill_runner.calls[0]["input_data"] == {"item": {"title": "OpenAI news"}}


def test_skill_output_can_be_read_by_downstream_step(tmp_path: Path) -> None:
    skill_runner = FakeSkillRunner(
        FakeSkillResult(status="success", output={"entities": ["OpenAI"]})
    )
    registry = _registry(skill_runner)

    result = WorkflowExecutor(
        function_step_runner=None,
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=registry,
    ).execute(_workflow(), {}, profile="test", run_id="run-skill-downstream")

    assert result.output["extracted_entities"] == {"entities": ["OpenAI"]}
    assert result.output["summary"] == "OpenAI"


def test_default_registry_can_register_skill_step_runner() -> None:
    skill_runner = FakeSkillRunner(
        FakeSkillResult(status="success", output={"entities": ["OpenAI"]})
    )
    registry = build_default_step_runner_registry(skill_runner=skill_runner)

    assert registry.has_step_type(StepType.SKILL)
    assert isinstance(registry.get(StepType.SKILL), SkillStepRunner)


def test_compiler_and_validator_accept_skill_step() -> None:
    skill_runner = FakeSkillRunner(
        FakeSkillResult(status="success", output={"entities": ["OpenAI"]})
    )
    registry = _registry(skill_runner)
    workflow = _workflow()

    validation = workflow.validation_result(strict=True, request_keys=["request"])
    compiled = WorkflowCompiler(runner_registry=registry).compile(workflow)

    assert validation.passed
    assert compiled.passed
    assert StepType.SKILL in compiled.required_step_types


def test_validator_rejects_skill_step_missing_skill() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf-bad-skill",
        name="Bad Skill Workflow",
        version="1.0",
        steps=[
            StepSpec(step_id="extract_entities", step_type=StepType.SKILL),
        ],
        terminal_step_ids=["extract_entities"],
    )

    validation = workflow.validation_result(strict=True, request_keys=["request"])

    assert not validation.passed
    assert validation.errors[0].code == "skill_step_missing_skill"


def test_validator_rejects_invalid_skill_timeout_without_policy_coercion() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf-bad-skill-timeout",
        name="Bad Skill Workflow",
        version="1.0",
        steps=[
            {
                "id": "extract_entities",
                "type": "skill",
                "skill": "entity-extraction",
                "timeout_seconds": 0,
            },
        ],
        terminal_step_ids=["extract_entities"],
    )

    validation = workflow.validation_result(strict=True, request_keys=["request"])

    assert not validation.passed
    assert validation.errors[0].code == "skill_step_timeout_invalid"


def _workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="wf-skill-integration",
        name="Skill Workflow",
        version="1.0",
        steps=[
            StepSpec(
                step_id="collect",
                implementation="collect",
                step_type=StepType.FUNCTION,
                write_keys=["collected_item"],
            ),
            {
                "id": "extract_entities",
                "type": "skill",
                "skill": "entity-extraction",
                "input": {"item": "{{ collected_item }}"},
                "output_key": "extracted_entities",
            },
            StepSpec(
                step_id="summarize",
                implementation="summarize",
                step_type=StepType.FUNCTION,
                read_keys=["extracted_entities"],
                write_keys=["summary"],
            ),
        ],
        edges=[
            EdgeSpec(source_step_id="collect", target_step_id="extract_entities"),
            EdgeSpec(source_step_id="extract_entities", target_step_id="summarize"),
        ],
        terminal_step_ids=["summarize"],
    )


def _registry(skill_runner: FakeSkillRunner):
    functions = FunctionStepRegistry()
    functions.register("collect", lambda _: {"collected_item": {"title": "OpenAI news"}})

    def summarize(buffer: Any) -> dict[str, Any]:
        entities = buffer.read("extracted_entities")
        return {"summary": entities["entities"][0]}

    functions.register("summarize", summarize)
    return build_default_step_runner_registry(
        function_registry=functions,
        skill_runner=skill_runner,
    )
