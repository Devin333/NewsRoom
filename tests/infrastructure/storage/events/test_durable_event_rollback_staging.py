from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from framework.events.canonical import checksum_for
from scripts import durable_event_rollback_staging as staging
from scripts import durable_event_rollback_stage_worker as worker


def test_worker_protocol_rejects_boolean_gate_claims() -> None:
    digest = "a" * 40
    payload = _worker_payload(digest)
    payload["facts"] = {"passed": True}

    with pytest.raises(staging.StagingRollbackError, match="gate_boolean"):
        staging._parse_worker_result(
            json.dumps(payload).encode("utf-8"),
            command="initialize",
            release_digest=digest,
        )


def test_worker_protocol_accepts_only_release_observations_and_facts() -> None:
    digest = "a" * 40
    payload = _worker_payload(digest)

    result = staging._parse_worker_result(
        json.dumps(payload).encode("utf-8"),
        command="initialize",
        release_digest=digest,
    )

    assert result["release_digest"] == digest
    assert result["facts"] == {"event_count": 20}


def test_worker_config_rejects_duplicate_fields_and_paths_outside_workspace(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.sqlite3"
    config = _worker_config(workspace)
    config["effect_database"] = str(outside)
    config_path = workspace / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(worker.StagingWorkerError, match="outside_workspace"):
        worker._load_config(config_path)

    duplicate_path = workspace / "duplicate.json"
    duplicate_path.write_text(
        '{"schema":"x","schema":"y"}',
        encoding="utf-8",
    )
    with pytest.raises(worker.StagingWorkerError, match="duplicate_field"):
        worker._load_config(duplicate_path)


def test_staging_workspace_must_be_new(tmp_path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()

    with pytest.raises(staging.StagingRollbackError, match="workspace_exists"):
        staging._prepare_workspace(existing)


def test_approval_record_binds_summary_artifacts_and_separated_identities() -> None:
    completed_at = datetime.now(UTC) - timedelta(minutes=1)
    technical = _technical_evidence(completed_at)
    supplied = {
        "operator_id": "operator-a",
        "approver_id": "approver-b",
        "approved_at": staging._utc_text(datetime.now(UTC)),
        "decision": "approved",
    }

    record = staging._expected_approval_record(technical, supplied)

    assert record["artifact_checksums"] == {
        "candidate_projection": "sha256:" + "3" * 64
    }
    assert record["evidence_summary_checksum"].startswith("sha256:")

    supplied["approver_id"] = supplied["operator_id"]
    with pytest.raises(staging.StagingRollbackError, match="separation"):
        staging._expected_approval_record(technical, supplied)


@pytest.mark.skipif(
    os.getenv("NEWSROOM_RUN_ROLLBACK_STAGING_INTEGRATION") != "1",
    reason="real cross-release rollback staging is an explicit PostgreSQL gate",
)
def test_real_postgres_cross_release_rollback_staging(tmp_path) -> None:
    admin_dsn = os.getenv(staging.ADMIN_DSN_ENV)
    if not admin_dsn:
        pytest.fail(f"{staging.ADMIN_DSN_ENV} is required")
    repository = Path(__file__).resolve().parents[4]
    candidate = _git(repository, "rev-parse", "HEAD")
    rollback = _git(repository, "rev-parse", "570f840c^{commit}")
    local_root = tmp_path / "local"
    local = __import__(
        "scripts.durable_event_rollback_drill",
        fromlist=["run_rollback_drill"],
    ).run_rollback_drill(
        workspace=local_root,
        drill_id=f"rollback-staging-{tmp_path.name}",
        candidate_release=candidate,
        rollback_release=rollback,
    )
    workspace = tmp_path / "staging"
    try:
        evidence = staging.run_staging_rollback(
            workspace=workspace,
            local_evidence_path=local_root / "rollback-evidence.json",
            rollback_release=rollback,
            event_count=8,
        )
        assert evidence["status"] == "awaiting_approval"
        verified = staging._verify_technical_evidence(
            workspace / "technical" / "technical-evidence.json"
        )
        assert verified["evidence_checksum"] == evidence["evidence_checksum"]
        assert verified["candidate_release_digest"] == candidate
        assert verified["rollback_release_digest"] == rollback
        assert local["overall_status"] == "incomplete"
    finally:
        for role in ("candidate", "rollback"):
            release_root = workspace / "releases" / role
            if release_root.exists():
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repository),
                        "worktree",
                        "remove",
                        "--force",
                        str(release_root),
                    ],
                    check=False,
                    capture_output=True,
                )
        if workspace.exists():
            config_path = workspace / "staging-config.json"
            if config_path.exists():
                config = json.loads(config_path.read_text(encoding="utf-8"))
                staging._drop_staging_database(admin_dsn, config["database_name"])


def _worker_payload(digest: str) -> dict[str, object]:
    modules = {
        name: {"path": f"{name.replace('.', '/')}.py", "checksum": "sha256:" + "1" * 64}
        for name in (
            "framework.events.canonical",
            "framework.events.runtime.publisher",
            "infrastructure.storage.events.postgres",
            "interfaces.services.event_projection_service",
        )
    }
    return {
        "schema": worker.WORKER_SCHEMA,
        "command": "initialize",
        "release_digest": digest,
        "process_id": 1234,
        "started_at": "2026-07-17T00:00:00Z",
        "completed_at": "2026-07-17T00:00:01Z",
        "release": {"commit": digest, "tree": "2" * 40, "modules": modules},
        "facts": {"event_count": 20},
    }


def _worker_config(workspace: Path) -> dict[str, object]:
    return {
        "schema": worker.CONFIG_SCHEMA,
        "drill_id": "rollback-stage-unit",
        "workspace": str(workspace),
        "database_name": "newsroom_rollback_staging_0123456789abcdef",
        "stream_id": "run:rollback-stage-unit",
        "run_id": "rollback-stage-unit",
        "tenant_id": "tenant-rollback-stage-unit",
        "occurred_at_base": "2026-07-17T00:00:00Z",
        "event_count": 8,
        "effect_database": str(workspace / "effect.sqlite3"),
        "candidate_projection_root": str(workspace / "candidate"),
        "rollback_projection_root": str(workspace / "rollback"),
    }


def _technical_evidence(completed_at: datetime) -> dict[str, object]:
    artifact = {
        "role": "candidate_projection",
        "path": "artifacts/candidate_projection.json",
        "size_bytes": 10,
        "checksum": "sha256:" + "3" * 64,
    }
    evidence = {
        "schema": staging.TECHNICAL_EVIDENCE_SCHEMA,
        "status": "awaiting_approval",
        "drill_id": "rollback-stage-approval",
        "drill_completed_at": staging._utc_text(completed_at),
        "candidate_release_digest": "a" * 40,
        "rollback_release_digest": "b" * 40,
        "postgresql": {"backend": "postgresql"},
        "external_effect": {"provider": "staging"},
        "orchestrator": {"run_ref": "artifact://rollback/run"},
        "external_gates": {"gate": True},
        "artifacts": [artifact],
    }
    evidence["evidence_checksum"] = checksum_for(evidence)
    return evidence


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()
