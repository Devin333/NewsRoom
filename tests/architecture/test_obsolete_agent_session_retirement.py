from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from framework.agent.loop.loop import AgentLoop
from framework.agent.loop.runner import AgentRunner
from framework.agent.models import AgentSpec
from framework.agent.subagents.executor import SubAgentTask, _child_inputs
from tests.architecture._helpers import PROJECT_ROOT


RETIRED_DIRS = (
    PROJECT_ROOT / "framework" / "agent" / "session",
    PROJECT_ROOT / "framework" / "memory" / "session",
    PROJECT_ROOT / "tests" / "framework" / "agent" / "session",
)
PRODUCTION_ROOTS = tuple(
    PROJECT_ROOT / name
    for name in ("business", "framework", "infrastructure", "interfaces", "scripts")
)
LEGACY_SESSION_DATABASE = ".newsroom/paper-agent-sessions.sqlite3"
RETIREMENT_OPERATIONS_NOTE = (
    PROJECT_ROOT / "docs" / "operations" / "agent-session-retirement.md"
)


def test_obsolete_agent_session_packages_and_dedicated_tests_are_absent() -> None:
    assert all(not path.exists() for path in RETIRED_DIRS)


def test_production_has_no_retired_agent_session_imports_or_definitions() -> None:
    violations: list[str] = []
    for root in PRODUCTION_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(
                        alias.name.startswith((
                            "framework.agent.session",
                            "framework.memory.session",
                        ))
                        for alias in node.names
                    ):
                        violations.append(path.relative_to(PROJECT_ROOT).as_posix())
                elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
                    ("framework.agent.session", "framework.memory.session")
                ):
                    violations.append(path.relative_to(PROJECT_ROOT).as_posix())
                elif isinstance(node, ast.ClassDef) and node.name in {
                    "AgentSessionContextPolicy",
                    "AgentSharedWorkspace",
                    "SharedSessionContextAssembler",
                }:
                    violations.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert violations == []


def test_agent_spec_and_loop_surfaces_have_no_shared_session_state_plane() -> None:
    payload = AgentSpec(
        agent_id="retirement-check",
        name="Retirement Check",
        instructions="Return a bounded result",
    ).to_dict()
    assert "session_context_policy" not in payload

    loop_params = set(inspect.signature(AgentLoop.__init__).parameters)
    runner_init_params = set(inspect.signature(AgentRunner.__init__).parameters)
    runner_run_params = set(inspect.signature(AgentRunner.run).parameters)
    forbidden = {
        "session_workspace",
        "session_context_assembler",
        "session_store",
        "shared_session_context",
        "_agent_session_workspace",
    }
    assert loop_params.isdisjoint(forbidden)
    assert runner_init_params.isdisjoint(forbidden)
    assert runner_run_params.isdisjoint(forbidden)

    loop_source = inspect.getsource(AgentLoop)
    assert "_agent_session_workspace" not in loop_source
    assert "shared_session_context" not in loop_source
    assert "_session_context_for_llm" not in loop_source


def test_stale_policy_is_rejected_and_metadata_session_id_is_not_promoted() -> None:
    with pytest.raises(ValueError, match="agent_session_context_policy_retired"):
        AgentSpec.from_dict(
            {
                "agent_id": "stale",
                "name": "Stale",
                "instructions": "must fail",
                "session_context_policy": {"enabled": True},
            }
        )

    task = SubAgentTask(
        parent_agent_id="parent",
        child_agent_id="child",
        task="check",
        metadata={
            "session_id": "obsolete-plane",
            "run_id": "run-1",
            "graph_id": "graph-1",
        },
    )
    child_inputs = _child_inputs(task)
    assert "session_id" not in child_inputs
    assert child_inputs["run_id"] == "run-1"
    assert child_inputs["graph_id"] == "graph-1"


def test_independent_session_owners_remain_present() -> None:
    retained_paths = (
        PROJECT_ROOT / "framework" / "harness" / "rag" / "session.py",
        PROJECT_ROOT / "business" / "research" / "reading_session",
        PROJECT_ROOT / "interfaces" / "api" / "routers" / "auth.py",
        PROJECT_ROOT / "interfaces" / "api" / "routers" / "projects.py",
        PROJECT_ROOT / "infrastructure" / "storage" / "conversation",
        PROJECT_ROOT / "framework" / "agent" / "messages",
        PROJECT_ROOT / "framework" / "harness" / "subagents" / "transcript.py",
    )
    assert all(path.exists() for path in retained_paths)


def test_no_production_fake_or_noop_agent_session_fallback_exists() -> None:
    forbidden_tokens = (
        "AgentSessionContextPolicy(",
        "AgentSharedWorkspace(",
        "SharedSessionContextAssembler(",
        "MemoryRuntimeAgentSessionStore(",
        "SQLiteAgentSessionStore(",
    )
    violations: list[str] = []
    for root in PRODUCTION_ROOTS:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in source:
                    violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {token}")
    assert violations == []


def test_historical_agent_session_data_is_operator_owned_and_never_recreated() -> None:
    note = RETIREMENT_OPERATIONS_NOTE.read_text(encoding="utf-8")
    assert LEGACY_SESSION_DATABASE in note
    assert "orphaned historical data" in note
    assert "must not automatically" in note.lower()
    assert "operator" in note.lower()

    violations: list[str] = []
    for root in PRODUCTION_ROOTS:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if LEGACY_SESSION_DATABASE in source or "paper-agent-sessions.sqlite3" in source:
                violations.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert violations == []
