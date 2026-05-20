import pytest

from framework.specs import StepSpec, WorkflowSpec, WorkflowSpecError, WorkflowSpecRegistry


def test_registry_prd_methods_and_version_compatibility() -> None:
    registry = WorkflowSpecRegistry()
    first = WorkflowSpec(
        workflow_id="daily",
        name="Daily",
        version="1.0",
        steps=[StepSpec("start", "daily.start")],
    )
    second = WorkflowSpec(
        workflow_id="daily",
        name="Daily",
        version="2.0",
        steps=[StepSpec("start", "daily.start")],
    )

    registry.register(first)
    registry.register(second)

    assert registry.get("daily") is second
    assert registry.require("daily", "1.0") is first
    assert registry.list() == [first, second]

    registry.remove("daily", "2.0")
    assert registry.get("daily") is first

    registry.clear()
    with pytest.raises(WorkflowSpecError):
        registry.require("daily")
