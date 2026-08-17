from __future__ import annotations

import ast
from pathlib import Path

import framework.harness as harness_api
import framework.harness.control_plane as control_plane_api
import framework.harness.control_plane.graph_state as graph_state_api
import framework.harness.graph as graph_api
from framework.harness.graph.reference import HarnessGraphReference


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_GRAPH_ROOT = _PROJECT_ROOT / "framework/harness/graph"
_WORKFLOW_ROOT = _PROJECT_ROOT / "framework/harness/workflow"
_MOVED_MODULES = {
    "binding_authority.py": "bindings.py",
    "canonical.py": "canonical.py",
    "conditions.py": "conditions.py",
    "dsl.py": "dsl.py",
    "graph.py": "model.py",
    "runtime_resolution.py": "runtime_resolution.py",
    "step.py": "activity.py",
    "validation/dataflow.py": "validation/dataflow.py",
    "validation/models.py": "validation/models.py",
    "validation/policy.py": "validation/policy.py",
    "validation/preflight.py": "validation/preflight.py",
    "validation/registry.py": "validation/registry.py",
    "validation/semantic.py": "validation/semantic.py",
    "validation/structural.py": "validation/structural.py",
}
_MOVED_IMPORTS = tuple(
    "framework.harness.workflow."
    + name.removesuffix(".py").replace("/", ".")
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
    "HarnessActivityCapabilities",
    "HarnessActivityContractBinding",
    "HarnessActivityUsage",
    "HarnessBranch",
    "HarnessCompensationHandlerBinding",
    "HarnessCompensationReference",
    "HarnessContractKind",
    "HarnessContractReference",
    "HarnessControlNode",
    "HarnessDeterministicMergeBinding",
    "HarnessExecutableNode",
    "HarnessGraphChecksumRegistry",
    "HarnessGraphEdge",
    "HarnessGraphEdgeKind",
    "HarnessGraphLeafBinding",
    "HarnessGraphRepairBinding",
    "HarnessGraphRepairTrigger",
    "HarnessGraphTaskPlanStageBinding",
    "HarnessGraphNode",
    "HarnessGraphNodeKind",
    "HarnessGraphPreflight",
    "HarnessGraphDiagnostic",
    "HarnessGraphPreflightPolicy",
    "HarnessGraphRegistrySnapshot",
    "HarnessGraphRuntimeResolver",
    "HarnessGraphSpec",
    "HarnessGraphValidationPhase",
    "HarnessGraphValidationResult",
    "HarnessJoinContract",
    "HarnessLoopContract",
    "HarnessMergeContract",
    "HarnessMergeKind",
    "HarnessRetryPolicy",
    "HarnessResolvedRuntimeBindings",
    "HarnessRuntimeBindingAuthority",
    "HarnessStepSpec",
    "HarnessPreparedGraph",
    "HarnessWaitContract",
    "HarnessWorkerBinding",
    "HarnessWorkerType",
    "NormalizedHarnessGraph",
    "ParallelAll",
    "ParallelAny",
    "ParallelBranch",
    "Sequence",
    "StepRef",
    "Wait",
    "graph_contract_references",
    "validate_dataflow",
    "validate_policy",
    "validate_registry",
    "validate_semantics",
    "validate_structure",
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
    assert [
        target
        for target in _MOVED_MODULES.values()
        if not (_GRAPH_ROOT / target).is_file()
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


def test_legacy_workflow_package_has_no_public_facade() -> None:
    tree = ast.parse(
        (_WORKFLOW_ROOT / "__init__.py").read_text(encoding="utf-8")
    )
    exported = _literal_all(tree)

    assert exported == set()


def test_production_and_tests_do_not_import_legacy_workflow_facade() -> None:
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
                if "framework.harness.workflow" in _imported_modules(node):
                    relative = path.relative_to(_PROJECT_ROOT).as_posix()
                    violations.append(f"{relative}:{node.lineno}")

    assert violations == []


def test_graph_public_api_excludes_legacy_declaration_and_compiler() -> None:
    exported = set(graph_api.__all__)

    assert {
        "HarnessGraphDefinition",
        "HarnessGraphDefinitionReader",
        "HarnessGraphLeafBinding",
        "HarnessGraphRepairBinding",
        "HarnessGraphRepairTrigger",
        "HarnessGraphTaskPlanStageBinding",
        "HarnessGraphPreflight",
        "HarnessGraphSpec",
        "HarnessStepSpec",
        "NormalizedHarnessGraph",
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


def test_graph_reference_has_one_graph_owned_public_definition() -> None:
    assert graph_api.HarnessGraphReference is HarnessGraphReference
    assert harness_api.HarnessGraphReference is HarnessGraphReference
    assert "HarnessGraphReference" in graph_api.__all__
    assert "HarnessGraphReference" not in control_plane_api.__all__
    assert not hasattr(control_plane_api, "HarnessGraphReference")
    assert not hasattr(graph_state_api, "HarnessGraphReference")


def test_harness_root_public_api_excludes_legacy_workflow_facade() -> None:
    legacy_names = {
        "DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY",
        "HarnessGraphCompileResult",
        "HarnessGraphSchemaRegistry",
        "HarnessRouteKind",
        "HarnessRoutingRule",
        "HarnessWorkflowContractReader",
        "HarnessWorkflowGraphCompiler",
        "HarnessWorkflowSpec",
        "WorkflowGraphEvaluator",
    }

    assert set(harness_api.__all__).isdisjoint(legacy_names)
    assert {name for name in legacy_names if hasattr(harness_api, name)} == set()
    assert "HarnessGraphEvaluator" in harness_api.__all__
    assert hasattr(harness_api, "HarnessGraphEvaluator")


def test_control_plane_public_api_excludes_workflow_evaluator_name() -> None:
    assert "WorkflowGraphEvaluator" not in control_plane_api.__all__
    assert not hasattr(control_plane_api, "WorkflowGraphEvaluator")
    assert "HarnessGraphEvaluator" in control_plane_api.__all__
    assert hasattr(control_plane_api, "HarnessGraphEvaluator")


def test_harness_root_public_api_retains_artifact_contracts() -> None:
    artifact_contract_names = {
        "ArtifactPort",
        "ArtifactReferenceVerifierPort",
        "GraphResultArtifactReadPort",
    }

    assert artifact_contract_names.issubset(set(harness_api.__all__))
    assert all(hasattr(harness_api, name) for name in artifact_contract_names)


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
