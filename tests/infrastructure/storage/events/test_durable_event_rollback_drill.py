from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

import scripts.durable_event_rollback_drill as rollback_drill
import scripts.durable_event_rollback_staging as rollback_staging
from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    ProducerIdentity,
    StoredEvent,
    checksum_for,
)
from scripts.durable_event_rollback_drill import (
    EVIDENCE_SCHEMA,
    EXTERNAL_EVIDENCE_SCHEMA,
    QUALIFICATION_EVIDENCE_SCHEMA,
    RollbackDrillInvariantError,
    attest_external_evidence,
    generate_signing_keypair,
    main,
    qualify_rollback_evidence,
    verify_unsigned_external_evidence,
    verify_rollback_evidence,
)


def test_phase_specific_rollback_drill_retains_verifiable_evidence(
    tmp_path,
    capsys,
) -> None:
    workspace = tmp_path / "rollback-drill"

    assert (
        main(
            [
                "run",
                "--workspace",
                str(workspace),
                "--drill-id",
                "rollback-test-1",
                "--candidate-release",
                "candidate-test-build",
                "--rollback-release",
                "compatible-test-build",
            ]
        )
        == 2
    )
    evidence_path = workspace / "rollback-evidence.json"
    assert main(["verify", "--evidence", str(evidence_path)]) == 1
    assert (
        main(
            [
                "verify",
                "--evidence",
                str(evidence_path),
                "--allow-incomplete-local",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert '"status":"incomplete"' in output.out
    assert '"reason_class":"RollbackDrillInvariantError"' in output.err

    with pytest.raises(RollbackDrillInvariantError, match="drill_not_passed"):
        verify_rollback_evidence(evidence_path)
    evidence = verify_rollback_evidence(
        evidence_path,
        allow_incomplete_local=True,
    )
    assert evidence["schema"] == EVIDENCE_SCHEMA
    assert evidence["overall_status"] == "incomplete"
    assert evidence["release_context"] == {
        "candidate_release": "candidate-test-build",
        "rollback_release": "compatible-test-build",
        "labels_source": "operator_input",
    }
    phases = {phase["phase"]: phase for phase in evidence["phases"]}
    assert set(phases) == {
        "pre_cutover_shadow_rollback",
        "post_cutover_canonical_writer",
        "dispatcher_runtime_recomposition",
        "rollback_gates_and_sequence_continuity",
        "same_binary_projection_rebuild",
    }
    assert all(
        all(phase["assertions"].values()) for phase in phases.values()
    )
    assert phases["dispatcher_runtime_recomposition"]["evidence"] == {
        "first_attempt_state": "retry_wait",
        "recovered_attempt_state": "acked",
        "consumer_invocations": 2,
        "external_effect_rows": 1,
        "checkpoint_sequence": 1,
    }
    assert phases["rollback_gates_and_sequence_continuity"]["evidence"] == {
        "watermark_before_rejections": 1,
        "watermark_after_rejections": 1,
        "accepted_sequences": [1, 2],
        "delivery_states": ["acked", "pending"],
    }

    artifacts = {item["role"]: item for item in evidence["artifacts"]}
    assert artifacts["candidate_projection"]["checksum"] == artifacts[
        "rebuilt_projection"
    ]["checksum"]
    rollback_projection = workspace / artifacts["rebuilt_projection"]["path"]
    rows = [
        json.loads(line)
        for line in rollback_projection.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["stream_sequence"] for row in rows] == [1, 2]
    assert rows[0]["payload"]["private_note"] == "[REDACTED]"

    effects_database = workspace / artifacts["external_effect_ledger"]["path"]
    with sqlite3.connect(effects_database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM applied_effects"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM effect_invocations"
        ).fetchone()[0] == 2

    rollback_projection.write_bytes(rollback_projection.read_bytes() + b"{}\n")
    with pytest.raises(
        RollbackDrillInvariantError,
        match="evidence_artifact_(size|checksum)_mismatch",
    ):
        verify_rollback_evidence(
            evidence_path,
            allow_incomplete_local=True,
        )


def test_local_evidence_remains_verifiable_after_bundle_move(tmp_path) -> None:
    workspace = tmp_path / "source"
    assert main(["run", "--workspace", str(workspace)]) == 2
    relocated = tmp_path / "relocated"
    shutil.move(str(workspace), relocated)

    evidence = verify_rollback_evidence(
        relocated / "rollback-evidence.json",
        allow_incomplete_local=True,
    )

    assert evidence["artifact_root"] == "."
    assert evidence["overall_status"] == "incomplete"


def test_release_qualification_requires_complete_signed_external_evidence(
    tmp_path,
) -> None:
    candidate = "a" * 40
    rollback = "b" * 40
    local_root = tmp_path / "local-source"
    assert (
        main(
            [
                "run",
                "--workspace",
                str(local_root),
                "--drill-id",
                "rollback-qualification-1",
                "--candidate-release",
                candidate,
                "--rollback-release",
                rollback,
            ]
        )
        == 2
    )
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-qualification-1",
        candidate=candidate,
        rollback=rollback,
    )
    approval_public_key = _approval_public_key(external_path)
    private_key = tmp_path / "keys" / "qualification-private.pem"
    public_key = tmp_path / "keys" / "qualification-public.pem"
    external_private_key = tmp_path / "keys" / "external-private.pem"
    external_public_key = tmp_path / "keys" / "external-public.pem"
    assert (
        main(
            [
                "keygen",
                "--private-key",
                str(private_key),
                "--public-key",
                str(public_key),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "keygen",
                "--private-key",
                str(external_private_key),
                "--public-key",
                str(external_public_key),
            ]
        )
        == 0
    )
    signed_external_path = external_path.with_name("external-evidence.signed.json")
    assert (
        main(
            [
                "attest-external",
                "--evidence",
                str(external_path),
                "--private-key",
                str(external_private_key),
                "--trusted-approval-public-key",
                str(approval_public_key),
                "--output",
                str(signed_external_path),
            ]
        )
        == 0
    )
    qualification_path = tmp_path / "qualification" / "qualification.json"
    assert (
        main(
            [
                "qualify",
                "--local-evidence",
                str(local_root / "rollback-evidence.json"),
                "--external-evidence",
                str(signed_external_path),
                "--private-key",
                str(private_key),
                "--trusted-external-public-key",
                str(external_public_key),
                "--trusted-approval-public-key",
                str(approval_public_key),
                "--output",
                str(qualification_path),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "verify",
                "--evidence",
                str(qualification_path),
                "--trusted-public-key",
                str(public_key),
                "--trusted-external-public-key",
                str(external_public_key),
                "--trusted-approval-public-key",
                str(approval_public_key),
            ]
        )
        == 0
    )

    evidence = verify_rollback_evidence(
        qualification_path,
        trusted_public_key=public_key,
        trusted_external_public_key=external_public_key,
        trusted_approval_public_key=approval_public_key,
    )
    assert evidence["schema"] == QUALIFICATION_EVIDENCE_SCHEMA
    assert evidence["overall_status"] == "passed"
    assert evidence["release_context"] == {
        "candidate_release_digest": candidate,
        "rollback_release_digest": rollback,
    }

    tampered = json.loads(qualification_path.read_text(encoding="utf-8"))
    tampered["release_context"]["rollback_release_digest"] = "c" * 40
    tampered_path = tmp_path / "qualification" / "tampered.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(
        RollbackDrillInvariantError,
        match="qualification_(checksum|signature)_invalid|qualification_checksum_mismatch",
    ):
        verify_rollback_evidence(
            tampered_path,
            trusted_public_key=public_key,
            trusted_external_public_key=external_public_key,
            trusted_approval_public_key=approval_public_key,
        )

    other_private = tmp_path / "keys" / "other-private.pem"
    other_public = tmp_path / "keys" / "other-public.pem"
    assert (
        main(
            [
                "keygen",
                "--private-key",
                str(other_private),
                "--public-key",
                str(other_public),
            ]
        )
        == 0
    )
    with pytest.raises(
        RollbackDrillInvariantError,
        match="trusted_public_key_mismatch",
    ):
        verify_rollback_evidence(
            qualification_path,
            trusted_public_key=other_public,
            trusted_external_public_key=external_public_key,
            trusted_approval_public_key=approval_public_key,
        )

    with pytest.raises(
        RollbackDrillInvariantError,
        match="trusted_external_public_key_mismatch",
    ):
        verify_rollback_evidence(
            qualification_path,
            trusted_public_key=public_key,
            trusted_external_public_key=other_public,
            trusted_approval_public_key=approval_public_key,
        )

    with pytest.raises(
        RollbackDrillInvariantError,
        match="trusted_approval_public_key_mismatch",
    ):
        verify_rollback_evidence(
            qualification_path,
            trusted_public_key=public_key,
            trusted_external_public_key=external_public_key,
            trusted_approval_public_key=other_public,
        )


def test_qualification_requires_independent_attester_and_qualifier(tmp_path) -> None:
    inputs = _prepare_qualification_inputs(tmp_path, "rollback-authority-separation")

    with pytest.raises(
        RollbackDrillInvariantError,
        match="signing_authority_separation_missing",
    ):
        qualify_rollback_evidence(
            local_evidence_path=inputs["local_evidence"],
            external_evidence_path=inputs["external_evidence"],
            private_key_path=inputs["external_private_key"],
            trusted_external_public_key=inputs["external_public_key"],
            trusted_approval_public_key=inputs["approval_public_key"],
            output_path=tmp_path / "qualification" / "qualification.json",
        )

    with pytest.raises(
        RollbackDrillInvariantError,
        match="signing_authority_separation_missing",
    ):
        qualify_rollback_evidence(
            local_evidence_path=inputs["local_evidence"],
            external_evidence_path=inputs["external_evidence"],
            private_key_path=inputs["approval_private_key"],
            trusted_external_public_key=inputs["external_public_key"],
            trusted_approval_public_key=inputs["approval_public_key"],
            output_path=tmp_path / "approval-qualification" / "qualification.json",
        )

    unsigned = inputs["external_evidence"].with_name("external-evidence.json")
    with pytest.raises(
        RollbackDrillInvariantError,
        match="signing_authority_separation_missing",
    ):
        attest_external_evidence(
            evidence_path=unsigned,
            private_key_path=inputs["approval_private_key"],
            trusted_approval_public_key=inputs["approval_public_key"],
            output_path=unsigned.with_name("approval-as-attester.json"),
        )


def test_private_signing_key_permissions_are_enforced(tmp_path) -> None:
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-private-key-permissions",
        candidate="a" * 40,
        rollback="b" * 40,
    )
    private_key = tmp_path / "external-private.pem"
    public_key = tmp_path / "external-public.pem"
    generate_signing_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )
    _make_private_key_insecure(private_key)

    with pytest.raises(
        RollbackDrillInvariantError,
        match="private_key_permissions_insecure",
    ):
        attest_external_evidence(
            evidence_path=external_path,
            private_key_path=private_key,
            trusted_approval_public_key=_approval_public_key(external_path),
            output_path=external_path.with_name("external-evidence.signed.json"),
        )


def test_external_evidence_rejects_duplicate_artifact_paths(tmp_path) -> None:
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-duplicate-artifact",
        candidate="a" * 40,
        rollback="b" * 40,
    )
    payload = json.loads(external_path.read_text(encoding="utf-8"))
    first = payload["artifacts"][0]
    payload["artifacts"][1].update(
        {
            "path": first["path"],
            "size_bytes": first["size_bytes"],
            "checksum": first["checksum"],
        }
    )
    _write_evidence_with_checksum(external_path, payload)
    private_key = tmp_path / "external-private.pem"
    public_key = tmp_path / "external-public.pem"
    generate_signing_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )

    with pytest.raises(
        RollbackDrillInvariantError,
        match="evidence_artifact_path_duplicate",
    ):
        attest_external_evidence(
            evidence_path=external_path,
            private_key_path=private_key,
            trusted_approval_public_key=_approval_public_key(external_path),
            output_path=external_path.with_name("external-evidence.signed.json"),
        )


def test_external_evidence_rejects_hard_link_artifact_alias(tmp_path) -> None:
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-hard-link-alias",
        candidate="a" * 40,
        rollback="b" * 40,
    )
    payload = json.loads(external_path.read_text(encoding="utf-8"))
    first, second = payload["artifacts"][:2]
    first_path = external_path.parent / first["path"]
    alias_path = external_path.parent / "artifacts" / "hard-link-alias.json"
    os.link(first_path, alias_path)
    second.update(
        {
            "path": "artifacts/hard-link-alias.json",
            "size_bytes": first["size_bytes"],
            "checksum": first["checksum"],
        }
    )
    _write_evidence_with_checksum(external_path, payload)
    private_key = tmp_path / "external-private.pem"
    public_key = tmp_path / "external-public.pem"
    generate_signing_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )

    with pytest.raises(
        RollbackDrillInvariantError,
        match="evidence_artifact_file_alias",
    ):
        attest_external_evidence(
            evidence_path=external_path,
            private_key_path=private_key,
            trusted_approval_public_key=_approval_public_key(external_path),
            output_path=external_path.with_name("external-evidence.signed.json"),
        )


def test_external_evidence_rejects_symlink_artifact(tmp_path, monkeypatch) -> None:
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-symlink-artifact",
        candidate="a" * 40,
        rollback="b" * 40,
    )
    payload = json.loads(external_path.read_text(encoding="utf-8"))
    manifest = payload["artifacts"][0]
    original = external_path.parent / manifest["path"]
    link = external_path.parent / "artifacts" / "symlink-artifact.json"
    shutil.copy2(original, link)
    manifest["path"] = "artifacts/symlink-artifact.json"
    _write_evidence_with_checksum(external_path, payload)
    private_key = tmp_path / "external-private.pem"
    public_key = tmp_path / "external-public.pem"
    generate_signing_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )

    path_type = type(link)
    original_is_symlink = path_type.is_symlink

    def reports_artifact_as_symlink(path):
        return path == link or original_is_symlink(path)

    with monkeypatch.context() as patch:
        patch.setattr(path_type, "is_symlink", reports_artifact_as_symlink)
        with pytest.raises(
            RollbackDrillInvariantError,
            match="evidence_artifact_reparse_point",
        ):
            attest_external_evidence(
                evidence_path=external_path,
                private_key_path=private_key,
                trusted_approval_public_key=_approval_public_key(external_path),
                output_path=external_path.with_name("external-evidence.signed.json"),
            )


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("artifacts/evidence.json:payload", "artifact.path_alternate_data_stream"),
        ("artifacts/CON.json", "artifact.path_windows_reserved_name"),
    ],
)
def test_external_evidence_rejects_nonportable_artifact_path(
    tmp_path,
    path,
    reason,
) -> None:
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-nonportable-path",
        candidate="a" * 40,
        rollback="b" * 40,
    )
    payload = json.loads(external_path.read_text(encoding="utf-8"))
    payload["artifacts"][0]["path"] = path
    _write_evidence_with_checksum(external_path, payload)
    private_key = tmp_path / "external-private.pem"
    public_key = tmp_path / "external-public.pem"
    generate_signing_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )

    with pytest.raises(RollbackDrillInvariantError, match=reason):
        attest_external_evidence(
            evidence_path=external_path,
            private_key_path=private_key,
            trusted_approval_public_key=_approval_public_key(external_path),
            output_path=external_path.with_name("external-evidence.signed.json"),
        )


def test_external_evidence_rejects_future_approval(tmp_path) -> None:
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-future-approval",
        candidate="a" * 40,
        rollback="b" * 40,
        approved_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    private_key = tmp_path / "external-private.pem"
    public_key = tmp_path / "external-public.pem"
    generate_signing_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )

    with pytest.raises(RollbackDrillInvariantError, match="approved_at_in_future"):
        attest_external_evidence(
            evidence_path=external_path,
            private_key_path=private_key,
            trusted_approval_public_key=_approval_public_key(external_path),
            output_path=external_path.with_name("external-evidence.signed.json"),
        )


def test_external_evidence_rejects_invalid_approval_signature(tmp_path) -> None:
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-invalid-approval-signature",
        candidate="a" * 40,
        rollback="b" * 40,
    )
    payload = json.loads(external_path.read_text(encoding="utf-8"))
    payload["approval"]["signature"] = base64.b64encode(b"invalid").decode(
        "ascii"
    )
    _write_evidence_with_checksum(external_path, payload)
    private_key = tmp_path / "external-private.pem"
    public_key = tmp_path / "external-public.pem"
    generate_signing_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )

    with pytest.raises(RollbackDrillInvariantError, match="approval_signature_invalid"):
        attest_external_evidence(
            evidence_path=external_path,
            private_key_path=private_key,
            trusted_approval_public_key=_approval_public_key(external_path),
            output_path=external_path.with_name("external-evidence.signed.json"),
        )


def test_external_attestation_rejects_signature_and_key_tampering(tmp_path) -> None:
    inputs = _prepare_qualification_inputs(tmp_path, "rollback-attestation-tamper")
    signed = json.loads(inputs["external_evidence"].read_text(encoding="utf-8"))
    signed["external_effect"]["provider"] = "tampered-staging-provider"
    effect_manifest = next(
        item
        for item in signed["artifacts"]
        if item["role"] == "external_effect_audit"
    )
    effect_path = inputs["external_evidence"].parent / effect_manifest["path"]
    effect_artifact = json.loads(effect_path.read_text(encoding="utf-8"))
    effect_artifact["provider"] = "tampered-staging-provider"
    effect_bytes = json.dumps(
        effect_artifact,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    effect_path.write_bytes(effect_bytes)
    effect_manifest["size_bytes"] = len(effect_bytes)
    effect_manifest["checksum"] = f"sha256:{sha256(effect_bytes).hexdigest()}"
    attestation = signed.pop("attestation")
    _resign_external_approval(
        inputs["external_evidence"].parent,
        signed,
        inputs["approval_private_key"],
    )
    _write_evidence_with_checksum(inputs["external_evidence"], signed)
    signed = json.loads(inputs["external_evidence"].read_text(encoding="utf-8"))
    signed["attestation"] = attestation
    inputs["external_evidence"].write_text(json.dumps(signed), encoding="utf-8")

    with pytest.raises(
        RollbackDrillInvariantError,
        match="external_attestation_signature_invalid",
    ):
        qualify_rollback_evidence(
            local_evidence_path=inputs["local_evidence"],
            external_evidence_path=inputs["external_evidence"],
            private_key_path=inputs["qualification_private_key"],
            trusted_external_public_key=inputs["external_public_key"],
            trusted_approval_public_key=inputs["approval_public_key"],
            output_path=tmp_path / "signature-tamper" / "qualification.json",
        )

    other_private = tmp_path / "other-private.pem"
    other_public = tmp_path / "other-public.pem"
    generate_signing_keypair(
        private_key_path=other_private,
        public_key_path=other_public,
    )
    with pytest.raises(
        RollbackDrillInvariantError,
        match="trusted_external_public_key_mismatch",
    ):
        qualify_rollback_evidence(
            local_evidence_path=inputs["local_evidence"],
            external_evidence_path=inputs["external_evidence"],
            private_key_path=inputs["qualification_private_key"],
            trusted_external_public_key=other_public,
            trusted_approval_public_key=inputs["approval_public_key"],
            output_path=tmp_path / "key-tamper" / "qualification.json",
        )


def test_attestation_and_qualification_outputs_refuse_alias_or_overwrite(
    tmp_path,
) -> None:
    inputs = _prepare_qualification_inputs(tmp_path, "rollback-output-safety")
    unsigned = inputs["external_evidence"].with_name("external-evidence.json")

    with pytest.raises(
        RollbackDrillInvariantError,
        match="external_attestation_output_alias",
    ):
        attest_external_evidence(
            evidence_path=unsigned,
            private_key_path=inputs["external_private_key"],
            trusted_approval_public_key=inputs["approval_public_key"],
            output_path=unsigned,
        )

    existing_attestation = unsigned.with_name("existing-attestation.json")
    existing_attestation.write_text("sentinel", encoding="utf-8")
    with pytest.raises(
        RollbackDrillInvariantError,
        match="external_attestation_output_exists",
    ):
        attest_external_evidence(
            evidence_path=unsigned,
            private_key_path=inputs["external_private_key"],
            trusted_approval_public_key=inputs["approval_public_key"],
            output_path=existing_attestation,
        )
    assert existing_attestation.read_text(encoding="utf-8") == "sentinel"

    with pytest.raises(
        RollbackDrillInvariantError,
        match="qualification_output_alias",
    ):
        qualify_rollback_evidence(
            local_evidence_path=inputs["local_evidence"],
            external_evidence_path=inputs["external_evidence"],
            private_key_path=inputs["qualification_private_key"],
            trusted_external_public_key=inputs["external_public_key"],
            trusted_approval_public_key=inputs["approval_public_key"],
            output_path=inputs["local_evidence"],
        )

    qualification_path = tmp_path / "existing-qualification" / "qualification.json"
    qualification_path.parent.mkdir()
    qualification_path.write_text("sentinel", encoding="utf-8")
    with pytest.raises(
        RollbackDrillInvariantError,
        match="qualification_output_exists",
    ):
        qualify_rollback_evidence(
            local_evidence_path=inputs["local_evidence"],
            external_evidence_path=inputs["external_evidence"],
            private_key_path=inputs["qualification_private_key"],
            trusted_external_public_key=inputs["external_public_key"],
            trusted_approval_public_key=inputs["approval_public_key"],
            output_path=qualification_path,
        )
    assert qualification_path.read_text(encoding="utf-8") == "sentinel"


def test_atomic_file_publish_does_not_overwrite_racing_outputs(
    tmp_path,
    monkeypatch,
) -> None:
    inputs = _prepare_qualification_inputs(tmp_path, "rollback-output-race")
    unsigned = inputs["external_evidence"].with_name("external-evidence.json")
    raced_attestation = unsigned.with_name("raced-attestation.json")
    original_link = rollback_drill.os.link

    def create_attestation_racer(source, target):
        target_path = type(raced_attestation)(target)
        target_path.write_text("racer-owned", encoding="utf-8")
        return original_link(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(rollback_drill.os, "link", create_attestation_racer)
        with pytest.raises(
            RollbackDrillInvariantError,
            match="external_attestation_output_exists",
        ):
            attest_external_evidence(
                evidence_path=unsigned,
                private_key_path=inputs["external_private_key"],
                trusted_approval_public_key=inputs["approval_public_key"],
                output_path=raced_attestation,
            )
    assert raced_attestation.read_text(encoding="utf-8") == "racer-owned"

    raced_private = tmp_path / "raced-private.pem"
    raced_public = tmp_path / "raced-public.pem"

    def create_key_racer(source, target):
        target_path = type(raced_public)(target)
        target_path.write_text("racer-owned", encoding="utf-8")
        return original_link(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(rollback_drill.os, "link", create_key_racer)
        with pytest.raises(
            RollbackDrillInvariantError,
            match="public_key_already_exists",
        ):
            generate_signing_keypair(
                private_key_path=raced_private,
                public_key_path=raced_public,
            )
    assert raced_public.read_text(encoding="utf-8") == "racer-owned"
    assert not raced_private.exists()


def test_qualification_bundle_copy_is_atomic_and_retryable(
    tmp_path,
    monkeypatch,
) -> None:
    inputs = _prepare_qualification_inputs(tmp_path, "rollback-atomic-copy")
    qualification_path = tmp_path / "qualification" / "qualification.json"
    original_copy = rollback_drill.shutil.copy2
    copy_count = 0

    def fail_during_copy(source, target, *args, **kwargs):
        nonlocal copy_count
        copy_count += 1
        if copy_count == 3:
            raise OSError("injected copy failure")
        return original_copy(source, target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(rollback_drill.shutil, "copy2", fail_during_copy)
        with pytest.raises(OSError, match="injected copy failure"):
            qualify_rollback_evidence(
                local_evidence_path=inputs["local_evidence"],
                external_evidence_path=inputs["external_evidence"],
                private_key_path=inputs["qualification_private_key"],
                trusted_external_public_key=inputs["external_public_key"],
                trusted_approval_public_key=inputs["approval_public_key"],
                output_path=qualification_path,
            )

    assert not qualification_path.parent.exists()
    assert not list(tmp_path.glob(".qualification.*.tmp"))

    evidence = qualify_rollback_evidence(
        local_evidence_path=inputs["local_evidence"],
        external_evidence_path=inputs["external_evidence"],
        private_key_path=inputs["qualification_private_key"],
        trusted_external_public_key=inputs["external_public_key"],
        trusted_approval_public_key=inputs["approval_public_key"],
        output_path=qualification_path,
    )
    assert evidence["overall_status"] == "passed"


def test_external_evidence_rejects_semantically_unbound_artifact(tmp_path) -> None:
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-artifact-contract",
        candidate="a" * 40,
        rollback="b" * 40,
    )
    payload = json.loads(external_path.read_text(encoding="utf-8"))
    _replace_artifact(
        external_path.parent,
        payload,
        role="candidate_projection",
        content={"role": "candidate_projection", "drill_id": payload["drill_id"]},
    )
    _write_evidence_with_checksum(external_path, payload)
    private_key = tmp_path / "external-private.pem"
    public_key = tmp_path / "external-public.pem"
    generate_signing_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )

    with pytest.raises(
        (RollbackDrillInvariantError, ValueError),
        match="candidate_projection",
    ):
        attest_external_evidence(
            evidence_path=external_path,
            private_key_path=private_key,
            trusted_approval_public_key=_approval_public_key(external_path),
            output_path=external_path.with_name("external-evidence.signed.json"),
        )


def test_unsigned_external_evidence_requires_real_approval_signature(tmp_path) -> None:
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-unsigned-external",
        candidate="a" * 40,
        rollback="b" * 40,
    )

    evidence = verify_unsigned_external_evidence(
        external_path,
        trusted_approval_public_key=_approval_public_key(external_path),
    )

    assert evidence["status"] == "passed"
    assert "attestation" not in evidence


def test_staging_finalize_binds_signed_approval_request_to_technical_bundle(
    tmp_path,
) -> None:
    source_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-staging-finalize",
        candidate="a" * 40,
        rollback="b" * 40,
    )
    external = json.loads(source_path.read_text(encoding="utf-8"))
    technical = {
        "schema": rollback_staging.TECHNICAL_EVIDENCE_SCHEMA,
        "status": "awaiting_approval",
        "drill_id": external["drill_id"],
        "drill_completed_at": external["drill_completed_at"],
        "candidate_release_digest": external["candidate_release_digest"],
        "rollback_release_digest": external["rollback_release_digest"],
        "postgresql": external["postgresql"],
        "external_effect": external["external_effect"],
        "orchestrator": external["orchestrator"],
        "external_gates": external["external_gates"],
        "artifacts": [
            item for item in external["artifacts"] if item["role"] != "approval_record"
        ],
    }
    technical["evidence_checksum"] = checksum_for(technical)
    technical_path = source_path.parent / "technical-evidence.json"
    technical_path.write_text(json.dumps(technical), encoding="utf-8")
    approval_request = {
        "schema": rollback_staging.APPROVAL_REQUEST_SCHEMA,
        "status": "awaiting_approval",
        "drill_id": technical["drill_id"],
        "candidate_release_digest": technical["candidate_release_digest"],
        "rollback_release_digest": technical["rollback_release_digest"],
        "drill_completed_at": technical["drill_completed_at"],
        "decision_required": "approved",
        "evidence_summary_checksum": checksum_for(
            rollback_drill._approval_summary(
                {**technical, "schema": EXTERNAL_EVIDENCE_SCHEMA}
            )
        ),
        "artifact_checksums": {
            item["role"]: item["checksum"] for item in technical["artifacts"]
        },
    }
    approval_request["request_checksum"] = checksum_for(approval_request)
    approval_request_path = source_path.parent / "approval-request.json"
    approval_request_path.write_text(json.dumps(approval_request), encoding="utf-8")
    approval_request = json.loads(approval_request_path.read_text(encoding="utf-8"))
    request_checksum = approval_request.pop("request_checksum")
    assert request_checksum == checksum_for(approval_request)
    assert approval_request == {
        "schema": rollback_staging.APPROVAL_REQUEST_SCHEMA,
        "status": "awaiting_approval",
        "drill_id": technical["drill_id"],
        "candidate_release_digest": technical["candidate_release_digest"],
        "rollback_release_digest": technical["rollback_release_digest"],
        "drill_completed_at": technical["drill_completed_at"],
        "decision_required": "approved",
        "evidence_summary_checksum": checksum_for(
            rollback_drill._approval_summary(
                {**technical, "schema": EXTERNAL_EVIDENCE_SCHEMA}
            )
        ),
        "artifact_checksums": {
            item["role"]: item["checksum"] for item in technical["artifacts"]
        },
    }

    approval_record_payload = {
        "schema": rollback_drill.APPROVAL_RECORD_SCHEMA,
        "drill_id": approval_request["drill_id"],
        "candidate_release_digest": approval_request["candidate_release_digest"],
        "rollback_release_digest": approval_request["rollback_release_digest"],
        "drill_completed_at": approval_request["drill_completed_at"],
        "operator_id": "operator-requester",
        "approver_id": "approver-authority",
        "approved_at": _utc_text(datetime.now(UTC)),
        "decision": approval_request["decision_required"],
        "evidence_summary_checksum": approval_request["evidence_summary_checksum"],
        "artifact_checksums": approval_request["artifact_checksums"],
    }
    approval_record = source_path.parent / "separate-approval-record.json"
    approval_record_bytes = json.dumps(
        approval_record_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    approval_record.write_bytes(approval_record_bytes)
    approval_private_key = source_path.parent / "separate-approval-private.pem"
    approval_public_key = source_path.parent / "separate-approval-public.pem"
    generate_signing_keypair(
        private_key_path=approval_private_key,
        public_key_path=approval_public_key,
    )
    approval_signature = source_path.parent / "separate-approval-record.sig"
    approval_signature.write_text(
        base64.b64encode(
            rollback_drill._load_private_key(approval_private_key).sign(
                approval_record_bytes
            )
        ).decode("ascii"),
        encoding="ascii",
    )

    invalid_signature = source_path.parent / "invalid-approval-record.sig"
    invalid_signature.write_bytes(b"\x00" * 64)
    rejected_output = tmp_path / "rejected-external" / "external-evidence.json"
    with pytest.raises(
        rollback_staging.StagingRollbackError,
        match="approval_signature_invalid",
    ):
        rollback_staging.finalize_external_evidence(
            technical_evidence_path=technical_path,
            approval_record_path=approval_record,
            approval_signature_path=invalid_signature,
            trusted_approval_public_key=approval_public_key,
            output_path=rejected_output,
        )
    assert not rejected_output.parent.exists()

    output = tmp_path / "unsigned-external" / "external-evidence.json"

    finalized = rollback_staging.finalize_external_evidence(
        technical_evidence_path=technical_path,
        approval_record_path=approval_record,
        approval_signature_path=approval_signature,
        trusted_approval_public_key=approval_public_key,
        output_path=output,
    )

    assert finalized["status"] == "passed"
    assert finalized["approval"]["operator_id"] == "operator-requester"
    assert output.is_file()


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            "postgres_canonical_checksum",
            "postgres_before_canonical_events_checksum_mismatch",
        ),
        (
            "projection_canonical_checksum",
            "candidate_projection_content_mismatch",
        ),
        (
            "projection_native_checksum",
            "projection_source_checksum_mismatch",
        ),
        (
            "projection_source_alias",
            "projection_source_refs_not_distinct",
        ),
    ],
)
def test_external_evidence_separates_native_and_canonical_checksums(
    tmp_path,
    mutation,
    reason,
) -> None:
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id=f"rollback-checksum-{mutation}",
        candidate="a" * 40,
        rollback="b" * 40,
    )
    payload = json.loads(external_path.read_text(encoding="utf-8"))
    artifacts = {
        item["role"]: json.loads(
            (external_path.parent / item["path"]).read_text(encoding="utf-8")
        )
        for item in payload["artifacts"]
        if item["role"] != "approval_record"
    }
    candidate = artifacts["candidate_projection"]
    assert candidate["source_checksum"] == candidate["projection_checksum"]
    assert candidate["source_checksum"] != candidate["canonical_events_checksum"]

    role = "candidate_projection"
    artifact = candidate
    if mutation == "postgres_canonical_checksum":
        role = "postgres_before_snapshot"
        artifact = artifacts[role]
        artifact["canonical_events_checksum"] = _test_checksum("changed-canonical")
    elif mutation == "projection_canonical_checksum":
        artifact["canonical_events_checksum"] = _test_checksum("changed-canonical")
    elif mutation == "projection_native_checksum":
        role = "rollback_projection"
        artifact = artifacts[role]
        changed = _test_checksum("changed-native-projection")
        artifact["source_checksum"] = changed
        artifact["projection_checksum"] = changed
    else:
        role = "rollback_projection"
        artifact = artifacts[role]
        artifact["source_ref"] = candidate["source_ref"]

    _replace_artifact(
        external_path.parent,
        payload,
        role=role,
        content=artifact,
    )
    _resign_external_approval(
        external_path.parent,
        payload,
        _approval_private_key(external_path),
    )
    _write_evidence_with_checksum(external_path, payload)
    private_key = tmp_path / "external-private.pem"
    public_key = tmp_path / "external-public.pem"
    generate_signing_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )

    with pytest.raises(RollbackDrillInvariantError, match=reason):
        attest_external_evidence(
            evidence_path=external_path,
            private_key_path=private_key,
            trusted_approval_public_key=_approval_public_key(external_path),
            output_path=external_path.with_name("external-evidence.signed.json"),
        )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "preserved_event_count",
            0,
            "preserved_event_count_invalid",
        ),
        (
            "delivery_history_checksum_after",
            f"sha256:{sha256(b'changed-delivery-history').hexdigest()}",
            "postgres_delivery_history_checksum_changed",
        ),
    ],
)
def test_external_evidence_rejects_empty_or_changed_postgres_history(
    tmp_path,
    field,
    value,
    reason,
) -> None:
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id=f"rollback-postgres-{field}",
        candidate="a" * 40,
        rollback="b" * 40,
    )
    payload = json.loads(external_path.read_text(encoding="utf-8"))
    payload["postgresql"][field] = value
    _write_evidence_with_checksum(external_path, payload)
    private_key = tmp_path / "external-private.pem"
    public_key = tmp_path / "external-public.pem"
    generate_signing_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )

    with pytest.raises(RollbackDrillInvariantError, match=reason):
        attest_external_evidence(
            evidence_path=external_path,
            private_key_path=private_key,
            trusted_approval_public_key=_approval_public_key(external_path),
            output_path=external_path.with_name("external-evidence.signed.json"),
        )


def test_local_drill_evidence_output_cannot_escape_or_alias_workspace(
    tmp_path,
) -> None:
    sentinel = tmp_path / "sentinel.json"
    sentinel.write_text("must-remain-unchanged", encoding="utf-8")
    workspace = tmp_path / "workspace"

    with pytest.raises(
        RollbackDrillInvariantError,
        match="local_evidence_output_outside_workspace",
    ):
        rollback_drill.run_rollback_drill(
            workspace=workspace,
            evidence_path=sentinel,
        )
    assert sentinel.read_text(encoding="utf-8") == "must-remain-unchanged"
    assert not any(workspace.iterdir())

    alias_workspace = tmp_path / "alias-workspace"
    with pytest.raises(
        RollbackDrillInvariantError,
        match="local_evidence_output_outside_workspace",
    ):
        rollback_drill.run_rollback_drill(
            workspace=alias_workspace,
            evidence_path=alias_workspace / "canonical" / "events.sqlite3",
        )
    assert not any(alias_workspace.iterdir())


def test_strict_verifier_rebinds_local_release_context(tmp_path) -> None:
    inputs = _prepare_qualification_inputs(tmp_path, "rollback-local-release-bind")
    qualification_path = tmp_path / "qualification" / "qualification.json"
    qualify_rollback_evidence(
        local_evidence_path=inputs["local_evidence"],
        external_evidence_path=inputs["external_evidence"],
        private_key_path=inputs["qualification_private_key"],
        trusted_external_public_key=inputs["external_public_key"],
        trusted_approval_public_key=inputs["approval_public_key"],
        output_path=qualification_path,
    )
    local_path = qualification_path.parent / "local" / "rollback-evidence.json"
    local = json.loads(local_path.read_text(encoding="utf-8"))
    local["release_context"]["candidate_release"] = "c" * 40
    _write_evidence_with_checksum(local_path, local)
    local = json.loads(local_path.read_text(encoding="utf-8"))
    qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    qualification["local_evidence"]["checksum"] = local["evidence_checksum"]
    _resign_qualification(
        qualification_path,
        qualification,
        inputs["qualification_private_key"],
    )

    with pytest.raises(
        RollbackDrillInvariantError,
        match="local_release_context_mismatch",
    ):
        verify_rollback_evidence(
            qualification_path,
            trusted_public_key=inputs["qualification_public_key"],
            trusted_external_public_key=inputs["external_public_key"],
            trusted_approval_public_key=inputs["approval_public_key"],
        )


def test_qualification_binds_the_complete_external_attestation_file(tmp_path) -> None:
    inputs = _prepare_qualification_inputs(tmp_path, "rollback-attestation-instance")
    qualification_path = tmp_path / "qualification" / "qualification.json"
    qualify_rollback_evidence(
        local_evidence_path=inputs["local_evidence"],
        external_evidence_path=inputs["external_evidence"],
        private_key_path=inputs["qualification_private_key"],
        trusted_external_public_key=inputs["external_public_key"],
        trusted_approval_public_key=inputs["approval_public_key"],
        output_path=qualification_path,
    )
    replacement = inputs["external_evidence"].with_name(
        "external-evidence.replacement.json"
    )
    attest_external_evidence(
        evidence_path=inputs["external_evidence"].with_name("external-evidence.json"),
        private_key_path=inputs["external_private_key"],
        trusted_approval_public_key=inputs["approval_public_key"],
        output_path=replacement,
    )
    bundled_external = (
        qualification_path.parent / "external" / "external-evidence.json"
    )
    shutil.copy2(replacement, bundled_external)

    with pytest.raises(
        RollbackDrillInvariantError,
        match="external_evidence_bundle_checksum_mismatch",
    ):
        verify_rollback_evidence(
            qualification_path,
            trusted_public_key=inputs["qualification_public_key"],
            trusted_external_public_key=inputs["external_public_key"],
            trusted_approval_public_key=inputs["approval_public_key"],
        )


def test_staged_qualification_verify_failure_is_atomic_and_retryable(
    tmp_path,
    monkeypatch,
) -> None:
    inputs = _prepare_qualification_inputs(tmp_path, "rollback-staged-verify")
    qualification_path = tmp_path / "qualification" / "qualification.json"
    original_verify = rollback_drill._verify_qualification_evidence

    def fail_staged_verify(path, evidence, **kwargs):
        if path.parent.name.startswith(".qualification."):
            raise RollbackDrillInvariantError("injected_staged_verify_failure")
        return original_verify(path, evidence, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(
            rollback_drill,
            "_verify_qualification_evidence",
            fail_staged_verify,
        )
        with pytest.raises(
            RollbackDrillInvariantError,
            match="injected_staged_verify_failure",
        ):
            qualify_rollback_evidence(
                local_evidence_path=inputs["local_evidence"],
                external_evidence_path=inputs["external_evidence"],
                private_key_path=inputs["qualification_private_key"],
                trusted_external_public_key=inputs["external_public_key"],
                trusted_approval_public_key=inputs["approval_public_key"],
                output_path=qualification_path,
            )

    assert not qualification_path.parent.exists()
    assert not list(tmp_path.glob(".qualification.*.tmp"))
    evidence = qualify_rollback_evidence(
        local_evidence_path=inputs["local_evidence"],
        external_evidence_path=inputs["external_evidence"],
        private_key_path=inputs["qualification_private_key"],
        trusted_external_public_key=inputs["external_public_key"],
        trusted_approval_public_key=inputs["approval_public_key"],
        output_path=qualification_path,
    )
    assert evidence["overall_status"] == "passed"


def test_local_evidence_cannot_be_promoted_by_rewriting_status(tmp_path) -> None:
    workspace = tmp_path / "rollback-drill"
    assert main(["run", "--workspace", str(workspace)]) == 2
    evidence_path = workspace / "rollback-evidence.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["overall_status"] = "passed"
    payload["unverified_external_gates"] = []
    payload.pop("evidence_checksum")
    from framework.events.canonical import checksum_for

    payload["evidence_checksum"] = checksum_for(payload)
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        RollbackDrillInvariantError,
        match="local_status_not_incomplete",
    ):
        verify_rollback_evidence(evidence_path, allow_incomplete_local=True)


def test_local_evidence_rejects_missing_required_phase(tmp_path) -> None:
    workspace = tmp_path / "rollback-drill"
    assert main(["run", "--workspace", str(workspace)]) == 2
    evidence_path = workspace / "rollback-evidence.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["phases"].pop()
    payload.pop("evidence_checksum")
    from framework.events.canonical import checksum_for

    payload["evidence_checksum"] = checksum_for(payload)
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        RollbackDrillInvariantError,
        match="evidence_phase_set_invalid",
    ):
        verify_rollback_evidence(evidence_path, allow_incomplete_local=True)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("fake_digest", "candidate_release_digest_invalid"),
        ("missing_artifact", "evidence_artifact_role_set_invalid"),
    ],
)
def test_qualification_rejects_incomplete_external_evidence(
    tmp_path,
    mutation,
    reason,
) -> None:
    candidate = "a" * 40
    rollback = "b" * 40
    local_root = tmp_path / "local-source"
    assert (
        main(
            [
                "run",
                "--workspace",
                str(local_root),
                "--drill-id",
                "rollback-invalid-external",
                "--candidate-release",
                candidate,
                "--rollback-release",
                rollback,
            ]
        )
        == 2
    )
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id="rollback-invalid-external",
        candidate=candidate,
        rollback=rollback,
    )
    payload = json.loads(external_path.read_text(encoding="utf-8"))
    if mutation == "fake_digest":
        payload["candidate_release_digest"] = "candidate-label"
    else:
        payload["artifacts"].pop()
    payload.pop("evidence_checksum")
    from framework.events.canonical import checksum_for

    payload["evidence_checksum"] = checksum_for(payload)
    external_path.write_text(json.dumps(payload), encoding="utf-8")
    private_key = tmp_path / "external-private.pem"
    public_key = tmp_path / "external-public.pem"
    generate_signing_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )
    with pytest.raises(RollbackDrillInvariantError, match=reason):
        attest_external_evidence(
            evidence_path=external_path,
            private_key_path=private_key,
            trusted_approval_public_key=_approval_public_key(external_path),
            output_path=external_path.with_name("external-evidence.signed.json"),
        )


def test_rollback_drill_refuses_nonempty_workspace_without_mutation(
    tmp_path,
    capsys,
) -> None:
    workspace = tmp_path / "existing"
    workspace.mkdir()
    sentinel = workspace / "production.sqlite3"
    sentinel.write_bytes(b"must-remain-unchanged")

    assert main(["run", "--workspace", str(workspace)]) == 1

    assert sentinel.read_bytes() == b"must-remain-unchanged"
    assert not (workspace / "rollback-evidence.json").exists()
    assert '"reason_class":"ValueError"' in capsys.readouterr().err


def _prepare_qualification_inputs(tmp_path, drill_id: str):
    candidate = "a" * 40
    rollback = "b" * 40
    local_root = tmp_path / "local-source"
    assert (
        main(
            [
                "run",
                "--workspace",
                str(local_root),
                "--drill-id",
                drill_id,
                "--candidate-release",
                candidate,
                "--rollback-release",
                rollback,
            ]
        )
        == 2
    )
    external_path = _write_external_evidence(
        tmp_path / "external-source",
        drill_id=drill_id,
        candidate=candidate,
        rollback=rollback,
    )
    approval_private_key = _approval_private_key(external_path)
    approval_public_key = _approval_public_key(external_path)
    key_root = tmp_path / "keys"
    qualification_private_key = key_root / "qualification-private.pem"
    qualification_public_key = key_root / "qualification-public.pem"
    external_private_key = key_root / "external-private.pem"
    external_public_key = key_root / "external-public.pem"
    generate_signing_keypair(
        private_key_path=qualification_private_key,
        public_key_path=qualification_public_key,
    )
    generate_signing_keypair(
        private_key_path=external_private_key,
        public_key_path=external_public_key,
    )
    signed_external_path = external_path.with_name("external-evidence.signed.json")
    attest_external_evidence(
        evidence_path=external_path,
        private_key_path=external_private_key,
        trusted_approval_public_key=approval_public_key,
        output_path=signed_external_path,
    )
    return {
        "local_evidence": local_root / "rollback-evidence.json",
        "external_evidence": signed_external_path,
        "qualification_private_key": qualification_private_key,
        "qualification_public_key": qualification_public_key,
        "external_private_key": external_private_key,
        "external_public_key": external_public_key,
        "approval_private_key": approval_private_key,
        "approval_public_key": approval_public_key,
    }


def _write_evidence_with_checksum(path, payload) -> None:
    payload.pop("evidence_checksum", None)
    payload["evidence_checksum"] = checksum_for(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _replace_artifact(root, evidence, *, role: str, content) -> None:
    manifest = next(item for item in evidence["artifacts"] if item["role"] == role)
    artifact_path = root / manifest["path"]
    payload = json.dumps(content, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    artifact_path.write_bytes(payload)
    manifest["size_bytes"] = len(payload)
    manifest["checksum"] = f"sha256:{sha256(payload).hexdigest()}"


def _resign_qualification(path, evidence, private_key_path) -> None:
    evidence.pop("signature", None)
    evidence.pop("evidence_checksum", None)
    evidence["evidence_checksum"] = checksum_for(evidence)
    key = rollback_drill._load_private_key(private_key_path)
    signature = key.sign(rollback_drill._qualification_signature_payload(evidence))
    evidence["signature"] = base64.b64encode(signature).decode("ascii")
    path.write_text(json.dumps(evidence), encoding="utf-8")


def _resign_external_approval(root, evidence, private_key_path) -> None:
    approval = evidence["approval"]
    manifest = next(
        item for item in evidence["artifacts"] if item["role"] == "approval_record"
    )
    artifact_checksums = {
        item["role"]: item["checksum"]
        for item in evidence["artifacts"]
        if item["role"] != "approval_record"
    }
    record = {
        "schema": "newsroom.durable-event-rollback-approval/v1",
        "drill_id": evidence["drill_id"],
        "candidate_release_digest": evidence["candidate_release_digest"],
        "rollback_release_digest": evidence["rollback_release_digest"],
        "drill_completed_at": evidence["drill_completed_at"],
        "operator_id": approval["operator_id"],
        "approver_id": approval["approver_id"],
        "approved_at": approval["approved_at"],
        "decision": "approved",
        "evidence_summary_checksum": checksum_for(
            rollback_drill._approval_summary(evidence)
        ),
        "artifact_checksums": artifact_checksums,
    }
    content = json.dumps(record, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    path = root / manifest["path"]
    path.write_bytes(content)
    key = rollback_drill._load_private_key(private_key_path)
    record_checksum = f"sha256:{sha256(content).hexdigest()}"
    approval.update(
        {
            "record_checksum": record_checksum,
            "public_key_fingerprint": rollback_drill._public_key_fingerprint(
                key.public_key()
            ),
            "signature": base64.b64encode(key.sign(content)).decode("ascii"),
        }
    )
    manifest.update(
        {
            "size_bytes": len(content),
            "checksum": record_checksum,
        }
    )


def _make_private_key_insecure(path) -> None:
    if os.name != "nt":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        return

    import ntsecuritycon
    import win32security

    descriptor = win32security.GetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION,
    )
    owner = descriptor.GetSecurityDescriptorOwner()
    everyone = win32security.CreateWellKnownSid(win32security.WinWorldSid, None)
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION_DS,
        0,
        ntsecuritycon.FILE_ALL_ACCESS,
        owner,
    )
    dacl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION_DS,
        0,
        ntsecuritycon.FILE_GENERIC_READ,
        everyone,
    )
    replacement = win32security.SECURITY_DESCRIPTOR()
    replacement.SetSecurityDescriptorDacl(1, dacl, 0)
    win32security.SetFileSecurity(
        str(path),
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        replacement,
    )


def _write_external_evidence(
    root,
    *,
    drill_id: str,
    candidate: str,
    rollback: str,
    drill_completed_at: datetime | None = None,
    approved_at: datetime | None = None,
):
    root.mkdir(parents=True)
    approval_private_key = root / "approval-private.pem"
    approval_public_key = root / "approval-public.pem"
    generate_signing_keypair(
        private_key_path=approval_private_key,
        public_key_path=approval_public_key,
    )
    completed_at = drill_completed_at or datetime.now(UTC) - timedelta(minutes=2)
    approval_time = approved_at or datetime.now(UTC) - timedelta(minutes=1)
    stream_id = "run:rollback-staging"
    event_rows = _external_event_rows(
        drill_id=drill_id,
        stream_id=stream_id,
        count=21,
        base_time=completed_at - timedelta(minutes=5),
    )
    before_event_rows = event_rows[:20]
    prefix_checksum = checksum_for(before_event_rows)
    after_snapshot_checksum = checksum_for(event_rows)
    effect_checksum = _test_checksum("external-effect")
    ledger_counts = {
        "delivery_history": 3,
        "inbox": 2,
        "checkpoint": 1,
        "dead_letter": 1,
    }
    ledger_checksums = {
        name: _test_checksum(f"{name}-state") for name in ledger_counts
    }
    postgresql = {
        "backend": "postgresql",
        "database_name": "newsroom_rollback_staging",
        "server_version": "18.3",
        "migration_version": "002_durable_events.sql",
        "before_snapshot_ref": (
            "artifact://rollback/postgres_before_snapshot"
        ),
        "after_snapshot_ref": "artifact://rollback/postgres_after_snapshot",
        "stream_id": stream_id,
        "preserved_event_count": 20,
        "preserved_prefix_checksum_before": prefix_checksum,
        "preserved_prefix_checksum_after": prefix_checksum,
        "watermark_before": 20,
        "watermark_after_rejections": 20,
        "next_accepted_sequence": 21,
        "watermark_after": 21,
        "duplicate_sequences": 0,
        "checksum_failures": 0,
        "concurrent_writer_continuity": True,
        "crash_recovery_passed": True,
    }
    for name, count in ledger_counts.items():
        postgresql[f"{name}_count_before"] = count
        postgresql[f"{name}_count_after"] = count
        postgresql[f"{name}_checksum_before"] = ledger_checksums[name]
        postgresql[f"{name}_checksum_after"] = ledger_checksums[name]
    external_effect = {
        "provider": "rollback-staging-provider",
        "provider_kind": "staging_database",
        "idempotency_contract_ref": "artifact://rollback/external_effect_audit",
        "idempotency_key_hash": effect_checksum,
        "invocation_count": 2,
        "applied_effect_count": 1,
        "result_checksum_before": effect_checksum,
        "result_checksum_after": effect_checksum,
        "audited": True,
    }
    orchestrator = {
        "run_ref": "artifact://rollback/orchestrator_run#run",
        "traffic_freeze_ref": "artifact://rollback/traffic_control#freeze",
        "dispatcher_pause_ref": "artifact://rollback/traffic_control#dispatcher",
        "candidate_deployment_ref": (
            "artifact://rollback/orchestrator_run#candidate"
        ),
        "rollback_deployment_ref": (
            "artifact://rollback/orchestrator_run#rollback"
        ),
        "binary_switch_observed": True,
        "claims_frozen_during_switch": True,
        "concurrent_dispatchers_observed": 0,
    }
    payload = {
        "schema": EXTERNAL_EVIDENCE_SCHEMA,
        "status": "passed",
        "drill_id": drill_id,
        "drill_completed_at": _utc_text(completed_at),
        "candidate_release_digest": candidate,
        "rollback_release_digest": rollback,
        "postgresql": postgresql,
        "external_effect": external_effect,
        "orchestrator": orchestrator,
        "external_gates": {
            "actual_deployment_binary_switch": True,
            "real_postgresql_rollback_and_concurrent_writer_continuity": True,
            "production_external_effect_provider_idempotency": True,
            "deployment_orchestrator_and_traffic_control_evidence": True,
            "accepted_events_and_sequences_preserved": True,
            "schema_security_identity_integrity_gates_enabled": True,
            "compatible_projection_rebuilt": True,
        },
    }

    approval = {
        "operator_id": "operator-1",
        "approver_id": "approver-1",
        "approved_at": _utc_text(approval_time),
        "decision": "approved",
        "record_ref": "artifact://rollback/approval_record",
    }
    def source(role: str) -> dict[str, str]:
        return {
            "source_ref": f"https://evidence.example/{drill_id}/{role}",
            "source_checksum": _test_checksum(f"raw-{role}"),
        }
    ledgers_before = {
        name: {"count": count, "checksum": ledger_checksums[name]}
        for name, count in ledger_counts.items()
    }
    ledgers_after = json.loads(json.dumps(ledgers_before))
    canonical_projection_checksum = checksum_for(before_event_rows)
    native_projection_checksum = _test_checksum("native-projection")
    sequence_checksum = checksum_for(list(range(1, 21)))
    artifact_payloads = {
        "orchestrator_run": {
            "schema": "newsroom.durable-event-rollback-orchestrator/v1",
            "drill_id": drill_id,
            **source("orchestrator-run"),
            "run_id": "deployment-run-rollback-1",
            "candidate_deployment_id": "deployment-candidate-1",
            "rollback_deployment_id": "deployment-rollback-1",
            "candidate_release_digest": candidate,
            "rollback_release_digest": rollback,
            "binary_switch_observed": True,
            "concurrent_dispatchers_observed": 0,
        },
        "traffic_control": {
            "schema": "newsroom.durable-event-rollback-traffic-control/v1",
            "drill_id": drill_id,
            **source("traffic-control"),
            "traffic_frozen": True,
            "dispatcher_claims_paused": True,
            "concurrent_dispatchers_observed": 0,
        },
        "postgres_before_snapshot": {
            "schema": "newsroom.durable-event-rollback-postgres-snapshot/v2",
            "drill_id": drill_id,
            "stage": "before",
            "source_ref": (
                f"https://evidence.example/{drill_id}/postgres-before-snapshot"
            ),
            "source_checksum": _test_checksum("raw-postgres-before-snapshot"),
            "backend": "postgresql",
            "database_name": postgresql["database_name"],
            "server_version": postgresql["server_version"],
            "migration_version": postgresql["migration_version"],
            "stream_id": postgresql["stream_id"],
            "ledgers": ledgers_before,
            "release_digest": candidate,
            "captured_at": _utc_text(completed_at - timedelta(seconds=20)),
            "canonical_events_checksum": prefix_checksum,
            "events": before_event_rows,
            "event_count": 20,
            "prefix_checksum": prefix_checksum,
            "watermark": 20,
        },
        "postgres_after_snapshot": {
            "schema": "newsroom.durable-event-rollback-postgres-snapshot/v2",
            "drill_id": drill_id,
            "stage": "after",
            "source_ref": (
                f"https://evidence.example/{drill_id}/postgres-after-snapshot"
            ),
            "source_checksum": _test_checksum("raw-postgres-after-snapshot"),
            "backend": "postgresql",
            "database_name": postgresql["database_name"],
            "server_version": postgresql["server_version"],
            "migration_version": postgresql["migration_version"],
            "stream_id": postgresql["stream_id"],
            "ledgers": ledgers_after,
            "release_digest": rollback,
            "captured_at": _utc_text(completed_at - timedelta(seconds=5)),
            "canonical_events_checksum": after_snapshot_checksum,
            "events": event_rows,
            "event_count": 21,
            "preserved_prefix_count": 20,
            "preserved_prefix_checksum": prefix_checksum,
            "watermark_after_rejections": 20,
            "next_accepted_sequence": 21,
            "watermark": 21,
            "duplicate_sequences": 0,
            "checksum_failures": 0,
            "concurrent_writer_continuity": True,
            "crash_recovery_passed": True,
        },
        "external_effect_audit": {
            "schema": "newsroom.durable-event-rollback-effect-audit/v1",
            "drill_id": drill_id,
            **source("external-effect-audit"),
            **{
                field: external_effect[field]
                for field in (
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
        "candidate_projection": {
            "schema": "newsroom.durable-event-rollback-projection/v2",
            "drill_id": drill_id,
            "role": "candidate",
            "source_ref": f"https://evidence.example/{drill_id}/candidate.jsonl",
            "source_checksum": native_projection_checksum,
            "release_digest": candidate,
            "stream_id": postgresql["stream_id"],
            "high_watermark": 20,
            "event_count": 20,
            "ordered_sequence_checksum": sequence_checksum,
            "canonical_events_checksum": canonical_projection_checksum,
            "projection_checksum": native_projection_checksum,
            "events": before_event_rows,
        },
        "rollback_projection": {
            "schema": "newsroom.durable-event-rollback-projection/v2",
            "drill_id": drill_id,
            "role": "rollback",
            "source_ref": f"https://evidence.example/{drill_id}/rollback.jsonl",
            "source_checksum": native_projection_checksum,
            "release_digest": rollback,
            "stream_id": postgresql["stream_id"],
            "high_watermark": 20,
            "event_count": 20,
            "ordered_sequence_checksum": sequence_checksum,
            "canonical_events_checksum": canonical_projection_checksum,
            "projection_checksum": native_projection_checksum,
            "events": before_event_rows,
        },
        "schema_security_negative_tests": {
            "schema": "newsroom.durable-event-rollback-negative-tests/v1",
            "drill_id": drill_id,
            **source("schema-security-negative-tests"),
            "watermark_before": 20,
            "watermark_after": 20,
            "cases": [
                {
                    "case": "unknown_schema",
                    "outcome": "rejected",
                    "reason_class": "EventUnknownSchemaError",
                },
                {
                    "case": "forbidden_payload",
                    "outcome": "rejected",
                    "reason_class": "EventSecurityError",
                },
                {
                    "case": "identity_collision",
                    "outcome": "rejected",
                    "reason_class": "EventIdentityCollisionError",
                },
                {
                    "case": "record_checksum_tamper",
                    "outcome": "rejected",
                    "reason_class": "EventRecordChecksumError",
                },
            ],
        },
    }
    artifacts = []
    for role, artifact_payload in artifact_payloads.items():
        relative = f"artifacts/{role}.json"
        artifact_path = root / relative
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(
            artifact_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        artifact_path.write_bytes(content)
        artifacts.append(
            {
                "role": role,
                "path": relative,
                "size_bytes": len(content),
                "checksum": f"sha256:{sha256(content).hexdigest()}",
            }
        )

    payload["artifacts"] = artifacts
    artifact_checksums = {
        item["role"]: item["checksum"] for item in artifacts
    }
    approval_record = {
        "schema": "newsroom.durable-event-rollback-approval/v1",
        "drill_id": drill_id,
        "candidate_release_digest": candidate,
        "rollback_release_digest": rollback,
        "drill_completed_at": _utc_text(completed_at),
        "operator_id": approval["operator_id"],
        "approver_id": approval["approver_id"],
        "approved_at": approval["approved_at"],
        "decision": "approved",
        "evidence_summary_checksum": checksum_for(
            rollback_drill._approval_summary(payload)
        ),
        "artifact_checksums": artifact_checksums,
    }
    approval_relative = "artifacts/approval_record.json"
    approval_path = root / approval_relative
    approval_content = json.dumps(
        approval_record,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    approval_path.write_bytes(approval_content)
    approval_key = rollback_drill._load_private_key(approval_private_key)
    approval.update(
        {
            "record_checksum": (
                f"sha256:{sha256(approval_content).hexdigest()}"
            ),
            "public_key_fingerprint": rollback_drill._public_key_fingerprint(
                approval_key.public_key()
            ),
            "signature": base64.b64encode(
                approval_key.sign(approval_content)
            ).decode("ascii"),
        }
    )
    artifacts.append(
        {
            "role": "approval_record",
            "path": approval_relative,
            "size_bytes": len(approval_content),
            "checksum": approval["record_checksum"],
        }
    )
    payload["approval"] = approval
    payload["evidence_checksum"] = checksum_for(payload)
    path = root / "external-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _external_event_rows(
    *,
    drill_id: str,
    stream_id: str,
    count: int,
    base_time: datetime,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for sequence in range(1, count + 1):
        occurred_at = base_time + timedelta(seconds=sequence)
        candidate = EventCandidate(
            event_id=f"{drill_id}:event:{sequence}",
            event_type="io.newsroom.event.rollback.drill",
            data_schema="io.newsroom.event.rollback.drill/v1",
            source="tests.rollback.staging",
            occurred_at=occurred_at,
            stream_id=stream_id,
            business_context=BusinessContext(run_id="rollback-staging"),
            producer=ProducerIdentity(
                component="rollback-test-fixture",
                version="1",
                instance_id="pytest",
            ),
            tenant_id="tenant-rollback-staging",
            payload={"drill_id": drill_id, "sequence": sequence},
        )
        rows.append(
            StoredEvent(
                candidate=candidate,
                observed_at=occurred_at + timedelta(milliseconds=1),
                stream_sequence=sequence,
            ).to_dict()
        )
    return rows


def _approval_private_key(external_path):
    return external_path.parent / "approval-private.pem"


def _approval_public_key(external_path):
    return external_path.parent / "approval-public.pem"


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _test_checksum(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"
