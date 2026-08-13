from __future__ import annotations

import ast
from pathlib import Path

from tests.architecture._helpers import PROJECT_ROOT


RUNTIME = PROJECT_ROOT / "framework" / "harness" / "subagents" / "runtime.py"
COMPOSITION = PROJECT_ROOT / "interfaces" / "composition" / "research.py"
FAKE_RUNTIME = (
    PROJECT_ROOT / "framework" / "harness" / "subagents" / "fake.py"
)


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_subagent_runtime_requires_explicit_transcript_store() -> None:
    tree = ast.parse(RUNTIME.read_text(encoding="utf-8"), filename=str(RUNTIME))
    runtime = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SubAgentRuntime"
    )
    init = next(
        node
        for node in runtime.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    transcript_arg = next(
        arg for arg in init.args.kwonlyargs if arg.arg == "transcript_store"
    )
    default_index = init.args.kwonlyargs.index(transcript_arg)
    assert init.args.kw_defaults[default_index] is None


def test_research_composition_owns_the_production_transcript_adapter() -> None:
    source = COMPOSITION.read_text(encoding="utf-8")
    assert "FilesystemSubAgentTranscriptStore(" in source
    assert "FakeSubAgentTranscriptStore(" not in source
    assert source.count("subagent_transcript_store") >= 3


def test_interfaces_do_not_expose_transcript_store_inbound() -> None:
    violations: list[str] = []
    interfaces_root = PROJECT_ROOT / "interfaces"
    for path in sorted(interfaces_root.rglob("*.py")):
        if path.parent == COMPOSITION.parent:
            continue
        source = path.read_text(encoding="utf-8")
        if "SubAgentTranscriptStore" in source:
            violations.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert violations == []


def test_fake_transcript_store_is_constructed_only_by_explicit_fake_runtime() -> None:
    violations: list[str] = []
    roots = (
        PROJECT_ROOT / "business",
        PROJECT_ROOT / "framework",
        PROJECT_ROOT / "infrastructure",
        PROJECT_ROOT / "interfaces",
        PROJECT_ROOT / "scripts",
    )
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.parts or path == FAKE_RUNTIME:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if any(
                isinstance(node, ast.Call)
                and _call_name(node.func) == "FakeSubAgentTranscriptStore"
                for node in ast.walk(tree)
            ):
                violations.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert violations == []
