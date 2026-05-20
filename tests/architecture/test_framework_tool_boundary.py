from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT = PROJECT_ROOT / "framework" / "tool"
CORE_TOOLS_ROOT = PROJECT_ROOT / "core" / "framework" / "tools"
FORBIDDEN_FRAMEWORK_TOOL_IMPORTS = (
    "core.framework",
    "storage",
    "business",
    "interfaces",
    "infrastructure",
    "workflows",
    "domain",
    "evidence",
    "quality",
)


def test_framework_tool_does_not_import_forbidden_layers() -> None:
    violations: list[str] = []
    for path in TOOL_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for imported in _imported_modules(tree):
            if any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_FRAMEWORK_TOOL_IMPORTS
            ):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def test_non_compat_code_does_not_import_core_framework_tools() -> None:
    violations: list[str] = []
    for scan_root in _source_roots():
        for path in scan_root.rglob("*.py"):
            if _is_under(path, CORE_TOOLS_ROOT):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for imported in _imported_modules(tree):
                if imported == "core.framework.tools" or imported.startswith("core.framework.tools."):
                    violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def _source_roots() -> list[Path]:
    names = [
        "framework",
        "core",
        "business",
        "infrastructure",
        "interfaces",
        "workflows",
        "tests",
    ]
    return [PROJECT_ROOT / name for name in names if (PROJECT_ROOT / name).exists()]


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
