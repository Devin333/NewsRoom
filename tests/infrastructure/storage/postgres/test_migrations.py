
import pytest

from infrastructure.storage.postgres import load_migration_sql
from infrastructure.storage.postgres import migrations as migrations_module


def test_postgres_migration_sql_contains_required_tables() -> None:
    sql = load_migration_sql()

    for table in [
        "workflow_runs",
        "workflow_events",
        "artifact_index",
        "lineage_refs",
        "reports",
        "source_items",
        "evidence_items",
        "claims",
        "claim_supports",
        "quality_results",
        "memory_documents",
        "memory_entities",
        "memory_events",
        "memory_event_entities",
        "memory_event_claims",
        "memory_event_evidence",
        "memory_claim_history",
        "memory_decisions",
        "memory_preferences",
        "agent_conversations",
        "agent_conversation_messages",
        "agent_conversation_state",
        "tool_executions",
        "schema_versions",
        "report_sections",
        "source_health",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "UNIQUE (claim_id, evidence_id, support_type)" in sql
    assert "idx_agent_conversations_run" in sql
    assert "idx_agent_conversation_messages_conversation_offset" in sql
    assert "idx_agent_conversation_state_updated" in sql
    assert "idx_tool_executions_run" in sql
    assert "idx_workflow_runs_workflow_id" in sql
    assert "idx_workflow_runs_status" in sql
    assert "idx_workflow_runs_topic" in sql
    assert "idx_reports_status" in sql
    assert "idx_source_items_source_published" in sql
    assert "idx_source_items_published" in sql
    assert "idx_evidence_items_source_urls_gin" in sql
    assert "idx_evidence_items_source_item_ids_gin" in sql
    assert "idx_evidence_items_lineage_gin" in sql
    assert "success_count_24h INTEGER" in sql
    assert "failure_count_24h INTEGER" in sql
    assert "avg_latency_ms_24h DOUBLE PRECISION" in sql
    assert "idx_memory_entities_type" in sql
    assert "idx_memory_events_run" in sql
    assert "idx_memory_decisions_target" in sql
    assert "idx_memory_preferences_owner" in sql
    assert "idx_memory_claim_history_claim" in sql
    assert "idx_memory_claim_history_evidence" in sql
    assert "ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'mentioned'" in sql
    assert "ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'supporting'" in sql
    assert "ADD COLUMN IF NOT EXISTS support_type TEXT NOT NULL DEFAULT 'supporting'" in sql
    assert "idx_memory_event_entities_role" in sql
    assert "idx_memory_event_claims_role" in sql
    assert "idx_memory_event_evidence_support_type" in sql
    assert "ADD PRIMARY KEY (event_id, entity_id, role)" in sql
    assert "ADD PRIMARY KEY (event_id, claim_id, role)" in sql
    assert "ADD PRIMARY KEY (event_id, evidence_id, support_type)" in sql


def test_postgres_migration_sql_exposes_storage_contract_query_columns() -> None:
    sql = load_migration_sql()

    for column in [
        "topic TEXT",
        "metadata_json JSONB",
        "canonical_url TEXT",
        "published_at TIMESTAMPTZ",
        "fetched_at TIMESTAMPTZ",
        "raw_artifact_id TEXT",
        "source_urls JSONB",
        "source_item_ids JSONB",
        "lineage_json JSONB",
        "updated_at TIMESTAMPTZ",
    ]:
        assert column in sql



def test_postgres_migration_loader_rejects_missing_sql_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(migrations_module, "_MIGRATIONS_DIR", tmp_path)

    with pytest.raises(FileNotFoundError, match="no SQL migrations"):
        migrations_module.load_migration_sql()



def test_postgres_migration_loader_rejects_empty_sql_files(monkeypatch, tmp_path) -> None:
    (tmp_path / "001_empty.sql").write_text("\n\n", encoding="utf-8")
    monkeypatch.setattr(migrations_module, "_MIGRATIONS_DIR", tmp_path)

    with pytest.raises(ValueError, match="are empty"):
        migrations_module.load_migration_sql()
