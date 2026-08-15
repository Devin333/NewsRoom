from __future__ import annotations

import ast
from pathlib import Path

from business.research.workflows.paper_analysis_workflow import (
    build_paper_analysis_workflow_spec,
)


_FORBIDDEN_FRAMEWORK_IMPORTS = ("business", "interfaces", "infrastructure")
_FORBIDDEN_BUSINESS_AUTHORITY_MODULES = frozenset(
    {
        "framework.harness.control_plane.graph_decision",
        "framework.harness.control_plane.graph_evaluator",
        "framework.harness.control_plane.scheduler",
        "framework.harness.task_plan.scheduler",
    }
)
_FORBIDDEN_BUSINESS_AUTHORITY_SYMBOLS = frozenset(
    {
        "HarnessDecision",
        "HarnessDecisionType",
        "HarnessGraphDecision",
        "HarnessGraphDecisionType",
        "HarnessRoutingEvaluator",
        "HarnessScheduler",
        "TaskPlanReadyDecision",
        "TaskPlanScheduler",
        "WorkflowGraphEvaluator",
    }
)
_FORBIDDEN_RESEARCH_AUTHORITY_NAMES = frozenset(
    {
        "HarnessDecision",
        "HarnessDecisionType",
        "HarnessRoutingEvaluator",
        "HarnessScheduler",
        "HarnessGraphState",
        "transition_run",
        "transition_step",
    }
)
_ROUTING_METADATA_KEYS = frozenset(
    {
        "next_step",
        "next_route",
        "route",
        "route_to",
        "routing_decision",
    }
)
_LEGACY_RUNTIME_AUTHORITY_MARKERS = (
    ".current_step_id",
    "HarnessRunStatus.PLANNING",
    "HarnessRunStatus.EXECUTING",
    "HarnessRunStatus.VERIFYING",
    "HarnessRunStatus.REPLANNING",
    "routing_rules=",
)


def test_harness_graph_modules_do_not_import_outer_layers() -> None:
    graph_modules = (
        *sorted(Path("framework/harness/graph").rglob("*.py")),
        Path("framework/harness/workflow/compiler.py"),
        Path("framework/harness/workflow/reader.py"),
        Path("framework/harness/workflow/versioning.py"),
        *sorted(Path("framework/harness/workflow/validation").glob("*.py")),
    )
    violations: list[str] = []

    for path in graph_modules:
        for imported in _imports(path):
            if any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in _FORBIDDEN_FRAMEWORK_IMPORTS
            ):
                violations.append(f"{path.as_posix()}: {imported}")

    assert violations == []


def test_research_workers_and_gates_do_not_own_harness_routing() -> None:
    worker_and_gate_sources = (
        Path("business/research/application/single_paper_runtime.py"),
        Path("business/research/workflows/paper_analysis_gates.py"),
    )
    violations: list[str] = []

    for path in worker_and_gate_sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN_RESEARCH_AUTHORITY_NAMES:
                violations.append(f"{path.as_posix()}: {node.id}")
            if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_RESEARCH_AUTHORITY_NAMES:
                violations.append(f"{path.as_posix()}: {node.attr}")

    assert violations == []

    workflow = build_paper_analysis_workflow_spec()
    assert workflow.graph is not None
    assert workflow.routing_rules == ()
    assert all(
        not _ROUTING_METADATA_KEYS.intersection(step.metadata)
        for step in workflow.steps
    )


def test_research_business_does_not_import_graph_decision_authority() -> None:
    violations: list[str] = []
    for path in Path("business/research").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_BUSINESS_AUTHORITY_MODULES:
                        violations.append(
                            f"{path.as_posix()}:{node.lineno}:{alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module in _FORBIDDEN_BUSINESS_AUTHORITY_MODULES:
                    violations.append(
                        f"{path.as_posix()}:{node.lineno}:{node.module}"
                    )
                for alias in node.names:
                    if alias.name in _FORBIDDEN_BUSINESS_AUTHORITY_SYMBOLS:
                        violations.append(
                            f"{path.as_posix()}:{node.lineno}:{alias.name}"
                        )

    assert violations == []


def test_production_callers_do_not_read_legacy_harness_cursor_or_phase_status() -> (
    None
):
    roots = (
        Path("business/research"),
        Path("interfaces"),
        Path("infrastructure/storage/harness"),
    )
    violations = [
        f"{path.as_posix()}: {marker}"
        for root in roots
        for path in root.rglob("*.py")
        for source in (path.read_text(encoding="utf-8"),)
        for marker in _LEGACY_RUNTIME_AUTHORITY_MARKERS
        if marker in source
    ]

    assert violations == []


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return tuple(imports)
