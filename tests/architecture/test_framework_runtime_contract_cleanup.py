from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_ROOT = PROJECT_ROOT / "framework"


def test_llm_contract_models_have_single_concrete_definitions() -> None:
    definitions: dict[str, list[str]] = {"LLMRequest": [], "LLMResponse": [], "TokenUsage": []}
    for path in FRAMEWORK_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in definitions:
                definitions[node.name].append(path.relative_to(PROJECT_ROOT).as_posix())

    assert definitions == {
        "LLMRequest": ["framework/llm/models/request.py"],
        "LLMResponse": ["framework/llm/models/response.py"],
        "TokenUsage": ["framework/llm/models/usage.py"],
    }


def test_framework_routing_has_no_business_predicate_keys() -> None:
    routing_root = FRAMEWORK_ROOT / "harness" / "graph"
    forbidden = ("source_unavailable", "editor_review", "report_quality_summary", "validation_metrics")
    violations: list[str] = []
    for path in routing_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {token}")

    assert violations == []


def test_worker_runtime_does_not_depend_on_in_memory_queue() -> None:
    runtime_root = FRAMEWORK_ROOT / "workers" / "runtime"
    violations: list[str] = []
    for path in runtime_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "framework.workers.queue.in_memory":
                violations.append(path.relative_to(PROJECT_ROOT).as_posix())
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "framework.workers.queue.in_memory":
                        violations.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert violations == []


def test_workflow_executor_is_thin_runtime_orchestrator() -> None:
    assert not (FRAMEWORK_ROOT / "workflow" / "runtime" / "executor.py").exists()
