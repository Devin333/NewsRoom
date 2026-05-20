from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_ROOT = PROJECT_ROOT / "framework" / "governance"
CORE_GOVERNANCE_ROOT = PROJECT_ROOT / "core" / "framework" / "governance"
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
)


def test_framework_governance_does_not_import_forbidden_layers() -> None:
    violations: list[str] = []
    for path in GOVERNANCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imported_modules(tree):
            if _is_forbidden_import(imported):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def test_non_compat_source_code_does_not_import_core_framework_governance() -> None:
    violations: list[str] = []
    for scan_root in _source_roots():
        for path in scan_root.rglob("*.py"):
            if _is_under(path, CORE_GOVERNANCE_ROOT):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for imported in _imported_modules(tree):
                if imported == "core.framework.governance" or imported.startswith("core.framework.governance."):
                    violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def _source_roots() -> list[Path]:
    names = ["framework", "core", "business", "interfaces", "infrastructure", "storage", "workflows"]
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
