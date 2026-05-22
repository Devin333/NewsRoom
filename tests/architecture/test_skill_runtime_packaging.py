from __future__ import annotations

import ast
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ("framework", "business", "infrastructure", "interfaces", "scripts")
LEGACY_SKILL_MODULES = {
    "framework.skills.runner",
    "framework.skills.executor",
    "framework.skills.prompt",
    "framework.skills.schema",
    "framework.skills.registry",
    "framework.skills.scanner",
    "framework.skills.validator",
    "framework.skills.evaluator",
    "framework.skills.trace",
    "framework.skills.context",
    "framework.skills.errors",
    "framework.skills.io",
    "framework.skills.metadata",
    "framework.skills.manifest",
    "framework.skills.result",
}


def test_pyproject_declares_skill_subpackages() -> None:
    content = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pyproject = tomllib.loads(content)

    required_packages = {
        "framework.skills.core",
        "framework.skills.package",
        "framework.skills.runtime",
        "framework.skills.validation",
        "framework.skills.quality",
        "framework.skills.evaluation",
        "framework.skills.tracing",
    }

    package_find = (
        pyproject.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find")
    )
    if package_find is not None:
        assert "framework*" in package_find.get("include", [])
        assert "tests*" in package_find.get("exclude", [])
        return

    for package_name in required_packages:
        assert f'"{package_name}"' in content


def test_internal_code_does_not_import_legacy_skill_flat_modules() -> None:
    violations: list[str] = []
    for root_name in SOURCE_ROOTS:
        for path in (PROJECT_ROOT / root_name).rglob("*.py"):
            for imported in _imports_for_file(path):
                if imported in LEGACY_SKILL_MODULES:
                    violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def test_workflow_skill_runner_does_not_import_skill_runtime_implementation() -> None:
    skill_runner_files = [
        PROJECT_ROOT / "framework" / "workflow" / "runners" / "skill" / "runner.py",
        PROJECT_ROOT / "framework" / "workflow" / "runners" / "skill_step_runner.py",
    ]
    forbidden = {
        "framework.skills.runtime.runner",
        "framework.skills.runtime.executor",
        "framework.skills.runtime.prompt",
        "framework.skills.package.loader",
        "framework.skills.package.registry",
        "framework.skills.package.scanner",
        "framework.skills.package.validator",
    }

    violations: list[str] = []
    for path in skill_runner_files:
        for imported in _imports_for_file(path):
            if imported in forbidden:
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def test_agent_skill_call_model_does_not_import_skill_runtime() -> None:
    path = PROJECT_ROOT / "framework" / "agent" / "skill_call.py"

    assert all(not imported.startswith("framework.skills") for imported in _imports_for_file(path))


def test_business_foundation_skills_contains_only_skill_package_assets() -> None:
    root = PROJECT_ROOT / "business" / "foundation" / "skills"

    python_files = [path.relative_to(root).as_posix() for path in root.rglob("*.py")]

    assert python_files == []


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
