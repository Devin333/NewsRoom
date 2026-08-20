from pathlib import Path
import tomllib

import pytest

from infrastructure.storage.postgres import load_migration_sql
from infrastructure.storage.postgres import migrations as migrations_module


ROOT = Path(__file__).resolve().parents[4]
MIGRATIONS_DIR = ROOT / "infrastructure" / "storage" / "postgres" / "migrations"
DURABLE_EVENT_MIGRATION = MIGRATIONS_DIR / "006_durable_event_runtime.sql"
REPLAY_CHECKPOINT_MIGRATION = MIGRATIONS_DIR / "007_replay_checkpoints.sql"
AUTHORIZED_REDELIVERY_MIGRATION = MIGRATIONS_DIR / "008_authorized_redelivery.sql"
RECORDED_ACTIVITIES_MIGRATION = MIGRATIONS_DIR / "009_recorded_activities.sql"
RETIREMENT_CANCELLATION_MIGRATION = (
    MIGRATIONS_DIR / "010_retirement_cancellations.sql"
)
READER_REPAIR_MEMORY_COMMIT_MIGRATION = (
    MIGRATIONS_DIR / "011_reader_repair_memory_commits.sql"
)
GRAPH_ACTIVITY_STORE_CUTOVER_MIGRATION = (
    MIGRATIONS_DIR / "012_graph_activity_store_cutover.sql"
)


def test_postgres_migration_sql_contains_required_tables() -> None:
    sql = load_migration_sql()

    for table in [
        "graph_runs",
        "durable_events",
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
        "reader_repair_memory_objects",
        "reader_repair_memory_versions",
        "reader_repair_memory_commits",
        "reader_repair_memory_commit_members",
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
    assert "idx_graph_runs_graph_id" in sql
    assert "idx_graph_runs_status" in sql
    assert "idx_graph_runs_topic" in sql
    assert "graph_id TEXT NOT NULL" in sql
    assert "graph_version TEXT NOT NULL" in sql
    assert "CREATE TABLE IF NOT EXISTS workflow_runs" not in sql
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
    assert "idx_reader_repair_memory_objects_issue" in sql
    assert "idx_reader_repair_memory_objects_signature" in sql
    assert "idx_reader_repair_memory_objects_status" in sql
    assert "idx_reader_repair_memory_versions_object" in sql
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


def test_graph_identity_columns_are_added_before_dependent_indexes() -> None:
    sql = load_migration_sql()

    artifact_columns = sql.index("ALTER TABLE artifact_index")
    artifact_index = sql.index("CREATE INDEX IF NOT EXISTS idx_artifact_index_graph")
    assert artifact_columns < artifact_index

    graph_run_columns = sql.index("ALTER TABLE graph_runs")
    graph_run_index = sql.index("CREATE INDEX IF NOT EXISTS idx_graph_runs_graph_id")
    assert graph_run_columns < graph_run_index

    memory_columns = sql.index("ALTER TABLE memory_decisions")
    memory_index = sql.index("CREATE INDEX IF NOT EXISTS idx_memory_decisions_target")
    assert memory_columns < memory_index


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


def test_durable_event_runtime_migration_defines_complete_additive_schema() -> None:
    sql = DURABLE_EVENT_MIGRATION.read_text(encoding="utf-8")

    tables = [
        "event_stream_sequences",
        "durable_events",
        "event_subscriptions",
        "event_subscription_status_audit",
        "event_subscription_stream_states",
        "event_deliveries",
        "event_inbox",
        "event_consumer_checkpoints",
        "event_dead_letters",
        "event_quarantine",
        "event_replay_reports",
    ]
    for table in tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "ALTER TABLE" not in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert sql.count("CREATE TABLE IF NOT EXISTS") == len(tables)
    assert "tenant_scope    TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED" in sql
    assert "PRIMARY KEY (tenant_scope, stream_id)" in sql
    assert "UNIQUE (tenant_scope, stream_id, stream_sequence)" in sql
    assert "PRIMARY KEY (tenant_scope, subscription_id, subscription_version, stream_id)" in sql
    assert "UNIQUE (event_id, subscription_id, subscription_version, delivery_generation)" in sql
    assert "PRIMARY KEY (event_id, consumer_effect_id)" in sql
    assert "highest_contiguous_terminal_sequence   BIGINT" in sql
    assert "FOREIGN KEY (tenant_scope, subscription_id, subscription_version, stream_id)" in sql
    assert "FOREIGN KEY (subscription_id, subscription_version, tenant_scope)" in sql
    assert "CONSTRAINT uq_event_subscriptions_delivery_ref" in sql
    assert "CONSTRAINT uq_event_deliveries_inbox_ref" in sql
    assert "CONSTRAINT ck_event_deliveries_non_claimed_lease" in sql
    assert "consumer_effect_scope" in sql
    assert "WHERE state IN ('pending', 'retry_wait')" in sql
    assert "WHERE state = 'claimed'" in sql
    assert "CHECK (content_checksum ~ '^sha256:[0-9a-f]{64}$')" in sql
    assert "CHECK (record_checksum ~ '^sha256:[0-9a-f]{64}$')" in sql
    assert "jsonb_typeof(versions) = 'array'" in sql
    assert "mode IN ('rebuild_state', 'verify_history', 'redeliver')" in sql

    for constraint in [
        "pk_event_stream_sequences",
        "uq_durable_events_stream_sequence",
        "fk_durable_events_stream",
        "pk_event_subscriptions",
        "ck_event_subscriptions_start",
        "ck_event_subscriptions_effect_contract",
        "fk_event_subscription_status_audit_subscription",
        "ck_event_subscription_status_audit_status",
        "ck_event_subscription_status_audit_reason",
        "pk_event_subscription_stream_states",
        "fk_event_subscription_stream_states_stream",
        "uq_event_deliveries_identity",
        "fk_event_deliveries_event",
        "fk_event_deliveries_stream_state",
        "ck_event_deliveries_lease_atomic",
        "pk_event_inbox",
        "pk_event_consumer_checkpoints",
        "ck_event_consumer_checkpoints_frontier",
        "uq_event_dead_letters_delivery",
        "ck_event_dead_letters_operator",
        "ck_event_quarantine_reason",
        "ck_event_quarantine_operator",
        "fk_event_replay_reports_stream",
        "ck_event_replay_reports_terminal",
        "ck_event_replay_reports_redelivery_operator",
    ]:
        assert f"CONSTRAINT {constraint}" in sql

    for index in [
        "idx_durable_events_stream_observed",
        "idx_event_subscriptions_event_types_gin",
        "idx_event_subscription_status_audit_subscription",
        "idx_event_subscription_stream_states_stream",
        "idx_event_deliveries_claimable",
        "idx_event_deliveries_lease_expiry",
        "uq_event_inbox_delivery",
        "idx_event_consumer_checkpoints_subscription",
        "idx_event_dead_letters_open",
        "idx_event_quarantine_tenant_status",
        "idx_event_replay_reports_stream",
    ]:
        assert f"CREATE INDEX IF NOT EXISTS {index}" in sql or (
            f"CREATE UNIQUE INDEX IF NOT EXISTS {index}" in sql
        )


def test_durable_event_runtime_migration_is_loaded_after_existing_schema() -> None:
    sql = load_migration_sql()

    assert sql.index("CREATE TABLE IF NOT EXISTS reader_repair_memory_objects") < sql.index(
        "CREATE TABLE IF NOT EXISTS event_stream_sequences"
    )
    assert sql.count("CREATE TABLE IF NOT EXISTS event_stream_sequences") == 1


def test_replay_checkpoint_migration_is_additive_and_loaded_after_event_runtime() -> None:
    sql = REPLAY_CHECKPOINT_MIGRATION.read_text(encoding="utf-8")
    loaded = load_migration_sql()

    assert "CREATE TABLE IF NOT EXISTS event_replay_checkpoints" in sql
    assert "checkpoint_id           TEXT PRIMARY KEY" in sql
    assert "UNIQUE (checkpoint_id, tenant_scope)" in sql
    assert "FOREIGN KEY (tenant_scope, source_stream_id)" in sql
    assert "source_high_watermark >= last_sequence" in sql
    assert "event_replay_checkpoints_update" in sql
    assert "replay checkpoint immutable identity changed" in sql
    assert "equal replay checkpoint sequence is not exactly idempotent" in sql
    assert "ALTER TABLE" not in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert loaded.index("CREATE TABLE IF NOT EXISTS event_replay_reports") < loaded.index(
        "CREATE TABLE IF NOT EXISTS event_replay_checkpoints"
    )


def test_authorized_redelivery_migration_is_additive_and_loaded_last() -> None:
    sql = AUTHORIZED_REDELIVERY_MIGRATION.read_text(encoding="utf-8")
    loaded = load_migration_sql()

    assert "CREATE TABLE IF NOT EXISTS event_redelivery_reports" in sql
    assert "CREATE TABLE IF NOT EXISTS event_redelivery_items" in sql
    assert "PRIMARY KEY (tenant_scope, redelivery_id)" in sql
    assert "FOREIGN KEY (tenant_scope, redelivery_id)" in sql
    assert "captured_high_watermark >= through_sequence" in sql
    assert "through_sequence - from_sequence < 1000" in sql
    assert "requested_through_sequence = through_sequence" in sql
    assert "char_length(authorization_evidence_ref) <= 512" in sql
    assert "delivery_generation >= 2" in sql
    assert "ALTER TABLE" not in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert loaded.index("CREATE TABLE IF NOT EXISTS event_replay_checkpoints") < loaded.index(
        "CREATE TABLE IF NOT EXISTS event_redelivery_reports"
    )


def test_recorded_activity_migration_is_graph_only_encrypted_and_loaded_in_order() -> None:
    sql = RECORDED_ACTIVITIES_MIGRATION.read_text(encoding="utf-8")
    loaded = load_migration_sql()

    for table in (
        "event_activity_payloads",
        "event_activity_records",
        "event_activity_access_audit",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "harness_activity_results" not in sql
    assert "ciphertext               BYTEA NOT NULL" in sql
    assert sql.count("ciphertext               BYTEA NOT NULL") == 2
    assert "payload JSON" not in sql
    assert "payload JSONB" not in sql
    assert "record JSON" not in sql
    assert "record JSONB" not in sql
    assert "PRIMARY KEY (tenant_scope, activity_id, payload_role)" in sql
    assert "PRIMARY KEY (tenant_scope, activity_id)" in sql
    assert sql.count("tenant_id IS NULL OR btrim(tenant_id) <> ''") == 3
    assert "payload_role IN ('input', 'output', 'error')" in sql
    assert "status IN ('pending', 'succeeded', 'failed')" in sql
    assert "operation IN ('write', 'read')" in sql
    assert "ALTER TABLE" not in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert loaded.index("CREATE TABLE IF NOT EXISTS event_redelivery_reports") < loaded.index(
        "CREATE TABLE IF NOT EXISTS event_activity_payloads"
    )


def test_graph_activity_store_cutover_drops_flat_result_table_last() -> None:
    sql = GRAPH_ACTIVITY_STORE_CUTOVER_MIGRATION.read_text(encoding="utf-8")
    loaded = load_migration_sql()

    assert "DROP TABLE IF EXISTS harness_activity_results" in sql
    assert loaded.index(
        "CREATE TABLE IF NOT EXISTS reader_repair_memory_commits"
    ) < loaded.index("DROP TABLE IF EXISTS harness_activity_results")


def test_retirement_cancellation_migration_is_additive_bounded_and_loaded_in_order() -> None:
    sql = RETIREMENT_CANCELLATION_MIGRATION.read_text(encoding="utf-8")
    loaded = load_migration_sql()

    assert "CREATE TABLE IF NOT EXISTS event_retirement_cancellation_reports" in sql
    assert "CREATE TABLE IF NOT EXISTS event_retirement_cancellation_items" in sql
    assert "PRIMARY KEY (tenant_scope, cancellation_id)" in sql
    assert "PRIMARY KEY (tenant_scope, cancellation_id, delivery_id)" in sql
    assert "cancelled_count BETWEEN 0 AND item_limit" in sql
    assert "remaining_nonterminal_count_truncated" in sql
    assert "UNIQUE (delivery_id)" in sql
    assert "FOREIGN KEY (\n            tenant_scope,\n            cancellation_id," in sql
    assert "FOREIGN KEY (delivery_id)" in sql
    assert "item_limit BETWEEN 1 AND 1000" in sql
    assert "remaining_nonterminal_count >= 0" in sql
    assert "previous_state IN ('claimed', 'retry_wait')" in sql
    assert "terminal_state = 'dropped'" in sql
    assert sql.count("tenant_id IS NULL OR btrim(tenant_id) <> ''") == 2
    assert "char_length(authorization_evidence_ref) <= 512" in sql
    assert "ALTER TABLE" not in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert loaded.index("CREATE TABLE IF NOT EXISTS event_activity_payloads") < (
        loaded.index("CREATE TABLE IF NOT EXISTS event_retirement_cancellation_reports")
    )


def test_reader_repair_memory_commit_migration_is_atomic_and_append_only() -> None:
    sql = READER_REPAIR_MEMORY_COMMIT_MIGRATION.read_text(encoding="utf-8")
    loaded = load_migration_sql()

    assert "CREATE TABLE IF NOT EXISTS reader_repair_memory_commits" in sql
    assert "CREATE TABLE IF NOT EXISTS reader_repair_memory_commit_members" in sql
    assert "UNIQUE (run_id, terminal_effect_id)" in sql
    assert "UNIQUE (idempotency_key, object_type, object_id)" in sql
    assert "request_checksum ~ '^sha256:[0-9a-f]{64}$'" in sql
    assert "FOREIGN KEY (idempotency_key, namespace)" in sql
    assert "REFERENCES reader_repair_memory_versions" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "reader repair memory commit requires exactly one case member" in sql
    assert "reader repair memory commit receipts are append-only" in sql
    assert "reader repair memory versions are append-only" in sql
    assert "trg_reader_repair_memory_commits_immutable" in sql
    assert "trg_reader_repair_memory_commit_members_immutable" in sql
    assert "trg_reader_repair_memory_versions_immutable" in sql
    assert "ALTER TABLE" not in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert loaded.index(
        "CREATE TABLE IF NOT EXISTS event_retirement_cancellation_reports"
    ) < loaded.index("CREATE TABLE IF NOT EXISTS reader_repair_memory_commits")


def test_postgres_migration_directory_has_no_legacy_identity_cutover_script() -> None:
    assert not (MIGRATIONS_DIR / "000_graph_identity_cutover.sql").exists()


def test_postgres_sql_migrations_are_included_in_wheel_package_data() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    package_data = configuration["tool"]["setuptools"]["package-data"]
    assert package_data["infrastructure.storage.postgres"] == ["migrations/*.sql"]


def test_postgres_migration_loader_rejects_missing_sql_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(migrations_module, "_MIGRATIONS_DIR", tmp_path)

    with pytest.raises(FileNotFoundError, match="no SQL migrations"):
        migrations_module.load_migration_sql()


def test_postgres_migration_loader_rejects_empty_sql_files(monkeypatch, tmp_path) -> None:
    (tmp_path / "001_empty.sql").write_text("\n\n", encoding="utf-8")
    monkeypatch.setattr(migrations_module, "_MIGRATIONS_DIR", tmp_path)

    with pytest.raises(ValueError, match="are empty"):
        migrations_module.load_migration_sql()
