from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = (
    ROOT
    / "openspec"
    / "changes"
    / "harness-runtime-production-composition"
    / "caller-inventory.json"
)
PRODUCTION_ROOTS = ("business", "framework", "infrastructure", "interfaces")


def _inventory() -> list[dict[str, object]]:
    payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert payload["schema"] == "newsroom.production-caller-inventory/v1"
    callers = payload["callers"]
    assert isinstance(callers, list)
    return [item for item in callers if isinstance(item, dict)]


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
    return calls


def test_production_process_and_executor_callers_are_inventory_bound() -> None:
    callers = _inventory()
    indexed = {(str(item["path"]), str(item["kind"])) for item in callers}
    missing: list[str] = []
    for path, kind, line in _calls():
        inventory_kind = "subprocess" if kind == "subprocess" else (
            "subagent_runtime" if kind == "SubAgentRuntime" else "tool_executor"
        )
        if (path, inventory_kind) not in indexed:
            missing.append(f"{path}:{line} ({inventory_kind})")
    assert not missing, "unregistered production caller(s): " + ", ".join(missing)


def test_blocked_callers_are_explicit_and_not_qualified() -> None:
    blocked = [item for item in _inventory() if item.get("classification") == "blocked"]
    assert blocked
    assert all(item.get("state") == "follow-up-required" for item in blocked)
    assert any(item.get("id") == "nougat-direct-process" for item in blocked)
