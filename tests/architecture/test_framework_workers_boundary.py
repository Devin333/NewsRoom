from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKERS_ROOT = PROJECT_ROOT / "framework" / "workers"
FORBIDDEN_IMPORT_PREFIXES = (
    "business",
    "interfaces",
    "infrastructure",
    "storage",
    "workflows",
    "domain",
    "sources",
    "evidence",
    "quality",
    "redis",
    "postgres",
)
BUSINESS_HANDLER_TOKENS = (
    "DailyIntelligenceTaskHandler",
    "MemoryReindexTaskHandler",
    "SourceHealthCheckTaskHandler",
)


def test_framework_workers_do_not_import_forbidden_layers() -> None:
    violations: list[str] = []
    for path in WORKERS_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imported_modules(tree):
            if _is_forbidden_import(imported):
                relative_path = path.relative_to(PROJECT_ROOT).as_posix()
                violations.append(f"{relative_path}: {imported}")

    assert violations == []


def test_framework_workers_do_not_define_business_handlers() -> None:
    violations: list[str] = []
    for path in WORKERS_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in BUSINESS_HANDLER_TOKENS:
            if token in text:
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {token}")

    assert violations == []


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _is_forbidden_import(module: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )
