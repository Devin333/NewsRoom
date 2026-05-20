from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def forbidden_imports(root: Path, prefixes: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for path in root.rglob("*.py"):
        for imported in imported_modules(path):
            if matches_prefix(imported, prefixes):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")
    return violations


def token_violations(root: Path, tokens: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in tokens:
            if token in text:
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {token}")
    return violations


def matches_prefix(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )
