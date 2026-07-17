from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from framework.events.canonical import checksum_for
from scripts import durable_event_rollback_drill as rollback_drill
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


def test_worker_error_reason_allows_only_bounded_protocol_codes() -> None:
    payload = json.dumps(
        {
            "schema": worker.WORKER_SCHEMA,
            "command": "initialize",
            "error_type": "StagingWorkerError",
            "reason_class": "path_missing",
        }
    ).encode("utf-8")

    assert staging._worker_error_reason(payload, command="initialize") == "path_missing"
    assert (
        staging._worker_error_reason(
            b'{"reason_class":"postgresql://secret"}',
            command="initialize",
        )
        == "invalid_error_payload"
    )


def test_crash_handshake_reports_the_actual_worker_pid() -> None:
    digest = "a" * 40
    payload = {
        "schema": worker.CRASH_HANDSHAKE_SCHEMA,
        "command": "crash-effect",
        "release_digest": digest,
        "process_id": 4321,
        "started_at": "2026-07-17T00:00:00Z",
    }

    result = staging._parse_crash_handshake(
        json.dumps(payload).encode("utf-8"),
        release_digest=digest,
    )

    assert result["process_id"] == 4321


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


def test_windows_release_worktree_path_budget_fails_before_checkout(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(staging.os, "name", "nt")
    monkeypatch.setattr(staging, "_git", lambda *_args: "x" * 220)

    with pytest.raises(staging.StagingRollbackError, match="path_budget"):
        staging._validate_release_path_budget(
            tmp_path,
            tmp_path / "candidate",
        )


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
    short_root = Path(os.environ.get("TEMP") or tmp_path.parent) / (
        f"nr-rb-{uuid4().hex[:8]}"
    )
    local_root = short_root / "local"
    workspace = short_root / "staging"
    try:
        local = rollback_drill.run_rollback_drill(
            workspace=local_root,
            drill_id=f"rollback-staging-{tmp_path.name}",
            candidate_release=candidate,
            rollback_release=rollback,
        )
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

        approval_request = json.loads(
            (workspace / "technical" / "approval-request.json").read_text(
                encoding="utf-8"
            )
        )
        request_checksum = approval_request.pop("request_checksum")
        assert request_checksum == checksum_for(approval_request)
        assert approval_request == {
            "schema": staging.APPROVAL_REQUEST_SCHEMA,
            "status": "awaiting_approval",
            "drill_id": verified["drill_id"],
            "candidate_release_digest": verified["candidate_release_digest"],
            "rollback_release_digest": verified["rollback_release_digest"],
            "drill_completed_at": verified["drill_completed_at"],
            "decision_required": "approved",
            "evidence_summary_checksum": checksum_for(
                rollback_drill._approval_summary(
                    {
                        **verified,
                        "schema": rollback_drill.EXTERNAL_EVIDENCE_SCHEMA,
                    }
                )
            ),
            "artifact_checksums": {
                item["role"]: item["checksum"] for item in verified["artifacts"]
            },
        }
        approval_record = {
            "schema": rollback_drill.APPROVAL_RECORD_SCHEMA,
            "drill_id": approval_request["drill_id"],
            "candidate_release_digest": approval_request[
                "candidate_release_digest"
            ],
            "rollback_release_digest": approval_request[
                "rollback_release_digest"
            ],
            "drill_completed_at": approval_request["drill_completed_at"],
            "operator_id": "integration-operator",
            "approver_id": "integration-approver",
            "approved_at": staging._utc_text(datetime.now(UTC)),
            "decision": approval_request["decision_required"],
            "evidence_summary_checksum": approval_request[
                "evidence_summary_checksum"
            ],
            "artifact_checksums": approval_request["artifact_checksums"],
        }

        approval_root = short_root / "approval"
        approval_root.mkdir()
        approval_record_path = approval_root / "approval-record.json"
        approval_record_bytes = json.dumps(
            approval_record,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        approval_record_path.write_bytes(approval_record_bytes)
        approval_private_key = approval_root / "approval-private.pem"
        approval_public_key = approval_root / "approval-public.pem"
        rollback_drill.generate_signing_keypair(
            private_key_path=approval_private_key,
            public_key_path=approval_public_key,
        )
        approval_signature_path = approval_root / "approval-record.sig"
        approval_signature_path.write_text(
            base64.b64encode(
                rollback_drill._load_private_key(approval_private_key).sign(
                    approval_record_bytes
                )
            ).decode("ascii"),
            encoding="ascii",
        )
        finalized = staging.finalize_external_evidence(
            technical_evidence_path=(
                workspace / "technical" / "technical-evidence.json"
            ),
            approval_record_path=approval_record_path,
            approval_signature_path=approval_signature_path,
            trusted_approval_public_key=approval_public_key,
            output_path=short_root / "external" / "external-evidence.json",
        )
        assert finalized["status"] == "passed"
        assert finalized["approval"]["operator_id"] == "integration-operator"
    finally:
        _strict_cleanup_staging_run(
            repository=repository,
            short_root=short_root,
            workspace=workspace,
            admin_dsn=admin_dsn,
        )


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


def _strict_cleanup_staging_run(
    *,
    repository: Path,
    short_root: Path,
    workspace: Path,
    admin_dsn: str,
) -> None:
    release_roots = tuple(
        (workspace / "releases" / role).resolve()
        for role in ("candidate", "rollback")
    )
    registered = _registered_worktree_roots(repository)
    for release_root in release_roots:
        if release_root in registered:
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
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
    assert not set(release_roots) & _registered_worktree_roots(repository)

    config_path = workspace / "staging-config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        database_name = str(config["database_name"])
        staging._drop_staging_database(admin_dsn, database_name)
        assert not _postgres_database_exists(admin_dsn, database_name)

    if short_root.exists():
        shutil.rmtree(short_root)
    assert not short_root.exists()


def _registered_worktree_roots(repository: Path) -> set[Path]:
    return {
        Path(line.removeprefix("worktree ")).resolve()
        for line in _git(repository, "worktree", "list", "--porcelain").splitlines()
        if line.startswith("worktree ")
    }


def _postgres_database_exists(admin_dsn: str, database_name: str) -> bool:
    import psycopg

    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database_name,),
            )
            return cursor.fetchone() is not None
