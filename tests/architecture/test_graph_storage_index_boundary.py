from __future__ import annotations

import ast
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OWNER_ROOT = _PROJECT_ROOT / "infrastructure/storage/indexing"
_PRODUCTION_ROOTS = (
    _PROJECT_ROOT / "backend",
    _PROJECT_ROOT / "framework",
    _PROJECT_ROOT / "interfaces",
    _PROJECT_ROOT / "infrastructure",
)
_FORBIDDEN_IMPORT_ROOTS = (
    "backend",
    "framework.workflow",
    "interfaces",
)
_INACTIVE_TYPES = {
    "InactiveGraphStorageIndexAdapter",
    "LocalGraphIndexCandidateStore",
}


def test_graph_index_owner_does_not_depend_on_orchestration_or_interfaces() -> None:
    violations: list[str] = []
    for path in _OWNER_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for module in _imported_modules(node):
                if any(
                    module == root or module.startswith(f"{root}.")
                    for root in _FORBIDDEN_IMPORT_ROOTS
                ):
                    violations.append(f"{path.name}:{node.lineno}:{module}")

    assert violations == []


def test_inactive_graph_index_adapter_has_no_live_writer_or_pointer_api() -> None:
    path = _OWNER_ROOT / "inactive.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    adapter = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "InactiveGraphStorageIndexAdapter"
    )
    methods = {
        node.name
        for node in adapter.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert methods == {
        "__init__",
        "dry_run",
        "stage_qualified_candidate",
        "read_back",
        "_validate_events",
        "_validate_bindings",
    }
    assert methods.isdisjoint(
        {
            "append_event",
            "index_artifact",
            "switch_pointer",
            "activate",
            "publish",
        }
    )


def test_gate_a_graph_index_types_are_not_activated_by_production_modules() -> None:
    violations: list[str] = []
    for root in _PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            if path.is_relative_to(_OWNER_ROOT):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            used_names = {
                node.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Name)
            } | {
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
            }
            activated = sorted(used_names.intersection(_INACTIVE_TYPES))
            if activated:
                relative = path.relative_to(_PROJECT_ROOT).as_posix()
                violations.append(f"{relative}: {', '.join(activated)}")

    assert violations == []


def test_existing_artifact_and_event_factories_do_not_select_graph_index() -> None:
    factory_paths = (
        _PROJECT_ROOT / "infrastructure/storage/artifacts/factory.py",
        _PROJECT_ROOT / "infrastructure/storage/events/factory.py",
    )
    violations = {
        path.relative_to(_PROJECT_ROOT).as_posix(): [
            module
            for node in ast.walk(
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            )
            for module in _imported_modules(node)
            if module.startswith("infrastructure.storage.indexing")
        ]
        for path in factory_paths
    }

    assert violations == {
        "infrastructure/storage/artifacts/factory.py": [],
        "infrastructure/storage/events/factory.py": [],
    }


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
