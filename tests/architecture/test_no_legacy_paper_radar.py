from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOTS = ("business", "framework", "interfaces", "infrastructure", "scripts")


def test_legacy_paper_radar_package_is_removed() -> None:
    assert not (PROJECT_ROOT / "business" / "boards" / "paper_radar").exists()


def test_production_code_does_not_import_legacy_paper_radar() -> None:
    violations = _forbidden_imports(("business.boards.paper_radar",))

    assert violations == []


def _forbidden_imports(prefixes: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for root_name in PRODUCTION_ROOTS:
        root = PROJECT_ROOT / root_name
        for path in root.rglob("*.py"):
            for imported in _imports_for_file(path):
                if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in prefixes):
                    violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")
    return violations


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
