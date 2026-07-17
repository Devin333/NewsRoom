from __future__ import annotations

import base64
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess

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


CANDIDATE = "42a8636cd72aea0c466126fc5f2d69c55db1a1d6"
DELETION = "570f840c7df3870841c93e37480d7a53a67921dd"
ROOT = Path(__file__).resolve().parents[4]
TRACKED_POLICY = (
    ROOT
    / "openspec"
    / "changes"
    / "durable-event-runtime"
    / "evidence"
    / "compatibility-observation-policy.json"
)


def test_tracked_policy_is_checksum_verified_and_binds_git_objects() -> None:
    policy = json.loads(TRACKED_POLICY.read_text(encoding="utf-8"))

    compatibility._verify_policy(policy)
    assert (
        _git("rev-parse", f"{CANDIDATE}^{{tree}}")
        == policy["compatibility_source_tree"]
    )
    assert _git("rev-parse", f"{DELETION}^{{tree}}") == policy["deletion_source_tree"]
    assert _git("rev-parse", f"{DELETION}^") == CANDIDATE


def test_signed_compatibility_release_evidence_passes_strict_verification(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = _write_bundle(tmp_path)

    result = verify_compatibility_release_evidence(**bundle["verify_args"])

    assert result["status"] == "passed"
    assert result["compatibility_release_digest"] == CANDIDATE
    assert result["deletion_release_digest"] == DELETION
    assert (
        result["observer_public_key_fingerprint"]
        != result["consumer_owner_public_key_fingerprint"]
    )
    assert (
        compatibility.main(
            [
                "--observation",
                str(bundle["observation_path"]),
                "--policy",
                str(bundle["policy_path"]),
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
            ]
        )
        == 0
    )
    assert '"status":"passed"' in capsys.readouterr().out


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda value: value["compatibility_release"].__setitem__(
                "release_digest", "1" * 40
            ),
            "compatibility_release_digest_mismatch",
        ),
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
            lambda value: value["external_evidence"].__setitem__(
                "uri", "https://evidence.newsroom.dev/bundles/wrong-digest"
            ),
            "external_evidence.uri_not_content_addressed",
        ),
        (
            lambda value: value["compatibility_release"].__setitem__(
                "deployment_uri", "http://localhost:8000/deployments/1"
            ),
            "compatibility_release.deployment_uri_invalid",
        ),
        (
            lambda value: value.__setitem__("unexpected", True),
            "observation_fields_invalid",
        ),
    ],
)
def test_observation_mutations_fail_closed(
    tmp_path: Path,
    mutation,
    reason: str,
) -> None:
    bundle = _write_bundle(tmp_path)
    observation = deepcopy(bundle["observation"])
    mutation(observation)
    if "unexpected" not in observation:
        _set_record_checksum(observation)
    _rewrite_signed_record(
        bundle["observation_path"],
        bundle["observation_signature_path"],
        observation,
        bundle["observer_key"],
    )

    with pytest.raises(CompatibilityObservationError, match=reason):
        verify_compatibility_release_evidence(**bundle["verify_args"])


def test_external_consumer_signoff_is_bound_to_inventory_and_observation(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    signoff = deepcopy(bundle["signoff"])
    signoff["surfaces"][0]["consumer_count"] = 9
    _set_record_checksum(signoff)
    _rewrite_signed_record(
        bundle["signoff_path"],
        bundle["signoff_signature_path"],
        signoff,
        bundle["owner_key"],
    )

    with pytest.raises(
        CompatibilityObservationError,
        match="consumer_signoff_surfaces_mismatch",
    ):
        verify_compatibility_release_evidence(**bundle["verify_args"])


def test_deployment_and_consumer_authorities_must_be_distinct(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    args = dict(bundle["verify_args"])
    args["trusted_consumer_owner_public_key"] = bundle["observer_public_path"]

    with pytest.raises(
        CompatibilityObservationError,
        match="signing_authority_separation_missing",
    ):
        verify_compatibility_release_evidence(**args)


def test_exact_record_bytes_are_covered_by_detached_signatures(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    bundle["observation_path"].write_bytes(
        bundle["observation_path"].read_bytes() + b"\n"
    )

    with pytest.raises(
        CompatibilityObservationError,
        match="observation_signature_invalid",
    ):
        verify_compatibility_release_evidence(**bundle["verify_args"])


def test_deletion_deployment_must_follow_owner_signoff(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    signoff = deepcopy(bundle["signoff"])
    signoff["signed_at"] = _utc_text(bundle["times"]["deletion"] + timedelta(minutes=1))
    _set_record_checksum(signoff)
    _rewrite_signed_record(
        bundle["signoff_path"],
        bundle["signoff_signature_path"],
        signoff,
        bundle["owner_key"],
    )

    with pytest.raises(
        CompatibilityObservationError,
        match="deletion_deployment_predates_consumer_signoff",
    ):
        verify_compatibility_release_evidence(**bundle["verify_args"])


def test_policy_is_checksum_verified_and_pinned_to_release_git_objects(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    policy = deepcopy(bundle["policy"])
    policy["compatibility_source_tree"] = "1" * 40
    policy.pop("policy_checksum")
    policy["policy_checksum"] = checksum_for(policy)
    bundle["policy_path"].write_text(stable_json_dumps(policy), encoding="utf-8")

    with pytest.raises(
        CompatibilityObservationError,
        match="policy_compatibility_source_tree_mismatch",
    ):
        verify_compatibility_release_evidence(**bundle["verify_args"])


def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    original = bundle["observation_path"].read_text(encoding="utf-8")
    duplicate = original.replace(
        '{"compatibility_release"',
        '{"status":"passed","compatibility_release"',
        1,
    )
    bundle["observation_path"].write_text(duplicate, encoding="utf-8")
    with pytest.raises(
        CompatibilityObservationError,
        match="observation_duplicate_json_key",
    ):
        verify_compatibility_release_evidence(**bundle["verify_args"])

    nonfinite = original.replace('"duration_seconds":7200', '"duration_seconds":NaN')
    bundle["observation_path"].write_text(nonfinite, encoding="utf-8")
    with pytest.raises(
        CompatibilityObservationError,
        match="observation_nonfinite_number",
    ):
        verify_compatibility_release_evidence(**bundle["verify_args"])


def test_consumer_signoff_signature_cannot_be_replaced_by_observer_signature(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    payload = bundle["signoff_path"].read_bytes()
    bundle["signoff_signature_path"].write_bytes(bundle["observer_key"].sign(payload))

    with pytest.raises(
        CompatibilityObservationError,
        match="consumer_signoff_signature_invalid",
    ):
        verify_compatibility_release_evidence(**bundle["verify_args"])


def _write_bundle(tmp_path: Path) -> dict:
    policy = {
        "schema": compatibility.POLICY_SCHEMA,
        "release_id": compatibility.RELEASE_ID,
        "compatibility_source_commit": compatibility.COMPATIBILITY_RELEASE,
        "compatibility_source_tree": compatibility.COMPATIBILITY_TREE,
        "compatibility_parent_commit": compatibility.COMPATIBILITY_PARENT,
        "deletion_source_commit": compatibility.DELETION_RELEASE,
        "deletion_source_tree": compatibility.DELETION_TREE,
        "deletion_parent_commit": compatibility.COMPATIBILITY_RELEASE,
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
    policy["policy_checksum"] = checksum_for(policy)
    policy_path = tmp_path / "compatibility-policy.json"
    policy_path.write_text(stable_json_dumps(policy), encoding="utf-8")
    observer_key = Ed25519PrivateKey.generate()
    owner_key = Ed25519PrivateKey.generate()
    observer_public_path = tmp_path / "observer-public.pem"
    owner_public_path = tmp_path / "owner-public.pem"
    _write_public_key(observer_public_path, observer_key)
    _write_public_key(owner_public_path, owner_key)
    observer_fingerprint = compatibility._public_key_fingerprint(
        observer_key.public_key()
    )
    owner_fingerprint = compatibility._public_key_fingerprint(owner_key.public_key())

    now = datetime.now(UTC).replace(microsecond=0)
    times = {
        "candidate": now - timedelta(hours=6),
        "start": now - timedelta(hours=5),
        "sample": now - timedelta(hours=4),
        "end": now - timedelta(hours=3),
        "signoff": now - timedelta(hours=2),
        "deletion": now - timedelta(hours=1),
        "observer": now - timedelta(minutes=30),
    }
    candidate_build = "sha256:" + "a" * 64
    deletion_build = "sha256:" + "b" * 64
    external_checksum = "sha256:" + "e" * 64
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
            "duration_seconds": 7200,
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
        "deletion_release": {
            "release_digest": DELETION,
            "source_tree": compatibility.DELETION_TREE,
            "parent_release_digest": compatibility.COMPATIBILITY_RELEASE,
            "build_digest": deletion_build,
            "build_uri": f"oci://registry.newsroom.dev/newsroom@{deletion_build}",
            "deployment_id": "deployment-deletion-1",
            "environment": "staging",
            "deployed_at": _utc_text(times["deletion"]),
            "deployment_uri": "https://deployments.newsroom.dev/newsroom/deletion-1",
        },
        "external_evidence": {
            "uri": "https://evidence.newsroom.dev/bundles/" + "e" * 64,
            "checksum": external_checksum,
            "retention_mode": "content_addressed",
            "retention_until": None,
            "retention_lock_id": None,
        },
        "deployment_observer": {
            "observer_id": "deployment-observer",
            "public_key_fingerprint": observer_fingerprint,
            "signed_at": _utc_text(times["observer"]),
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

    signoff = {
        "schema": compatibility.CONSUMER_SIGNOFF_SCHEMA,
        "decision": "approved",
        "release_id": compatibility.RELEASE_ID,
        "policy_checksum": policy["policy_checksum"],
        "compatibility_release_digest": CANDIDATE,
        "deletion_release_digest": DELETION,
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
    verify_args = {
        "policy_path": policy_path,
        "observation_path": observation_path,
        "observation_signature_path": observation_signature_path,
        "trusted_observer_public_key": observer_public_path,
        "consumer_signoff_path": signoff_path,
        "consumer_signoff_signature_path": signoff_signature_path,
        "trusted_consumer_owner_public_key": owner_public_path,
    }
    return {
        "verify_args": verify_args,
        "policy": policy,
        "policy_path": policy_path,
        "observation": observation,
        "signoff": signoff,
        "observation_path": observation_path,
        "observation_signature_path": observation_signature_path,
        "signoff_path": signoff_path,
        "signoff_signature_path": signoff_signature_path,
        "observer_public_path": observer_public_path,
        "owner_public_path": owner_public_path,
        "observer_key": observer_key,
        "owner_key": owner_key,
        "times": times,
    }


def _set_record_checksum(value: dict) -> None:
    value.pop("record_checksum", None)
    value["record_checksum"] = checksum_for(value)


def _rewrite_signed_record(
    record_path: Path,
    signature_path: Path,
    value: dict,
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
