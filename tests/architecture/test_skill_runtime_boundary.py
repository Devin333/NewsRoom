from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_ROOT = PROJECT_ROOT / "framework"
SKILLS_ROOT = FRAMEWORK_ROOT / "skills"

FORBIDDEN_SKILL_IMPORT_PREFIXES = ("backend", "infrastructure", "interfaces")
ALLOWED_SKILL_RUNTIME_BRIDGES = {
    "framework/agent/skill_context.py",
    "framework/workflow/runners/skill/context.py",
}


def test_framework_skills_does_not_import_outer_layers() -> None:
    violations: list[str] = []
    for path in SKILLS_ROOT.rglob("*.py"):
        for imported in _imports_for_file(path):
            if _matches(imported, FORBIDDEN_SKILL_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def test_skill_runtime_implementation_stays_in_framework_skills() -> None:
    violations: list[str] = []
    for root in (FRAMEWORK_ROOT / "agent", FRAMEWORK_ROOT / "workflow"):
        for path in root.rglob("*.py"):
            relative_path = path.relative_to(PROJECT_ROOT).as_posix()
            if relative_path in ALLOWED_SKILL_RUNTIME_BRIDGES:
                continue
            for imported in _imports_for_file(path):
                if imported == "framework.skills" or imported.startswith("framework.skills."):
                    violations.append(f"{relative_path}: {imported}")

    assert violations == []


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _matches(imported: str, prefixes: tuple[str, ...]) -> bool:
    return any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in prefixes)
