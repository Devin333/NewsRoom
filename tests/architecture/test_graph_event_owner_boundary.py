from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GRAPH_PHASE_CONTRACT = PROJECT_ROOT / "framework" / "events" / "graph_phase.py"
ACTIVE_PHASE_WRITERS = (
    PROJECT_ROOT / "framework" / "harness" / "control_plane" / "harness.py",
    PROJECT_ROOT / "framework" / "harness" / "control_plane" / "durable_events.py",
)


def test_event_projection_mechanics_are_owned_by_framework_events() -> None:
    owner = PROJECT_ROOT / "framework" / "events" / "projection.py"
    owner_tree = ast.parse(owner.read_text(encoding="utf-8"), filename=str(owner))

    owner_classes = {
        node.name for node in ast.walk(owner_tree) if isinstance(node, ast.ClassDef)
    }
    assert "EventProjectionExporter" in owner_classes
    assert "GraphRunIdentity" not in owner_classes
    imported_modules = {
        module
        for node in ast.walk(owner_tree)
        for module in _imported_modules(node)
    }
    assert "framework.shared.graph_identity" in imported_modules
    assert not (PROJECT_ROOT / "framework/workflow/runtime/event_projection.py").exists()


def test_graph_phase_transition_contract_is_event_owned_and_active() -> None:
    source = GRAPH_PHASE_CONTRACT.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(GRAPH_PHASE_CONTRACT))

    assert "class GraphPhaseTransitionRecord" in source
    assert "class GraphRunIdentity" not in source
    assert "GraphEventContext" in source
    assert "GRAPH_PHASE_TRANSITION_SCHEMA" in source
    assert [
        module
        for node in ast.walk(tree)
        for module in _imported_modules(node)
        if module == "framework.workflow"
        or module.startswith("framework.workflow.")
        or module == "framework.harness"
        or module.startswith("framework.harness.")
    ] == []
    for writer in ACTIVE_PHASE_WRITERS:
        writer_source = writer.read_text(encoding="utf-8")
        assert "GraphPhaseTransitionRecord" in writer_source


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
