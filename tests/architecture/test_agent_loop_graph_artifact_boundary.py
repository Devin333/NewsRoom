from __future__ import annotations

import ast
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_AGENT_ROOT = _PROJECT_ROOT / "framework/agent"
_INTEGRATION_ROOT = _PROJECT_ROOT / "framework/harness/agent_loop"
_LIVE_ROOTS = (
    _PROJECT_ROOT / "business",
    _PROJECT_ROOT / "interfaces",
    _PROJECT_ROOT / "infrastructure",
)
_ADAPTER_NAMES = {
    "AgentLoopGraphActivityBindingBundle",
    "AgentLoopGraphActivityContract",
    "AgentLoopGraphActivityOutput",
    "AgentLoopGraphActivityTask",
    "AgentLoopGraphApprovalRequest",
    "AgentLoopGraphWorker",
    "AgentLoopGraphArtifactContext",
    "AgentLoopGraphArtifactReceipt",
    "AgentLoopGraphArtifactRecorder",
    "AgentLoopGraphWaitCandidate",
    "build_agent_loop_graph_activity_binding_bundle",
}


def test_agent_core_does_not_depend_on_harness_graph_integration() -> None:
    violations: list[str] = []
    for path in _AGENT_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for module in _imported_modules(node):
                if module == "framework.harness" or module.startswith(
                    "framework.harness."
                ):
                    violations.append(
                        f"{path.relative_to(_PROJECT_ROOT)}:{node.lineno}:{module}"
                    )

    assert violations == []


def test_graph_artifact_adapter_has_no_legacy_or_publication_authority() -> None:
    forbidden_calls = {
        "commit_terminal_manifest",
        "publish",
        "publish_artifact",
        "write_terminal_manifest",
    }
    for path in _INTEGRATION_ROOT.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }

        assert "framework.workflow" not in source
        assert "framework.harness.workflow" not in source
        assert calls.isdisjoint(forbidden_calls)


def test_production_layers_do_not_activate_gate_a_agent_loop_artifact_adapter() -> None:
    violations: list[str] = []
    for root in _LIVE_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if any(
                (
                    isinstance(node, ast.Name)
                    and node.id in _ADAPTER_NAMES
                )
                or (
                    isinstance(node, ast.Attribute)
                    and node.attr in _ADAPTER_NAMES
                )
                for node in ast.walk(tree)
            ):
                violations.append(str(path.relative_to(_PROJECT_ROOT)))

    assert violations == []


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
