from __future__ import annotations

import pytest

from core.framework.specs import StepStatus, StepType
from core.framework.workflow import (
    DataBuffer,
    FunctionStepRunner,
    StepRunnerRegistry,
    StepRunnerRegistryError,
)

from helpers import make_function_registry, make_step


def test_step_runner_contract_validates_function_outputs() -> None:
    runner = FunctionStepRunner(make_function_registry({"test.empty": lambda buffer: {}}))

    outcome = runner.run(
        make_step(
            "empty",
            "test.empty",
            write_keys=["report"],
            required_output_keys=["report"],
        ),
        DataBuffer().scope(read_keys=[], write_keys=["report"]),
    )

    assert outcome.status == StepStatus.FAILED
    assert outcome.error_type == "StepExecutionError"
    assert "required output keys" in str(outcome.error_message)


def test_step_runner_contract_registry_reports_missing_runner() -> None:
    registry = StepRunnerRegistry()

    with pytest.raises(StepRunnerRegistryError, match="not registered: artifact"):
        registry.get(StepType.ARTIFACT)


def test_step_runner_contract_exposes_capability_metadata() -> None:
    runner = FunctionStepRunner(make_function_registry())
    registry = StepRunnerRegistry.with_function_runner(runner)

    descriptor = registry.describe()[0]

    assert descriptor.runner_id == "builtin.function"
    assert descriptor.step_type == StepType.FUNCTION
    assert descriptor.supports_checkpoint is True
    assert descriptor.supports_resume is True
    assert descriptor.supports_timeout is True
    assert descriptor.supports_retry is True
