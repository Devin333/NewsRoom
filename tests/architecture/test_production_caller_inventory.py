from __future__ import annotations

import ast
from datetime import date
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = (
    ROOT
    / "openspec"
    / "changes"
    / "harness-runtime-production-composition"
    / "caller-inventory.json"
)
PRODUCTION_ROOTS = ("backend", "framework", "infrastructure", "interfaces")
INVENTORY_SCHEMA = "newsroom.production-caller-inventory/v1"
CLASSIFICATIONS = {"migrate", "trusted_exemption", "blocked"}
CLASSIFICATION_STATES = {
    "migrate": "migrated",
    "trusted_exemption": "approved",
    "blocked": "follow-up-required",
}
CALLER_KINDS = {
    "subprocess",
    "tool_executor",
    "subagent_runtime",
    "runtime_event_authority",
}
ENTRY_FIELDS = {
    "id",
    "kind",
    "path",
    "symbol",
    "classification",
    "state",
    "owner",
    "rationale",
    "non_harness_managed_proof",
    "review_by",
    "check",
}
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_RUNTIME_EVENT_AUTHORITY_CALLS = {
    "durable_event_storage_from_env",
    "CanonicalRuntimeEventPublisher",
    "DurableGraphEventProjectionAdapter",
}
_RUNTIME_EVENT_AUTHORITY_PATHS = {"interfaces/composition/research.py"}


def _inventory() -> list[dict[str, object]]:
    payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema",
        "scope",
        "generated_at",
        "classification_values",
        "callers",
    }
    assert payload["schema"] == INVENTORY_SCHEMA
    assert payload["scope"] == "production-runtime-packages"
    assert payload["classification_values"] == [
        "migrate",
        "trusted_exemption",
        "blocked",
    ]
    assert isinstance(payload["generated_at"], str)
    assert _DATE.fullmatch(payload["generated_at"])
    date.fromisoformat(payload["generated_at"])
    callers = payload["callers"]
    assert isinstance(callers, list)
    assert all(isinstance(item, dict) for item in callers)
    return callers


def _calls() -> list[tuple[str, str, int]]:
    calls: list[tuple[str, str, int]] = []
    for root_name in PRODUCTION_ROOTS:
        for path in (ROOT / root_name).rglob("*.py"):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            relative = path.relative_to(ROOT).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr in {"run", "Popen", "call", "check_call", "check_output"}:
                        owner = node.func.value
                        if isinstance(owner, ast.Name) and owner.id == "subprocess":
                            calls.append((relative, "subprocess", node.lineno))
                elif isinstance(node.func, ast.Name) and node.func.id in {
                    "ToolExecutor",
                    "SubAgentRuntime",
                }:
                    calls.append((relative, node.func.id, node.lineno))
                elif (
                    relative in _RUNTIME_EVENT_AUTHORITY_PATHS
                    and isinstance(node.func, ast.Name)
                    and node.func.id in _RUNTIME_EVENT_AUTHORITY_CALLS
                ):
                    calls.append((relative, "runtime_event_authority", node.lineno))
    return calls


def test_inventory_schema_and_entries_are_complete() -> None:
    callers = _inventory()
    assert callers
    ids: set[str] = set()
    for entry in callers:
        assert set(entry) == ENTRY_FIELDS
        identifier = entry["id"]
        assert isinstance(identifier, str) and identifier.strip()
        assert identifier not in ids
        ids.add(identifier)

        kind = entry["kind"]
        assert kind in CALLER_KINDS
        for field in (
            "path",
            "symbol",
            "owner",
            "rationale",
            "non_harness_managed_proof",
            "check",
        ):
            assert isinstance(entry[field], str) and entry[field].strip(), field

        path = ROOT / str(entry["path"])
        assert path.is_file(), entry["path"]

        classification = entry["classification"]
        assert classification in CLASSIFICATIONS
        assert entry["state"] == CLASSIFICATION_STATES[classification]

        review_by = entry["review_by"]
        assert isinstance(review_by, str) and _DATE.fullmatch(review_by)
        date.fromisoformat(review_by)


def test_production_process_and_executor_callers_are_inventory_bound() -> None:
    callers = _inventory()
    indexed = {(str(item["path"]), str(item["kind"])) for item in callers}
    missing: list[str] = []
    for path, kind, line in _calls():
        inventory_kind = "subprocess" if kind == "subprocess" else (
            "subagent_runtime"
            if kind == "SubAgentRuntime"
            else "tool_executor"
            if kind == "ToolExecutor"
            else "runtime_event_authority"
        )
        if (path, inventory_kind) not in indexed:
            missing.append(f"{path}:{line} ({inventory_kind})")
    assert not missing, "unregistered production caller(s): " + ", ".join(missing)


def test_blocked_callers_are_explicit_and_not_qualified() -> None:
    blocked = [item for item in _inventory() if item.get("classification") == "blocked"]
    assert blocked
    assert all(item.get("state") == "follow-up-required" for item in blocked)
    assert any(item.get("id") == "nougat-direct-process" for item in blocked)


def test_runtime_event_authority_is_an_inherited_handoff() -> None:
    authorities = [
        item
        for item in _inventory()
        if item["kind"] == "runtime_event_authority"
    ]

    assert len(authorities) == 1
    authority = authorities[0]
    assert authority["id"] == "research-canonical-events"
    assert authority["classification"] == "blocked"
    assert authority["state"] == "follow-up-required"
    assert authority["owner"] == "runtime-event-transport"
    handoff = " ".join(
        str(authority[field]).lower()
        for field in ("rationale", "non_harness_managed_proof")
    )
    assert "existing" in handoff
    assert "does not migrate" in handoff
    assert "independently" in handoff
