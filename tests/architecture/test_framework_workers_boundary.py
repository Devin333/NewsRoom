from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKERS_ROOT = PROJECT_ROOT / "framework" / "workers"
CORE_WORKERS_ROOT = PROJECT_ROOT / "core" / "framework" / "workers"
FORBIDDEN_IMPORT_PREFIXES = (
    "core.framework",
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


def test_non_compat_source_code_does_not_import_core_framework_workers() -> None:
    violations: list[str] = []
    for scan_root in _source_roots():
        for path in scan_root.rglob("*.py"):
            if _is_under(path, CORE_WORKERS_ROOT):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for imported in _imported_modules(tree):
                if imported == "core.framework.workers" or imported.startswith("core.framework.workers."):
                    violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def test_framework_workers_do_not_define_business_handlers() -> None:
    violations: list[str] = []
    for path in WORKERS_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in BUSINESS_HANDLER_TOKENS:
            if token in text:
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {token}")

    assert violations == []


def _source_roots() -> list[Path]:
    names = ["framework", "core", "business", "infrastructure", "interfaces", "storage"]
    return [PROJECT_ROOT / name for name in names if (PROJECT_ROOT / name).exists()]


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


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
