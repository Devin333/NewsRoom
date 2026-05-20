from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_check_postgres_skips_without_dsn(monkeypatch, capsys) -> None:
    module = _load_script("check_postgres")
    monkeypatch.delenv("NEWS_DATABASE_DSN", raising=False)

    exit_code = module.main()

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["service"] == "postgres"
    assert output["status"] == "skipped"
    assert "NEWS_DATABASE_DSN" in output["reason"]


def test_check_qdrant_skips_without_url(monkeypatch, capsys) -> None:
    module = _load_script("check_qdrant")
    monkeypatch.delenv("NEWS_QDRANT_URL", raising=False)

    exit_code = module.main()

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["service"] == "qdrant"
    assert output["status"] == "skipped"
    assert "NEWS_QDRANT_URL" in output["reason"]


def test_check_postgres_required_objects_do_not_expose_dsn() -> None:
    module = _load_script("check_postgres")

    assert "agent_conversation_messages" in module.REQUIRED_TABLES
    assert "agent_conversation_state" in module.REQUIRED_TABLES
    assert "idx_agent_conversation_messages_conversation_offset" in module.REQUIRED_INDEXES
    assert "NEWS_DATABASE_DSN" not in module.REQUIRED_TABLES


def test_check_qdrant_default_payload_indexes() -> None:
    module = _load_script("check_qdrant")

    assert "evidence_items" in module.DEFAULT_COLLECTIONS
    assert "report_sections" in module.DEFAULT_COLLECTIONS
    assert "run_id" in module.DEFAULT_PAYLOAD_INDEXES
    assert "published_at" in module.DEFAULT_PAYLOAD_INDEXES


def test_check_qdrant_default_collections_include_storage_memory_contract_sets() -> None:
    module = _load_script("check_qdrant")

    assert set(module.DEFAULT_COLLECTIONS) >= {"report_sections", "evidence_items"}


def _load_script(name: str):
    script_path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
