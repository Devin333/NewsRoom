from __future__ import annotations

import ast
from pathlib import Path

import framework.harness.graph as graph_api


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_GRAPH_ROOT = _PROJECT_ROOT / "framework/harness/graph"
_WORKFLOW_ROOT = _PROJECT_ROOT / "framework/harness/workflow"
_MOVED_MODULES = (
    "canonical.py",
    "conditions.py",
    "dsl.py",
    "step.py",
)
_MOVED_IMPORTS = tuple(
    f"framework.harness.workflow.{name.removesuffix('.py')}"
    for name in _MOVED_MODULES
)
_MOVED_PUBLIC_NAMES = {
    "BoundedLoop",
    "Choice",
    "ChoiceBranch",
    "CompensationBinding",
    "ConditionAll",
    "ConditionAny",
    "ConditionOperator",
    "ConditionPredicate",
    "HarnessGraphSpec",
    "HarnessRetryPolicy",
    "HarnessStepSpec",
    "HarnessWorkerType",
    "ParallelAll",
    "ParallelAny",
    "ParallelBranch",
    "Sequence",
    "StepRef",
    "Wait",
}


def test_graph_owner_does_not_import_legacy_workflow_namespace() -> None:
    violations: list[str] = []
    for path in _GRAPH_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for module in _imported_modules(node):
                if module == "framework.harness.workflow" or module.startswith(
                    "framework.harness.workflow."
                ):
                    violations.append(f"{path.name}:{node.lineno}:{module}")

    assert violations == []


def test_moved_graph_owner_modules_have_no_workflow_path_shims() -> None:
    assert [
        name for name in _MOVED_MODULES if (_WORKFLOW_ROOT / name).exists()
    ] == []


def test_graph_versioning_is_split_from_legacy_schema_window() -> None:
    graph_versioning = (_GRAPH_ROOT / "versioning.py").read_text(
        encoding="utf-8"
    )
    legacy_versioning = (_WORKFLOW_ROOT / "versioning.py").read_text(
        encoding="utf-8"
    )

    assert "LEGACY_WORKFLOW_SCHEMA" not in graph_versioning
    assert "LEGACY_EVENT_SCHEMA" not in graph_versioning
    assert "LEGACY_WORKFLOW_SCHEMA =" in legacy_versioning
    assert "LEGACY_EVENT_SCHEMA =" in legacy_versioning


def test_production_and_tests_do_not_import_moved_workflow_modules() -> None:
    violations: list[str] = []
    for root_name in (
        "business",
        "framework",
        "infrastructure",
        "interfaces",
        "scripts",
        "tests",
    ):
        for path in (_PROJECT_ROOT / root_name).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                for module in _imported_modules(node):
                    if module in _MOVED_IMPORTS:
                        relative = path.relative_to(_PROJECT_ROOT).as_posix()
                        violations.append(f"{relative}:{node.lineno}:{module}")

    assert violations == []


def test_legacy_workflow_package_does_not_forward_moved_graph_contracts() -> None:
    tree = ast.parse(
        (_WORKFLOW_ROOT / "__init__.py").read_text(encoding="utf-8")
    )
    exported = _literal_all(tree)

    assert exported.isdisjoint(_MOVED_PUBLIC_NAMES)


def test_graph_public_api_excludes_legacy_declaration_and_compiler() -> None:
    exported = set(graph_api.__all__)

    assert {
        "HarnessGraphDefinition",
        "HarnessGraphDefinitionReader",
        "HarnessGraphSpec",
        "HarnessStepSpec",
    }.issubset(exported)
    assert exported.isdisjoint(
        {
            "HarnessWorkflowSpec",
            "HarnessWorkflowGraphCompiler",
            "HarnessWorkflowContractReader",
            "condition_from_legacy_dict",
            "LEGACY_WORKFLOW_SCHEMA",
        }
    )


def test_graph_definition_is_not_activated_in_gate_a_runtime() -> None:
    paths = (
        _PROJECT_ROOT / "framework/harness/control_plane/state.py",
        _PROJECT_ROOT / "framework/harness/workflow/compiler.py",
        _PROJECT_ROOT / "interfaces/composition/research.py",
        _PROJECT_ROOT / "business/research/application/single_paper_runtime.py",
    )
    violations = [
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in paths
        if "HarnessGraphDefinition" in path.read_text(encoding="utf-8")
    ]

    assert violations == []


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()


def _literal_all(tree: ast.Module) -> set[str]:
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            return {
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant)
                and isinstance(element.value, str)
            }
    raise AssertionError("workflow package must declare a literal __all__")
