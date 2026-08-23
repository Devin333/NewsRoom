from __future__ import annotations

import ast
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ("framework", "business", "infrastructure", "interfaces", "scripts")

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


def test_flat_skill_compatibility_modules_are_removed() -> None:
    removed_modules = {
        "runner.py",
        "executor.py",
        "prompt.py",
        "schema.py",
        "registry.py",
        "scanner.py",
        "validator.py",
        "evaluator.py",
        "trace.py",
        "context.py",
        "errors.py",
        "io.py",
        "metadata.py",
        "manifest.py",
        "result.py",
    }
    existing = {
        path.name
        for path in (PROJECT_ROOT / "framework" / "skills").glob("*.py")
        if path.name in removed_modules
    }

    assert existing == set()


def test_internal_code_does_not_import_removed_skill_flat_modules() -> None:
    removed_imports = {
        f"framework.skills.{path.stem}"
        for path in (PROJECT_ROOT / "framework" / "skills").glob("*.py")
        if path.name != "__init__.py"
    }
    violations: list[str] = []
    for root_name in SOURCE_ROOTS:
        for path in (PROJECT_ROOT / root_name).rglob("*.py"):
            for imported in _imports_for_file(path):
                if imported in removed_imports:
                    violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def test_workflow_skill_runner_does_not_import_skill_runtime_implementation() -> None:
    skill_runner_files = list((PROJECT_ROOT / "framework" / "harness").rglob("*.py"))
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


def test_business_foundation_skills_contains_only_skill_package_assets_and_business_wrappers() -> None:
    root = PROJECT_ROOT / "business" / "foundation" / "skills"

    python_files = sorted(path.relative_to(root).as_posix() for path in root.rglob("*.py"))

    assert python_files == ["__init__.py", "fallbacks.py", "runtime.py"]


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
