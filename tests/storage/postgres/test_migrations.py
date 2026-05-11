from storage.postgres import load_migration_sql


def test_postgres_migration_sql_contains_required_tables() -> None:
    sql = load_migration_sql()

    for table in [
        "workflow_runs",
        "workflow_events",
        "reports",
        "source_items",
        "evidence_items",
        "claims",
        "report_sections",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
