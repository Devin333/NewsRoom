from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_EVENTS_ROOT = PROJECT_ROOT / "storage" / "events"


def test_storage_events_is_compatibility_only() -> None:
    violations: list[str] = []
    for path in STORAGE_EVENTS_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if _is_docstring(node):
                continue
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("infrastructure.storage.events")
            ):
                continue
            violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {type(node).__name__}")

    assert violations == []


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )
