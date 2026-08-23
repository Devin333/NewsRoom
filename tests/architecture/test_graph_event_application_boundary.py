from __future__ import annotations

import ast
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OWNER = _PROJECT_ROOT / "framework/events/application.py"
_LEGACY_PROJECTION_SERVICE = (
    _PROJECT_ROOT / "interfaces/services/event_projection_service.py"
)
_LIVE_ROOTS = (
    _PROJECT_ROOT / "business",
    _PROJECT_ROOT / "infrastructure",
    _PROJECT_ROOT / "scripts",
    _PROJECT_ROOT / "interfaces/api",
    _PROJECT_ROOT / "interfaces/cli",
    _PROJECT_ROOT / "interfaces/composition",
    _PROJECT_ROOT / "interfaces/mcp",
)
_ACTIVE_NAMES = frozenset(
    {
        "DurableGraphEventProjectionAdapter",
    }
)


def test_graph_event_application_owner_has_no_legacy_or_outer_layer_imports() -> None:
    tree = ast.parse(_OWNER.read_text(encoding="utf-8"), filename=str(_OWNER))

    assert [
        f"{node.lineno}:{module}"
        for node in ast.walk(tree)
        for module in _imported_modules(node)
        if module == "framework.workflow"
        or module.startswith("framework.workflow.")
        or module == "interfaces"
        or module.startswith("interfaces.")
        or module == "infrastructure"
        or module.startswith("infrastructure.")
    ] == []


def test_projection_service_uses_graph_application_port() -> None:
    tree = ast.parse(
        _LEGACY_PROJECTION_SERVICE.read_text(encoding="utf-8"),
        filename=str(_LEGACY_PROJECTION_SERVICE),
    )
    imports = {
        module
        for node in ast.walk(tree)
        for module in _imported_modules(node)
    }

    assert "framework.events.application" in imports
    assert "framework.workflow.runtime.event_projection" not in imports


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
