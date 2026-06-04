from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT, forbidden_imports


def test_framework_harness_does_not_import_outer_layers() -> None:
    violations = forbidden_imports(
        PROJECT_ROOT / "framework" / "harness",
        (
            "business",
            "interfaces",
            "infrastructure",
            "frontend",
            "apps",
            "framework.agent.harness",
        ),
    )

    assert violations == []


def test_legacy_agent_harness_package_is_removed_from_public_framework() -> None:
    assert not (PROJECT_ROOT / "framework" / "agent" / "harness").exists()

    import framework.agent as agent

    assert "AgentHarness" not in agent.__all__
    assert "AgentHarnessScenario" not in agent.__all__
