from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENTS_ROOT = PROJECT_ROOT / "framework" / "events"
PRODUCTION_ROOTS = tuple(
    PROJECT_ROOT / name
    for name in ("backend", "framework", "infrastructure", "interfaces", "scripts")
)
EVENT_CANDIDATE_CONSTRUCTION_BOUNDARIES = frozenset(
    {
        "framework/events/runtime/publisher.py",
    }
)
FORBIDDEN_IMPORT_PREFIXES = (
    "backend",
    "framework.workflow",
    "interfaces",
    "infrastructure",
    "storage",
    "workflows",
    "domain",
    "sources",
    "evidence",
    "quality",
)


def test_framework_events_do_not_import_forbidden_layers() -> None:
    violations: list[str] = []
    for path in EVENTS_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imported_modules(tree):
            if _is_forbidden_import(imported):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def test_event_candidate_construction_stays_behind_security_projection() -> None:
    violations: list[str] = []
    for root in PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            aliases = _event_candidate_aliases(tree)
            if not any(_constructs_event_candidate(node, aliases) for node in ast.walk(tree)):
                continue
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            if relative not in EVENT_CANDIDATE_CONSTRUCTION_BOUNDARIES:
                violations.append(relative)

    assert violations == []


def test_workflow_runner_cannot_reintroduce_post_run_event_indexing() -> None:
    assert not (PROJECT_ROOT / "framework" / "workflow" / "runtime" / "runner.py").exists()


def test_framework_legacy_event_recorders_are_not_public_writers() -> None:
    events_init = (EVENTS_ROOT / "__init__.py").read_text(encoding="utf-8")

    assert not (EVENTS_ROOT / "recorder.py").exists()
    assert '"EventRecord"' not in events_init
    assert '"EventRecorder"' not in events_init


def test_expired_event_compatibility_runtime_shims_are_removed() -> None:
    events_init = (EVENTS_ROOT / "__init__.py").read_text(encoding="utf-8")

    assert not (EVENTS_ROOT / "publisher.py").exists()
    assert not (EVENTS_ROOT / "replay.py").exists()
    assert not (EVENTS_ROOT / "bus.py").exists()
    assert not (EVENTS_ROOT / "envelope.py").exists()
    assert not (EVENTS_ROOT / "event.py").exists()
    assert not (EVENTS_ROOT / "filters.py").exists()
    assert not (EVENTS_ROOT / "ordering.py").exists()
    assert not (EVENTS_ROOT / "recorder.py").exists()
    for retired_name in (
        "Event",
        "EventBus",
        "EventEnvelope",
        "EventFilter",
        "EventPublisher",
        "EventReplay",
        "EventType",
        "FunctionEventSubscriber",
        "InMemoryEventBus",
        "InMemoryEventRecorder",
    ):
        assert f'"{retired_name}"' not in events_init

    assert not any((PROJECT_ROOT / "framework/workflow").glob("*.py"))


def test_legacy_postgres_event_writer_and_migration_reader_are_removed() -> None:
    postgres_root = PROJECT_ROOT / "infrastructure" / "storage" / "postgres"
    postgres_init = (postgres_root / "__init__.py").read_text(encoding="utf-8")

    assert not (postgres_root / "event_store.py").exists()
    assert "PostgresEventStore" not in postgres_init
    assert not (PROJECT_ROOT / "infrastructure/storage/events/migration_readers.py").exists()


def test_legacy_storage_event_record_and_jsonl_writer_are_removed() -> None:
    events_root = PROJECT_ROOT / "infrastructure" / "storage" / "events"
    events_init = (events_root / "__init__.py").read_text(encoding="utf-8")

    assert not (events_root / "models.py").exists()
    assert not (events_root / "local_json.py").exists()
    assert '"EventRecord"' not in events_init
    assert '"LocalJsonEventStore"' not in events_init


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _event_candidate_aliases(tree: ast.AST) -> set[str]:
    aliases = {"EventCandidate"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name == "EventCandidate":
                aliases.add(alias.asname or alias.name)
    return aliases


def _constructs_event_candidate(node: ast.AST, aliases: set[str]) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Name):
        return node.func.id in aliases
    return isinstance(node.func, ast.Attribute) and node.func.attr == "EventCandidate"


def _is_forbidden_import(module: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )
