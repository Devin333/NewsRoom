from __future__ import annotations

import ast

from tests.architecture._helpers import (
    PROJECT_ROOT,
    imported_modules,
    matches_prefix,
)


SUBAGENT_ADAPTER = (
    PROJECT_ROOT
    / "framework"
    / "harness"
    / "runtime"
    / "subagent_result_adapter.py"
)
SUBAGENT_RUNTIME = (
    PROJECT_ROOT / "framework" / "harness" / "subagents" / "runtime.py"
)


def _call_names(path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def test_subagent_adapter_uses_common_materializer_and_graph_runtime() -> None:
    source = SUBAGENT_ADAPTER.read_text(encoding="utf-8")
    calls = _call_names(SUBAGENT_ADAPTER)

    assert "ResultMaterializer" in source
    assert "HarnessGraphResultRuntime" in source
    assert "SubAgentTranscriptStorePort" in source
    assert "NodeResultRequest" in source
    assert "materialize" in calls
    assert "accept_materialized_result" in calls
    assert "ArtifactManager" not in source
    assert "write_json" not in calls
    assert "write_text" not in calls


def test_subagent_owner_does_not_import_result_runtime() -> None:
    assert all(
        not matches_prefix(module, ("framework.harness.runtime",))
        for module in imported_modules(SUBAGENT_RUNTIME)
    )


def test_subagent_adapter_does_not_import_outer_layers_or_legacy_runner() -> None:
    assert all(
        not matches_prefix(
            module,
            (
                "business",
                "interfaces",
                "infrastructure",
                "storage",
                "framework.workflow.runners",
            ),
        )
        for module in imported_modules(SUBAGENT_ADAPTER)
    )
