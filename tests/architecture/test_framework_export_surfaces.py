from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_framework_root_exports_only_cross_cutting_surface() -> None:
    import framework

    assert set(framework.__all__) == {"env", "shared"}
    assert not hasattr(framework, "WorkflowRunner")
    assert not hasattr(framework, "RunResult")


def test_graph_and_artifact_owners_are_explicit_public_surfaces() -> None:
    import framework.harness as harness
    import framework.harness.graph as graph

    assert "HarnessGraphDefinition" in graph.__all__
    assert hasattr(graph, "HarnessGraphDefinition")
    assert hasattr(harness, "ArtifactPort")


def test_retired_framework_namespaces_are_not_importable() -> None:
    for relative in ("framework/workflow", "framework/specs", "framework/harness/workflow"):
        assert not any((PROJECT_ROOT / relative).rglob("*.py"))
