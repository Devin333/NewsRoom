from __future__ import annotations


def test_framework_public_api_imports() -> None:
    import framework
    import framework.agent
    import framework.artifacts
    import framework.events
    import framework.governance
    import framework.llm
    import framework.memory
    import framework.shared
    import framework.specs
    import framework.tool
    import framework.workflow
    import framework.workers

    assert framework
    assert framework.RunResult
    assert framework.WorkflowRunner
