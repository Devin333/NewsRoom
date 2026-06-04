from __future__ import annotations

import ast
from pathlib import Path


def test_harness_port_contracts_do_not_import_concrete_infrastructure() -> None:
    roots = [
        Path("framework/harness/artifacts"),
        Path("framework/harness/context"),
        Path("framework/harness/mcp"),
        Path("framework/harness/memory"),
        Path("framework/harness/rag"),
        Path("framework/harness/retrieval"),
        Path("framework/harness/skills"),
        Path("framework/harness/workers"),
    ]
    forbidden_prefixes = ("business", "interfaces", "infrastructure")
    violations: list[str] = []

    for root in roots:
        for path in sorted(root.rglob("*.py")):
            for imported in _imports_for_file(path):
                if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes):
                    violations.append(f"{path.as_posix()}: {imported}")

    assert violations == []


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
