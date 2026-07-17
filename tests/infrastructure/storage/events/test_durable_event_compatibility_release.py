from __future__ import annotations

import base64
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import scripts.durable_event_compatibility_release as compatibility
from framework.events.canonical import checksum_for
from framework.shared.json import stable_json_dumps
from scripts.durable_event_compatibility_release import (
    CompatibilityObservationError,
    verify_compatibility_release_evidence,
)


CANDIDATE = compatibility.COMPATIBILITY_RELEASE
DELETION_BOUNDARY = compatibility.DELETION_BOUNDARY
QUALIFIED_DELETION = compatibility.QUALIFIED_DELETION_RELEASE
ROOT = Path(__file__).resolve().parents[4]
TRACKED_POLICY = (
    ROOT
    / "openspec"
    / "changes"
    / "durable-event-runtime"
    / "evidence"
    / "compatibility-observation-policy.json"
)
TRACKED_PENDING_POLICY_CHECKSUM = (
    "sha256:383355c7a5382fb47448346a1da8f6c3f38475615042cbab8a5072c128d4eb1f"
)
TEST_OBSERVER_AUTHORITY_ID = "deployment-observer"
TEST_OBSERVER_KEY_ID = "deployment-observer-ed25519-test"
TEST_CONSUMER_OWNER_AUTHORITY_ID = "consumer-registry-owner"
TEST_CONSUMER_OWNER_KEY_ID = "consumer-registry-owner-ed25519-test"
TEST_GOVERNANCE_AUTHORITY_ID = "compatibility-governance"
TEST_GOVERNANCE_KEY_ID = "compatibility-governance-ed25519-test"
TEST_TRUST_EPOCH = 1
TEST_OBSERVER_PRIVATE_KEY_BYTES = bytes.fromhex("11" * 32)
TEST_CONSUMER_OWNER_PRIVATE_KEY_BYTES = bytes.fromhex("22" * 32)
ATTACKER_OBSERVER_PRIVATE_KEY_BYTES = bytes.fromhex("33" * 32)
ATTACKER_CONSUMER_OWNER_PRIVATE_KEY_BYTES = bytes.fromhex("44" * 32)
TEST_GOVERNANCE_PRIVATE_KEY_BYTES = bytes.fromhex("55" * 32)
ATTACKER_GOVERNANCE_PRIVATE_KEY_BYTES = bytes.fromhex("66" * 32)


@pytest.fixture(autouse=True)
def _activate_deterministic_test_authority_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer_key = _test_observer_key()
    owner_key = _test_consumer_owner_key()
    governance_key = _test_governance_key()
    monkeypatch.setattr(
        compatibility,
        "TRUSTED_OBSERVER_AUTHORITY_ID",
        TEST_OBSERVER_AUTHORITY_ID,
    )
    monkeypatch.setattr(
        compatibility,
        "TRUSTED_OBSERVER_KEY_ID",
        TEST_OBSERVER_KEY_ID,
    )
    monkeypatch.setattr(
        compatibility,
        "TRUSTED_OBSERVER_PUBLIC_KEY_FINGERPRINT",
        compatibility._public_key_fingerprint(observer_key.public_key()),
    )
    monkeypatch.setattr(
        compatibility,
        "TRUSTED_CONSUMER_OWNER_AUTHORITY_ID",
        TEST_CONSUMER_OWNER_AUTHORITY_ID,
    )
    monkeypatch.setattr(
        compatibility,
        "TRUSTED_CONSUMER_OWNER_KEY_ID",
        TEST_CONSUMER_OWNER_KEY_ID,
    )
    monkeypatch.setattr(
        compatibility,
        "TRUSTED_CONSUMER_OWNER_PUBLIC_KEY_FINGERPRINT",
        compatibility._public_key_fingerprint(owner_key.public_key()),
    )
    monkeypatch.setattr(
        compatibility,
        "TRUSTED_GOVERNANCE_AUTHORITY_ID",
        TEST_GOVERNANCE_AUTHORITY_ID,
    )
    monkeypatch.setattr(
        compatibility,
        "TRUSTED_GOVERNANCE_KEY_ID",
        TEST_GOVERNANCE_KEY_ID,
    )
    monkeypatch.setattr(
        compatibility,
        "TRUSTED_GOVERNANCE_PUBLIC_KEY_FINGERPRINT",
        compatibility._public_key_fingerprint(governance_key.public_key()),
    )
    monkeypatch.setattr(compatibility, "ACTIVE_TRUST_EPOCH", TEST_TRUST_EPOCH)
    active_policy = _policy_record()
    monkeypatch.setattr(
        compatibility,
        "ACTIVE_AUTHORITY_POLICY_CHECKSUM",
        active_policy["policy_checksum"],
    )


def test_tracked_policy_is_pending_and_cannot_qualify_evidence(
    tmp_path: Path,
) -> None:
    policy = json.loads(TRACKED_POLICY.read_text(encoding="utf-8"))

    compatibility._verify_policy(policy)
    assert policy["schema"] == compatibility.POLICY_SCHEMA
    assert policy["authority_trust_status"] == compatibility.AUTHORITY_TRUST_PENDING
    assert policy["trust_epoch"] is None
    assert policy["trusted_governance_authority"] is None
    assert policy["trusted_observer_authority"] is None
    assert policy["trusted_consumer_owner_authority"] is None
    assert policy["policy_checksum"] == TRACKED_PENDING_POLICY_CHECKSUM
    assert (
        _git("rev-parse", f"{CANDIDATE}^{{tree}}")
        == policy["compatibility_source_tree"]
    )
    assert _git("rev-parse", f"{CANDIDATE}^") == policy["compatibility_parent_commit"]
    assert (
        _git("rev-parse", f"{DELETION_BOUNDARY}^{{tree}}")
        == policy["deletion_boundary_tree"]
    )
    assert _git("rev-parse", f"{DELETION_BOUNDARY}^") == CANDIDATE
    assert (
        _git("rev-parse", f"{QUALIFIED_DELETION}^{{tree}}")
        == policy["qualified_deletion_source_tree"]
    )
    assert (
        _git("rev-parse", f"{QUALIFIED_DELETION}^")
        == policy["qualified_deletion_source_parent_commit"]
    )
    _git("merge-base", "--is-ancestor", DELETION_BOUNDARY, QUALIFIED_DELETION)
    assert (
        int(_git("rev-list", "--count", f"{DELETION_BOUNDARY}..{QUALIFIED_DELETION}"))
        > 0
    )
    bundle = _write_bundle(tmp_path)
    args = dict(bundle["verify_args"])
    args["policy_path"] = TRACKED_POLICY
    with pytest.raises(
        CompatibilityObservationError,
        match=_reason("authority_trust_not_activated"),
    ):
        verify_compatibility_release_evidence(**args)


def test_policy_rejects_a_qualified_source_outside_the_deletion_ancestry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy_record()
    monkeypatch.setattr(compatibility, "QUALIFIED_DELETION_RELEASE", CANDIDATE)
    monkeypatch.setattr(
        compatibility, "QUALIFIED_DELETION_TREE", compatibility.COMPATIBILITY_TREE
    )
    monkeypatch.setattr(
        compatibility,
        "QUALIFIED_DELETION_PARENT",
        compatibility.COMPATIBILITY_PARENT,
    )
    policy["qualified_deletion_source_commit"] = CANDIDATE
    policy["qualified_deletion_source_tree"] = compatibility.COMPATIBILITY_TREE
    policy["qualified_deletion_source_parent_commit"] = (
        compatibility.COMPATIBILITY_PARENT
    )
    _set_policy_checksum(policy)
    monkeypatch.setattr(
        compatibility,
        "ACTIVE_AUTHORITY_POLICY_CHECKSUM",
        policy["policy_checksum"],
    )

    with pytest.raises(
        CompatibilityObservationError,
        match=_reason("policy_deletion_boundary_not_ancestor"),
    ):
        compatibility._verify_policy(policy)


@pytest.mark.parametrize(
    ("authority_field", "root_field", "replacement", "reason"),
    [
        (
            "trusted_governance_authority",
            "authority_id",
            "alternate-governance",
            "policy_trusted_governance_authority_mismatch",
        ),
        (
            "trusted_governance_authority",
            "key_id",
            "alternate-governance-key",
            "policy_trusted_governance_authority_mismatch",
        ),
        (
            "trusted_governance_authority",
            "public_key_fingerprint",
            "sha256:" + "c" * 64,
            "policy_trusted_governance_authority_mismatch",
        ),
        (
            "trusted_observer_authority",
            "authority_id",
            "alternate-observer",
            "policy_trusted_observer_authority_mismatch",
        ),
        (
            "trusted_observer_authority",
            "key_id",
            "alternate-observer-key",
            "policy_trusted_observer_authority_mismatch",
        ),
        (
            "trusted_observer_authority",
            "public_key_fingerprint",
            "sha256:" + "a" * 64,
            "policy_trusted_observer_authority_mismatch",
        ),
        (
            "trusted_consumer_owner_authority",
            "authority_id",
            "alternate-consumer-owner",
            "policy_trusted_consumer_owner_authority_mismatch",
        ),
        (
            "trusted_consumer_owner_authority",
            "key_id",
            "alternate-consumer-owner-key",
            "policy_trusted_consumer_owner_authority_mismatch",
        ),
        (
            "trusted_consumer_owner_authority",
            "public_key_fingerprint",
            "sha256:" + "b" * 64,
            "policy_trusted_consumer_owner_authority_mismatch",
        ),
    ],
)
def test_active_policy_roots_must_match_compiled_authority_constants(
    authority_field: str,
    root_field: str,
    replacement: str,
    reason: str,
) -> None:
    policy = _policy_record()
    policy[authority_field][root_field] = replacement
    _set_policy_checksum(policy)

    with pytest.raises(CompatibilityObservationError, match=_reason(reason)):
        compatibility._verify_policy(policy)


@pytest.mark.parametrize(
    ("authority_field", "reason"),
    [
        (
            "trusted_governance_authority",
            "policy_trusted_governance_authority_algorithm_invalid",
        ),
        (
            "trusted_observer_authority",
            "policy_trusted_observer_authority_algorithm_invalid",
        ),
        (
            "trusted_consumer_owner_authority",
            "policy_trusted_consumer_owner_authority_algorithm_invalid",
        ),
    ],
)
def test_active_policy_authority_algorithm_is_exactly_ed25519(
    authority_field: str,
    reason: str,
) -> None:
    policy = _policy_record()
    policy[authority_field]["algorithm"] = "RSA"
    _set_policy_checksum(policy)

    with pytest.raises(CompatibilityObservationError, match=_reason(reason)):
        compatibility._verify_policy(policy)


def test_alternate_self_checksummed_active_policy_is_rejected() -> None:
    policy = _policy_record()
    policy["required_query_surfaces"].reverse()
    _set_policy_checksum(policy)

    with pytest.raises(
        CompatibilityObservationError,
        match=_reason("active_authority_policy_checksum_mismatch"),
    ):
        compatibility._verify_policy(policy)


def test_active_policy_trust_epoch_must_match_the_compiled_epoch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy_record()
    policy["trust_epoch"] = TEST_TRUST_EPOCH + 1
    _set_policy_checksum(policy)
    monkeypatch.setattr(
        compatibility,
        "ACTIVE_AUTHORITY_POLICY_CHECKSUM",
        policy["policy_checksum"],
    )

    with pytest.raises(
        CompatibilityObservationError,
        match=_reason("compiled_authority_trust_not_activated"),
    ):
        compatibility._verify_policy(policy)


def test_git_verification_is_bounded_and_ignores_ambient_git_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    expected_revisions = {
        f"{compatibility.COMPATIBILITY_RELEASE}^{{tree}}": (
            compatibility.COMPATIBILITY_TREE
        ),
        f"{compatibility.COMPATIBILITY_RELEASE}^": compatibility.COMPATIBILITY_PARENT,
        f"{compatibility.DELETION_BOUNDARY}^{{tree}}": (
            compatibility.DELETION_BOUNDARY_TREE
        ),
        f"{compatibility.DELETION_BOUNDARY}^": (compatibility.DELETION_BOUNDARY_PARENT),
        f"{compatibility.QUALIFIED_DELETION_RELEASE}^{{tree}}": (
            compatibility.QUALIFIED_DELETION_TREE
        ),
        f"{compatibility.QUALIFIED_DELETION_RELEASE}^": (
            compatibility.QUALIFIED_DELETION_PARENT
        ),
    }

    def fake_run(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, kwargs))
        stdout = expected_revisions.get(command[-1], "")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(stdout + "\n").encode("ascii"),
            stderr=b"",
        )

    monkeypatch.setenv("GIT_DIR", "attacker-controlled-git-dir")
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", "attacker-controlled-objects")
    monkeypatch.setenv("GIT_REPLACE_REF_BASE", "refs/replace/attacker")
    monkeypatch.setattr(compatibility.subprocess, "run", fake_run)

    compatibility._verify_policy_git_objects(_policy_record())

    assert len(calls) == 7
    for _command, kwargs in calls:
        assert 0 < kwargs["timeout"] <= 30
        git_env = kwargs["env"]
        assert git_env["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert git_env["GIT_NO_LAZY_FETCH"] == "1"
        assert git_env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert git_env["GIT_CONFIG_GLOBAL"] == os.devnull
        assert "GIT_DIR" not in git_env
        assert "GIT_OBJECT_DIRECTORY" not in git_env
        assert "GIT_REPLACE_REF_BASE" not in git_env


def test_git_timeout_fails_closed_with_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def time_out(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 1))

    monkeypatch.setattr(compatibility.subprocess, "run", time_out)

    with pytest.raises(
        CompatibilityObservationError,
        match=_reason("policy_git_command_timeout"),
    ):
        compatibility._verify_policy_git_objects(_policy_record())


def test_signed_three_record_evidence_and_cli_pass_strict_verification(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = _write_bundle(tmp_path)

    result = verify_compatibility_release_evidence(**bundle["verify_args"])

    assert result["schema"] == compatibility.DELETION_ATTESTATION_SCHEMA
    assert result["status"] == "passed"
    assert result["compatibility_release_digest"] == CANDIDATE
    assert result["deletion_boundary_digest"] == DELETION_BOUNDARY
    assert result["deletion_release_digest"] == QUALIFIED_DELETION
    assert result["deletion_deployment_id"] == "deployment-deletion-1"
    assert result["trust_epoch"] == TEST_TRUST_EPOCH
    assert (
        result["trust_activation_record_checksum"]
        == bundle["activation"]["record_checksum"]
    )
    assert result["governance_authority_id"] == TEST_GOVERNANCE_AUTHORITY_ID
    assert result["governance_key_id"] == TEST_GOVERNANCE_KEY_ID
    assert result["observer_authority_id"] == TEST_OBSERVER_AUTHORITY_ID
    assert result["observer_key_id"] == TEST_OBSERVER_KEY_ID
    assert result["consumer_owner_authority_id"] == TEST_CONSUMER_OWNER_AUTHORITY_ID
    assert result["consumer_owner_key_id"] == TEST_CONSUMER_OWNER_KEY_ID
    assert (
        result["observation_record_checksum"]
        == bundle["observation"]["record_checksum"]
    )
    assert (
        result["consumer_signoff_record_checksum"]
        == bundle["signoff"]["record_checksum"]
    )
    assert (
        result["deletion_attestation_checksum"]
        == bundle["attestation"]["record_checksum"]
    )
    assert (
        result["observation_external_evidence_uri"]
        == bundle["observation"]["external_evidence"]["uri"]
    )
    assert (
        result["deletion_deployment_evidence_uri"]
        == bundle["attestation"]["deployment_evidence"]["uri"]
    )
    assert (
        len(
            {
                result["governance_public_key_fingerprint"],
                result["observer_public_key_fingerprint"],
                result["consumer_owner_public_key_fingerprint"],
            }
        )
        == 3
    )
    assert compatibility.main(_cli_args(bundle)) == 0
    assert '"status":"passed"' in capsys.readouterr().out


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda value: value["observations"]["queries"][0].__setitem__(
                "authoritative_source", "projection"
            ),
            "query_source_not_durable",
        ),
        (
            lambda value: value["observations"]["projections"][0].__setitem__(
                "projection_high_watermark", 1
            ),
            "projection_watermark_mismatch",
        ),
        (
            lambda value: value["consumer_inventory"]["surfaces"].pop(),
            "consumer_surface_coverage_incomplete",
        ),
        (
            lambda value: value["observations"]["queries"].pop(),
            "query_surface_coverage_incomplete",
        ),
        (
            lambda value: value["observations"]["checkpoints"][0].__setitem__(
                "legacy_offset_used", True
            ),
            "checkpoint_legacy_offset_used",
        ),
        (
            lambda value: value["observations"]["projections"][0].__setitem__(
                "raw_secret_findings", 1
            ),
            "projection_secret_finding",
        ),
        (
            lambda value: value["consumer_inventory"]["sources"].pop(),
            "consumer_inventory_sources_incomplete",
        ),
        (
            lambda value: value["consumer_inventory"]["surfaces"][0].__setitem__(
                "flat_record_read_count", 1
            ),
            "flat_record_consumer_found",
        ),
        (
            lambda value: value["compatibility_release"].__setitem__(
                "deployment_uri", "http://localhost:8000/deployments/1"
            ),
            "compatibility_release.deployment_uri_invalid",
        ),
        (
            lambda value: value.__setitem__("deletion_release", {}),
            "observation_fields_invalid",
        ),
    ],
)
def test_observation_business_mutations_fail_closed(
    tmp_path: Path,
    mutation,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    observation = deepcopy(bundle["observation"])
    mutation(observation)
    _write_record(bundle, "observation", observation)

    _assert_rejected(bundle, reason)


def test_every_required_query_run_has_checkpoint_and_projection_evidence(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    observation = deepcopy(bundle["observation"])
    sse_query = next(
        query
        for query in observation["observations"]["queries"]
        if query["surface"] == "sse"
    )
    sse_query["run_id"] = "run-orphan-sse"
    _rewrite_observation_chain(bundle, observation)

    _assert_rejected(bundle, "observation_run_correlation_incomplete")


def test_projection_must_cover_each_observed_source_high_watermark(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    observation = deepcopy(bundle["observation"])
    for query in observation["observations"]["queries"]:
        query["source_high_watermark"] = 9
    for checkpoint in observation["observations"]["checkpoints"]:
        checkpoint["source_high_watermark"] = 9
    _rewrite_observation_chain(bundle, observation)

    _assert_rejected(bundle, "projection_watermark_does_not_cover_source")


@pytest.mark.parametrize(
    ("record_name", "mutation", "reason"),
    [
        (
            "observation",
            lambda value: value.__setitem__("release_id", "wrong-release"),
            "release_id_mismatch",
        ),
        (
            "observation",
            lambda value: value.__setitem__("policy_checksum", "sha256:" + "1" * 64),
            "policy_checksum_mismatch",
        ),
        (
            "signoff",
            lambda value: value.__setitem__("release_id", "wrong-release"),
            "consumer_signoff_release_id_mismatch",
        ),
        (
            "signoff",
            lambda value: value.__setitem__("policy_checksum", "sha256:" + "1" * 64),
            "consumer_signoff_policy_mismatch",
        ),
        (
            "signoff",
            lambda value: value.__setitem__("compatibility_release_digest", "1" * 40),
            "consumer_signoff_candidate_mismatch",
        ),
        (
            "signoff",
            lambda value: value.__setitem__(
                "compatibility_build_digest", "sha256:" + "1" * 64
            ),
            "consumer_signoff_compatibility_build_mismatch",
        ),
        (
            "signoff",
            lambda value: value.__setitem__(
                "observation_record_checksum", "sha256:" + "1" * 64
            ),
            "consumer_signoff_observation_checksum_mismatch",
        ),
        (
            "signoff",
            lambda value: value.__setitem__(
                "consumer_inventory_checksum", "sha256:" + "1" * 64
            ),
            "consumer_signoff_inventory_checksum_mismatch",
        ),
        (
            "attestation",
            lambda value: value.__setitem__("release_id", "wrong-release"),
            "deletion_attestation_release_id_mismatch",
        ),
        (
            "attestation",
            lambda value: value.__setitem__("policy_checksum", "sha256:" + "1" * 64),
            "deletion_attestation_policy_mismatch",
        ),
        (
            "attestation",
            lambda value: value.__setitem__(
                "observation_record_checksum", "sha256:" + "1" * 64
            ),
            "deletion_attestation_observation_checksum_mismatch",
        ),
        (
            "attestation",
            lambda value: value.__setitem__(
                "consumer_signoff_record_checksum", "sha256:" + "1" * 64
            ),
            "deletion_attestation_consumer_signoff_checksum_mismatch",
        ),
    ],
)
def test_a_b_c_cross_record_bindings_fail_closed(
    tmp_path: Path,
    record_name: str,
    mutation,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    record = deepcopy(bundle[record_name])
    mutation(record)
    _write_record(bundle, record_name, record)

    _assert_rejected(bundle, reason)


def test_consumer_signoff_is_bound_to_inventory_surface_facts(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    signoff = deepcopy(bundle["signoff"])
    signoff["surfaces"][0]["consumer_count"] = 9
    _write_record(bundle, "signoff", signoff)

    _assert_rejected(bundle, "consumer_signoff_surfaces_mismatch")


@pytest.mark.parametrize(
    ("record_name", "section", "field", "replacement", "reason"),
    [
        (
            "observation",
            "compatibility_release",
            "release_digest",
            "1" * 40,
            "compatibility_release_digest_mismatch",
        ),
        (
            "observation",
            "compatibility_release",
            "source_tree",
            "2" * 40,
            "compatibility_release_source_tree_mismatch",
        ),
        (
            "observation",
            "compatibility_release",
            "parent_release_digest",
            "3" * 40,
            "compatibility_release_parent_release_mismatch",
        ),
        (
            "signoff",
            "approved_deletion_release",
            "release_digest",
            "1" * 40,
            "approved_deletion_release_digest_mismatch",
        ),
        (
            "signoff",
            "approved_deletion_release",
            "source_tree",
            "2" * 40,
            "approved_deletion_release_source_tree_mismatch",
        ),
        (
            "signoff",
            "approved_deletion_release",
            "parent_release_digest",
            "3" * 40,
            "approved_deletion_release_parent_release_mismatch",
        ),
        (
            "signoff",
            "approved_deletion_release",
            "environment",
            "production",
            "consumer_signoff_deletion_environment_mismatch",
        ),
        (
            "attestation",
            "deletion_release",
            "release_digest",
            "1" * 40,
            "deletion_release_digest_mismatch",
        ),
        (
            "attestation",
            "deletion_release",
            "source_tree",
            "2" * 40,
            "deletion_release_source_tree_mismatch",
        ),
        (
            "attestation",
            "deletion_release",
            "parent_release_digest",
            "3" * 40,
            "deletion_release_parent_release_mismatch",
        ),
    ],
)
def test_release_tree_parent_and_environment_mismatches_fail_closed(
    tmp_path: Path,
    record_name: str,
    section: str,
    field: str,
    replacement: str,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    record = deepcopy(bundle[record_name])
    record[section][field] = replacement
    _write_record(bundle, record_name, record)

    _assert_rejected(bundle, reason)


def test_approved_build_uri_must_be_bound_to_its_digest(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    signoff = deepcopy(bundle["signoff"])
    signoff["approved_deletion_release"]["build_uri"] = (
        "oci://registry.newsroom.dev/newsroom@sha256:" + "c" * 64
    )
    _write_record(bundle, "signoff", signoff)

    _assert_rejected(
        bundle,
        "approved_deletion_release.build_uri_not_content_addressed",
    )


@pytest.mark.parametrize(
    ("scheme", "claim_location", "reason"),
    [
        ("oci", "query", "approved_deletion_release.build_uri_credentials_forbidden"),
        (
            "docker",
            "query",
            "approved_deletion_release.build_uri_credentials_forbidden",
        ),
        (
            "oci",
            "path",
            "approved_deletion_release.build_uri_not_content_addressed",
        ),
        (
            "docker",
            "path",
            "approved_deletion_release.build_uri_not_content_addressed",
        ),
    ],
)
def test_mutable_container_tag_cannot_claim_content_addressing(
    tmp_path: Path,
    scheme: str,
    claim_location: str,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    signoff = deepcopy(bundle["signoff"])
    digest = signoff["approved_deletion_release"]["build_digest"]
    digest_hex = digest.removeprefix("sha256:")
    if claim_location == "query":
        mutable_uri = (
            f"{scheme}://registry.newsroom.dev/newsroom:latest?claimed={digest_hex}"
        )
    else:
        mutable_uri = f"{scheme}://registry.newsroom.dev/newsroom:latest/{digest_hex}"
    signoff["approved_deletion_release"]["build_uri"] = mutable_uri
    _write_record(bundle, "signoff", signoff)
    attestation = deepcopy(bundle["attestation"])
    attestation["consumer_signoff_record_checksum"] = signoff["record_checksum"]
    attestation["deletion_release"]["build_uri"] = mutable_uri
    _write_record(bundle, "attestation", attestation)

    _assert_rejected(bundle, reason)


@pytest.mark.parametrize(
    ("digest_placement", "reason"),
    [
        ("query", "external_evidence.uri_credentials_forbidden"),
        ("embedded_path", "external_evidence.uri_not_content_addressed"),
    ],
)
def test_https_content_address_uses_an_exact_digest_path_segment(
    tmp_path: Path,
    digest_placement: str,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    observation = deepcopy(bundle["observation"])
    checksum = observation["external_evidence"]["checksum"]
    digest = checksum.removeprefix("sha256:")
    if digest_placement == "query":
        uri = f"https://evidence.newsroom.dev/bundles/latest?digest={digest}"
    else:
        uri = f"https://evidence.newsroom.dev/bundles/prefix-{digest}-suffix"
    observation["external_evidence"]["uri"] = uri
    _rewrite_observation_chain(bundle, observation)

    _assert_rejected(bundle, reason)


@pytest.mark.parametrize(
    "credential_suffix",
    [
        "?X-Amz-Credential=AKIA_TEST&X-Amz-Signature=TOP_SECRET_QUERY",
        "#access_token=TOP_SECRET_FRAGMENT",
    ],
)
def test_external_evidence_uri_rejects_query_and_fragment_credentials(
    tmp_path: Path,
    credential_suffix: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    observation = deepcopy(bundle["observation"])
    observation["external_evidence"]["uri"] += credential_suffix
    _rewrite_observation_chain(bundle, observation)

    _assert_rejected(bundle, "external_evidence.uri_credentials_forbidden")


def test_cli_never_echoes_uri_credentials_to_stdout_or_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = _write_bundle(tmp_path)
    observation = deepcopy(bundle["observation"])
    secret = "TOP_SECRET_URI_CREDENTIAL"
    observation["external_evidence"]["uri"] += f"?X-Amz-Signature={secret}"
    _rewrite_observation_chain(bundle, observation)

    exit_code = compatibility.main(_cli_args(bundle))
    captured = capsys.readouterr()

    assert secret not in captured.out
    assert secret not in captured.err
    assert exit_code == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("deployment_id", "deployment-not-yet-created"),
        ("deployed_at", "2026-07-17T00:00:00Z"),
        ("deployment_uri", "https://deployments.newsroom.dev/future/deletion"),
    ],
)
def test_owner_approval_rejects_future_deployment_facts(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    signoff = deepcopy(bundle["signoff"])
    signoff["approved_deletion_release"][field] = value
    _write_record(bundle, "signoff", signoff)

    _assert_rejected(bundle, "approved_deletion_release_fields_invalid")


@pytest.mark.parametrize("field", ["build_digest", "build_uri", "environment"])
def test_deletion_attestation_plan_must_exactly_match_owner_approval(
    tmp_path: Path,
    field: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    attestation = deepcopy(bundle["attestation"])
    deletion = attestation["deletion_release"]
    if field == "build_digest":
        deletion["build_digest"] = "sha256:" + "c" * 64
        deletion["build_uri"] = (
            "oci://registry.newsroom.dev/newsroom@sha256:" + "c" * 64
        )
    elif field == "build_uri":
        deletion["build_uri"] = (
            "oci://registry.newsroom.dev/alternate@" + deletion["build_digest"]
        )
    else:
        deletion["environment"] = "production"
    _write_record(bundle, "attestation", attestation)

    _assert_rejected(bundle, "deletion_attestation_plan_mismatch")


def test_activation_environment_must_match_the_observation_environment(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    activation = deepcopy(bundle["activation"])
    activation["activation_deployment"]["environment"] = "production"
    _rewrite_activation_chain(bundle, activation)

    _assert_rejected(bundle, "activation_environment_mismatch")


def test_candidate_and_deletion_builds_and_deployments_must_be_distinct(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    signoff = deepcopy(bundle["signoff"])
    candidate = bundle["observation"]["compatibility_release"]
    plan = signoff["approved_deletion_release"]
    plan["build_digest"] = candidate["build_digest"]
    plan["build_uri"] = candidate["build_uri"]
    _write_record(bundle, "signoff", signoff)
    _assert_rejected(bundle, "consumer_signoff_build_not_distinct")

    bundle = _write_bundle(tmp_path / "deployment")
    attestation = deepcopy(bundle["attestation"])
    attestation["deletion_release"]["deployment_id"] = bundle["observation"][
        "compatibility_release"
    ]["deployment_id"]
    _write_record(bundle, "attestation", attestation)
    _assert_rejected(bundle, "deletion_deployment_id_not_distinct")


def test_trust_activation_signed_one_second_before_observation_window_is_accepted(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)

    assert (
        bundle["times"]["activation_signed"] + timedelta(seconds=1)
        == bundle["times"]["start"]
    )
    verify_compatibility_release_evidence(**bundle["verify_args"])


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(seconds=1)])
def test_late_trust_activation_cannot_retroactively_qualify_a_resigned_chain(
    tmp_path: Path,
    offset: timedelta,
) -> None:
    bundle = _write_bundle(tmp_path)
    activation = deepcopy(bundle["activation"])
    activation["governance_attestor"]["signed_at"] = _utc_text(
        bundle["times"]["start"] + offset
    )
    _rewrite_activation_chain(bundle, activation)

    _assert_rejected(bundle, "authority_activation_not_before_observation_window")


@pytest.mark.parametrize(
    ("authority_field", "replacement", "reason"),
    [
        (
            "trusted_governance_authority",
            "alternate-governance",
            "authority_activation_trusted_governance_authority_mismatch",
        ),
        (
            "trusted_observer_authority",
            "alternate-observer",
            "authority_activation_trusted_observer_authority_mismatch",
        ),
        (
            "trusted_consumer_owner_authority",
            "alternate-consumer-owner",
            "authority_activation_trusted_consumer_owner_authority_mismatch",
        ),
    ],
)
def test_activation_record_authorities_must_match_the_active_policy(
    tmp_path: Path,
    authority_field: str,
    replacement: str,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    activation = deepcopy(bundle["activation"])
    activation[authority_field]["authority_id"] = replacement
    _write_record(bundle, "activation", activation)

    _assert_rejected(bundle, reason)


def test_activation_record_trust_epoch_must_match_the_active_policy(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    activation = deepcopy(bundle["activation"])
    activation["trust_epoch"] = TEST_TRUST_EPOCH + 1
    _write_record(bundle, "activation", activation)

    _assert_rejected(bundle, "authority_activation_trust_epoch_mismatch")


def test_activation_record_policy_checksum_must_match_the_active_policy(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    activation = deepcopy(bundle["activation"])
    activation["policy_checksum"] = "sha256:" + "e" * 64
    _write_record(bundle, "activation", activation)

    _assert_rejected(bundle, "authority_activation_policy_mismatch")


@pytest.mark.parametrize("field", ["attestor_id", "key_id"])
def test_activation_governance_attestor_identity_is_pinned(
    tmp_path: Path,
    field: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    activation = deepcopy(bundle["activation"])
    activation["governance_attestor"][field] = f"alternate-{field}"
    _write_record(bundle, "activation", activation)

    _assert_rejected(bundle, "governance_attestor_identity_mismatch")


def test_activation_verifier_build_uri_must_bind_its_digest(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    activation = deepcopy(bundle["activation"])
    activation["activation_deployment"]["verifier_build_digest"] = "sha256:" + "d" * 64
    _write_record(bundle, "activation", activation)

    _assert_rejected(
        bundle,
        "activation_deployment.verifier_build_uri_not_content_addressed",
    )


def test_activation_evidence_uri_must_bind_its_digest(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    activation = deepcopy(bundle["activation"])
    activation["activation_evidence"]["checksum"] = "sha256:" + "c" * 64
    _write_record(bundle, "activation", activation)

    _assert_rejected(bundle, "activation_evidence.uri_not_content_addressed")


@pytest.mark.parametrize(
    ("record_name", "reason"),
    [
        ("observation", "observation_trust_epoch_mismatch"),
        ("signoff", "consumer_signoff_trust_epoch_mismatch"),
        ("attestation", "deletion_attestation_trust_epoch_mismatch"),
    ],
)
def test_evidence_chain_records_bind_the_active_trust_epoch(
    tmp_path: Path,
    record_name: str,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    record = deepcopy(bundle[record_name])
    record["trust_epoch"] = TEST_TRUST_EPOCH + 1
    _write_record(bundle, record_name, record)

    _assert_rejected(bundle, reason)


@pytest.mark.parametrize(
    ("record_name", "reason"),
    [
        ("observation", "observation_trust_activation_checksum_mismatch"),
        ("signoff", "consumer_signoff_trust_activation_checksum_mismatch"),
        ("attestation", "deletion_attestation_trust_activation_checksum_mismatch"),
    ],
)
def test_evidence_chain_records_bind_the_exact_activation_record(
    tmp_path: Path,
    record_name: str,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    record = deepcopy(bundle[record_name])
    record["trust_activation_record_checksum"] = "sha256:" + "f" * 64
    _write_record(bundle, record_name, record)

    _assert_rejected(bundle, reason)


@pytest.mark.parametrize(
    ("record_name", "mutate", "reason"),
    [
        (
            "activation",
            lambda value, times: value["activation_deployment"].__setitem__(
                "deployed_at",
                _utc_text(times["activation_signed"] + timedelta(minutes=1)),
            ),
            "governance_signature_predates_activation_deployment",
        ),
        (
            "observation",
            lambda value, times: value["compatibility_release"].__setitem__(
                "deployed_at", _utc_text(times["start"] + timedelta(minutes=1))
            ),
            "observation_predates_compatibility_deployment",
        ),
        (
            "observation",
            lambda value, times: value["observation_window"].__setitem__(
                "started_at", value["observation_window"]["ended_at"]
            ),
            "observation_window_not_positive",
        ),
        (
            "observation",
            lambda value, times: value["deployment_observer"].__setitem__(
                "signed_at", _utc_text(times["end"] - timedelta(minutes=1))
            ),
            "observer_signature_predates_observation",
        ),
        (
            "signoff",
            lambda value, times: value.__setitem__(
                "signed_at",
                _utc_text(times["observation_signed"] - timedelta(minutes=1)),
            ),
            "consumer_signoff_predates_observer_signature",
        ),
        (
            "attestation",
            lambda value, times: value["deletion_release"].__setitem__(
                "deployed_at", _utc_text(times["signoff"] - timedelta(minutes=1))
            ),
            "deletion_deployment_predates_consumer_signoff",
        ),
        (
            "attestation",
            lambda value, times: value["deployment_attestor"].__setitem__(
                "signed_at", _utc_text(times["deletion"] - timedelta(minutes=1))
            ),
            "deletion_attestor_signature_predates_deployment",
        ),
    ],
)
def test_every_protocol_time_reversal_fails_closed(
    tmp_path: Path,
    record_name: str,
    mutate,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    record = deepcopy(bundle[record_name])
    mutate(record, bundle["times"])
    _write_record(bundle, record_name, record)

    _assert_rejected(bundle, reason)


@pytest.mark.parametrize(
    ("record_name", "mutate", "reason"),
    [
        (
            "activation",
            lambda value, future: value["activation_deployment"].__setitem__(
                "deployed_at", future
            ),
            "activation_deployment.deployed_at_in_future",
        ),
        (
            "activation",
            lambda value, future: value["governance_attestor"].__setitem__(
                "signed_at", future
            ),
            "governance_attestor.signed_at_in_future",
        ),
        (
            "observation",
            lambda value, future: value["compatibility_release"].__setitem__(
                "deployed_at", future
            ),
            "compatibility_release.deployed_at_in_future",
        ),
        (
            "observation",
            lambda value, future: value["observation_window"].__setitem__(
                "started_at", future
            ),
            "observation_window.started_at_in_future",
        ),
        (
            "observation",
            lambda value, future: value["observation_window"].__setitem__(
                "ended_at", future
            ),
            "observation_window.ended_at_in_future",
        ),
        (
            "observation",
            lambda value, future: value["deployment_observer"].__setitem__(
                "signed_at", future
            ),
            "deployment_observer.signed_at_in_future",
        ),
        (
            "signoff",
            lambda value, future: value.__setitem__("signed_at", future),
            "consumer_signoff.signed_at_in_future",
        ),
        (
            "attestation",
            lambda value, future: value["deletion_release"].__setitem__(
                "deployed_at", future
            ),
            "deletion_release.deployed_at_in_future",
        ),
        (
            "attestation",
            lambda value, future: value["deployment_attestor"].__setitem__(
                "signed_at", future
            ),
            "deployment_attestor.signed_at_in_future",
        ),
    ],
)
def test_future_protocol_timestamps_fail_closed(
    tmp_path: Path,
    record_name: str,
    mutate,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    record = deepcopy(bundle[record_name])
    mutate(record, _utc_text(datetime.now(UTC) + timedelta(minutes=10)))
    _write_record(bundle, record_name, record)

    _assert_rejected(bundle, reason)


@pytest.mark.parametrize(
    ("arg_name", "replacement_path_name"),
    [
        ("trusted_consumer_owner_public_key", "observer_public_path"),
        ("trusted_governance_public_key", "observer_public_path"),
        ("trusted_governance_public_key", "owner_public_path"),
    ],
)
def test_governance_observer_and_consumer_authorities_must_be_distinct(
    tmp_path: Path,
    arg_name: str,
    replacement_path_name: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    args = dict(bundle["verify_args"])
    args[arg_name] = bundle[replacement_path_name]

    with pytest.raises(
        CompatibilityObservationError,
        match=_reason("signing_authority_separation_missing"),
    ):
        verify_compatibility_release_evidence(**args)


def test_attacker_governance_key_cannot_self_authorize_activation(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    attacker_key = Ed25519PrivateKey.from_private_bytes(
        ATTACKER_GOVERNANCE_PRIVATE_KEY_BYTES
    )
    bundle["governance_key"] = attacker_key
    _write_public_key(bundle["governance_public_path"], attacker_key)
    activation = deepcopy(bundle["activation"])
    attacker_fingerprint = compatibility._public_key_fingerprint(
        attacker_key.public_key()
    )
    activation["trusted_governance_authority"]["public_key_fingerprint"] = (
        attacker_fingerprint
    )
    activation["governance_attestor"]["public_key_fingerprint"] = attacker_fingerprint
    _rewrite_activation_chain(bundle, activation)

    _assert_rejected(bundle, "trusted_governance_authority_root_mismatch")


@pytest.mark.parametrize(
    ("replace_observer", "replace_owner", "reason"),
    [
        (True, False, "trusted_observer_authority_root_mismatch"),
        (False, True, "trusted_consumer_owner_authority_root_mismatch"),
        (True, True, "trusted_observer_authority_root_mismatch"),
    ],
)
def test_attacker_keys_cannot_self_authorize_a_fully_resigned_chain(
    tmp_path: Path,
    replace_observer: bool,
    replace_owner: bool,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    observer_key = (
        Ed25519PrivateKey.from_private_bytes(ATTACKER_OBSERVER_PRIVATE_KEY_BYTES)
        if replace_observer
        else _test_observer_key()
    )
    owner_key = (
        Ed25519PrivateKey.from_private_bytes(ATTACKER_CONSUMER_OWNER_PRIVATE_KEY_BYTES)
        if replace_owner
        else _test_consumer_owner_key()
    )
    _resign_bundle_with_authority_keys(
        bundle,
        observer_key=observer_key,
        owner_key=owner_key,
    )

    _assert_rejected(bundle, reason)


def test_two_attacker_keys_are_rejected_before_record_signature_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _write_bundle(tmp_path)
    _resign_bundle_with_authority_keys(
        bundle,
        observer_key=Ed25519PrivateKey.from_private_bytes(
            ATTACKER_OBSERVER_PRIVATE_KEY_BYTES
        ),
        owner_key=Ed25519PrivateKey.from_private_bytes(
            ATTACKER_CONSUMER_OWNER_PRIVATE_KEY_BYTES
        ),
    )

    def fail_if_signature_verification_is_reached(**_kwargs: Any) -> None:
        pytest.fail("record signature verification must follow authority root checks")

    monkeypatch.setattr(
        compatibility,
        "_verify_detached_signature",
        fail_if_signature_verification_is_reached,
    )

    _assert_rejected(bundle, "trusted_observer_authority_root_mismatch")


def test_authority_identities_and_attestor_binding_must_be_distinct_and_stable(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    signoff = deepcopy(bundle["signoff"])
    signoff["registry_owner_id"] = "deployment-observer"
    signoff["signer"]["signer_id"] = "deployment-observer"
    _write_record(bundle, "signoff", signoff)
    _assert_rejected(bundle, "consumer_owner_authority_mismatch")

    bundle = _write_bundle(tmp_path / "attestor")
    attestation = deepcopy(bundle["attestation"])
    attestation["deployment_attestor"]["attestor_id"] = "different-observer"
    _write_record(bundle, "attestation", attestation)
    _assert_rejected(bundle, "deletion_attestor_identity_mismatch")


@pytest.mark.parametrize(
    ("record_name", "section", "reason"),
    [
        (
            "activation",
            "governance_attestor",
            "trusted_governance_public_key_mismatch",
        ),
        (
            "observation",
            "deployment_observer",
            "trusted_observer_public_key_mismatch",
        ),
        (
            "signoff",
            "signer",
            "trusted_consumer_owner_public_key_mismatch",
        ),
        (
            "attestation",
            "deployment_attestor",
            "trusted_deletion_attestor_public_key_mismatch",
        ),
    ],
)
def test_claimed_authority_fingerprints_are_bound_to_their_trust_roots(
    tmp_path: Path,
    record_name: str,
    section: str,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    record = deepcopy(bundle[record_name])
    wrong_key = (
        bundle["observer_key"] if record_name == "signoff" else bundle["owner_key"]
    )
    record[section]["public_key_fingerprint"] = compatibility._public_key_fingerprint(
        wrong_key.public_key()
    )
    _write_record(bundle, record_name, record)

    _assert_rejected(bundle, reason)


@pytest.mark.parametrize(
    ("record_name", "expected_reason"),
    [
        ("activation", "authority_activation_record_checksum_mismatch"),
        ("observation", "observation_record_checksum_mismatch"),
        ("signoff", "consumer_signoff_record_checksum_mismatch"),
        ("attestation", "deletion_attestation_record_checksum_mismatch"),
    ],
)
def test_each_record_checksum_covers_the_complete_record(
    tmp_path: Path,
    record_name: str,
    expected_reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    record = deepcopy(bundle[record_name])
    record["record_checksum"] = "sha256:" + "0" * 64
    _write_record(bundle, record_name, record, set_checksum=False)

    _assert_rejected(bundle, expected_reason)


def test_policy_checksum_covers_the_complete_policy(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    policy = deepcopy(bundle["policy"])
    policy["policy_checksum"] = "sha256:" + "0" * 64
    bundle["policy_path"].write_text(stable_json_dumps(policy), encoding="utf-8")

    _assert_rejected(bundle, "policy_record_checksum_mismatch")


@pytest.mark.parametrize(
    ("record_name", "expected_reason"),
    [
        ("activation", "authority_activation_signature_invalid"),
        ("observation", "observation_signature_invalid"),
        ("signoff", "consumer_signoff_signature_invalid"),
        ("attestation", "deletion_attestation_signature_invalid"),
    ],
)
def test_detached_signatures_cover_exact_record_bytes(
    tmp_path: Path,
    record_name: str,
    expected_reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    path = bundle[f"{record_name}_path"]
    path.write_bytes(path.read_bytes() + b"\n")

    _assert_rejected(bundle, expected_reason)


@pytest.mark.parametrize(
    ("record_name", "wrong_key_name", "expected_reason"),
    [
        (
            "activation",
            "observer_key",
            "authority_activation_signature_invalid",
        ),
        ("observation", "owner_key", "observation_signature_invalid"),
        ("signoff", "observer_key", "consumer_signoff_signature_invalid"),
        ("attestation", "owner_key", "deletion_attestation_signature_invalid"),
    ],
)
def test_each_record_rejects_a_signature_from_the_wrong_authority(
    tmp_path: Path,
    record_name: str,
    wrong_key_name: str,
    expected_reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    payload = bundle[f"{record_name}_path"].read_bytes()
    signature = bundle[wrong_key_name].sign(payload)
    bundle[f"{record_name}_signature_path"].write_bytes(base64.b64encode(signature))

    _assert_rejected(bundle, expected_reason)


@pytest.mark.parametrize(
    ("record_name", "expected_reason"),
    [
        ("policy", "policy_duplicate_json_key"),
        ("activation", "authority_activation_duplicate_json_key"),
        ("observation", "observation_duplicate_json_key"),
        ("signoff", "consumer_signoff_duplicate_json_key"),
        ("attestation", "deletion_attestation_duplicate_json_key"),
    ],
)
def test_duplicate_json_keys_are_rejected_for_every_protocol_record(
    tmp_path: Path,
    record_name: str,
    expected_reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    path = bundle[f"{record_name}_path"]
    original = path.read_bytes()
    path.write_bytes(b'{"schema":"duplicate",' + original[1:])

    _assert_rejected(bundle, expected_reason)


@pytest.mark.parametrize(
    ("record_name", "expected_reason"),
    [
        ("policy", "policy_nonfinite_number"),
        ("activation", "authority_activation_nonfinite_number"),
        ("observation", "observation_nonfinite_number"),
        ("signoff", "consumer_signoff_nonfinite_number"),
        ("attestation", "deletion_attestation_nonfinite_number"),
    ],
)
def test_nonfinite_numbers_are_rejected_for_every_protocol_record(
    tmp_path: Path,
    record_name: str,
    expected_reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    path = bundle[f"{record_name}_path"]
    original = path.read_bytes()
    path.write_bytes(original[:-1] + b',"nonfinite":NaN}')

    _assert_rejected(bundle, expected_reason)


@pytest.mark.parametrize(
    ("record_name", "expected_reason"),
    [
        ("policy", "policy_fields_invalid"),
        ("activation", "authority_activation_fields_invalid"),
        ("observation", "observation_fields_invalid"),
        ("signoff", "consumer_signoff_fields_invalid"),
        ("attestation", "deletion_attestation_fields_invalid"),
    ],
)
def test_extra_fields_are_rejected_for_every_protocol_record(
    tmp_path: Path,
    record_name: str,
    expected_reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    record = deepcopy(bundle[record_name])
    record["unexpected"] = True
    if record_name == "policy":
        _set_policy_checksum(record)
        bundle["policy_path"].write_text(stable_json_dumps(record), encoding="utf-8")
    else:
        _write_record(bundle, record_name, record)

    _assert_rejected(bundle, expected_reason)


@pytest.mark.parametrize(
    ("path_name", "size_label"),
    [
        ("policy_path", "policy"),
        ("activation_path", "authority_activation"),
        ("observation_path", "observation"),
        ("signoff_path", "consumer_signoff"),
        ("attestation_path", "deletion_attestation"),
        ("activation_signature_path", "authority_activation_signature"),
        ("observation_signature_path", "observation_signature"),
        ("signoff_signature_path", "consumer_signoff_signature"),
        ("attestation_signature_path", "deletion_attestation_signature"),
    ],
)
def test_all_protocol_inputs_enforce_bounded_file_sizes(
    tmp_path: Path,
    path_name: str,
    size_label: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    bundle[path_name].write_bytes(
        b"x" * (compatibility._MAX_FILE_BYTES[size_label] + 1)
    )

    _assert_rejected(bundle, f"{size_label}_size_invalid")


@pytest.mark.parametrize(
    ("arg_name", "label"),
    [
        ("policy_path", "policy"),
        ("authority_activation_path", "authority_activation"),
        (
            "authority_activation_signature_path",
            "authority_activation_signature",
        ),
        ("observation_path", "observation"),
        ("consumer_signoff_path", "consumer_signoff"),
        ("deletion_attestation_path", "deletion_attestation"),
        ("deletion_attestation_signature_path", "deletion_attestation_signature"),
    ],
)
def test_protocol_inputs_reject_symlinks(
    tmp_path: Path,
    arg_name: str,
    label: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    target = Path(bundle["verify_args"][arg_name])
    link = tmp_path / f"{label}.link"
    try:
        link.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")
    args = dict(bundle["verify_args"])
    args[arg_name] = link

    with pytest.raises(
        CompatibilityObservationError,
        match=_reason(f"{label}_symlink_forbidden"),
    ):
        verify_compatibility_release_evidence(**args)


def test_protocol_inputs_reject_a_symlinked_parent_directory(tmp_path: Path) -> None:
    real_directory = tmp_path / "real"
    bundle = _write_bundle(real_directory)
    linked_directory = tmp_path / "linked"
    try:
        linked_directory.symlink_to(real_directory, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink creation is unavailable: {error}")
    args = dict(bundle["verify_args"])
    args["policy_path"] = linked_directory / bundle["policy_path"].name

    with pytest.raises(
        CompatibilityObservationError,
        match=_reason("policy_symlink_forbidden"),
    ):
        verify_compatibility_release_evidence(**args)


def test_file_limit_applies_to_the_bytes_read_after_metadata_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _write_bundle(tmp_path)
    observation_path = bundle["observation_path"].resolve()
    original_stat = Path.stat
    small_stat = original_stat(observation_path)
    original_payload = observation_path.read_bytes()
    oversized_payload = original_payload + b" " * (
        compatibility._MAX_FILE_BYTES["observation"] - len(original_payload) + 1
    )
    observation_path.write_bytes(oversized_payload)
    bundle["observation_signature_path"].write_bytes(
        base64.b64encode(bundle["observer_key"].sign(oversized_payload))
    )

    def stale_stat(path: Path, *args: Any, **kwargs: Any):
        if str(path.absolute()).casefold() == str(observation_path).casefold():
            return small_stat
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stale_stat)

    _assert_rejected(bundle, "observation_size_invalid")


def test_content_addressed_and_retention_locked_evidence_are_accepted(
    tmp_path: Path,
) -> None:
    content_addressed = _write_bundle(tmp_path / "content-addressed")
    verify_compatibility_release_evidence(**content_addressed["verify_args"])

    locked = _write_bundle(tmp_path / "retention-locked")
    observation = deepcopy(locked["observation"])
    observation["external_evidence"].update(
        {
            "retention_mode": "retention_locked",
            "retention_until": _utc_text(datetime.now(UTC) + timedelta(days=30)),
            "retention_lock_id": "lock-observation-1",
        }
    )
    _write_record(locked, "observation", observation)
    signoff = deepcopy(locked["signoff"])
    signoff["observation_record_checksum"] = observation["record_checksum"]
    _write_record(locked, "signoff", signoff)
    attestation = deepcopy(locked["attestation"])
    attestation["observation_record_checksum"] = observation["record_checksum"]
    attestation["consumer_signoff_record_checksum"] = signoff["record_checksum"]
    attestation["deployment_evidence"].update(
        {
            "retention_mode": "retention_locked",
            "retention_until": _utc_text(datetime.now(UTC) + timedelta(days=30)),
            "retention_lock_id": "lock-deletion-1",
        }
    )
    _write_record(locked, "attestation", attestation)

    verify_compatibility_release_evidence(**locked["verify_args"])


def test_observation_retention_lock_must_cover_deletion_attestation(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    observation = deepcopy(bundle["observation"])
    observation["external_evidence"].update(
        {
            "retention_mode": "retention_locked",
            "retention_until": _utc_text(bundle["times"]["signoff"]),
            "retention_lock_id": "lock-observation-too-short",
        }
    )
    _write_record(bundle, "observation", observation)

    signoff = deepcopy(bundle["signoff"])
    signoff["observation_record_checksum"] = observation["record_checksum"]
    _write_record(bundle, "signoff", signoff)

    attestation = deepcopy(bundle["attestation"])
    attestation["observation_record_checksum"] = observation["record_checksum"]
    attestation["consumer_signoff_record_checksum"] = signoff["record_checksum"]
    _write_record(bundle, "attestation", attestation)

    _assert_rejected(bundle, "external_evidence_retention_expired")


def test_activation_retention_lock_must_cover_deletion_attestation(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    activation = deepcopy(bundle["activation"])
    activation["activation_evidence"].update(
        {
            "retention_mode": "retention_locked",
            "retention_until": _utc_text(bundle["times"]["attestor"]),
            "retention_lock_id": "lock-activation-too-short",
        }
    )
    _rewrite_activation_chain(bundle, activation)

    _assert_rejected(bundle, "activation_evidence_retention_expired")


@pytest.mark.parametrize(
    ("record_name", "mutation", "reason"),
    [
        (
            "observation",
            lambda value, times: value["external_evidence"].__setitem__(
                "uri", "https://evidence.newsroom.dev/bundles/wrong-digest"
            ),
            "external_evidence.uri_not_content_addressed",
        ),
        (
            "attestation",
            lambda value, times: value["deployment_evidence"].__setitem__(
                "uri", "https://evidence.newsroom.dev/bundles/wrong-digest"
            ),
            "deployment_evidence.uri_not_content_addressed",
        ),
        (
            "observation",
            lambda value, times: value["external_evidence"].__setitem__(
                "retention_until",
                _utc_text(times["observation_signed"] + timedelta(days=1)),
            ),
            "external_evidence_content_addressed_retention_until_invalid",
        ),
        (
            "observation",
            lambda value, times: value["external_evidence"].update(
                {
                    "retention_mode": "retention_locked",
                    "retention_until": _utc_text(times["observation_signed"]),
                    "retention_lock_id": "expired-lock",
                }
            ),
            "external_evidence_retention_expired",
        ),
        (
            "attestation",
            lambda value, times: value["deployment_evidence"].update(
                {
                    "retention_mode": "retention_locked",
                    "retention_until": _utc_text(times["attestor"]),
                    "retention_lock_id": "expired-lock",
                }
            ),
            "deployment_evidence_retention_expired",
        ),
    ],
)
def test_external_evidence_retention_failures_are_rejected(
    tmp_path: Path,
    record_name: str,
    mutation,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    record = deepcopy(bundle[record_name])
    mutation(record, bundle["times"])
    _write_record(bundle, record_name, record)

    _assert_rejected(bundle, reason)


def test_policy_git_pins_reject_wrong_boundary_and_qualified_objects(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    policy = deepcopy(bundle["policy"])
    policy["deletion_boundary_tree"] = "1" * 40
    _set_policy_checksum(policy)
    bundle["policy_path"].write_text(stable_json_dumps(policy), encoding="utf-8")
    _assert_rejected(bundle, "policy_deletion_boundary_tree_mismatch")

    bundle = _write_bundle(tmp_path / "qualified")
    policy = deepcopy(bundle["policy"])
    policy["qualified_deletion_source_parent_commit"] = "2" * 40
    _set_policy_checksum(policy)
    bundle["policy_path"].write_text(stable_json_dumps(policy), encoding="utf-8")
    _assert_rejected(bundle, "policy_qualified_deletion_source_parent_commit_mismatch")


def _write_bundle(tmp_path: Path) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    policy = _policy_record()
    policy_path = tmp_path / "compatibility-policy.json"
    policy_path.write_text(stable_json_dumps(policy), encoding="utf-8")

    observer_key = _test_observer_key()
    owner_key = _test_consumer_owner_key()
    governance_key = _test_governance_key()
    observer_public_path = tmp_path / "observer-public.pem"
    owner_public_path = tmp_path / "owner-public.pem"
    governance_public_path = tmp_path / "governance-public.pem"
    _write_public_key(observer_public_path, observer_key)
    _write_public_key(owner_public_path, owner_key)
    _write_public_key(governance_public_path, governance_key)
    observer_fingerprint = compatibility._public_key_fingerprint(
        observer_key.public_key()
    )
    owner_fingerprint = compatibility._public_key_fingerprint(owner_key.public_key())
    governance_fingerprint = compatibility._public_key_fingerprint(
        governance_key.public_key()
    )

    now = datetime.now(UTC).replace(microsecond=0)
    times = {
        "activation_deployed": now - timedelta(hours=12),
        "candidate": now - timedelta(hours=10),
        "start": now - timedelta(hours=9),
        "activation_signed": now - timedelta(hours=9, seconds=1),
        "sample": now - timedelta(hours=7),
        "end": now - timedelta(hours=6),
        "observation_signed": now - timedelta(hours=5),
        "signoff": now - timedelta(hours=4),
        "deletion": now - timedelta(hours=3),
        "attestor": now - timedelta(hours=2),
    }
    candidate_build = "sha256:" + "a" * 64
    deletion_build = "sha256:" + "b" * 64
    observation_evidence_checksum = "sha256:" + "e" * 64
    deletion_evidence_checksum = "sha256:" + "f" * 64
    activation_evidence_checksum = "sha256:" + "8" * 64
    verifier_build_digest = "sha256:" + "7" * 64

    activation = {
        "schema": compatibility.TRUST_ACTIVATION_SCHEMA,
        "status": "active",
        "release_id": compatibility.RELEASE_ID,
        "policy_checksum": policy["policy_checksum"],
        "trust_epoch": policy["trust_epoch"],
        "trusted_governance_authority": deepcopy(
            policy["trusted_governance_authority"]
        ),
        "trusted_observer_authority": deepcopy(policy["trusted_observer_authority"]),
        "trusted_consumer_owner_authority": deepcopy(
            policy["trusted_consumer_owner_authority"]
        ),
        "activation_deployment": {
            "deployment_id": "deployment-trust-activation-1",
            "environment": "staging",
            "deployed_at": _utc_text(times["activation_deployed"]),
            "verifier_build_digest": verifier_build_digest,
            "verifier_build_uri": (
                f"oci://registry.newsroom.dev/newsroom-verifier@{verifier_build_digest}"
            ),
            "deployment_uri": (
                "https://deployments.newsroom.dev/newsroom/trust-activation-1"
            ),
        },
        "activation_evidence": {
            "uri": "https://evidence.newsroom.dev/bundles/" + "8" * 64,
            "checksum": activation_evidence_checksum,
            "retention_mode": "content_addressed",
            "retention_until": None,
            "retention_lock_id": None,
        },
        "governance_attestor": {
            "attestor_id": TEST_GOVERNANCE_AUTHORITY_ID,
            "key_id": TEST_GOVERNANCE_KEY_ID,
            "public_key_fingerprint": governance_fingerprint,
            "signed_at": _utc_text(times["activation_signed"]),
        },
    }
    _set_record_checksum(activation)
    activation_path = tmp_path / "trust-activation.json"
    activation_signature_path = tmp_path / "trust-activation.sig"
    _rewrite_signed_record(
        activation_path,
        activation_signature_path,
        activation,
        governance_key,
    )

    surfaces = [
        {
            "surface": surface,
            "consumer_count": 0,
            "unknown_consumer_count": 0,
            "unowned_consumer_count": 0,
            "flat_record_read_count": 0,
            "owner_id": "consumer-registry-owner",
            "disposition": "no_consumers",
            "observed_at": _utc_text(times["sample"]),
            "evidence_uri": f"https://evidence.newsroom.dev/consumers/{surface}.json",
        }
        for surface in compatibility.REQUIRED_SURFACES
    ]
    inventory = {
        "registry_id": "newsroom-consumer-registry",
        "coverage_started_at": _utc_text(times["start"]),
        "coverage_ended_at": _utc_text(times["end"]),
        "sources": [
            {
                "source_id": source_id,
                "coverage_started_at": _utc_text(times["start"]),
                "coverage_ended_at": _utc_text(times["end"]),
                "evidence_uri": (
                    f"https://evidence.newsroom.dev/inventory/{source_id}.json"
                ),
            }
            for source_id in compatibility.REQUIRED_INVENTORY_SOURCES
        ],
        "surfaces": surfaces,
    }
    inventory["inventory_checksum"] = checksum_for(inventory)

    observation = {
        "schema": compatibility.OBSERVATION_SCHEMA,
        "status": "passed",
        "release_id": compatibility.RELEASE_ID,
        "policy_checksum": policy["policy_checksum"],
        "trust_epoch": policy["trust_epoch"],
        "trust_activation_record_checksum": activation["record_checksum"],
        "compatibility_release": {
            "release_digest": CANDIDATE,
            "source_tree": compatibility.COMPATIBILITY_TREE,
            "parent_release_digest": compatibility.COMPATIBILITY_PARENT,
            "build_digest": candidate_build,
            "build_uri": f"oci://registry.newsroom.dev/newsroom@{candidate_build}",
            "deployment_id": "deployment-migration-1",
            "environment": "staging",
            "deployed_at": _utc_text(times["candidate"]),
            "deployment_uri": "https://deployments.newsroom.dev/newsroom/migration-1",
        },
        "observation_window": {
            "started_at": _utc_text(times["start"]),
            "ended_at": _utc_text(times["end"]),
            "duration_seconds": 10800,
        },
        "observations": {
            "queries": [
                {
                    "surface": surface,
                    "request_id": f"request-{surface}",
                    "run_id": "run-compatibility-1",
                    "observed_at": _utc_text(times["sample"]),
                    "stream_sequence": 5,
                    "source_high_watermark": 5,
                    "authoritative_source": "durable_store",
                    "projection_fallback_used": False,
                    "response_status": "success",
                    "evidence_uri": (
                        "https://evidence.newsroom.dev/observations/"
                        f"query-{surface}.json"
                    ),
                }
                for surface in compatibility.REQUIRED_QUERY_SURFACES
            ],
            "checkpoints": [
                {
                    "checkpoint_id": "checkpoint-1",
                    "run_id": "run-compatibility-1",
                    "event_id": "event-5",
                    "observed_at": _utc_text(times["sample"]),
                    "stream_sequence": 5,
                    "source_high_watermark": 5,
                    "sequence_base": 1,
                    "legacy_offset_used": False,
                    "evidence_uri": "https://evidence.newsroom.dev/observations/checkpoint-1.json",
                }
            ],
            "projections": [
                {
                    "projection_id": "projection-1",
                    "run_id": "run-compatibility-1",
                    "observed_at": _utc_text(times["sample"]),
                    "store_high_watermark": 5,
                    "manifest_high_watermark": 5,
                    "projection_high_watermark": 5,
                    "ordered_events_checksum": "sha256:" + "d" * 64,
                    "projection_checksum": "sha256:" + "c" * 64,
                    "raw_secret_findings": 0,
                    "store_write_back_count": 0,
                    "evidence_uri": "https://evidence.newsroom.dev/observations/projection-1.json",
                }
            ],
        },
        "consumer_inventory": inventory,
        "external_evidence": {
            "uri": "https://evidence.newsroom.dev/bundles/" + "e" * 64,
            "checksum": observation_evidence_checksum,
            "retention_mode": "content_addressed",
            "retention_until": None,
            "retention_lock_id": None,
        },
        "deployment_observer": {
            "observer_id": "deployment-observer",
            "public_key_fingerprint": observer_fingerprint,
            "signed_at": _utc_text(times["observation_signed"]),
        },
    }
    _set_record_checksum(observation)
    observation_path = tmp_path / "compatibility-observation.json"
    observation_signature_path = tmp_path / "compatibility-observation.sig"
    _rewrite_signed_record(
        observation_path,
        observation_signature_path,
        observation,
        observer_key,
    )

    approved_deletion = {
        "release_digest": QUALIFIED_DELETION,
        "source_tree": compatibility.QUALIFIED_DELETION_TREE,
        "parent_release_digest": compatibility.QUALIFIED_DELETION_PARENT,
        "build_digest": deletion_build,
        "build_uri": f"oci://registry.newsroom.dev/newsroom@{deletion_build}",
        "environment": "staging",
    }
    signoff = {
        "schema": compatibility.CONSUMER_SIGNOFF_SCHEMA,
        "decision": "approved",
        "release_id": compatibility.RELEASE_ID,
        "policy_checksum": policy["policy_checksum"],
        "trust_epoch": policy["trust_epoch"],
        "trust_activation_record_checksum": activation["record_checksum"],
        "compatibility_release_digest": CANDIDATE,
        "compatibility_build_digest": candidate_build,
        "approved_deletion_release": approved_deletion,
        "observation_record_checksum": observation["record_checksum"],
        "consumer_inventory_checksum": inventory["inventory_checksum"],
        "registry_id": inventory["registry_id"],
        "registry_owner_id": "consumer-registry-owner",
        "surfaces": [
            {
                "surface": item["surface"],
                "consumer_count": item["consumer_count"],
                "owner_id": item["owner_id"],
                "disposition": item["disposition"],
                "flat_record_read_count": item["flat_record_read_count"],
            }
            for item in surfaces
        ],
        "signed_at": _utc_text(times["signoff"]),
        "signer": {
            "signer_id": "consumer-registry-owner",
            "public_key_fingerprint": owner_fingerprint,
        },
    }
    _set_record_checksum(signoff)
    signoff_path = tmp_path / "consumer-signoff.json"
    signoff_signature_path = tmp_path / "consumer-signoff.sig"
    _rewrite_signed_record(
        signoff_path,
        signoff_signature_path,
        signoff,
        owner_key,
    )

    attestation = {
        "schema": compatibility.DELETION_ATTESTATION_SCHEMA,
        "status": "passed",
        "release_id": compatibility.RELEASE_ID,
        "policy_checksum": policy["policy_checksum"],
        "trust_epoch": policy["trust_epoch"],
        "trust_activation_record_checksum": activation["record_checksum"],
        "observation_record_checksum": observation["record_checksum"],
        "consumer_signoff_record_checksum": signoff["record_checksum"],
        "deletion_release": {
            **approved_deletion,
            "deployment_id": "deployment-deletion-1",
            "deployed_at": _utc_text(times["deletion"]),
            "deployment_uri": "https://deployments.newsroom.dev/newsroom/deletion-1",
        },
        "deployment_evidence": {
            "uri": "https://evidence.newsroom.dev/bundles/" + "f" * 64,
            "checksum": deletion_evidence_checksum,
            "retention_mode": "content_addressed",
            "retention_until": None,
            "retention_lock_id": None,
        },
        "deployment_attestor": {
            "attestor_id": "deployment-observer",
            "public_key_fingerprint": observer_fingerprint,
            "signed_at": _utc_text(times["attestor"]),
        },
    }
    _set_record_checksum(attestation)
    attestation_path = tmp_path / "deletion-attestation.json"
    attestation_signature_path = tmp_path / "deletion-attestation.sig"
    _rewrite_signed_record(
        attestation_path,
        attestation_signature_path,
        attestation,
        observer_key,
    )

    verify_args = {
        "policy_path": policy_path,
        "authority_activation_path": activation_path,
        "authority_activation_signature_path": activation_signature_path,
        "trusted_governance_public_key": governance_public_path,
        "observation_path": observation_path,
        "observation_signature_path": observation_signature_path,
        "trusted_observer_public_key": observer_public_path,
        "consumer_signoff_path": signoff_path,
        "consumer_signoff_signature_path": signoff_signature_path,
        "trusted_consumer_owner_public_key": owner_public_path,
        "deletion_attestation_path": attestation_path,
        "deletion_attestation_signature_path": attestation_signature_path,
    }
    return {
        "verify_args": verify_args,
        "policy": policy,
        "policy_path": policy_path,
        "activation": activation,
        "activation_path": activation_path,
        "activation_signature_path": activation_signature_path,
        "observation": observation,
        "observation_path": observation_path,
        "observation_signature_path": observation_signature_path,
        "signoff": signoff,
        "signoff_path": signoff_path,
        "signoff_signature_path": signoff_signature_path,
        "attestation": attestation,
        "attestation_path": attestation_path,
        "attestation_signature_path": attestation_signature_path,
        "observer_public_path": observer_public_path,
        "owner_public_path": owner_public_path,
        "governance_public_path": governance_public_path,
        "observer_key": observer_key,
        "owner_key": owner_key,
        "governance_key": governance_key,
        "times": times,
    }


def _test_observer_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(TEST_OBSERVER_PRIVATE_KEY_BYTES)


def _test_consumer_owner_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(TEST_CONSUMER_OWNER_PRIVATE_KEY_BYTES)


def _test_governance_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(TEST_GOVERNANCE_PRIVATE_KEY_BYTES)


def _policy_record() -> dict[str, Any]:
    policy = {
        "schema": compatibility.POLICY_SCHEMA,
        "release_id": compatibility.RELEASE_ID,
        "compatibility_source_commit": compatibility.COMPATIBILITY_RELEASE,
        "compatibility_source_tree": compatibility.COMPATIBILITY_TREE,
        "compatibility_parent_commit": compatibility.COMPATIBILITY_PARENT,
        "deletion_boundary_commit": compatibility.DELETION_BOUNDARY,
        "deletion_boundary_tree": compatibility.DELETION_BOUNDARY_TREE,
        "deletion_boundary_parent_commit": compatibility.DELETION_BOUNDARY_PARENT,
        "qualified_deletion_source_commit": compatibility.QUALIFIED_DELETION_RELEASE,
        "qualified_deletion_source_tree": compatibility.QUALIFIED_DELETION_TREE,
        "qualified_deletion_source_parent_commit": compatibility.QUALIFIED_DELETION_PARENT,
        "authority_trust_status": compatibility.AUTHORITY_TRUST_ACTIVE,
        "trust_epoch": TEST_TRUST_EPOCH,
        "trusted_governance_authority": {
            "authority_id": TEST_GOVERNANCE_AUTHORITY_ID,
            "key_id": TEST_GOVERNANCE_KEY_ID,
            "algorithm": "Ed25519",
            "public_key_fingerprint": compatibility._public_key_fingerprint(
                _test_governance_key().public_key()
            ),
        },
        "trusted_observer_authority": {
            "authority_id": TEST_OBSERVER_AUTHORITY_ID,
            "key_id": TEST_OBSERVER_KEY_ID,
            "algorithm": "Ed25519",
            "public_key_fingerprint": compatibility._public_key_fingerprint(
                _test_observer_key().public_key()
            ),
        },
        "trusted_consumer_owner_authority": {
            "authority_id": TEST_CONSUMER_OWNER_AUTHORITY_ID,
            "key_id": TEST_CONSUMER_OWNER_KEY_ID,
            "algorithm": "Ed25519",
            "public_key_fingerprint": compatibility._public_key_fingerprint(
                _test_consumer_owner_key().public_key()
            ),
        },
        "required_query_surfaces": list(compatibility.REQUIRED_QUERY_SURFACES),
        "required_consumer_surfaces": list(compatibility.REQUIRED_SURFACES),
        "required_inventory_sources": list(compatibility.REQUIRED_INVENTORY_SOURCES),
        "minimum_observation_seconds": int(
            compatibility.MIN_OBSERVATION_WINDOW.total_seconds()
        ),
        "maximum_observation_seconds": int(
            compatibility.MAX_OBSERVATION_WINDOW.total_seconds()
        ),
        "maximum_observation_records": compatibility.MAX_OBSERVATION_RECORDS,
    }
    _set_policy_checksum(policy)
    return policy


def _set_policy_checksum(value: dict[str, Any]) -> None:
    value.pop("policy_checksum", None)
    value["policy_checksum"] = checksum_for(value)


def _set_record_checksum(value: dict[str, Any]) -> None:
    value.pop("record_checksum", None)
    value["record_checksum"] = checksum_for(value)


def _write_record(
    bundle: dict[str, Any],
    record_name: str,
    value: dict[str, Any],
    *,
    set_checksum: bool = True,
) -> None:
    if set_checksum:
        _set_record_checksum(value)
    key = {
        "activation": bundle["governance_key"],
        "observation": bundle["observer_key"],
        "signoff": bundle["owner_key"],
        "attestation": bundle["observer_key"],
    }[record_name]
    _rewrite_signed_record(
        bundle[f"{record_name}_path"],
        bundle[f"{record_name}_signature_path"],
        value,
        key,
    )
    bundle[record_name] = value


def _resign_bundle_with_authority_keys(
    bundle: dict[str, Any],
    *,
    observer_key: Ed25519PrivateKey,
    owner_key: Ed25519PrivateKey,
) -> None:
    bundle["observer_key"] = observer_key
    bundle["owner_key"] = owner_key
    _write_public_key(bundle["observer_public_path"], observer_key)
    _write_public_key(bundle["owner_public_path"], owner_key)

    observation = deepcopy(bundle["observation"])
    observation["deployment_observer"]["public_key_fingerprint"] = (
        compatibility._public_key_fingerprint(observer_key.public_key())
    )
    _write_record(bundle, "observation", observation)

    signoff = deepcopy(bundle["signoff"])
    signoff["observation_record_checksum"] = observation["record_checksum"]
    signoff["signer"]["public_key_fingerprint"] = compatibility._public_key_fingerprint(
        owner_key.public_key()
    )
    _write_record(bundle, "signoff", signoff)

    attestation = deepcopy(bundle["attestation"])
    attestation["observation_record_checksum"] = observation["record_checksum"]
    attestation["consumer_signoff_record_checksum"] = signoff["record_checksum"]
    attestation["deployment_attestor"]["public_key_fingerprint"] = (
        compatibility._public_key_fingerprint(observer_key.public_key())
    )
    _write_record(bundle, "attestation", attestation)


def _rewrite_observation_chain(
    bundle: dict[str, Any],
    observation: dict[str, Any],
) -> None:
    _write_record(bundle, "observation", observation)
    signoff = deepcopy(bundle["signoff"])
    signoff["observation_record_checksum"] = observation["record_checksum"]
    _write_record(bundle, "signoff", signoff)
    attestation = deepcopy(bundle["attestation"])
    attestation["observation_record_checksum"] = observation["record_checksum"]
    attestation["consumer_signoff_record_checksum"] = signoff["record_checksum"]
    _write_record(bundle, "attestation", attestation)


def _rewrite_activation_chain(
    bundle: dict[str, Any],
    activation: dict[str, Any],
) -> None:
    _write_record(bundle, "activation", activation)
    activation_checksum = activation["record_checksum"]

    observation = deepcopy(bundle["observation"])
    observation["trust_activation_record_checksum"] = activation_checksum
    _write_record(bundle, "observation", observation)

    signoff = deepcopy(bundle["signoff"])
    signoff["trust_activation_record_checksum"] = activation_checksum
    signoff["observation_record_checksum"] = observation["record_checksum"]
    _write_record(bundle, "signoff", signoff)

    attestation = deepcopy(bundle["attestation"])
    attestation["trust_activation_record_checksum"] = activation_checksum
    attestation["observation_record_checksum"] = observation["record_checksum"]
    attestation["consumer_signoff_record_checksum"] = signoff["record_checksum"]
    _write_record(bundle, "attestation", attestation)


def _cli_args(bundle: dict[str, Any]) -> list[str]:
    return [
        "--policy",
        str(bundle["policy_path"]),
        "--authority-activation",
        str(bundle["activation_path"]),
        "--authority-activation-signature",
        str(bundle["activation_signature_path"]),
        "--trusted-governance-public-key",
        str(bundle["governance_public_path"]),
        "--observation",
        str(bundle["observation_path"]),
        "--observation-signature",
        str(bundle["observation_signature_path"]),
        "--trusted-observer-public-key",
        str(bundle["observer_public_path"]),
        "--consumer-signoff",
        str(bundle["signoff_path"]),
        "--consumer-signoff-signature",
        str(bundle["signoff_signature_path"]),
        "--trusted-consumer-owner-public-key",
        str(bundle["owner_public_path"]),
        "--deletion-attestation",
        str(bundle["attestation_path"]),
        "--deletion-attestation-signature",
        str(bundle["attestation_signature_path"]),
    ]


def _rewrite_signed_record(
    record_path: Path,
    signature_path: Path,
    value: dict[str, Any],
    key: Ed25519PrivateKey,
) -> None:
    payload = stable_json_dumps(value).encode("utf-8")
    record_path.write_bytes(payload)
    signature_path.write_bytes(base64.b64encode(key.sign(payload)))


def _write_public_key(path: Path, key: Ed25519PrivateKey) -> None:
    path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def _assert_rejected(bundle: dict[str, Any], reason: str) -> None:
    with pytest.raises(CompatibilityObservationError, match=_reason(reason)):
        verify_compatibility_release_evidence(**bundle["verify_args"])


def _reason(value: str) -> str:
    return rf"^{re.escape(value)}$"


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
