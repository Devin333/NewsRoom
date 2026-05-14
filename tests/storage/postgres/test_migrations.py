from storage.postgres import load_migration_sql


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
        "agent_conversations",
        "tool_executions",
        "schema_versions",
        "report_sections",
        "source_health",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "UNIQUE (claim_id, evidence_id, support_type)" in sql
    assert "idx_agent_conversations_run" in sql
    assert "idx_tool_executions_run" in sql
    assert "success_count_24h INTEGER" in sql
    assert "failure_count_24h INTEGER" in sql
    assert "avg_latency_ms_24h DOUBLE PRECISION" in sql
