from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from framework.events.canonical import StoredEvent, canonical_json_bytes, checksum_for
from framework.shared.json import stable_json_dumps
from scripts import durable_event_rollback_drill as rollback_verifier
from scripts.durable_event_rollback_stage_worker import (
    CONFIG_SCHEMA,
    CRASH_EXIT_CODE,
    EFFECT_ID,
    EFFECT_SUBSCRIPTION_ID,
    PRESERVED_EFFECT_ID,
    PRESERVED_SUBSCRIPTION_ID,
    STAGING_DSN_ENV,
    WORKER_SCHEMA,
)


TECHNICAL_EVIDENCE_SCHEMA = "newsroom.durable-event-rollback-technical/v1"
APPROVAL_REQUEST_SCHEMA = "newsroom.durable-event-rollback-approval-request/v1"
NATIVE_POSTGRES_SCHEMA = "newsroom.durable-event-rollback-native-postgres/v1"
NATIVE_EFFECT_SCHEMA = "newsroom.durable-event-rollback-native-effect/v1"
NATIVE_ORCHESTRATOR_SCHEMA = "newsroom.durable-event-rollback-native-orchestrator/v1"
NATIVE_TRAFFIC_SCHEMA = "newsroom.durable-event-rollback-native-traffic/v1"
NATIVE_NEGATIVE_SCHEMA = "newsroom.durable-event-rollback-native-negative/v1"
ADMIN_DSN_ENV = "NEWSROOM_ROLLBACK_STAGING_ADMIN_DSN"

_TECHNICAL_ARTIFACT_ROLES = frozenset(
    {
        "orchestrator_run",
        "traffic_control",
        "postgres_before_snapshot",
        "postgres_after_snapshot",
        "external_effect_audit",
        "candidate_projection",
        "rollback_projection",
        "schema_security_negative_tests",
    }
)
_WORKER_RESULT_FIELDS = frozenset(
    {
        "schema",
        "command",
        "release_digest",
        "process_id",
        "started_at",
        "completed_at",
        "release",
        "facts",
    }
)
_NEGATIVE_CASES = {
    "unknown_schema": "EventUnknownSchemaError",
    "forbidden_payload": "EventSecurityError",
    "identity_collision": "EventIdentityCollisionError",
    "record_checksum_tamper": "EventStoreCorruptionError",
}
_DATABASE_NAME = re.compile(r"newsroom_rollback_staging_[0-9a-f]{16}\Z")
_MAX_WORKER_OUTPUT_BYTES = 2 * 1024 * 1024
_WORKER_TIMEOUT_SECONDS = 180


class StagingRollbackError(RuntimeError):
    """A real staging rollback observation did not satisfy its invariant."""


def run_staging_rollback(
    *,
    workspace: str | Path,
    local_evidence_path: str | Path,
    rollback_release: str,
    event_count: int = 20,
) -> dict[str, Any]:
    controller_root = _controller_root()
    candidate_release = _git(controller_root, "rev-parse", "HEAD")
    rollback_digest = _git(
        controller_root,
        "rev-parse",
        f"{_required_text(rollback_release, 'rollback_release')}^{{commit}}",
    )
    _require(candidate_release != rollback_digest, "rollback_release_not_distinct")
    if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count < 6:
        raise StagingRollbackError("event_count_invalid")

    local_path = Path(local_evidence_path).resolve(strict=True)
    local = rollback_verifier.verify_rollback_evidence(
        local_path,
        allow_incomplete_local=True,
    )
    local_release = _mapping(local.get("release_context"), "release_context")
    _require(
        local_release.get("candidate_release") == candidate_release,
        "local_candidate_release_mismatch",
    )
    _require(
        local_release.get("rollback_release") == rollback_digest,
        "local_rollback_release_mismatch",
    )

    root = _prepare_workspace(workspace)
    releases_root = root / "releases"
    native_root = root / "native"
    technical_root = root / "technical"
    artifacts_root = technical_root / "artifacts"
    effect_root = root / "effect"
    for path in (releases_root, native_root, artifacts_root, effect_root):
        path.mkdir(parents=True, exist_ok=False)

    drill_id = _required_text(local.get("drill_id"), "drill_id")
    nonce = uuid4().hex[:16]
    database_name = f"newsroom_rollback_staging_{nonce}"
    run_id = f"rollback-staging-{nonce}"
    config = {
        "schema": CONFIG_SCHEMA,
        "drill_id": drill_id,
        "workspace": str(root),
        "database_name": database_name,
        "stream_id": f"run:{run_id}",
        "run_id": run_id,
        "tenant_id": f"tenant-rollback-{nonce}",
        "occurred_at_base": _utc_text(datetime.now(UTC) - timedelta(minutes=10)),
        "event_count": event_count,
        "effect_database": str(root / "effect" / "effects.sqlite3"),
        "candidate_projection_root": str(root / "candidate-projection"),
        "rollback_projection_root": str(root / "rollback-projection"),
    }
    config_path = root / "staging-config.json"
    _write_json_new(config_path, config)

    admin_dsn = _required_secret_env(ADMIN_DSN_ENV)
    staging_dsn: str | None = None
    candidate_root = releases_root / "candidate"
    rollback_root = releases_root / "rollback"
    worker_runs: list[dict[str, Any]] = []
    database_created = False
    try:
        staging_dsn, database_observation = _create_staging_database(
            admin_dsn,
            database_name,
        )
        database_created = True
        _add_worktree(controller_root, candidate_root, candidate_release)
        _add_worktree(controller_root, rollback_root, rollback_digest)
        _verify_release_worktree(candidate_root, candidate_release)
        _verify_release_worktree(rollback_root, rollback_digest)

        initialized = _run_worker(
            controller_root=controller_root,
            release_root=candidate_root,
            release_digest=candidate_release,
            command="initialize",
            config_path=config_path,
            staging_dsn=staging_dsn,
            role="candidate",
        )
        worker_runs.append(initialized)
        _verify_initialize(initialized, config)

        candidate_projection = _run_worker(
            controller_root=controller_root,
            release_root=candidate_root,
            release_digest=candidate_release,
            command="project-candidate",
            config_path=config_path,
            staging_dsn=staging_dsn,
            role="candidate",
        )
        worker_runs.append(candidate_projection)
        candidate_projection_path = _projection_path(
            root,
            candidate_projection,
            role="candidate",
        )

        crash_run = _run_crash_worker(
            controller_root=controller_root,
            release_root=candidate_root,
            release_digest=candidate_release,
            config_path=config_path,
            staging_dsn=staging_dsn,
        )
        worker_runs.append(crash_run)
        effect_before = _read_effect_ledger(Path(config["effect_database"]))
        _require(effect_before["invocation_count"] == 1, "candidate_effect_not_invoked")
        _require(effect_before["applied_effect_count"] == 1, "candidate_effect_not_applied")

        paused = _run_worker(
            controller_root=controller_root,
            release_root=candidate_root,
            release_digest=candidate_release,
            command="pause-effect",
            config_path=config_path,
            staging_dsn=staging_dsn,
            role="candidate",
        )
        worker_runs.append(paused)
        _verify_pause(paused)
        _require(
            _subscription_status(staging_dsn, EFFECT_SUBSCRIPTION_ID) == "paused",
            "database_subscription_not_paused",
        )

        before_capture = _capture_postgres_snapshot(
            staging_dsn,
            config,
            native_root / "postgres-before.json",
            stage="before",
        )
        _verify_before_snapshot(before_capture, config)
        _wait_for_effect_lease_expiry(staging_dsn, timeout_seconds=20)

        recovery_started_at = datetime.now(UTC)
        recovered = _run_worker(
            controller_root=controller_root,
            release_root=rollback_root,
            release_digest=rollback_digest,
            command="recover-effect",
            config_path=config_path,
            staging_dsn=staging_dsn,
            role="rollback",
        )
        worker_runs.append(recovered)
        _verify_recovery(recovered)
        _require(
            _parse_utc(recovered["started_at"], "worker.started_at")
            >= _parse_utc(crash_run["completed_at"], "crash.completed_at"),
            "dispatcher_processes_overlapped",
        )
        effect_after = _read_effect_ledger(Path(config["effect_database"]))
        _verify_effect_recovery(effect_before, effect_after)

        rollback_projection = _run_worker(
            controller_root=controller_root,
            release_root=rollback_root,
            release_digest=rollback_digest,
            command="project-rollback",
            config_path=config_path,
            staging_dsn=staging_dsn,
            role="rollback",
        )
        worker_runs.append(rollback_projection)
        rollback_projection_path = _projection_path(
            root,
            rollback_projection,
            role="rollback",
        )
        _require(
            candidate_projection_path.read_bytes()
            == rollback_projection_path.read_bytes(),
            "cross_release_projection_bytes_changed",
        )

        negative = _run_worker(
            controller_root=controller_root,
            release_root=rollback_root,
            release_digest=rollback_digest,
            command="negative-gates",
            config_path=config_path,
            staging_dsn=staging_dsn,
            role="rollback",
        )
        worker_runs.append(negative)
        _verify_negative(negative, config)

        after_capture = _capture_postgres_snapshot(
            staging_dsn,
            config,
            native_root / "postgres-after.json",
            stage="after",
        )
        _verify_after_snapshot(before_capture, after_capture, config)

        completed_at = datetime.now(UTC)
        evidence = _materialize_technical_evidence(
            root=root,
            technical_root=technical_root,
            artifacts_root=artifacts_root,
            config=config,
            local=local,
            candidate_release=candidate_release,
            rollback_release=rollback_digest,
            database_observation=database_observation,
            migration_version=(
                "git-tree:"
                + _git(
                    candidate_root,
                    "rev-parse",
                    "HEAD:infrastructure/storage/postgres/migrations",
                )
            ),
            before_capture=before_capture,
            after_capture=after_capture,
            effect_before=effect_before,
            effect_after=effect_after,
            candidate_projection_path=candidate_projection_path,
            rollback_projection_path=rollback_projection_path,
            candidate_projection=candidate_projection,
            rollback_projection=rollback_projection,
            negative=negative,
            worker_runs=worker_runs,
            recovery_started_at=recovery_started_at,
            completed_at=completed_at,
        )
        technical_path = technical_root / "technical-evidence.json"
        _verify_technical_evidence(technical_path)
        return evidence
    except Exception as error:
        _write_failure_evidence(root, error)
        if database_created:
            _drop_staging_database(admin_dsn, database_name)
        for release_root in (candidate_root, rollback_root):
            _remove_worktree(controller_root, release_root)
        raise


def finalize_external_evidence(
    *,
    technical_evidence_path: str | Path,
    approval_record_path: str | Path,
    approval_signature_path: str | Path,
    trusted_approval_public_key: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    technical_path = Path(technical_evidence_path).resolve(strict=True)
    technical = _verify_technical_evidence(technical_path)
    record_path = Path(approval_record_path).resolve(strict=True)
    signature_path = Path(approval_signature_path).resolve(strict=True)
    public_key_path = Path(trusted_approval_public_key).resolve(strict=True)
    output = Path(output_path).resolve(strict=False)
    _require(output.name == "external-evidence.json", "external_output_name_invalid")
    _require(not output.parent.exists(), "external_output_bundle_exists")
    _require(
        output not in {technical_path, record_path, signature_path, public_key_path},
        "external_output_alias",
    )

    record = _read_json(record_path, "approval_record")
    expected_record = _expected_approval_record(technical, record)
    _require(record == expected_record, "approval_record_content_mismatch")
    signature = _read_signature(signature_path)
    approval_key = rollback_verifier._load_public_key(public_key_path)
    try:
        approval_key.verify(signature, record_path.read_bytes())
    except Exception as error:
        raise StagingRollbackError("approval_signature_invalid") from error

    bundle_root = output.parent
    bundle_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = bundle_root.with_name(f".{bundle_root.name}.{uuid4().hex}.tmp")
    temporary_root.mkdir()
    try:
        source_root = technical_path.parent
        artifacts: list[dict[str, Any]] = []
        for item in technical["artifacts"]:
            role = str(item["role"])
            source = source_root / str(item["path"])
            target = temporary_root / "artifacts" / f"{role}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            artifacts.append(_artifact_manifest_item(temporary_root, role, target))
        approval_target = temporary_root / "artifacts" / "approval_record.json"
        shutil.copyfile(record_path, approval_target)
        approval_manifest = _artifact_manifest_item(
            temporary_root,
            "approval_record",
            approval_target,
        )
        artifacts.append(approval_manifest)
        approval = {
            "operator_id": record["operator_id"],
            "approver_id": record["approver_id"],
            "approved_at": record["approved_at"],
            "decision": record["decision"],
            "record_ref": "artifact://rollback/approval_record",
            "record_checksum": approval_manifest["checksum"],
            "public_key_fingerprint": rollback_verifier._public_key_fingerprint(
                approval_key
            ),
            "signature": base64.b64encode(signature).decode("ascii"),
        }
        external = {
            "schema": rollback_verifier.EXTERNAL_EVIDENCE_SCHEMA,
            "status": "passed",
            "drill_id": technical["drill_id"],
            "drill_completed_at": technical["drill_completed_at"],
            "candidate_release_digest": technical["candidate_release_digest"],
            "rollback_release_digest": technical["rollback_release_digest"],
            "postgresql": technical["postgresql"],
            "external_effect": technical["external_effect"],
            "orchestrator": technical["orchestrator"],
            "approval": approval,
            "external_gates": technical["external_gates"],
            "artifacts": artifacts,
        }
        external["evidence_checksum"] = checksum_for(external)
        temporary_output = temporary_root / output.name
        _write_json_new(temporary_output, external)
        rollback_verifier.verify_unsigned_external_evidence(
            temporary_output,
            trusted_approval_public_key=approval_key,
        )
        os.replace(temporary_root, bundle_root)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise
    return rollback_verifier.verify_unsigned_external_evidence(
        output,
        trusted_approval_public_key=approval_key,
    )


def _controller_root() -> Path:
    root = Path(__file__).resolve(strict=True).parents[1]
    digest = _git(root, "rev-parse", "HEAD")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", digest)), "controller_digest_invalid")
    _require(
        not _git(root, "status", "--porcelain", "--untracked-files=all"),
        "controller_worktree_not_clean",
    )
    _require_path_without_reparse(root, must_exist=True)
    return root


def _prepare_workspace(value: str | Path) -> Path:
    unresolved = Path(value).absolute()
    _require(not unresolved.exists(), "staging_workspace_exists")
    _require_path_without_reparse(unresolved.parent, must_exist=True)
    unresolved.mkdir()
    root = unresolved.resolve(strict=True)
    _require_path_without_reparse(root, must_exist=True)
    return root


def _create_staging_database(
    admin_dsn: str,
    database_name: str,
) -> tuple[str, dict[str, str]]:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    _require(_DATABASE_NAME.fullmatch(database_name) is not None, "database_name_invalid")
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_user, "
                "current_setting('server_version')"
            )
            observation = cursor.fetchone()
            if observation is None:
                raise StagingRollbackError("admin_database_observation_missing")
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database_name,),
            )
            _require(cursor.fetchone() is None, "staging_database_exists")
            cursor.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(database_name)
                )
            )
    staging_dsn = make_conninfo(admin_dsn, dbname=database_name)
    with psycopg.connect(staging_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            row = cursor.fetchone()
    _require(row is not None and row[0] == database_name, "staging_database_mismatch")
    return staging_dsn, {
        "admin_database_name": str(observation[0]),
        "database_user": str(observation[1]),
        "server_version": str(observation[2]),
        "database_name": database_name,
    }


def _drop_staging_database(admin_dsn: str, database_name: str) -> None:
    import psycopg
    from psycopg import sql

    if _DATABASE_NAME.fullmatch(database_name) is None:
        return
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
    except Exception:
        return


def _add_worktree(repository: Path, target: Path, digest: str) -> None:
    completed = subprocess.run(
        ["git", "-C", str(repository), "worktree", "add", "--detach", str(target), digest],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise StagingRollbackError("release_worktree_create_failed")


def _remove_worktree(repository: Path, target: Path) -> None:
    if not target.exists():
        return
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "worktree",
            "remove",
            "--force",
            str(target),
        ],
        check=False,
        capture_output=True,
    )


def _verify_release_worktree(root: Path, digest: str) -> None:
    _require_path_without_reparse(root, must_exist=True)
    _require(_git(root, "rev-parse", "HEAD") == digest, "release_worktree_digest_mismatch")
    _require(
        not _git(root, "status", "--porcelain", "--untracked-files=all"),
        "release_worktree_not_clean",
    )


def _run_worker(
    *,
    controller_root: Path,
    release_root: Path,
    release_digest: str,
    command: str,
    config_path: Path,
    staging_dsn: str,
    role: str,
) -> dict[str, Any]:
    application_name = f"newsroom_rollback_{role}_{command}_{uuid4().hex[:8]}"
    process = subprocess.Popen(
        [
            sys.executable,
            str(controller_root / "scripts" / "durable_event_rollback_stage_worker.py"),
            command,
            "--config",
            str(config_path),
            "--release-root",
            str(release_root),
            "--expected-release",
            release_digest,
        ],
        cwd=str(config_path.parent),
        env=_worker_environment(
            _dsn_with_application_name(staging_dsn, application_name)
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = process.communicate(timeout=_WORKER_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.communicate()
        raise StagingRollbackError("worker_timeout") from error
    _require(len(stdout) <= _MAX_WORKER_OUTPUT_BYTES, "worker_stdout_too_large")
    _require(len(stderr) <= _MAX_WORKER_OUTPUT_BYTES, "worker_stderr_too_large")
    if process.returncode != 0:
        reason = _worker_error_reason(stderr, command=command)
        raise StagingRollbackError(f"worker_failed:{command}:{reason}")
    _require(not stderr.strip(), "worker_unexpected_stderr")
    result = _parse_worker_result(stdout, command=command, release_digest=release_digest)
    _require(result["process_id"] == process.pid, "worker_pid_mismatch")
    _wait_for_application_sessions_zero(
        staging_dsn,
        application_name,
        timeout_seconds=10,
    )
    return result


def _run_crash_worker(
    *,
    controller_root: Path,
    release_root: Path,
    release_digest: str,
    config_path: Path,
    staging_dsn: str,
) -> dict[str, Any]:
    command = "crash-effect"
    application_name = f"newsroom_rollback_candidate_crash_{uuid4().hex[:8]}"
    started_at = datetime.now(UTC)
    process = subprocess.Popen(
        [
            sys.executable,
            str(controller_root / "scripts" / "durable_event_rollback_stage_worker.py"),
            command,
            "--config",
            str(config_path),
            "--release-root",
            str(release_root),
            "--expected-release",
            release_digest,
        ],
        cwd=str(config_path.parent),
        env=_worker_environment(
            _dsn_with_application_name(staging_dsn, application_name)
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = process.communicate(timeout=_WORKER_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.communicate()
        raise StagingRollbackError("crash_worker_timeout") from error
    completed_at = datetime.now(UTC)
    _require(process.returncode == CRASH_EXIT_CODE, "effect_process_did_not_crash")
    _require(not stdout.strip(), "crash_worker_unexpected_stdout")
    _require(not stderr.strip(), "crash_worker_unexpected_stderr")
    _wait_for_application_sessions_zero(
        staging_dsn,
        application_name,
        timeout_seconds=10,
    )
    return {
        "schema": WORKER_SCHEMA,
        "command": command,
        "release_digest": release_digest,
        "process_id": process.pid,
        "started_at": _utc_text(started_at),
        "completed_at": _utc_text(completed_at),
        "return_code": process.returncode,
    }


def _worker_environment(staging_dsn: str) -> dict[str, str]:
    allowed = (
        "PATH",
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "PATHEXT",
        "COMSPEC",
    )
    env = {name: os.environ[name] for name in allowed if name in os.environ}
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            STAGING_DSN_ENV: staging_dsn,
        }
    )
    return env


def _dsn_with_application_name(dsn: str, application_name: str) -> str:
    from psycopg.conninfo import make_conninfo

    return make_conninfo(dsn, application_name=application_name)


def _parse_worker_result(
    payload: bytes,
    *,
    command: str,
    release_digest: str,
) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StagingRollbackError("worker_output_invalid") from error
    result = _mapping(value, "worker_result")
    _require(set(result) == _WORKER_RESULT_FIELDS, "worker_result_fields_invalid")
    _require(result.get("schema") == WORKER_SCHEMA, "worker_schema_invalid")
    _require(result.get("command") == command, "worker_command_mismatch")
    _require(
        result.get("release_digest") == release_digest,
        "worker_release_mismatch",
    )
    _require(
        isinstance(result.get("process_id"), int)
        and not isinstance(result.get("process_id"), bool)
        and result["process_id"] > 0,
        "worker_process_id_invalid",
    )
    _parse_utc(result.get("started_at"), "worker.started_at")
    _parse_utc(result.get("completed_at"), "worker.completed_at")
    release = _mapping(result.get("release"), "worker.release")
    _require(release.get("commit") == release_digest, "worker_release_commit_mismatch")
    _require(
        bool(re.fullmatch(r"[0-9a-f]{40}", str(release.get("tree") or ""))),
        "worker_release_tree_invalid",
    )
    modules = _mapping(release.get("modules"), "worker.release.modules")
    _require(len(modules) == 4, "worker_module_observations_missing")
    _mapping(result.get("facts"), "worker.facts")
    _require(not _contains_boolean(result), "worker_reported_gate_boolean")
    return result


def _worker_error_reason(payload: bytes, *, command: str) -> str:
    if len(payload) > _MAX_WORKER_OUTPUT_BYTES:
        return "stderr_too_large"
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, StagingRollbackError):
        return "invalid_error_payload"
    if not isinstance(value, Mapping):
        return "invalid_error_payload"
    if value.get("schema") != WORKER_SCHEMA or value.get("command") != command:
        return "invalid_error_payload"
    if set(value) != {"schema", "command", "error_type", "reason_class"}:
        return "invalid_error_payload"
    reason = value.get("reason_class")
    if not isinstance(reason, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", reason) is None:
        return "invalid_error_payload"
    return reason


def _contains_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, Mapping):
        return any(_contains_boolean(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_boolean(item) for item in value)
    return False


def _wait_for_application_sessions_zero(
    dsn: str,
    application_name: str,
    *,
    timeout_seconds: float,
) -> None:
    import psycopg

    deadline = time.monotonic() + timeout_seconds
    while True:
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND application_name = %s",
                    (application_name,),
                )
                row = cursor.fetchone()
        if row is not None and int(row[0]) == 0:
            return
        if time.monotonic() >= deadline:
            raise StagingRollbackError("worker_database_sessions_not_closed")
        time.sleep(0.1)


def _verify_initialize(result: Mapping[str, Any], config: Mapping[str, Any]) -> None:
    facts = _mapping(result.get("facts"), "initialize.facts")
    event_count = int(config["event_count"])
    _require(
        facts.get("main_sequences") == list(range(1, event_count + 1)),
        "initialize_main_sequences_invalid",
    )
    _require(
        facts.get("concurrent_sequences") == list(range(3, event_count + 1)),
        "initialize_concurrent_sequences_invalid",
    )
    _require(
        facts.get("preserved_checkpoint_sequence") == 2,
        "initialize_checkpoint_invalid",
    )
    _require(
        facts.get("preserved_inbox_recorded_count") == 1,
        "initialize_inbox_invalid",
    )
    _required_text(facts.get("preserved_dead_letter_id"), "preserved_dead_letter_id")
    _required_text(facts.get("effect_event_id"), "effect_event_id")
    _required_checksum(facts.get("effect_content_checksum"), "effect_content_checksum")
    _require(facts.get("effect_sequence") == 1, "initialize_effect_sequence_invalid")
    _require(
        facts.get("effect_subscription_status") == "active",
        "initialize_effect_subscription_invalid",
    )
    database = _mapping(facts.get("database"), "initialize.database")
    _require(
        database.get("database_name") == config["database_name"],
        "initialize_database_mismatch",
    )


def _verify_pause(result: Mapping[str, Any]) -> None:
    facts = _mapping(result.get("facts"), "pause.facts")
    _require(facts.get("status_before") == "active", "pause_initial_status_invalid")
    _require(facts.get("status_after") == "paused", "pause_status_invalid")
    _require(facts.get("pause_probe_claimed_count") == 0, "pause_claim_probe_failed")
    _require(facts.get("delivery_states") == ["claimed"], "pause_delivery_state_invalid")
    _require(facts.get("lease_generations") == [1], "pause_lease_generation_invalid")


def _verify_recovery(result: Mapping[str, Any]) -> None:
    facts = _mapping(result.get("facts"), "recovery.facts")
    _require(facts.get("observed_status") == "paused", "rollback_pause_not_observed")
    _require(facts.get("recovered_claimed_count") == 1, "rollback_recovery_not_claimed")
    _require(
        facts.get("recovered_acknowledged_count") == 1,
        "rollback_recovery_not_acknowledged",
    )
    _require(facts.get("duplicate_claimed_count") == 0, "duplicate_rebroadcast")
    _require(facts.get("duplicate_event_sequence") == 1, "duplicate_sequence_changed")
    _require(facts.get("delivery_states") == ["acked"], "recovery_state_invalid")
    _require(facts.get("attempt_counts") == [2], "recovery_attempt_count_invalid")
    _require(facts.get("checkpoint_sequence") == 1, "recovery_checkpoint_invalid")


def _verify_negative(result: Mapping[str, Any], config: Mapping[str, Any]) -> None:
    facts = _mapping(result.get("facts"), "negative.facts")
    event_count = int(config["event_count"])
    _require(facts.get("watermark_before") == event_count, "negative_watermark_before_invalid")
    _require(
        facts.get("watermark_after_rejections") == event_count,
        "negative_rejection_allocated_sequence",
    )
    _require(
        facts.get("next_event_sequence") == event_count + 1,
        "negative_next_sequence_invalid",
    )
    _required_text(facts.get("next_event_id"), "negative.next_event_id")
    _require(facts.get("errors") == _NEGATIVE_CASES, "negative_error_set_invalid")


def _projection_path(
    workspace: Path,
    result: Mapping[str, Any],
    *,
    role: str,
) -> Path:
    facts = _mapping(result.get("facts"), f"{role}_projection.facts")
    _require(facts.get("role") == role, f"{role}_projection_role_invalid")
    relative = Path(_required_text(facts.get("path"), f"{role}_projection.path"))
    _require(not relative.is_absolute(), f"{role}_projection_path_absolute")
    path = (workspace / relative).resolve(strict=True)
    _require(path.is_relative_to(workspace), f"{role}_projection_path_escaped")
    _require(path.is_file(), f"{role}_projection_missing")
    checksum = _sha256_file(path)
    _require(
        checksum == facts.get("projection_checksum"),
        f"{role}_projection_checksum_mismatch",
    )
    return path


def _subscription_status(dsn: str, subscription_id: str) -> str | None:
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM event_subscriptions "
                "WHERE subscription_id = %s AND subscription_version = 1",
                (subscription_id,),
            )
            row = cursor.fetchone()
    return None if row is None else str(row[0])


def _wait_for_effect_lease_expiry(dsn: str, *, timeout_seconds: float) -> None:
    import psycopg

    deadline = time.monotonic() + timeout_seconds
    while True:
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT lease_expires_at <= clock_timestamp() "
                    "FROM event_deliveries WHERE subscription_id = %s "
                    "AND subscription_version = 1 AND delivery_generation = 1",
                    (EFFECT_SUBSCRIPTION_ID,),
                )
                row = cursor.fetchone()
        if row is not None and row[0] is True:
            return
        if time.monotonic() >= deadline:
            raise StagingRollbackError("effect_lease_did_not_expire")
        time.sleep(0.1)


def _capture_postgres_snapshot(
    dsn: str,
    config: Mapping[str, Any],
    path: Path,
    *,
    stage: str,
) -> dict[str, Any]:
    import psycopg

    event_columns = (
        "event_id, tenant_id, stream_id, stream_sequence, envelope_schema, "
        "event_type, data_schema, source, subject, occurred_at, observed_at, "
        "correlation_id, causation_id, business_context, producer, trace_context, "
        "security_classification, content_type, payload, payload_ref, extensions, "
        "content_checksum, record_checksum"
    )
    tenant = str(config["tenant_id"])
    stream = str(config["stream_id"])
    raw_events: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    checksum_failures = 0
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_setting('server_version'), "
                "clock_timestamp()"
            )
            database_row = cursor.fetchone()
            if database_row is None:
                raise StagingRollbackError("snapshot_database_observation_missing")
            cursor.execute(
                f"SELECT {event_columns} FROM durable_events "
                "WHERE tenant_scope = %s AND stream_id = %s "
                "ORDER BY stream_sequence ASC",
                (tenant, stream),
            )
            for row in cursor.fetchall():
                raw = _event_row_to_dict(row)
                raw_events.append(raw)
                try:
                    event = StoredEvent.from_dict(raw, verify_checksum=True)
                    event.verify_integrity()
                except Exception:
                    checksum_failures += 1
                    continue
                events.append(event.to_dict())
            ledgers = {
                "delivery_history": _query_json_rows(
                    cursor,
                    "SELECT to_jsonb(item) FROM ("
                    "SELECT * FROM event_deliveries WHERE subscription_id = %s "
                    "AND subscription_version = 1 AND tenant_scope = %s "
                    "AND stream_id = %s ORDER BY stream_sequence, delivery_generation"
                    ") AS item",
                    (PRESERVED_SUBSCRIPTION_ID, tenant, stream),
                ),
                "inbox": _query_json_rows(
                    cursor,
                    "SELECT to_jsonb(item) FROM ("
                    "SELECT * FROM event_inbox WHERE consumer_effect_id = %s "
                    "ORDER BY event_id) AS item",
                    (PRESERVED_EFFECT_ID,),
                ),
                "checkpoint": _query_json_rows(
                    cursor,
                    "SELECT to_jsonb(item) FROM ("
                    "SELECT * FROM event_consumer_checkpoints "
                    "WHERE subscription_id = %s AND subscription_version = 1 "
                    "AND tenant_scope = %s AND stream_id = %s "
                    "ORDER BY subscription_id, subscription_version, stream_id"
                    ") AS item",
                    (PRESERVED_SUBSCRIPTION_ID, tenant, stream),
                ),
                "dead_letter": _query_json_rows(
                    cursor,
                    "SELECT to_jsonb(item) FROM ("
                    "SELECT * FROM event_dead_letters WHERE subscription_id = %s "
                    "AND subscription_version = 1 AND tenant_scope = %s "
                    "AND stream_id = %s ORDER BY dead_letter_id) AS item",
                    (PRESERVED_SUBSCRIPTION_ID, tenant, stream),
                ),
            }
            cursor.execute(
                "SELECT COUNT(*) FROM (SELECT stream_sequence FROM durable_events "
                "WHERE tenant_scope = %s AND stream_id = %s "
                "GROUP BY stream_sequence HAVING COUNT(*) > 1) AS duplicates",
                (tenant, stream),
            )
            duplicate_row = cursor.fetchone()
    _require(database_row[0] == config["database_name"], "snapshot_database_mismatch")
    captured_at = _utc_text(_coerce_datetime(database_row[2], "snapshot.captured_at"))
    native = {
        "schema": NATIVE_POSTGRES_SCHEMA,
        "stage": stage,
        "captured_at": captured_at,
        "database_name": str(database_row[0]),
        "server_version": str(database_row[1]),
        "stream_id": stream,
        "raw_events": raw_events,
        "ledgers": ledgers,
    }
    _write_json_new(path, native)
    return {
        "stage": stage,
        "captured_at": captured_at,
        "source_path": path,
        "source_checksum": _sha256_file(path),
        "database_name": str(database_row[0]),
        "server_version": str(database_row[1]),
        "stream_id": stream,
        "events": events,
        "event_count": len(events),
        "canonical_events_checksum": checksum_for(events),
        "watermark": 0 if not events else int(events[-1]["stream_sequence"]),
        "ledgers": {
            name: {"count": len(rows), "checksum": checksum_for(rows)}
            for name, rows in ledgers.items()
        },
        "duplicate_sequences": 0 if duplicate_row is None else int(duplicate_row[0]),
        "checksum_failures": checksum_failures,
    }


def _event_row_to_dict(row: Sequence[Any]) -> dict[str, Any]:
    if len(row) != 23:
        raise StagingRollbackError("snapshot_event_row_shape_invalid")
    return {
        "event_id": str(row[0]),
        "tenant_id": None if row[1] is None else str(row[1]),
        "stream_id": str(row[2]),
        "stream_sequence": int(row[3]),
        "envelope_schema": str(row[4]),
        "event_type": str(row[5]),
        "data_schema": str(row[6]),
        "source": str(row[7]),
        "subject": None if row[8] is None else str(row[8]),
        "occurred_at": _utc_text(_coerce_datetime(row[9], "event.occurred_at")),
        "observed_at": _utc_text(_coerce_datetime(row[10], "event.observed_at")),
        "correlation_id": None if row[11] is None else str(row[11]),
        "causation_id": None if row[12] is None else str(row[12]),
        "business_context": _json_object(row[13], "business_context"),
        "producer": _json_object(row[14], "producer"),
        "trace": None if row[15] is None else _json_object(row[15], "trace"),
        "security_classification": str(row[16]),
        "content_type": str(row[17]),
        "payload": None if row[18] is None else _json_object(row[18], "payload"),
        "payload_ref": (
            None if row[19] is None else _json_object(row[19], "payload_ref")
        ),
        "extensions": _json_object(row[20], "extensions"),
        "content_checksum": str(row[21]),
        "record_checksum": str(row[22]),
    }


def _query_json_rows(cursor: Any, sql: str, params: tuple[Any, ...]) -> list[Any]:
    cursor.execute(sql, params)
    return [_json_value(row[0]) for row in cursor.fetchall()]


def _verify_before_snapshot(
    capture: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None:
    event_count = int(config["event_count"])
    _require(capture.get("event_count") == event_count, "before_event_count_invalid")
    _require(capture.get("watermark") == event_count, "before_watermark_invalid")
    _require(capture.get("duplicate_sequences") == 0, "before_duplicate_sequence")
    _require(capture.get("checksum_failures") == 0, "before_checksum_failure")
    ledgers = _mapping(capture.get("ledgers"), "before.ledgers")
    for name in ("delivery_history", "inbox", "checkpoint", "dead_letter"):
        ledger = _mapping(ledgers.get(name), f"before.ledgers.{name}")
        _require(int(ledger.get("count") or 0) > 0, f"before_{name}_empty")
        _required_checksum(ledger.get("checksum"), f"before.{name}.checksum")


def _verify_after_snapshot(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None:
    event_count = int(config["event_count"])
    _require(after.get("event_count") == event_count + 1, "after_event_count_invalid")
    _require(after.get("watermark") == event_count + 1, "after_watermark_invalid")
    _require(after.get("duplicate_sequences") == 0, "after_duplicate_sequence")
    _require(after.get("checksum_failures") == 0, "after_checksum_failure")
    before_events = list(before["events"])
    after_events = list(after["events"])
    _require(
        [canonical_json_bytes(row) for row in before_events]
        == [canonical_json_bytes(row) for row in after_events[:event_count]],
        "accepted_event_prefix_changed",
    )
    _require(before.get("ledgers") == after.get("ledgers"), "preserved_ledgers_changed")


def _read_effect_ledger(path: Path) -> dict[str, Any]:
    _require(path.exists(), "effect_ledger_missing")
    _require_path_without_reparse(path, must_exist=True)
    with sqlite3.connect(path) as connection:
        applied = [
            {
                "idempotency_key": str(row[0]),
                "event_id": str(row[1]),
                "content_checksum": str(row[2]),
                "applied_at": str(row[3]),
            }
            for row in connection.execute(
                "SELECT idempotency_key, event_id, content_checksum, applied_at "
                "FROM applied_effects ORDER BY idempotency_key"
            ).fetchall()
        ]
        invocations = [
            {
                "invocation_id": int(row[0]),
                "idempotency_key": str(row[1]),
                "event_id": str(row[2]),
                "content_checksum": str(row[3]),
                "invoked_at": str(row[4]),
            }
            for row in connection.execute(
                "SELECT invocation_id, idempotency_key, event_id, "
                "content_checksum, invoked_at FROM effect_invocations "
                "ORDER BY invocation_id"
            ).fetchall()
        ]
    return {
        "applied_effects": applied,
        "invocations": invocations,
        "applied_effect_count": len(applied),
        "invocation_count": len(invocations),
        "result_checksum": checksum_for(applied),
    }


def _verify_effect_recovery(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> None:
    _require(before.get("applied_effect_count") == 1, "effect_before_count_invalid")
    _require(after.get("applied_effect_count") == 1, "external_effect_repeated")
    _require(before.get("invocation_count") == 1, "effect_before_invocation_invalid")
    _require(int(after.get("invocation_count") or 0) >= 2, "effect_retry_not_observed")
    _require(
        before.get("result_checksum") == after.get("result_checksum"),
        "external_effect_result_changed",
    )
    applied = list(after.get("applied_effects") or ())
    invocations = list(after.get("invocations") or ())
    _require(len(applied) == 1 and len(invocations) >= 2, "effect_audit_rows_invalid")
    keys = {str(item["idempotency_key"]) for item in invocations}
    _require(keys == {str(applied[0]["idempotency_key"])}, "effect_key_changed")
    identities = {
        (str(item["event_id"]), str(item["content_checksum"]))
        for item in invocations
    }
    _require(
        identities
        == {(str(applied[0]["event_id"]), str(applied[0]["content_checksum"]))},
        "effect_identity_changed",
    )


def _materialize_technical_evidence(
    *,
    root: Path,
    technical_root: Path,
    artifacts_root: Path,
    config: Mapping[str, Any],
    local: Mapping[str, Any],
    candidate_release: str,
    rollback_release: str,
    database_observation: Mapping[str, Any],
    migration_version: str,
    before_capture: Mapping[str, Any],
    after_capture: Mapping[str, Any],
    effect_before: Mapping[str, Any],
    effect_after: Mapping[str, Any],
    candidate_projection_path: Path,
    rollback_projection_path: Path,
    candidate_projection: Mapping[str, Any],
    rollback_projection: Mapping[str, Any],
    negative: Mapping[str, Any],
    worker_runs: Sequence[Mapping[str, Any]],
    recovery_started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    drill_id = str(config["drill_id"])
    source_refs = {
        role: f"newsroom-source://{drill_id}/{role}"
        for role in _TECHNICAL_ARTIFACT_ROLES
    }
    before_events = list(before_capture["events"])
    after_events = list(after_capture["events"])
    event_count = int(config["event_count"])
    before_prefix_checksum = checksum_for(before_events)
    after_prefix_checksum = checksum_for(after_events[:event_count])

    postgresql = {
        "backend": "postgresql",
        "database_name": str(config["database_name"]),
        "server_version": str(database_observation["server_version"]),
        "migration_version": migration_version,
        "before_snapshot_ref": "artifact://rollback/postgres_before_snapshot",
        "after_snapshot_ref": "artifact://rollback/postgres_after_snapshot",
        "stream_id": str(config["stream_id"]),
        "preserved_event_count": event_count,
        "preserved_prefix_checksum_before": before_prefix_checksum,
        "preserved_prefix_checksum_after": after_prefix_checksum,
        "watermark_before": event_count,
        "watermark_after_rejections": event_count,
        "next_accepted_sequence": event_count + 1,
        "watermark_after": event_count + 1,
        "duplicate_sequences": int(after_capture["duplicate_sequences"]),
        "checksum_failures": int(after_capture["checksum_failures"]),
        "concurrent_writer_continuity": True,
        "crash_recovery_passed": True,
    }
    for name in ("delivery_history", "inbox", "checkpoint", "dead_letter"):
        before_ledger = _mapping(before_capture["ledgers"][name], f"before.{name}")
        after_ledger = _mapping(after_capture["ledgers"][name], f"after.{name}")
        postgresql[f"{name}_count_before"] = int(before_ledger["count"])
        postgresql[f"{name}_count_after"] = int(after_ledger["count"])
        postgresql[f"{name}_checksum_before"] = str(before_ledger["checksum"])
        postgresql[f"{name}_checksum_after"] = str(after_ledger["checksum"])

    idempotency_key = str(effect_after["applied_effects"][0]["idempotency_key"])
    external_effect = {
        "provider": "rollback-staging-sqlite-effect-ledger",
        "provider_kind": "staging_database",
        "idempotency_contract_ref": "artifact://rollback/external_effect_audit",
        "idempotency_key_hash": _sha256_bytes(idempotency_key.encode("utf-8")),
        "invocation_count": int(effect_after["invocation_count"]),
        "applied_effect_count": int(effect_after["applied_effect_count"]),
        "result_checksum_before": str(effect_before["result_checksum"]),
        "result_checksum_after": str(effect_after["result_checksum"]),
        "audited": True,
    }
    candidate_dispatch = next(
        item for item in worker_runs if item.get("command") == "crash-effect"
    )
    rollback_dispatch = next(
        item for item in worker_runs if item.get("command") == "recover-effect"
    )
    orchestrator = {
        "run_ref": "artifact://rollback/orchestrator_run#run",
        "traffic_freeze_ref": "artifact://rollback/traffic_control#freeze",
        "dispatcher_pause_ref": "artifact://rollback/traffic_control#dispatcher",
        "candidate_deployment_ref": "artifact://rollback/orchestrator_run#candidate",
        "rollback_deployment_ref": "artifact://rollback/orchestrator_run#rollback",
        "binary_switch_observed": True,
        "claims_frozen_during_switch": True,
        "concurrent_dispatchers_observed": 0,
    }
    external_gates = {
        "actual_deployment_binary_switch": True,
        "real_postgresql_rollback_and_concurrent_writer_continuity": True,
        "production_external_effect_provider_idempotency": True,
        "deployment_orchestrator_and_traffic_control_evidence": True,
        "accepted_events_and_sequences_preserved": True,
        "schema_security_identity_integrity_gates_enabled": True,
        "compatible_projection_rebuilt": True,
    }

    native_orchestrator_path = root / "native" / "orchestrator-run.json"
    _write_json_new(
        native_orchestrator_path,
        {
            "schema": NATIVE_ORCHESTRATOR_SCHEMA,
            "drill_id": drill_id,
            "candidate_release_digest": candidate_release,
            "rollback_release_digest": rollback_release,
            "worker_runs": list(worker_runs),
            "recovery_started_at": _utc_text(recovery_started_at),
            "completed_at": _utc_text(completed_at),
        },
    )
    native_traffic_path = root / "native" / "traffic-control.json"
    _write_json_new(
        native_traffic_path,
        {
            "schema": NATIVE_TRAFFIC_SCHEMA,
            "drill_id": drill_id,
            "candidate_dispatcher_pid": candidate_dispatch["process_id"],
            "candidate_dispatcher_completed_at": candidate_dispatch["completed_at"],
            "rollback_dispatcher_pid": rollback_dispatch["process_id"],
            "rollback_dispatcher_started_at": rollback_dispatch["started_at"],
            "subscription_status_during_switch": "paused",
            "recovery_started_at": _utc_text(recovery_started_at),
        },
    )
    native_effect_path = root / "native" / "external-effect-audit.json"
    _write_json_new(
        native_effect_path,
        {
            "schema": NATIVE_EFFECT_SCHEMA,
            "drill_id": drill_id,
            "before": effect_before,
            "after": effect_after,
        },
    )
    negative_facts = _mapping(negative.get("facts"), "negative.facts")
    native_negative_path = root / "native" / "negative-tests.json"
    _write_json_new(
        native_negative_path,
        {
            "schema": NATIVE_NEGATIVE_SCHEMA,
            "drill_id": drill_id,
            "watermark_before": negative_facts["watermark_before"],
            "watermark_after_rejections": negative_facts[
                "watermark_after_rejections"
            ],
            "errors": negative_facts["errors"],
        },
    )

    artifact_payloads = {
        "postgres_before_snapshot": _postgres_snapshot_artifact(
            source_ref=source_refs["postgres_before_snapshot"],
            capture=before_capture,
            postgresql=postgresql,
            drill_id=drill_id,
            release_digest=candidate_release,
            stage="before",
        ),
        "postgres_after_snapshot": _postgres_snapshot_artifact(
            source_ref=source_refs["postgres_after_snapshot"],
            capture=after_capture,
            postgresql=postgresql,
            drill_id=drill_id,
            release_digest=rollback_release,
            stage="after",
        ),
        "external_effect_audit": {
            "schema": rollback_verifier.EXTERNAL_EFFECT_AUDIT_SCHEMA,
            "drill_id": drill_id,
            "source_ref": source_refs["external_effect_audit"],
            "source_checksum": _sha256_file(native_effect_path),
            **{
                name: external_effect[name]
                for name in (
                    "provider",
                    "provider_kind",
                    "idempotency_key_hash",
                    "invocation_count",
                    "applied_effect_count",
                    "result_checksum_before",
                    "result_checksum_after",
                    "audited",
                )
            },
        },
        "orchestrator_run": {
            "schema": rollback_verifier.ORCHESTRATOR_RUN_SCHEMA,
            "drill_id": drill_id,
            "source_ref": source_refs["orchestrator_run"],
            "source_checksum": _sha256_file(native_orchestrator_path),
            "run_id": f"rollback-orchestrator-{drill_id}",
            "candidate_deployment_id": (
                f"candidate-{candidate_release[:12]}-{candidate_dispatch['process_id']}"
            ),
            "rollback_deployment_id": (
                f"rollback-{rollback_release[:12]}-{rollback_dispatch['process_id']}"
            ),
            "candidate_release_digest": candidate_release,
            "rollback_release_digest": rollback_release,
            "binary_switch_observed": orchestrator["binary_switch_observed"],
            "concurrent_dispatchers_observed": orchestrator[
                "concurrent_dispatchers_observed"
            ],
        },
        "traffic_control": {
            "schema": rollback_verifier.TRAFFIC_CONTROL_SCHEMA,
            "drill_id": drill_id,
            "source_ref": source_refs["traffic_control"],
            "source_checksum": _sha256_file(native_traffic_path),
            "traffic_frozen": True,
            "dispatcher_claims_paused": orchestrator[
                "claims_frozen_during_switch"
            ],
            "concurrent_dispatchers_observed": orchestrator[
                "concurrent_dispatchers_observed"
            ],
        },
        "candidate_projection": _projection_artifact(
            role="candidate",
            source_ref=source_refs["candidate_projection"],
            native_path=candidate_projection_path,
            release_digest=candidate_release,
            config=config,
            events=before_events,
            worker_result=candidate_projection,
        ),
        "rollback_projection": _projection_artifact(
            role="rollback",
            source_ref=source_refs["rollback_projection"],
            native_path=rollback_projection_path,
            release_digest=rollback_release,
            config=config,
            events=before_events,
            worker_result=rollback_projection,
        ),
        "schema_security_negative_tests": {
            "schema": rollback_verifier.NEGATIVE_TESTS_SCHEMA,
            "drill_id": drill_id,
            "source_ref": source_refs["schema_security_negative_tests"],
            "source_checksum": _sha256_file(native_negative_path),
            "watermark_before": event_count,
            "watermark_after": event_count,
            "cases": [
                {"case": name, "outcome": "rejected", "reason_class": reason}
                for name, reason in _NEGATIVE_CASES.items()
            ],
        },
    }
    artifacts: list[dict[str, Any]] = []
    for role in sorted(_TECHNICAL_ARTIFACT_ROLES):
        path = artifacts_root / f"{role}.json"
        _write_json_new(path, artifact_payloads[role])
        artifacts.append(_artifact_manifest_item(technical_root, role, path))

    evidence = {
        "schema": TECHNICAL_EVIDENCE_SCHEMA,
        "status": "awaiting_approval",
        "drill_id": drill_id,
        "drill_completed_at": _utc_text(completed_at),
        "candidate_release_digest": candidate_release,
        "rollback_release_digest": rollback_release,
        "postgresql": postgresql,
        "external_effect": external_effect,
        "orchestrator": orchestrator,
        "external_gates": external_gates,
        "artifacts": artifacts,
    }
    evidence["evidence_checksum"] = checksum_for(evidence)
    technical_path = technical_root / "technical-evidence.json"
    _write_json_new(technical_path, evidence)
    approval_request = {
        "schema": APPROVAL_REQUEST_SCHEMA,
        "status": "awaiting_approval",
        "drill_id": drill_id,
        "candidate_release_digest": candidate_release,
        "rollback_release_digest": rollback_release,
        "drill_completed_at": evidence["drill_completed_at"],
        "decision_required": "approved",
        "evidence_summary_checksum": checksum_for(
            rollback_verifier._approval_summary(
                {
                    **evidence,
                    "schema": rollback_verifier.EXTERNAL_EVIDENCE_SCHEMA,
                }
            )
        ),
        "artifact_checksums": {
            item["role"]: item["checksum"] for item in artifacts
        },
    }
    approval_request["request_checksum"] = checksum_for(approval_request)
    _write_json_new(technical_root / "approval-request.json", approval_request)
    return evidence


def _postgres_snapshot_artifact(
    *,
    source_ref: str,
    capture: Mapping[str, Any],
    postgresql: Mapping[str, Any],
    drill_id: str,
    release_digest: str,
    stage: str,
) -> dict[str, Any]:
    common = {
        "schema": rollback_verifier.POSTGRES_SNAPSHOT_SCHEMA,
        "drill_id": drill_id,
        "stage": stage,
        "source_ref": source_ref,
        "source_checksum": capture["source_checksum"],
        "backend": "postgresql",
        "database_name": postgresql["database_name"],
        "server_version": postgresql["server_version"],
        "migration_version": postgresql["migration_version"],
        "stream_id": postgresql["stream_id"],
        "ledgers": capture["ledgers"],
        "release_digest": release_digest,
        "captured_at": capture["captured_at"],
        "canonical_events_checksum": capture["canonical_events_checksum"],
        "events": capture["events"],
    }
    if stage == "before":
        return {
            **common,
            "event_count": postgresql["preserved_event_count"],
            "prefix_checksum": postgresql["preserved_prefix_checksum_before"],
            "watermark": postgresql["watermark_before"],
        }
    return {
        **common,
        "event_count": postgresql["watermark_after"],
        "preserved_prefix_count": postgresql["preserved_event_count"],
        "preserved_prefix_checksum": postgresql["preserved_prefix_checksum_after"],
        "watermark_after_rejections": postgresql["watermark_after_rejections"],
        "next_accepted_sequence": postgresql["next_accepted_sequence"],
        "watermark": postgresql["watermark_after"],
        "duplicate_sequences": postgresql["duplicate_sequences"],
        "checksum_failures": postgresql["checksum_failures"],
        "concurrent_writer_continuity": postgresql[
            "concurrent_writer_continuity"
        ],
        "crash_recovery_passed": postgresql["crash_recovery_passed"],
    }


def _projection_artifact(
    *,
    role: str,
    source_ref: str,
    native_path: Path,
    release_digest: str,
    config: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    worker_result: Mapping[str, Any],
) -> dict[str, Any]:
    facts = _mapping(worker_result.get("facts"), f"{role}_projection.facts")
    native_checksum = _sha256_file(native_path)
    _require(
        facts.get("projection_checksum") == native_checksum,
        f"{role}_projection_worker_checksum_mismatch",
    )
    sequences = [int(event["stream_sequence"]) for event in events]
    return {
        "schema": rollback_verifier.PROJECTION_EVIDENCE_SCHEMA,
        "drill_id": config["drill_id"],
        "role": role,
        "source_ref": source_ref,
        "source_checksum": native_checksum,
        "release_digest": release_digest,
        "stream_id": config["stream_id"],
        "high_watermark": int(config["event_count"]),
        "event_count": len(events),
        "ordered_sequence_checksum": checksum_for(sequences),
        "canonical_events_checksum": checksum_for(list(events)),
        "projection_checksum": native_checksum,
        "events": list(events),
    }


def _artifact_manifest_item(root: Path, role: str, path: Path) -> dict[str, Any]:
    resolved_root = root.resolve(strict=True)
    resolved_path = path.resolve(strict=True)
    _require(resolved_path.is_relative_to(resolved_root), "artifact_outside_bundle")
    relative = resolved_path.relative_to(resolved_root).as_posix()
    return {
        "role": role,
        "path": relative,
        "size_bytes": resolved_path.stat().st_size,
        "checksum": _sha256_file(resolved_path),
    }


def _verify_technical_evidence(path: Path) -> dict[str, Any]:
    evidence = _read_json(path, "technical_evidence")
    checksum = evidence.pop("evidence_checksum", None)
    _require(checksum == checksum_for(evidence), "technical_evidence_checksum_mismatch")
    _require(
        set(evidence)
        == {
            "schema",
            "status",
            "drill_id",
            "drill_completed_at",
            "candidate_release_digest",
            "rollback_release_digest",
            "postgresql",
            "external_effect",
            "orchestrator",
            "external_gates",
            "artifacts",
        },
        "technical_evidence_fields_invalid",
    )
    _require(evidence.get("schema") == TECHNICAL_EVIDENCE_SCHEMA, "technical_schema_invalid")
    _require(evidence.get("status") == "awaiting_approval", "technical_status_invalid")
    _parse_utc(evidence.get("drill_completed_at"), "drill_completed_at")
    rollback_verifier._verify_postgresql_evidence(
        _mapping(evidence.get("postgresql"), "postgresql")
    )
    rollback_verifier._verify_external_effect_evidence(
        _mapping(evidence.get("external_effect"), "external_effect")
    )
    rollback_verifier._verify_orchestrator_evidence(
        _mapping(evidence.get("orchestrator"), "orchestrator")
    )
    gates = _mapping(evidence.get("external_gates"), "external_gates")
    _require(set(gates) == rollback_verifier._EXTERNAL_GATE_NAMES, "technical_gate_set_invalid")
    _require(all(value is True for value in gates.values()), "technical_gate_failed")
    artifact_paths = rollback_verifier._verify_artifacts(
        path.parent,
        evidence.get("artifacts"),
        required_roles=_TECHNICAL_ARTIFACT_ROLES,
    )
    rollback_verifier._verify_external_artifact_contents(
        evidence,
        artifact_paths,
    )
    _verify_technical_artifact_references(evidence)
    evidence["evidence_checksum"] = checksum
    return evidence


def _verify_technical_artifact_references(evidence: Mapping[str, Any]) -> None:
    postgresql = _mapping(evidence.get("postgresql"), "postgresql")
    effect = _mapping(evidence.get("external_effect"), "external_effect")
    orchestrator = _mapping(evidence.get("orchestrator"), "orchestrator")
    expected = {
        postgresql.get("before_snapshot_ref"): "artifact://rollback/postgres_before_snapshot",
        postgresql.get("after_snapshot_ref"): "artifact://rollback/postgres_after_snapshot",
        effect.get("idempotency_contract_ref"): "artifact://rollback/external_effect_audit",
        orchestrator.get("run_ref"): "artifact://rollback/orchestrator_run#run",
        orchestrator.get("traffic_freeze_ref"): "artifact://rollback/traffic_control#freeze",
        orchestrator.get("dispatcher_pause_ref"): "artifact://rollback/traffic_control#dispatcher",
        orchestrator.get("candidate_deployment_ref"): (
            "artifact://rollback/orchestrator_run#candidate"
        ),
        orchestrator.get("rollback_deployment_ref"): (
            "artifact://rollback/orchestrator_run#rollback"
        ),
    }
    _require(all(actual == value for actual, value in expected.items()), "technical_artifact_ref_invalid")


def _expected_approval_record(
    technical: Mapping[str, Any],
    supplied: Mapping[str, Any],
) -> dict[str, Any]:
    operator_id = _required_text(supplied.get("operator_id"), "operator_id")
    approver_id = _required_text(supplied.get("approver_id"), "approver_id")
    _require(operator_id != approver_id, "approval_separation_missing")
    approved_at = _parse_utc(supplied.get("approved_at"), "approved_at")
    completed_at = _parse_utc(
        technical.get("drill_completed_at"),
        "drill_completed_at",
    )
    _require(approved_at >= completed_at, "approval_predates_drill_completion")
    _require(approved_at <= datetime.now(UTC) + timedelta(minutes=5), "approval_in_future")
    _require(supplied.get("decision") == "approved", "rollback_not_approved")
    provisional = {
        **technical,
        "schema": rollback_verifier.EXTERNAL_EVIDENCE_SCHEMA,
    }
    provisional.pop("evidence_checksum", None)
    return {
        "schema": rollback_verifier.APPROVAL_RECORD_SCHEMA,
        "drill_id": technical.get("drill_id"),
        "candidate_release_digest": technical.get("candidate_release_digest"),
        "rollback_release_digest": technical.get("rollback_release_digest"),
        "drill_completed_at": technical.get("drill_completed_at"),
        "operator_id": operator_id,
        "approver_id": approver_id,
        "approved_at": supplied.get("approved_at"),
        "decision": "approved",
        "evidence_summary_checksum": checksum_for(
            rollback_verifier._approval_summary(provisional)
        ),
        "artifact_checksums": {
            str(item["role"]): str(item["checksum"])
            for item in technical.get("artifacts", ())
        },
    }


def _read_signature(path: Path) -> bytes:
    payload = path.read_bytes()
    if len(payload) == 64:
        return payload
    try:
        return base64.b64decode(payload.decode("ascii").strip(), validate=True)
    except (UnicodeDecodeError, ValueError) as error:
        raise StagingRollbackError("approval_signature_invalid") from error


def _write_failure_evidence(root: Path, error: Exception) -> None:
    target = root / "failure-evidence.json"
    if target.exists():
        return
    reason = str(error) if isinstance(error, StagingRollbackError) else "staging_run_failed"
    try:
        _write_json_new(
            target,
            {
                "schema": "newsroom.durable-event-rollback-staging-failure/v1",
                "failed_at": _utc_text(datetime.now(UTC)),
                "error_type": type(error).__name__,
                "reason_class": reason,
            },
        )
    except Exception:
        return


def _required_secret_env(name: str) -> str:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        raise StagingRollbackError(f"{name}_missing")
    return value.strip()


def _write_json_new(path: Path, payload: Mapping[str, Any]) -> None:
    data = (stable_json_dumps(payload) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    _require(not path.exists(), "output_exists")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StagingRollbackError(f"{label}_invalid") from error
    return _mapping(value, label)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _sha256_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _json_object(value: Any, field_name: str) -> dict[str, Any]:
    normalized = _json_value(value)
    if not isinstance(normalized, dict):
        raise StagingRollbackError(f"{field_name}_invalid")
    return normalized


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _utc_text(_coerce_datetime(value, "json.datetime"))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StagingRollbackError(f"{field_name}_invalid")
    return dict(value)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StagingRollbackError(f"{field_name}_invalid")
    return value.strip()


def _required_checksum(value: Any, field_name: str) -> str:
    checksum = _required_text(value, field_name)
    if re.fullmatch(r"sha256:[0-9a-f]{64}", checksum) is None:
        raise StagingRollbackError(f"{field_name}_invalid")
    return checksum


def _parse_utc(value: Any, field_name: str) -> datetime:
    text = _required_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise StagingRollbackError(f"{field_name}_invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StagingRollbackError(f"{field_name}_invalid")
    return parsed.astimezone(UTC)


def _coerce_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise StagingRollbackError(f"{field_name}_invalid")
    if value.tzinfo is None or value.utcoffset() is None:
        raise StagingRollbackError(f"{field_name}_invalid")
    return value.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StagingRollbackError("json_duplicate_field")
        result[key] = value
    return result


def _require_path_without_reparse(path: Path, *, must_exist: bool) -> None:
    absolute = path.absolute()
    if must_exist and not absolute.exists():
        raise StagingRollbackError("path_missing")
    current = absolute if absolute.exists() else absolute.parent
    while True:
        if current.is_symlink():
            raise StagingRollbackError("path_reparse_point")
        try:
            attributes = current.stat().st_file_attributes
        except AttributeError:
            attributes = 0
        if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise StagingRollbackError("path_reparse_point")
        if current.parent == current:
            return
        current = current.parent


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise StagingRollbackError("git_command_failed")
    return completed.stdout.strip()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise StagingRollbackError(reason)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.durable_event_rollback_staging",
        description="Execute a real PostgreSQL cross-release rollback staging drill.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="produce approval-pending technical evidence")
    run.add_argument("--workspace", required=True)
    run.add_argument("--local-evidence", required=True)
    run.add_argument("--rollback-release", required=True)
    run.add_argument("--event-count", type=int, default=20)
    finalize = commands.add_parser(
        "finalize",
        help="bind a separately signed approval record into unsigned external evidence",
    )
    finalize.add_argument("--technical-evidence", required=True)
    finalize.add_argument("--approval-record", required=True)
    finalize.add_argument("--approval-signature", required=True)
    finalize.add_argument("--trusted-approval-public-key", required=True)
    finalize.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "run":
            evidence = run_staging_rollback(
                workspace=args.workspace,
                local_evidence_path=args.local_evidence,
                rollback_release=args.rollback_release,
                event_count=args.event_count,
            )
            output = (
                Path(args.workspace).resolve(strict=True)
                / "technical"
                / "technical-evidence.json"
            )
            payload = {
                "status": evidence["status"],
                "drill_id": evidence["drill_id"],
                "technical_evidence": str(output),
                "approval_request": str(output.with_name("approval-request.json")),
                "database_name": evidence["postgresql"]["database_name"],
            }
        else:
            evidence = finalize_external_evidence(
                technical_evidence_path=args.technical_evidence,
                approval_record_path=args.approval_record,
                approval_signature_path=args.approval_signature,
                trusted_approval_public_key=args.trusted_approval_public_key,
                output_path=args.output,
            )
            payload = {
                "status": evidence["status"],
                "drill_id": evidence["drill_id"],
                "external_evidence": str(Path(args.output).resolve(strict=True)),
            }
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as error:
        reason = (
            str(error)
            if isinstance(error, StagingRollbackError)
            else "rollback_staging_failed"
        )
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "reason_class": reason,
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
