from __future__ import annotations

import ast

from _helpers import PROJECT_ROOT, is_docstring


CORE_FRAMEWORK_ROOT = PROJECT_ROOT / "core" / "framework"


def test_core_framework_contains_only_compat_imports() -> None:
    violations: list[str] = []
    for path in CORE_FRAMEWORK_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if is_docstring(node):
                continue
            if isinstance(node, ast.ImportFrom) and _is_allowed_import(node):
                continue
            if isinstance(node, ast.Assign) and _is_dunder_all(node):
                continue
            violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {type(node).__name__}")

    assert violations == []


def _is_allowed_import(node: ast.ImportFrom) -> bool:
    module = node.module or ""
    return (
        module == "__future__"
        or module == "framework"
        or module.startswith("framework.")
        or module.startswith("infrastructure.")
    )


def _is_dunder_all(node: ast.Assign) -> bool:
    return any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
