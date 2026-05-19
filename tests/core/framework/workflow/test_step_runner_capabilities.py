from core.framework.workflow import (
    FunctionStepRegistry,
    StepRunnerSideEffectLevel,
    build_default_step_runner_registry,
)


def test_all_builtin_runners_declare_capabilities() -> None:
    registry = build_default_step_runner_registry(
        FunctionStepRegistry(),
        tool_registry=object(),
        agent_runner=object(),
        agent_registry={"analyst": object()},
        workflow_registry={"child": object()},
        artifact_manager=object(),
        memory_runtime=object(),
        approval_store=object(),
    )

    descriptors = registry.describe()
    runner_ids = {item.runner_id for item in descriptors}

    assert "builtin.function" in runner_ids
    assert "builtin.parallel_group" in runner_ids
    assert "builtin.tool" in runner_ids
    assert "builtin.tool_batch" in runner_ids
    assert "builtin.memory_recall" in runner_ids
    assert "builtin.memory_write" in runner_ids
    assert "builtin.agent_loop" in runner_ids
    assert "builtin.router" in runner_ids
    assert "builtin.join" in runner_ids
    assert "builtin.quality_gate" in runner_ids
    assert "builtin.human_review" in runner_ids
    assert "builtin.artifact" in runner_ids
    assert "builtin.subworkflow" in runner_ids


def test_builtin_capability_fields_are_well_formed() -> None:
    registry = build_default_step_runner_registry(
        FunctionStepRegistry(),
        tool_registry=object(),
        agent_runner=object(),
        agent_registry={"analyst": object()},
        workflow_registry={"child": object()},
        artifact_manager=object(),
        memory_runtime=object(),
        approval_store=object(),
    )

    for descriptor in registry.describe():
        assert descriptor.runner_id
        assert descriptor.version
        assert descriptor.step_type
        assert isinstance(descriptor.required_dependencies, list)
        assert descriptor.side_effect_level in {item.value for item in StepRunnerSideEffectLevel}


def test_default_registry_describe_reports_availability() -> None:
    registry = build_default_step_runner_registry(FunctionStepRegistry())

    descriptors = registry.describe()
    function = next(item for item in descriptors if item.runner_id == "builtin.function")
    tool = next(item for item in descriptors if item.runner_id == "builtin.tool")
    memory_recall = next(item for item in descriptors if item.runner_id == "builtin.memory_recall")

    assert function.available is True
    assert function.missing_dependencies == []
    assert tool.available is False
    assert tool.missing_dependencies == ["tool_registry"]
    assert memory_recall.available is False
    assert memory_recall.missing_dependencies == ["memory_runtime"]
