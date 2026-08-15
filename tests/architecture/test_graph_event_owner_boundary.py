from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENT_MIGRATION_SERVICE = (
    PROJECT_ROOT / "interfaces" / "services" / "event_migration_service.py"
)


def test_event_migration_service_does_not_import_workflow_projection() -> None:
    tree = ast.parse(
        EVENT_MIGRATION_SERVICE.read_text(encoding="utf-8"),
        filename=str(EVENT_MIGRATION_SERVICE),
    )

    assert [
        f"{node.lineno}:{module}"
        for node in ast.walk(tree)
        for module in _imported_modules(node)
        if module == "framework.workflow"
        or module.startswith("framework.workflow.")
    ] == []


def test_event_projection_mechanics_are_owned_by_framework_events() -> None:
    owner = PROJECT_ROOT / "framework" / "events" / "projection.py"
    legacy = (
        PROJECT_ROOT / "framework" / "workflow" / "runtime" / "event_projection.py"
    )
    owner_tree = ast.parse(owner.read_text(encoding="utf-8"), filename=str(owner))
    legacy_tree = ast.parse(
        legacy.read_text(encoding="utf-8"),
        filename=str(legacy),
    )

    owner_classes = {
        node.name for node in ast.walk(owner_tree) if isinstance(node, ast.ClassDef)
    }
    legacy_bases = {
        base.id
        for node in ast.walk(legacy_tree)
        if isinstance(node, ast.ClassDef)
        and node.name == "WorkflowEventProjectionExporter"
        for base in node.bases
        if isinstance(base, ast.Name)
    }

    assert "EventProjectionExporter" in owner_classes
    assert legacy_bases == {"EventProjectionExporter"}


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
