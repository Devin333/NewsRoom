from __future__ import annotations

import ast
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OWNER = _PROJECT_ROOT / "framework/events/application.py"
_INTERFACE_SERVICE = (
    _PROJECT_ROOT / "interfaces/services/graph_event_preparation_service.py"
)
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
_INACTIVE_NAMES = frozenset(
    {
        "InactiveGraphEventProjectionAdapter",
        "GraphEventPreparationApplicationService",
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


def test_new_interface_path_depends_only_on_event_application_contract() -> None:
    tree = ast.parse(
        _INTERFACE_SERVICE.read_text(encoding="utf-8"),
        filename=str(_INTERFACE_SERVICE),
    )
    project_imports = {
        module
        for node in ast.walk(tree)
        for module in _imported_modules(node)
        if module.startswith(("framework.", "interfaces.", "infrastructure."))
    }

    assert project_imports == {"framework.events.application"}


def test_gate_a_graph_event_adapter_is_not_activated_by_live_composition() -> None:
    violations: list[str] = []
    for root in _LIVE_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if any(
                (
                    isinstance(node, ast.Name)
                    and node.id in _INACTIVE_NAMES
                )
                or (
                    isinstance(node, ast.Attribute)
                    and node.attr in _INACTIVE_NAMES
                )
                for node in ast.walk(tree)
            ):
                violations.append(str(path.relative_to(_PROJECT_ROOT)))

    assert violations == []


def test_gate_a_does_not_switch_existing_projection_service_schema() -> None:
    tree = ast.parse(
        _LEGACY_PROJECTION_SERVICE.read_text(encoding="utf-8"),
        filename=str(_LEGACY_PROJECTION_SERVICE),
    )
    imports = {
        module
        for node in ast.walk(tree)
        for module in _imported_modules(node)
    }

    assert "framework.events.application" not in imports
    assert "interfaces.services.graph_event_preparation_service" not in imports
    assert "framework.workflow.runtime.event_projection" in imports


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
