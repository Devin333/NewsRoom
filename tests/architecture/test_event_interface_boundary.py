from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_run_event_interfaces_do_not_import_concrete_event_storage() -> None:
    interface_paths = (
        ROOT / "interfaces" / "services" / "run_inspection_service.py",
        ROOT / "interfaces" / "api" / "routers" / "runs.py",
        ROOT / "interfaces" / "cli" / "commands" / "runs.py",
        ROOT / "interfaces" / "services" / "mcp_service.py",
    )

    violations = {
        str(path.relative_to(ROOT)): sorted(_concrete_event_imports(path))
        for path in interface_paths
        if _concrete_event_imports(path)
    }

    assert violations == {}


def test_event_storage_selection_is_isolated_to_inspection_composition_module() -> None:
    path = ROOT / "interfaces" / "services" / "run_inspection_factory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top_level_concrete_imports = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("infrastructure.storage.events")
    }
    composition_imports = {
        node.module
        for function in tree.body
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(function)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("infrastructure.storage.events")
    }

    assert top_level_concrete_imports == set()
    assert composition_imports == {"infrastructure.storage.events.factory"}


def _concrete_event_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("infrastructure.storage.events"):
                imports.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("infrastructure.storage.events"):
                    imports.add(alias.name)
    return imports
