from __future__ import annotations

import ast
from pathlib import Path

import framework.harness as harness_api
import framework.harness.control_plane as control_plane_api
import framework.harness.graph as graph_api
from framework.harness.graph.decision import HarnessGraphDecision
from framework.harness.graph.observability import (
    HarnessGraphDiagnosticSeverity,
    HarnessGraphHealthReport,
    HarnessGraphHealthStatus,
    HarnessGraphMetricSample,
    HarnessGraphOperatorDiagnostic,
)
from framework.harness.graph.reference import HarnessGraphReference
from framework.harness.graph.result_lineage import HarnessGraphResultLineage


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GRAPH_ROOT = PROJECT_ROOT / "framework" / "harness" / "graph"


def test_graph_owner_does_not_import_retired_workflow_namespace() -> None:
    violations: list[str] = []
    for path in GRAPH_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for module in _imported_modules(node):
                if module == "framework.workflow" or module.startswith("framework.workflow."):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}:{module}")
                if module == "framework.harness.workflow" or module.startswith("framework.harness.workflow."):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}:{module}")
    assert violations == []


def test_retired_workflow_namespaces_have_no_source_package() -> None:
    for relative in ("framework/workflow", "framework/specs", "framework/harness/workflow"):
        root = PROJECT_ROOT / relative
        assert not (root / "__init__.py").exists()
        assert not any(root.rglob("*.py"))


def test_graph_versioning_has_no_legacy_writer_window() -> None:
    source = (GRAPH_ROOT / "versioning.py").read_text(encoding="utf-8")
    assert "LEGACY_WORKFLOW_SCHEMA" not in source
    assert "LEGACY_EVENT_SCHEMA" not in source
    assert "newsroom.harness-normalized-graph/v1" not in source
    assert "newsroom.harness-graph-compiler/v1" not in source
    assert "GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA" in source
    assert "HARNESS_GRAPH_ONLY_COMPILER_VERSION" in source


def test_production_and_tests_do_not_import_retired_workflow_modules() -> None:
    violations: list[str] = []
    for root_name in ("business", "framework", "infrastructure", "interfaces", "scripts", "tests"):
        for path in (PROJECT_ROOT / root_name).rglob("*.py"):
            if path.is_relative_to(PROJECT_ROOT / "tests" / "fixtures"):
                continue
            if path == PROJECT_ROOT / "tests" / "scripts" / "test_graph_only_migration.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                for module in _imported_modules(node):
                    if module == "framework.workflow" or module.startswith("framework.workflow."):
                        violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}:{module}")
                    if module == "framework.harness.workflow" or module.startswith("framework.harness.workflow."):
                        violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}:{module}")
    assert violations == []


def test_graph_public_api_excludes_retired_workflow_declarations() -> None:
    exported = set(graph_api.__all__)
    assert {
        "HarnessGraphDefinition",
        "HarnessGraphDefinitionReader",
        "HarnessGraphLeafBinding",
        "HarnessGraphPreflight",
        "HarnessGraphSpec",
        "NormalizedHarnessGraph",
    }.issubset(exported)
    assert exported.isdisjoint(
        {
            "HarnessWorkflowSpec",
            "HarnessWorkflowGraphCompiler",
            "HarnessWorkflowContractReader",
            "WorkflowGraphEvaluator",
        }
    )


def test_graph_reference_has_one_graph_owned_public_definition() -> None:
    assert graph_api.HarnessGraphReference is HarnessGraphReference
    assert harness_api.HarnessGraphReference is HarnessGraphReference
    assert "HarnessGraphReference" in graph_api.__all__
    assert "HarnessGraphReference" not in control_plane_api.__all__
    assert not hasattr(control_plane_api, "HarnessGraphReference")


def test_graph_result_lineage_has_one_graph_owned_public_definition() -> None:
    assert graph_api.HarnessGraphResultLineage is HarnessGraphResultLineage
    assert harness_api.HarnessGraphResultLineage is HarnessGraphResultLineage
    assert "HarnessGraphResultLineage" in graph_api.__all__
    assert "HarnessGraphResultLineage" not in control_plane_api.__all__
    assert not hasattr(control_plane_api, "HarnessGraphResultLineage")


def test_graph_decision_has_one_graph_owned_public_definition() -> None:
    assert graph_api.HarnessGraphDecision is HarnessGraphDecision
    assert harness_api.HarnessGraphDecision is HarnessGraphDecision
    assert "HarnessGraphDecision" in graph_api.__all__
    assert "HarnessGraphDecision" not in control_plane_api.__all__
    assert not hasattr(control_plane_api, "HarnessGraphDecision")
    assert not (PROJECT_ROOT / "framework/harness/control_plane/graph_decision.py").exists()


def test_graph_observability_values_have_one_graph_owned_public_definition() -> None:
    value_names = {
        "HarnessGraphDiagnosticSeverity": HarnessGraphDiagnosticSeverity,
        "HarnessGraphHealthReport": HarnessGraphHealthReport,
        "HarnessGraphHealthStatus": HarnessGraphHealthStatus,
        "HarnessGraphMetricSample": HarnessGraphMetricSample,
        "HarnessGraphOperatorDiagnostic": HarnessGraphOperatorDiagnostic,
    }
    for name, value_type in value_names.items():
        assert getattr(graph_api, name) is value_type
        assert getattr(harness_api, name) is value_type
        assert name in graph_api.__all__
        assert name in harness_api.__all__
        assert name not in control_plane_api.__all__


def test_harness_root_public_api_retains_artifact_contracts() -> None:
    names = {"ArtifactPort", "ArtifactReferenceVerifierPort", "GraphResultArtifactReadPort"}
    assert names.issubset(set(harness_api.__all__))
    assert all(hasattr(harness_api, name) for name in names)


def test_graph_definition_is_the_only_runtime_declaration() -> None:
    paths = (
        PROJECT_ROOT / "framework/harness/control_plane/state.py",
        PROJECT_ROOT / "interfaces/composition/research.py",
        PROJECT_ROOT / "business/research/application/single_paper_runtime.py",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "HarnessGraphDefinition" in source
    assert "HarnessWorkflowSpec" not in source
    assert "HarnessWorkflowGraphCompiler" not in source


def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return (node.module,)
    return ()
