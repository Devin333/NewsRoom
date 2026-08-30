from __future__ import annotations

import ast

from tests.architecture._helpers import PROJECT_ROOT, imported_modules, matches_prefix


TOOL_ADAPTER = (
    PROJECT_ROOT / "framework" / "harness" / "runtime" / "tool_result_adapter.py"
)
TOOL_EXECUTOR = PROJECT_ROOT / "framework" / "tool" / "runtime" / "executor.py"
MCP_OUTBOUND = PROJECT_ROOT / "framework" / "tool" / "runtime" / "mcp_adapter.py"
MCP_INBOUND_ROOT = PROJECT_ROOT / "interfaces" / "mcp"


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


def test_harness_tool_adapter_uses_common_materializer_and_graph_runtime() -> None:
    source = TOOL_ADAPTER.read_text(encoding="utf-8")
    calls = _call_names(TOOL_ADAPTER)

    assert "ResultMaterializer" in source
    assert "HarnessGraphResultRuntime" in source
    assert "NodeResultRequest" in source
    assert "materialize" in calls
    assert "accept_materialized_result" in calls
    assert "ArtifactManager" not in source
    assert "write_json" not in calls
    assert "write_text" not in calls


def test_tool_owner_does_not_import_harness_and_adapter_does_not_import_outer_layers() -> None:
    assert all(
        not matches_prefix(module, ("framework.harness",))
        for module in imported_modules(TOOL_EXECUTOR)
    )
    assert all(
        not matches_prefix(
            module,
            ("backend", "interfaces", "infrastructure", "storage"),
        )
        for module in imported_modules(TOOL_ADAPTER)
    )


def test_mcp_inbound_and_outbound_do_not_cross_import() -> None:
    assert all(
        not matches_prefix(module, ("interfaces.mcp",))
        for module in imported_modules(MCP_OUTBOUND)
    )
    assert all(
        not matches_prefix(module, ("framework.tool.runtime.mcp_adapter",))
        for path in MCP_INBOUND_ROOT.rglob("*.py")
        for module in imported_modules(path)
    )


def test_legacy_workflow_spill_is_not_imported_by_harness_tool_composition() -> None:
    imports = imported_modules(TOOL_ADAPTER)

    assert all(
        not matches_prefix(module, ("framework.workflow.runners",))
        for module in imports
    )
