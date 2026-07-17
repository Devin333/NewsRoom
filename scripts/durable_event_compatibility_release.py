from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from framework.events.canonical import checksum_for
from framework.shared.json import stable_json_dumps


OBSERVATION_SCHEMA = "newsroom.durable-event-compatibility-observation/v2"
CONSUMER_SIGNOFF_SCHEMA = "newsroom.durable-event-compatibility-consumer-signoff/v2"
DELETION_ATTESTATION_SCHEMA = (
    "newsroom.durable-event-compatibility-deletion-deployment-attestation/v1"
)
TRUST_ACTIVATION_SCHEMA = "newsroom.durable-event-compatibility-trust-activation/v1"
POLICY_SCHEMA = "newsroom.durable-event-compatibility-policy/v4"
RELEASE_ID = "durable-event-runtime-migration-1"
COMPATIBILITY_RELEASE = "42a8636cd72aea0c466126fc5f2d69c55db1a1d6"
COMPATIBILITY_TREE = "d6d2c55a965e47009d7dc8cf49582cb90e300c2d"
COMPATIBILITY_PARENT = "f6bce48f786d5b08cc77d226b8b993e6e6b974df"
DELETION_BOUNDARY = "570f840c7df3870841c93e37480d7a53a67921dd"
DELETION_BOUNDARY_TREE = "8607c510e87c7f405519f5851949f9f5b5b5203b"
DELETION_BOUNDARY_PARENT = COMPATIBILITY_RELEASE
QUALIFIED_DELETION_RELEASE = "0a24e52b8f084099aa5f614c7a9c64081ce79ca3"
QUALIFIED_DELETION_TREE = "9ef7b8720e6392845299849dbe1598f60e3d77f5"
QUALIFIED_DELETION_PARENT = "06b0b19eb7c0cd23a33cc98c9defaa449f3df68c"
AUTHORITY_TRUST_PENDING = "pending_external_activation"
AUTHORITY_TRUST_ACTIVE = "active"
ACTIVE_TRUST_EPOCH: int | None = None
TRUSTED_GOVERNANCE_AUTHORITY_ID: str | None = None
TRUSTED_GOVERNANCE_KEY_ID: str | None = None
TRUSTED_GOVERNANCE_PUBLIC_KEY_FINGERPRINT: str | None = None
TRUSTED_OBSERVER_AUTHORITY_ID: str | None = None
TRUSTED_OBSERVER_KEY_ID: str | None = None
TRUSTED_OBSERVER_PUBLIC_KEY_FINGERPRINT: str | None = None
TRUSTED_CONSUMER_OWNER_AUTHORITY_ID: str | None = None
TRUSTED_CONSUMER_OWNER_KEY_ID: str | None = None
TRUSTED_CONSUMER_OWNER_PUBLIC_KEY_FINGERPRINT: str | None = None
ACTIVE_AUTHORITY_POLICY_CHECKSUM: str | None = None
REQUIRED_SURFACES = ("api", "cli", "mcp", "sdk", "sse")
REQUIRED_QUERY_SURFACES = ("api", "cli", "mcp", "sse")
REQUIRED_INVENTORY_SOURCES = (
    "deployment_registry",
    "request_consumer_telemetry",
)
MIN_OBSERVATION_WINDOW = timedelta(hours=1)
MAX_OBSERVATION_WINDOW = timedelta(days=7)
MAX_OBSERVATION_RECORDS = 1000
MAX_EVIDENCE_CLOCK_SKEW = timedelta(minutes=5)
GIT_COMMAND_TIMEOUT_SECONDS = 10

_MAX_FILE_BYTES = {
    "policy": 64 * 1024,
    "authority_activation": 1024 * 1024,
    "observation": 4 * 1024 * 1024,
    "consumer_signoff": 1024 * 1024,
    "deletion_attestation": 1024 * 1024,
    "authority_activation_signature": 4096,
    "observation_signature": 4096,
    "consumer_signoff_signature": 4096,
    "deletion_attestation_signature": 4096,
    "trusted_public_key": 16 * 1024,
}

_RELEASE_DIGEST = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64}|sha256:[0-9a-f]{64})\Z")
_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}\Z")
_ALLOWED_EXTERNAL_SCHEMES = frozenset(
    {"https", "oci", "docker", "s3", "gs", "az", "ipfs"}
)


class CompatibilityObservationError(RuntimeError):
    """A compatibility-release observation failed deterministic qualification."""


def verify_compatibility_release_evidence(
    *,
    policy_path: str | Path,
    authority_activation_path: str | Path,
    authority_activation_signature_path: str | Path,
    trusted_governance_public_key: str | Path | Ed25519PublicKey,
    observation_path: str | Path,
    observation_signature_path: str | Path,
    trusted_observer_public_key: str | Path | Ed25519PublicKey,
    consumer_signoff_path: str | Path,
    consumer_signoff_signature_path: str | Path,
    trusted_consumer_owner_public_key: str | Path | Ed25519PublicKey,
    deletion_attestation_path: str | Path,
    deletion_attestation_signature_path: str | Path,
) -> dict[str, Any]:
    _policy_bytes, policy = _read_json_object(policy_path, "policy")
    policy_facts = _verify_policy(policy)
    _require(
        policy_facts["authority_trust_status"] == AUTHORITY_TRUST_ACTIVE,
        "authority_trust_not_activated",
    )

    governance_key = _coerce_public_key(trusted_governance_public_key)
    observer_key = _coerce_public_key(trusted_observer_public_key)
    owner_key = _coerce_public_key(trusted_consumer_owner_public_key)
    governance_fingerprint = _public_key_fingerprint(governance_key)
    observer_fingerprint = _public_key_fingerprint(observer_key)
    owner_fingerprint = _public_key_fingerprint(owner_key)
    _require(
        len({governance_fingerprint, observer_fingerprint, owner_fingerprint}) == 3,
        "signing_authority_separation_missing",
    )
    _require(
        governance_fingerprint == policy_facts["governance_public_key_fingerprint"],
        "trusted_governance_authority_root_mismatch",
    )
    _require(
        observer_fingerprint == policy_facts["observer_public_key_fingerprint"],
        "trusted_observer_authority_root_mismatch",
    )
    _require(
        owner_fingerprint == policy_facts["consumer_owner_public_key_fingerprint"],
        "trusted_consumer_owner_authority_root_mismatch",
    )

    activation_bytes, activation = _read_json_object(
        authority_activation_path,
        "authority_activation",
    )
    _verify_detached_signature(
        key=governance_key,
        signature_path=authority_activation_signature_path,
        payload=activation_bytes,
        label="authority_activation",
    )
    activation_facts = _verify_trust_activation_record(
        activation,
        governance_fingerprint=governance_fingerprint,
        policy=policy,
        policy_facts=policy_facts,
    )

    observation_bytes, observation = _read_json_object(
        observation_path,
        "observation",
    )
    _verify_detached_signature(
        key=observer_key,
        signature_path=observation_signature_path,
        payload=observation_bytes,
        label="observation",
    )
    observation_facts = _verify_observation_record(
        observation,
        observer_fingerprint=observer_fingerprint,
        policy=policy,
        policy_facts=policy_facts,
        activation=activation,
        activation_facts=activation_facts,
    )

    signoff_bytes, signoff = _read_json_object(
        consumer_signoff_path,
        "consumer_signoff",
    )
    _verify_detached_signature(
        key=owner_key,
        signature_path=consumer_signoff_signature_path,
        payload=signoff_bytes,
        label="consumer_signoff",
    )
    signoff_facts = _verify_consumer_signoff(
        signoff,
        owner_fingerprint=owner_fingerprint,
        observation=observation,
        observation_facts=observation_facts,
        policy=policy,
        policy_facts=policy_facts,
        activation=activation,
    )

    attestation_bytes, attestation = _read_json_object(
        deletion_attestation_path,
        "deletion_attestation",
    )
    _verify_detached_signature(
        key=observer_key,
        signature_path=deletion_attestation_signature_path,
        payload=attestation_bytes,
        label="deletion_attestation",
    )
    attestation_facts = _verify_deletion_attestation(
        attestation,
        observer_fingerprint=observer_fingerprint,
        observation=observation,
        observation_facts=observation_facts,
        signoff=signoff,
        signoff_facts=signoff_facts,
        policy=policy,
        activation=activation,
    )

    observation_external_evidence = observation_facts["external_evidence"]
    activation_evidence = activation_facts["activation_evidence"]
    _verify_evidence_retention(
        activation_evidence,
        signed_at=attestation_facts["attestor_signed_at"],
        error_prefix="activation_evidence",
    )
    _verify_evidence_retention(
        observation_external_evidence,
        signed_at=attestation_facts["attestor_signed_at"],
        error_prefix="external_evidence",
    )
    deletion_deployment_evidence = attestation_facts["deployment_evidence"]

    return {
        "schema": DELETION_ATTESTATION_SCHEMA,
        "status": "passed",
        "release_id": policy["release_id"],
        "policy_checksum": policy["policy_checksum"],
        "trust_epoch": policy_facts["trust_epoch"],
        "trust_activation_record_checksum": activation["record_checksum"],
        "trust_activation_evidence_uri": activation_evidence["uri"],
        "trust_activation_evidence_checksum": activation_evidence["checksum"],
        "governance_authority_id": policy_facts["governance_authority_id"],
        "governance_key_id": policy_facts["governance_key_id"],
        "governance_public_key_fingerprint": governance_fingerprint,
        "compatibility_release_digest": policy["compatibility_source_commit"],
        "deletion_boundary_digest": policy["deletion_boundary_commit"],
        "deletion_release_digest": policy["qualified_deletion_source_commit"],
        "observation_record_checksum": observation["record_checksum"],
        "consumer_signoff_record_checksum": signoff["record_checksum"],
        "deletion_attestation_checksum": attestation["record_checksum"],
        "observer_public_key_fingerprint": observer_fingerprint,
        "consumer_owner_public_key_fingerprint": owner_fingerprint,
        "observer_authority_id": policy_facts["observer_authority_id"],
        "observer_key_id": policy_facts["observer_key_id"],
        "consumer_owner_authority_id": policy_facts["consumer_owner_authority_id"],
        "consumer_owner_key_id": policy_facts["consumer_owner_key_id"],
        "observation_external_evidence_uri": observation_external_evidence["uri"],
        "deletion_deployment_evidence_uri": deletion_deployment_evidence["uri"],
        "deletion_deployment_id": attestation_facts["deployment_id"],
    }


def _verify_observation_record(
    evidence: Mapping[str, Any],
    *,
    observer_fingerprint: str,
    policy: Mapping[str, Any],
    policy_facts: Mapping[str, Any],
    activation: Mapping[str, Any],
    activation_facts: Mapping[str, Any],
) -> dict[str, Any]:
    _require_fields(
        evidence,
        {
            "schema",
            "status",
            "release_id",
            "policy_checksum",
            "trust_epoch",
            "trust_activation_record_checksum",
            "compatibility_release",
            "observation_window",
            "observations",
            "consumer_inventory",
            "external_evidence",
            "deployment_observer",
            "record_checksum",
        },
        "observation",
    )
    _require(evidence.get("schema") == OBSERVATION_SCHEMA, "observation_schema_invalid")
    _require(evidence.get("status") == "passed", "observation_not_passed")
    _require(evidence.get("release_id") == policy["release_id"], "release_id_mismatch")
    _require(
        evidence.get("policy_checksum") == policy["policy_checksum"],
        "policy_checksum_mismatch",
    )
    _require(
        _positive_int(evidence.get("trust_epoch"), "observation.trust_epoch")
        == policy_facts["trust_epoch"],
        "observation_trust_epoch_mismatch",
    )
    _require(
        evidence.get("trust_activation_record_checksum")
        == activation["record_checksum"],
        "observation_trust_activation_checksum_mismatch",
    )
    _verify_record_checksum(evidence, "observation")

    compatibility = _verify_deployment(
        evidence.get("compatibility_release"),
        label="compatibility_release",
        expected_release=policy["compatibility_source_commit"],
        expected_tree=policy["compatibility_source_tree"],
        expected_parent=policy["compatibility_parent_commit"],
    )
    window = _mapping(evidence.get("observation_window"), "observation_window")
    _require_fields(
        window,
        {"started_at", "ended_at", "duration_seconds"},
        "observation_window",
    )
    started_at = _parse_utc(window.get("started_at"), "observation_window.started_at")
    ended_at = _parse_utc(window.get("ended_at"), "observation_window.ended_at")
    _require_not_future(started_at, "observation_window.started_at")
    _require_not_future(ended_at, "observation_window.ended_at")
    _require(ended_at > started_at, "observation_window_not_positive")
    duration = ended_at - started_at
    duration_seconds = _positive_int(
        window.get("duration_seconds"),
        "observation_window.duration_seconds",
    )
    _require(
        duration.total_seconds() == duration_seconds,
        "observation_window_duration_mismatch",
    )
    _require(
        duration_seconds >= policy_facts["minimum_observation_seconds"],
        "observation_window_too_short",
    )
    _require(
        duration_seconds <= policy_facts["maximum_observation_seconds"],
        "observation_window_unbounded",
    )
    _require(
        compatibility["deployed_at"] <= started_at,
        "observation_predates_compatibility_deployment",
    )
    _require(
        activation_facts["attestor_signed_at"] < started_at,
        "authority_activation_not_before_observation_window",
    )
    _require(
        activation_facts["environment"] == compatibility["environment"],
        "activation_environment_mismatch",
    )

    observer = _mapping(evidence.get("deployment_observer"), "deployment_observer")
    _require_fields(
        observer,
        {"observer_id", "public_key_fingerprint", "signed_at"},
        "deployment_observer",
    )
    observer_id = _require_identifier(
        observer.get("observer_id"),
        "deployment_observer.observer_id",
    )
    _require(
        observer_id == policy_facts["observer_authority_id"],
        "deployment_observer_authority_mismatch",
    )
    _require(
        observer.get("public_key_fingerprint") == observer_fingerprint,
        "trusted_observer_public_key_mismatch",
    )
    observer_signed_at = _parse_utc(
        observer.get("signed_at"),
        "deployment_observer.signed_at",
    )
    _require_not_future(observer_signed_at, "deployment_observer.signed_at")
    _require(
        ended_at <= observer_signed_at,
        "observer_signature_predates_observation",
    )

    _verify_observations(
        evidence.get("observations"),
        started_at=started_at,
        ended_at=ended_at,
        required_query_surfaces=policy_facts["required_query_surfaces"],
    )
    _verify_consumer_inventory(
        evidence.get("consumer_inventory"),
        started_at=started_at,
        ended_at=ended_at,
        evidence_signed_at=observer_signed_at,
        required_surfaces=policy_facts["required_consumer_surfaces"],
        required_sources=policy_facts["required_inventory_sources"],
    )
    external_evidence = _verify_external_evidence(evidence.get("external_evidence"))
    _verify_evidence_retention(
        external_evidence,
        signed_at=observer_signed_at,
        error_prefix="external_evidence",
    )

    return {
        "window_started_at": started_at,
        "window_ended_at": ended_at,
        "observer_signed_at": observer_signed_at,
        "observer_id": observer_id,
        "compatibility_deployed_at": compatibility["deployed_at"],
        "compatibility_build_digest": compatibility["build_digest"],
        "compatibility_deployment_id": compatibility["deployment_id"],
        "environment": compatibility["environment"],
        "external_evidence": external_evidence,
    }


def _verify_deployment(
    value: Any,
    *,
    label: str,
    expected_release: str,
    expected_tree: str,
    expected_parent: str,
) -> dict[str, Any]:
    deployment = _mapping(value, label)
    _require_fields(
        deployment,
        {
            "release_digest",
            "source_tree",
            "parent_release_digest",
            "build_digest",
            "build_uri",
            "deployment_id",
            "environment",
            "deployed_at",
            "deployment_uri",
        },
        label,
    )
    release_digest = _require_release_digest(
        deployment.get("release_digest"),
        f"{label}.release_digest",
    )
    _require(release_digest == expected_release, f"{label}_digest_mismatch")
    source_tree = _require_release_digest(
        deployment.get("source_tree"),
        f"{label}.source_tree",
    )
    _require(source_tree == expected_tree, f"{label}_source_tree_mismatch")
    parent_release = _require_release_digest(
        deployment.get("parent_release_digest"),
        f"{label}.parent_release_digest",
    )
    _require(parent_release == expected_parent, f"{label}_parent_release_mismatch")
    build_digest = _require_checksum(
        deployment.get("build_digest"),
        f"{label}.build_digest",
    )
    build_uri = _require_external_uri(
        deployment.get("build_uri"),
        f"{label}.build_uri",
        content_checksum=build_digest,
    )
    deployment_id = _require_identifier(
        deployment.get("deployment_id"),
        f"{label}.deployment_id",
    )
    environment = _require_identifier(
        deployment.get("environment"),
        f"{label}.environment",
    )
    deployed_at = _parse_utc(deployment.get("deployed_at"), f"{label}.deployed_at")
    _require_not_future(deployed_at, f"{label}.deployed_at")
    deployment_uri = _require_external_uri(
        deployment.get("deployment_uri"),
        f"{label}.deployment_uri",
    )
    return {
        "release_digest": release_digest,
        "source_tree": source_tree,
        "parent_release_digest": parent_release,
        "build_digest": build_digest,
        "build_uri": build_uri,
        "deployment_id": deployment_id,
        "environment": environment,
        "deployed_at": deployed_at,
        "deployment_uri": deployment_uri,
    }


def _verify_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    _require_fields(
        value,
        {
            "schema",
            "release_id",
            "compatibility_source_commit",
            "compatibility_source_tree",
            "compatibility_parent_commit",
            "deletion_boundary_commit",
            "deletion_boundary_tree",
            "deletion_boundary_parent_commit",
            "qualified_deletion_source_commit",
            "qualified_deletion_source_tree",
            "qualified_deletion_source_parent_commit",
            "authority_trust_status",
            "trust_epoch",
            "trusted_governance_authority",
            "trusted_observer_authority",
            "trusted_consumer_owner_authority",
            "required_query_surfaces",
            "required_consumer_surfaces",
            "required_inventory_sources",
            "minimum_observation_seconds",
            "maximum_observation_seconds",
            "maximum_observation_records",
            "policy_checksum",
        },
        "policy",
    )
    _require(value.get("schema") == POLICY_SCHEMA, "policy_schema_invalid")
    _require(value.get("release_id") == RELEASE_ID, "policy_release_id_invalid")
    expected_git = {
        "compatibility_source_commit": COMPATIBILITY_RELEASE,
        "compatibility_source_tree": COMPATIBILITY_TREE,
        "compatibility_parent_commit": COMPATIBILITY_PARENT,
        "deletion_boundary_commit": DELETION_BOUNDARY,
        "deletion_boundary_tree": DELETION_BOUNDARY_TREE,
        "deletion_boundary_parent_commit": DELETION_BOUNDARY_PARENT,
        "qualified_deletion_source_commit": QUALIFIED_DELETION_RELEASE,
        "qualified_deletion_source_tree": QUALIFIED_DELETION_TREE,
        "qualified_deletion_source_parent_commit": QUALIFIED_DELETION_PARENT,
    }
    for field_name, expected in expected_git.items():
        actual = _require_release_digest(value.get(field_name), f"policy.{field_name}")
        _require(actual == expected, f"policy_{field_name}_mismatch")
    _require(
        value["deletion_boundary_parent_commit"]
        == value["compatibility_source_commit"],
        "policy_deletion_boundary_sequence_invalid",
    )
    _require(
        value["qualified_deletion_source_commit"] != value["deletion_boundary_commit"],
        "policy_qualified_deletion_ancestry_invalid",
    )
    required_query_surfaces = _strict_text_set(
        value.get("required_query_surfaces"),
        "policy.required_query_surfaces",
    )
    required_consumer_surfaces = _strict_text_set(
        value.get("required_consumer_surfaces"),
        "policy.required_consumer_surfaces",
    )
    required_inventory_sources = _strict_text_set(
        value.get("required_inventory_sources"),
        "policy.required_inventory_sources",
    )
    _require(
        required_query_surfaces == set(REQUIRED_QUERY_SURFACES),
        "policy_query_surfaces_invalid",
    )
    _require(
        required_consumer_surfaces == set(REQUIRED_SURFACES),
        "policy_consumer_surfaces_invalid",
    )
    _require(
        required_inventory_sources == set(REQUIRED_INVENTORY_SOURCES),
        "policy_inventory_sources_invalid",
    )
    minimum = _positive_int(
        value.get("minimum_observation_seconds"),
        "policy.minimum_observation_seconds",
    )
    maximum = _positive_int(
        value.get("maximum_observation_seconds"),
        "policy.maximum_observation_seconds",
    )
    _require(
        minimum == int(MIN_OBSERVATION_WINDOW.total_seconds()),
        "policy_minimum_observation_invalid",
    )
    _require(
        maximum == int(MAX_OBSERVATION_WINDOW.total_seconds()),
        "policy_maximum_observation_invalid",
    )
    _require(minimum <= maximum, "policy_observation_bounds_invalid")
    maximum_records = _positive_int(
        value.get("maximum_observation_records"),
        "policy.maximum_observation_records",
    )
    _require(
        maximum_records == MAX_OBSERVATION_RECORDS,
        "policy_maximum_observation_records_invalid",
    )
    authority_trust = _verify_authority_trust_policy(value)
    _verify_record_checksum(value, "policy", checksum_field="policy_checksum")
    if authority_trust["authority_trust_status"] == AUTHORITY_TRUST_ACTIVE:
        _require(
            ACTIVE_AUTHORITY_POLICY_CHECKSUM is not None
            and value["policy_checksum"] == ACTIVE_AUTHORITY_POLICY_CHECKSUM,
            "active_authority_policy_checksum_mismatch",
        )
    _verify_policy_git_objects(value)
    return {
        "required_query_surfaces": required_query_surfaces,
        "required_consumer_surfaces": required_consumer_surfaces,
        "required_inventory_sources": required_inventory_sources,
        "minimum_observation_seconds": minimum,
        "maximum_observation_seconds": maximum,
        "maximum_observation_records": maximum_records,
        **authority_trust,
    }


def _verify_authority_trust_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    status = _required_text(
        policy.get("authority_trust_status"),
        "policy.authority_trust_status",
    )
    _require(
        status in {AUTHORITY_TRUST_PENDING, AUTHORITY_TRUST_ACTIVE},
        "policy_authority_trust_status_invalid",
    )
    epoch_value = policy.get("trust_epoch")
    governance_value = policy.get("trusted_governance_authority")
    observer_value = policy.get("trusted_observer_authority")
    owner_value = policy.get("trusted_consumer_owner_authority")
    if status == AUTHORITY_TRUST_PENDING:
        _require(
            epoch_value is None
            and governance_value is None
            and observer_value is None
            and owner_value is None,
            "policy_pending_authority_roots_invalid",
        )
        return {
            "authority_trust_status": status,
            "trust_epoch": None,
            "governance_authority_id": None,
            "governance_key_id": None,
            "governance_public_key_fingerprint": None,
            "observer_authority_id": None,
            "observer_key_id": None,
            "observer_public_key_fingerprint": None,
            "consumer_owner_authority_id": None,
            "consumer_owner_key_id": None,
            "consumer_owner_public_key_fingerprint": None,
        }

    trust_epoch = _positive_int(epoch_value, "policy.trust_epoch")
    expected_values = (
        TRUSTED_GOVERNANCE_AUTHORITY_ID,
        TRUSTED_GOVERNANCE_KEY_ID,
        TRUSTED_GOVERNANCE_PUBLIC_KEY_FINGERPRINT,
        TRUSTED_OBSERVER_AUTHORITY_ID,
        TRUSTED_OBSERVER_KEY_ID,
        TRUSTED_OBSERVER_PUBLIC_KEY_FINGERPRINT,
        TRUSTED_CONSUMER_OWNER_AUTHORITY_ID,
        TRUSTED_CONSUMER_OWNER_KEY_ID,
        TRUSTED_CONSUMER_OWNER_PUBLIC_KEY_FINGERPRINT,
    )
    _require(
        isinstance(ACTIVE_TRUST_EPOCH, int)
        and not isinstance(ACTIVE_TRUST_EPOCH, bool)
        and ACTIVE_TRUST_EPOCH > 0
        and trust_epoch == ACTIVE_TRUST_EPOCH
        and all(isinstance(value, str) and value for value in expected_values),
        "compiled_authority_trust_not_activated",
    )
    governance = _verify_authority_root(
        governance_value,
        label="trusted_governance_authority",
        expected_authority_id=TRUSTED_GOVERNANCE_AUTHORITY_ID,
        expected_key_id=TRUSTED_GOVERNANCE_KEY_ID,
        expected_fingerprint=TRUSTED_GOVERNANCE_PUBLIC_KEY_FINGERPRINT,
    )
    observer = _verify_authority_root(
        observer_value,
        label="trusted_observer_authority",
        expected_authority_id=TRUSTED_OBSERVER_AUTHORITY_ID,
        expected_key_id=TRUSTED_OBSERVER_KEY_ID,
        expected_fingerprint=TRUSTED_OBSERVER_PUBLIC_KEY_FINGERPRINT,
    )
    owner = _verify_authority_root(
        owner_value,
        label="trusted_consumer_owner_authority",
        expected_authority_id=TRUSTED_CONSUMER_OWNER_AUTHORITY_ID,
        expected_key_id=TRUSTED_CONSUMER_OWNER_KEY_ID,
        expected_fingerprint=TRUSTED_CONSUMER_OWNER_PUBLIC_KEY_FINGERPRINT,
    )
    roots = (governance, observer, owner)
    _require(
        len({root["authority_id"] for root in roots}) == 3
        and len({root["key_id"] for root in roots}) == 3
        and len({root["public_key_fingerprint"] for root in roots}) == 3,
        "policy_authority_separation_missing",
    )
    return {
        "authority_trust_status": status,
        "trust_epoch": trust_epoch,
        "governance_authority_id": governance["authority_id"],
        "governance_key_id": governance["key_id"],
        "governance_public_key_fingerprint": governance["public_key_fingerprint"],
        "observer_authority_id": observer["authority_id"],
        "observer_key_id": observer["key_id"],
        "observer_public_key_fingerprint": observer["public_key_fingerprint"],
        "consumer_owner_authority_id": owner["authority_id"],
        "consumer_owner_key_id": owner["key_id"],
        "consumer_owner_public_key_fingerprint": owner["public_key_fingerprint"],
    }


def _verify_authority_root(
    value: Any,
    *,
    label: str,
    expected_authority_id: str | None,
    expected_key_id: str | None,
    expected_fingerprint: str | None,
) -> dict[str, str]:
    root = _mapping(value, f"policy.{label}")
    _require_fields(
        root,
        {"authority_id", "key_id", "algorithm", "public_key_fingerprint"},
        f"policy.{label}",
    )
    authority_id = _require_identifier(
        root.get("authority_id"),
        f"policy.{label}.authority_id",
    )
    key_id = _require_identifier(root.get("key_id"), f"policy.{label}.key_id")
    _require(root.get("algorithm") == "Ed25519", f"policy_{label}_algorithm_invalid")
    fingerprint = _require_checksum(
        root.get("public_key_fingerprint"),
        f"policy.{label}.public_key_fingerprint",
    )
    _require(
        authority_id == expected_authority_id
        and key_id == expected_key_id
        and fingerprint == expected_fingerprint,
        f"policy_{label}_mismatch",
    )
    return {
        "authority_id": authority_id,
        "key_id": key_id,
        "public_key_fingerprint": fingerprint,
    }


def _verify_trust_activation_record(
    activation: Mapping[str, Any],
    *,
    governance_fingerprint: str,
    policy: Mapping[str, Any],
    policy_facts: Mapping[str, Any],
) -> dict[str, Any]:
    _require_fields(
        activation,
        {
            "schema",
            "status",
            "release_id",
            "trust_epoch",
            "policy_checksum",
            "trusted_governance_authority",
            "trusted_observer_authority",
            "trusted_consumer_owner_authority",
            "activation_deployment",
            "activation_evidence",
            "governance_attestor",
            "record_checksum",
        },
        "authority_activation",
    )
    _require(
        activation.get("schema") == TRUST_ACTIVATION_SCHEMA,
        "authority_activation_schema_invalid",
    )
    _require(
        activation.get("status") == AUTHORITY_TRUST_ACTIVE,
        "authority_activation_not_active",
    )
    _require(
        activation.get("release_id") == policy["release_id"],
        "authority_activation_release_id_mismatch",
    )
    _require(
        _positive_int(
            activation.get("trust_epoch"),
            "authority_activation.trust_epoch",
        )
        == policy_facts["trust_epoch"],
        "authority_activation_trust_epoch_mismatch",
    )
    _require(
        activation.get("policy_checksum") == policy["policy_checksum"],
        "authority_activation_policy_mismatch",
    )
    for field_name in (
        "trusted_governance_authority",
        "trusted_observer_authority",
        "trusted_consumer_owner_authority",
    ):
        _verify_activation_authority_root(
            activation.get(field_name),
            label=field_name,
            expected=policy[field_name],
        )
    _verify_record_checksum(activation, "authority_activation")

    deployment = _mapping(
        activation.get("activation_deployment"),
        "activation_deployment",
    )
    _require_fields(
        deployment,
        {
            "deployment_id",
            "environment",
            "deployed_at",
            "verifier_build_digest",
            "verifier_build_uri",
            "deployment_uri",
        },
        "activation_deployment",
    )
    deployment_id = _require_identifier(
        deployment.get("deployment_id"),
        "activation_deployment.deployment_id",
    )
    environment = _require_identifier(
        deployment.get("environment"),
        "activation_deployment.environment",
    )
    deployed_at = _parse_utc(
        deployment.get("deployed_at"),
        "activation_deployment.deployed_at",
    )
    _require_not_future(deployed_at, "activation_deployment.deployed_at")
    verifier_build_digest = _require_checksum(
        deployment.get("verifier_build_digest"),
        "activation_deployment.verifier_build_digest",
    )
    verifier_build_uri = _require_external_uri(
        deployment.get("verifier_build_uri"),
        "activation_deployment.verifier_build_uri",
        content_checksum=verifier_build_digest,
    )
    deployment_uri = _require_external_uri(
        deployment.get("deployment_uri"),
        "activation_deployment.deployment_uri",
    )

    attestor = _mapping(
        activation.get("governance_attestor"),
        "governance_attestor",
    )
    _require_fields(
        attestor,
        {"attestor_id", "key_id", "public_key_fingerprint", "signed_at"},
        "governance_attestor",
    )
    attestor_id = _require_identifier(
        attestor.get("attestor_id"),
        "governance_attestor.attestor_id",
    )
    key_id = _require_identifier(
        attestor.get("key_id"),
        "governance_attestor.key_id",
    )
    _require(
        attestor_id == policy_facts["governance_authority_id"]
        and key_id == policy_facts["governance_key_id"],
        "governance_attestor_identity_mismatch",
    )
    _require(
        attestor.get("public_key_fingerprint") == governance_fingerprint,
        "trusted_governance_public_key_mismatch",
    )
    signed_at = _parse_utc(
        attestor.get("signed_at"),
        "governance_attestor.signed_at",
    )
    _require_not_future(signed_at, "governance_attestor.signed_at")
    _require(
        deployed_at <= signed_at,
        "governance_signature_predates_activation_deployment",
    )

    activation_evidence = _verify_external_evidence(
        activation.get("activation_evidence"),
        label="activation_evidence",
    )
    _verify_evidence_retention(
        activation_evidence,
        signed_at=signed_at,
        error_prefix="activation_evidence",
    )
    return {
        "deployment_id": deployment_id,
        "environment": environment,
        "deployed_at": deployed_at,
        "verifier_build_digest": verifier_build_digest,
        "verifier_build_uri": verifier_build_uri,
        "deployment_uri": deployment_uri,
        "attestor_signed_at": signed_at,
        "activation_evidence": activation_evidence,
    }


def _verify_activation_authority_root(
    value: Any,
    *,
    label: str,
    expected: Any,
) -> None:
    root = _mapping(value, f"authority_activation.{label}")
    _require_fields(
        root,
        {"authority_id", "key_id", "algorithm", "public_key_fingerprint"},
        f"authority_activation.{label}",
    )
    _require_identifier(
        root.get("authority_id"),
        f"authority_activation.{label}.authority_id",
    )
    _require_identifier(
        root.get("key_id"),
        f"authority_activation.{label}.key_id",
    )
    _require(
        root.get("algorithm") == "Ed25519",
        f"authority_activation_{label}_algorithm_invalid",
    )
    _require_checksum(
        root.get("public_key_fingerprint"),
        f"authority_activation.{label}.public_key_fingerprint",
    )
    _require(root == expected, f"authority_activation_{label}_mismatch")


def _verify_policy_git_objects(policy: Mapping[str, Any]) -> None:
    """Bind the tracked policy tuples to the repository's immutable Git graph."""
    repo_root = Path(__file__).resolve().parent.parent
    tuples = {
        "compatibility_source": (
            policy["compatibility_source_commit"],
            policy["compatibility_source_tree"],
            policy["compatibility_parent_commit"],
        ),
        "deletion_boundary": (
            policy["deletion_boundary_commit"],
            policy["deletion_boundary_tree"],
            policy["deletion_boundary_parent_commit"],
        ),
        "qualified_deletion_source": (
            policy["qualified_deletion_source_commit"],
            policy["qualified_deletion_source_tree"],
            policy["qualified_deletion_source_parent_commit"],
        ),
    }
    for label, (commit, tree, parent) in tuples.items():
        actual_tree = _git_rev_parse(repo_root, f"{commit}^{{tree}}", label)
        _require(actual_tree == tree, f"policy_{label}_tree_git_mismatch")
        actual_parent = _git_rev_parse(repo_root, f"{commit}^", label)
        _require(actual_parent == parent, f"policy_{label}_parent_git_mismatch")
    result = _run_git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        policy["deletion_boundary_commit"],
        policy["qualified_deletion_source_commit"],
    )
    _require(
        result.returncode == 0,
        "policy_deletion_boundary_not_ancestor",
    )


def _git_rev_parse(repo_root: Path, revision: str, label: str) -> str:
    result = _run_git(repo_root, "rev-parse", revision)
    _require(result.returncode == 0, f"policy_{label}_git_object_missing")
    try:
        return result.stdout.decode("ascii").strip().lower()
    except UnicodeError as error:
        raise CompatibilityObservationError("policy_git_output_invalid") from error


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    try:
        return subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "--no-optional-locks",
                "-C",
                str(repo_root),
                *args,
            ],
            check=False,
            env=environment,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            timeout=GIT_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise CompatibilityObservationError("policy_git_command_timeout") from error
    except OSError as error:
        raise CompatibilityObservationError("policy_git_objects_unavailable") from error


def _verify_observations(
    value: Any,
    *,
    started_at: datetime,
    ended_at: datetime,
    required_query_surfaces: set[str],
) -> None:
    observations = _mapping(value, "observations")
    _require_fields(
        observations,
        {"queries", "checkpoints", "projections"},
        "observations",
    )
    queries = _list(observations.get("queries"), "observations.queries")
    checkpoints = _list(
        observations.get("checkpoints"),
        "observations.checkpoints",
    )
    projections = _list(
        observations.get("projections"),
        "observations.projections",
    )
    _require(bool(queries), "query_observation_missing")
    _require(bool(checkpoints), "checkpoint_observation_missing")
    _require(bool(projections), "projection_observation_missing")
    _require(
        len(queries) <= MAX_OBSERVATION_RECORDS,
        "query_observation_limit_exceeded",
    )
    _require(
        len(checkpoints) <= MAX_OBSERVATION_RECORDS,
        "checkpoint_observation_limit_exceeded",
    )
    _require(
        len(projections) <= MAX_OBSERVATION_RECORDS,
        "projection_observation_limit_exceeded",
    )

    query_source_watermarks: dict[str, list[int]] = {}
    checkpoint_source_watermarks: dict[str, list[int]] = {}
    projection_watermarks: dict[str, list[int]] = {}
    query_ids: set[str] = set()
    query_surfaces: set[str] = set()
    checkpoint_ids: set[str] = set()
    projection_ids: set[str] = set()

    for index, raw in enumerate(queries):
        label = f"observations.queries[{index}]"
        item = _mapping(raw, label)
        _require_fields(
            item,
            {
                "surface",
                "request_id",
                "run_id",
                "observed_at",
                "stream_sequence",
                "source_high_watermark",
                "authoritative_source",
                "projection_fallback_used",
                "response_status",
                "evidence_uri",
            },
            label,
        )
        surface = _required_text(item.get("surface"), f"{label}.surface")
        _require(surface in required_query_surfaces, "query_surface_invalid")
        query_surfaces.add(surface)
        request_id = _require_identifier(item.get("request_id"), f"{label}.request_id")
        _require(request_id not in query_ids, "query_request_id_duplicate")
        query_ids.add(request_id)
        run_id = _require_identifier(item.get("run_id"), f"{label}.run_id")
        _verify_observed_at(item.get("observed_at"), label, started_at, ended_at)
        sequence = _positive_int(
            item.get("stream_sequence"), f"{label}.stream_sequence"
        )
        source_watermark = _positive_int(
            item.get("source_high_watermark"),
            f"{label}.source_high_watermark",
        )
        _require(sequence <= source_watermark, "query_sequence_above_source_watermark")
        _require(
            item.get("authoritative_source") == "durable_store",
            "query_source_not_durable",
        )
        _require(
            item.get("projection_fallback_used") is False,
            "query_projection_fallback_used",
        )
        _require(
            item.get("response_status") == "success", "query_response_not_successful"
        )
        _require_external_uri(item.get("evidence_uri"), f"{label}.evidence_uri")
        query_source_watermarks.setdefault(run_id, []).append(source_watermark)

    for index, raw in enumerate(checkpoints):
        label = f"observations.checkpoints[{index}]"
        item = _mapping(raw, label)
        _require_fields(
            item,
            {
                "checkpoint_id",
                "run_id",
                "event_id",
                "observed_at",
                "stream_sequence",
                "source_high_watermark",
                "sequence_base",
                "legacy_offset_used",
                "evidence_uri",
            },
            label,
        )
        checkpoint_id = _require_identifier(
            item.get("checkpoint_id"),
            f"{label}.checkpoint_id",
        )
        _require(checkpoint_id not in checkpoint_ids, "checkpoint_id_duplicate")
        checkpoint_ids.add(checkpoint_id)
        run_id = _require_identifier(item.get("run_id"), f"{label}.run_id")
        _require_identifier(item.get("event_id"), f"{label}.event_id")
        _verify_observed_at(item.get("observed_at"), label, started_at, ended_at)
        sequence = _positive_int(
            item.get("stream_sequence"), f"{label}.stream_sequence"
        )
        source_watermark = _positive_int(
            item.get("source_high_watermark"),
            f"{label}.source_high_watermark",
        )
        _require(
            sequence <= source_watermark, "checkpoint_sequence_above_source_watermark"
        )
        _require(item.get("sequence_base") == 1, "checkpoint_sequence_base_invalid")
        _require(
            item.get("legacy_offset_used") is False, "checkpoint_legacy_offset_used"
        )
        _require_external_uri(item.get("evidence_uri"), f"{label}.evidence_uri")
        checkpoint_source_watermarks.setdefault(run_id, []).append(source_watermark)

    for index, raw in enumerate(projections):
        label = f"observations.projections[{index}]"
        item = _mapping(raw, label)
        _require_fields(
            item,
            {
                "projection_id",
                "run_id",
                "observed_at",
                "store_high_watermark",
                "manifest_high_watermark",
                "projection_high_watermark",
                "ordered_events_checksum",
                "projection_checksum",
                "raw_secret_findings",
                "store_write_back_count",
                "evidence_uri",
            },
            label,
        )
        projection_id = _require_identifier(
            item.get("projection_id"),
            f"{label}.projection_id",
        )
        _require(projection_id not in projection_ids, "projection_id_duplicate")
        projection_ids.add(projection_id)
        run_id = _require_identifier(item.get("run_id"), f"{label}.run_id")
        _verify_observed_at(item.get("observed_at"), label, started_at, ended_at)
        store_watermark = _positive_int(
            item.get("store_high_watermark"),
            f"{label}.store_high_watermark",
        )
        manifest_watermark = _positive_int(
            item.get("manifest_high_watermark"),
            f"{label}.manifest_high_watermark",
        )
        projection_watermark = _positive_int(
            item.get("projection_high_watermark"),
            f"{label}.projection_high_watermark",
        )
        _require(
            store_watermark == manifest_watermark == projection_watermark,
            "projection_watermark_mismatch",
        )
        _require_checksum(
            item.get("ordered_events_checksum"),
            f"{label}.ordered_events_checksum",
        )
        _require_checksum(
            item.get("projection_checksum"), f"{label}.projection_checksum"
        )
        _require(
            _nonnegative_int(
                item.get("raw_secret_findings"), f"{label}.raw_secret_findings"
            )
            == 0,
            "projection_secret_finding",
        )
        _require(
            _nonnegative_int(
                item.get("store_write_back_count"),
                f"{label}.store_write_back_count",
            )
            == 0,
            "projection_wrote_back_to_store",
        )
        _require_external_uri(item.get("evidence_uri"), f"{label}.evidence_uri")
        projection_watermarks.setdefault(run_id, []).append(projection_watermark)

    _require(
        query_surfaces == required_query_surfaces,
        "query_surface_coverage_incomplete",
    )

    query_runs = set(query_source_watermarks)
    _require(
        bool(query_runs)
        and query_runs
        == set(checkpoint_source_watermarks)
        == set(projection_watermarks),
        "observation_run_correlation_incomplete",
    )
    _require(
        all(
            max(projection_watermarks[run_id])
            >= max(
                query_source_watermarks[run_id] + checkpoint_source_watermarks[run_id]
            )
            for run_id in query_runs
        ),
        "projection_watermark_does_not_cover_source",
    )


def _verify_consumer_inventory(
    value: Any,
    *,
    started_at: datetime,
    ended_at: datetime,
    evidence_signed_at: datetime,
    required_surfaces: set[str],
    required_sources: set[str],
) -> None:
    inventory = _mapping(value, "consumer_inventory")
    _require_fields(
        inventory,
        {
            "registry_id",
            "coverage_started_at",
            "coverage_ended_at",
            "sources",
            "surfaces",
            "inventory_checksum",
        },
        "consumer_inventory",
    )
    _require_identifier(inventory.get("registry_id"), "consumer_inventory.registry_id")
    coverage_started_at = _parse_utc(
        inventory.get("coverage_started_at"),
        "consumer_inventory.coverage_started_at",
    )
    coverage_ended_at = _parse_utc(
        inventory.get("coverage_ended_at"),
        "consumer_inventory.coverage_ended_at",
    )
    _require_not_future(
        coverage_started_at,
        "consumer_inventory.coverage_started_at",
    )
    _require_not_future(
        coverage_ended_at,
        "consumer_inventory.coverage_ended_at",
    )
    _require(
        coverage_started_at <= coverage_ended_at,
        "consumer_inventory_window_invalid",
    )
    _require(
        coverage_started_at <= started_at and coverage_ended_at >= ended_at,
        "consumer_inventory_window_incomplete",
    )
    _require(
        coverage_ended_at <= evidence_signed_at,
        "consumer_inventory_postdates_observer_signature",
    )
    sources = _list(inventory.get("sources"), "consumer_inventory.sources")
    source_ids: set[str] = set()
    for index, raw in enumerate(sources):
        label = f"consumer_inventory.sources[{index}]"
        item = _mapping(raw, label)
        _require_fields(
            item,
            {
                "source_id",
                "coverage_started_at",
                "coverage_ended_at",
                "evidence_uri",
            },
            label,
        )
        source_id = _required_text(item.get("source_id"), f"{label}.source_id")
        _require(source_id in required_sources, "consumer_inventory_source_invalid")
        _require(source_id not in source_ids, "consumer_inventory_source_duplicate")
        source_ids.add(source_id)
        source_started = _parse_utc(
            item.get("coverage_started_at"),
            f"{label}.coverage_started_at",
        )
        source_ended = _parse_utc(
            item.get("coverage_ended_at"),
            f"{label}.coverage_ended_at",
        )
        _require_not_future(source_started, f"{label}.coverage_started_at")
        _require_not_future(source_ended, f"{label}.coverage_ended_at")
        _require(
            source_started <= source_ended, "consumer_inventory_source_window_invalid"
        )
        _require(
            source_started <= started_at and source_ended >= ended_at,
            "consumer_inventory_source_window_incomplete",
        )
        _require(
            source_ended <= evidence_signed_at,
            "consumer_inventory_source_postdates_observer_signature",
        )
        _require_external_uri(item.get("evidence_uri"), f"{label}.evidence_uri")
    _require(source_ids == required_sources, "consumer_inventory_sources_incomplete")
    surfaces = _list(inventory.get("surfaces"), "consumer_inventory.surfaces")
    by_surface: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(surfaces):
        label = f"consumer_inventory.surfaces[{index}]"
        item = _mapping(raw, label)
        _require_fields(
            item,
            {
                "surface",
                "consumer_count",
                "unknown_consumer_count",
                "unowned_consumer_count",
                "flat_record_read_count",
                "owner_id",
                "disposition",
                "observed_at",
                "evidence_uri",
            },
            label,
        )
        surface = _required_text(item.get("surface"), f"{label}.surface")
        _require(surface in required_surfaces, "consumer_surface_invalid")
        _require(surface not in by_surface, "consumer_surface_duplicate")
        count = _nonnegative_int(item.get("consumer_count"), f"{label}.consumer_count")
        _require(
            _nonnegative_int(
                item.get("unknown_consumer_count"),
                f"{label}.unknown_consumer_count",
            )
            == 0,
            "unknown_consumer_found",
        )
        _require(
            _nonnegative_int(
                item.get("unowned_consumer_count"),
                f"{label}.unowned_consumer_count",
            )
            == 0,
            "unowned_consumer_found",
        )
        _require(
            _nonnegative_int(
                item.get("flat_record_read_count"),
                f"{label}.flat_record_read_count",
            )
            == 0,
            "flat_record_consumer_found",
        )
        expected_disposition = "no_consumers" if count == 0 else "compatible"
        _require(
            item.get("disposition") == expected_disposition,
            "consumer_disposition_invalid",
        )
        _require_identifier(item.get("owner_id"), f"{label}.owner_id")
        _verify_observed_at(item.get("observed_at"), label, started_at, ended_at)
        _require_external_uri(item.get("evidence_uri"), f"{label}.evidence_uri")
        by_surface[surface] = item
    _require(
        set(by_surface) == required_surfaces, "consumer_surface_coverage_incomplete"
    )
    checksum = _require_checksum(
        inventory.get("inventory_checksum"),
        "consumer_inventory.inventory_checksum",
    )
    _require(
        checksum
        == checksum_for(
            {
                "registry_id": inventory["registry_id"],
                "coverage_started_at": inventory["coverage_started_at"],
                "coverage_ended_at": inventory["coverage_ended_at"],
                "sources": inventory["sources"],
                "surfaces": inventory["surfaces"],
            }
        ),
        "consumer_inventory_checksum_mismatch",
    )


def _verify_external_evidence(
    value: Any,
    *,
    label: str = "external_evidence",
) -> dict[str, Any]:
    evidence = _mapping(value, label)
    _require_fields(
        evidence,
        {
            "uri",
            "checksum",
            "retention_mode",
            "retention_until",
            "retention_lock_id",
        },
        label,
    )
    checksum = _require_checksum(evidence.get("checksum"), f"{label}.checksum")
    mode = evidence.get("retention_mode")
    _require(
        mode in {"content_addressed", "retention_locked"},
        f"{label}_retention_mode_invalid",
    )
    uri = _require_external_uri(
        evidence.get("uri"),
        f"{label}.uri",
        content_checksum=checksum if mode == "content_addressed" else None,
    )
    if mode == "content_addressed":
        _require(
            evidence.get("retention_until") is None,
            f"{label}_content_addressed_retention_until_invalid",
        )
        _require(
            evidence.get("retention_lock_id") is None,
            f"{label}_content_addressed_lock_id_invalid",
        )
    else:
        _parse_utc(evidence.get("retention_until"), f"{label}.retention_until")
        _require_identifier(
            evidence.get("retention_lock_id"),
            f"{label}.retention_lock_id",
        )
    evidence["uri"] = uri
    evidence["checksum"] = checksum
    evidence["retention_mode"] = mode
    return evidence


def _verify_evidence_retention(
    evidence: Mapping[str, Any],
    *,
    signed_at: datetime,
    error_prefix: str,
) -> None:
    if evidence["retention_mode"] != "retention_locked":
        return
    retention_until = _parse_utc(
        evidence.get("retention_until"),
        f"{error_prefix}.retention_until",
    )
    _require(
        retention_until > signed_at,
        f"{error_prefix}_retention_expired",
    )


def _verify_deletion_plan(
    value: Any,
    *,
    label: str,
    policy: Mapping[str, Any],
) -> dict[str, str]:
    plan = _mapping(value, label)
    _require_fields(
        plan,
        {
            "release_digest",
            "source_tree",
            "parent_release_digest",
            "build_digest",
            "build_uri",
            "environment",
        },
        label,
    )
    release_digest = _require_release_digest(
        plan.get("release_digest"), f"{label}.release_digest"
    )
    _require(
        release_digest == policy["qualified_deletion_source_commit"],
        f"{label}_digest_mismatch",
    )
    source_tree = _require_release_digest(
        plan.get("source_tree"), f"{label}.source_tree"
    )
    _require(
        source_tree == policy["qualified_deletion_source_tree"],
        f"{label}_source_tree_mismatch",
    )
    parent_release = _require_release_digest(
        plan.get("parent_release_digest"), f"{label}.parent_release_digest"
    )
    _require(
        parent_release == policy["qualified_deletion_source_parent_commit"],
        f"{label}_parent_release_mismatch",
    )
    build_digest = _require_checksum(plan.get("build_digest"), f"{label}.build_digest")
    build_uri = _require_external_uri(
        plan.get("build_uri"),
        f"{label}.build_uri",
        content_checksum=build_digest,
    )
    environment = _require_identifier(plan.get("environment"), f"{label}.environment")
    return {
        "release_digest": release_digest,
        "source_tree": source_tree,
        "parent_release_digest": parent_release,
        "build_digest": build_digest,
        "build_uri": build_uri,
        "environment": environment,
    }


def _verify_consumer_signoff(
    signoff: Mapping[str, Any],
    *,
    owner_fingerprint: str,
    observation: Mapping[str, Any],
    observation_facts: Mapping[str, Any],
    policy: Mapping[str, Any],
    policy_facts: Mapping[str, Any],
    activation: Mapping[str, Any],
) -> dict[str, Any]:
    _require_fields(
        signoff,
        {
            "schema",
            "decision",
            "release_id",
            "policy_checksum",
            "trust_epoch",
            "trust_activation_record_checksum",
            "compatibility_release_digest",
            "compatibility_build_digest",
            "approved_deletion_release",
            "observation_record_checksum",
            "consumer_inventory_checksum",
            "registry_id",
            "registry_owner_id",
            "surfaces",
            "signed_at",
            "signer",
            "record_checksum",
        },
        "consumer_signoff",
    )
    _require(
        signoff.get("schema") == CONSUMER_SIGNOFF_SCHEMA,
        "consumer_signoff_schema_invalid",
    )
    _require(signoff.get("decision") == "approved", "consumer_signoff_not_approved")
    _verify_record_checksum(signoff, "consumer_signoff")
    compatibility = _mapping(
        observation.get("compatibility_release"),
        "compatibility_release",
    )
    inventory = _mapping(observation.get("consumer_inventory"), "consumer_inventory")
    _require(
        signoff.get("release_id") == observation["release_id"],
        "consumer_signoff_release_id_mismatch",
    )
    _require(
        signoff.get("policy_checksum") == observation["policy_checksum"],
        "consumer_signoff_policy_mismatch",
    )
    _require(
        _positive_int(signoff.get("trust_epoch"), "consumer_signoff.trust_epoch")
        == observation["trust_epoch"]
        == policy_facts["trust_epoch"],
        "consumer_signoff_trust_epoch_mismatch",
    )
    _require(
        signoff.get("trust_activation_record_checksum")
        == observation["trust_activation_record_checksum"]
        == activation["record_checksum"],
        "consumer_signoff_trust_activation_checksum_mismatch",
    )
    _require(
        signoff.get("compatibility_release_digest")
        == compatibility["release_digest"]
        == policy["compatibility_source_commit"],
        "consumer_signoff_candidate_mismatch",
    )
    compatibility_build_digest = _require_checksum(
        signoff.get("compatibility_build_digest"),
        "consumer_signoff.compatibility_build_digest",
    )
    _require(
        compatibility_build_digest == observation_facts["compatibility_build_digest"],
        "consumer_signoff_compatibility_build_mismatch",
    )
    approved_deletion = _verify_deletion_plan(
        signoff.get("approved_deletion_release"),
        label="approved_deletion_release",
        policy=policy,
    )
    _require(
        approved_deletion["environment"] == observation_facts["environment"],
        "consumer_signoff_deletion_environment_mismatch",
    )
    _require(
        approved_deletion["build_digest"]
        != observation_facts["compatibility_build_digest"],
        "consumer_signoff_build_not_distinct",
    )
    _require(
        signoff.get("observation_record_checksum") == observation["record_checksum"],
        "consumer_signoff_observation_checksum_mismatch",
    )
    _require(
        signoff.get("consumer_inventory_checksum") == inventory["inventory_checksum"],
        "consumer_signoff_inventory_checksum_mismatch",
    )
    _require(
        signoff.get("registry_id") == inventory["registry_id"],
        "consumer_registry_id_mismatch",
    )
    registry_owner_id = _require_identifier(
        signoff.get("registry_owner_id"), "consumer_signoff.registry_owner_id"
    )
    _require(
        registry_owner_id == policy_facts["consumer_owner_authority_id"],
        "consumer_owner_authority_mismatch",
    )

    signed_surfaces = _list(signoff.get("surfaces"), "consumer_signoff.surfaces")
    normalized_signed = _normalize_signoff_surfaces(signed_surfaces)
    normalized_inventory = _normalize_inventory_surfaces(inventory["surfaces"])
    _require(
        normalized_signed == normalized_inventory, "consumer_signoff_surfaces_mismatch"
    )

    signer = _mapping(signoff.get("signer"), "consumer_signoff.signer")
    _require_fields(
        signer,
        {"signer_id", "public_key_fingerprint"},
        "consumer_signoff.signer",
    )
    signer_id = _require_identifier(
        signer.get("signer_id"), "consumer_signoff.signer.signer_id"
    )
    _require(
        signer_id == registry_owner_id,
        "consumer_signoff_signer_not_registry_owner",
    )
    _require(
        signer.get("public_key_fingerprint") == owner_fingerprint,
        "trusted_consumer_owner_public_key_mismatch",
    )
    observer = _mapping(observation.get("deployment_observer"), "deployment_observer")
    _require(
        signer_id != observer["observer_id"], "observer_and_consumer_owner_not_distinct"
    )
    signed_at = _parse_utc(signoff.get("signed_at"), "consumer_signoff.signed_at")
    _require_not_future(signed_at, "consumer_signoff.signed_at")
    _require(
        observation_facts["observer_signed_at"] <= signed_at,
        "consumer_signoff_predates_observer_signature",
    )
    return {
        "signed_at": signed_at,
        "approved_deletion_release": approved_deletion,
        "registry_owner_id": signer_id,
    }


def _verify_deletion_attestation(
    attestation: Mapping[str, Any],
    *,
    observer_fingerprint: str,
    observation: Mapping[str, Any],
    observation_facts: Mapping[str, Any],
    signoff: Mapping[str, Any],
    signoff_facts: Mapping[str, Any],
    policy: Mapping[str, Any],
    activation: Mapping[str, Any],
) -> dict[str, Any]:
    _require_fields(
        attestation,
        {
            "schema",
            "status",
            "release_id",
            "policy_checksum",
            "trust_epoch",
            "trust_activation_record_checksum",
            "observation_record_checksum",
            "consumer_signoff_record_checksum",
            "deletion_release",
            "deployment_evidence",
            "deployment_attestor",
            "record_checksum",
        },
        "deletion_attestation",
    )
    _require(
        attestation.get("schema") == DELETION_ATTESTATION_SCHEMA,
        "deletion_attestation_schema_invalid",
    )
    _require(
        attestation.get("status") == "passed",
        "deletion_attestation_not_passed",
    )
    _require(
        attestation.get("release_id")
        == observation["release_id"]
        == signoff["release_id"],
        "deletion_attestation_release_id_mismatch",
    )
    _require(
        attestation.get("policy_checksum")
        == observation["policy_checksum"]
        == signoff["policy_checksum"]
        == policy["policy_checksum"],
        "deletion_attestation_policy_mismatch",
    )
    _require(
        _positive_int(
            attestation.get("trust_epoch"),
            "deletion_attestation.trust_epoch",
        )
        == observation["trust_epoch"]
        == signoff["trust_epoch"],
        "deletion_attestation_trust_epoch_mismatch",
    )
    _require(
        attestation.get("trust_activation_record_checksum")
        == observation["trust_activation_record_checksum"]
        == signoff["trust_activation_record_checksum"]
        == activation["record_checksum"],
        "deletion_attestation_trust_activation_checksum_mismatch",
    )
    _require(
        attestation.get("observation_record_checksum")
        == observation["record_checksum"],
        "deletion_attestation_observation_checksum_mismatch",
    )
    _require(
        attestation.get("consumer_signoff_record_checksum")
        == signoff["record_checksum"],
        "deletion_attestation_consumer_signoff_checksum_mismatch",
    )
    _verify_record_checksum(attestation, "deletion_attestation")

    deletion = _verify_deployment(
        attestation.get("deletion_release"),
        label="deletion_release",
        expected_release=policy["qualified_deletion_source_commit"],
        expected_tree=policy["qualified_deletion_source_tree"],
        expected_parent=policy["qualified_deletion_source_parent_commit"],
    )
    approved = signoff_facts["approved_deletion_release"]
    _require(
        all(
            deletion[field] == approved[field]
            for field in (
                "release_digest",
                "source_tree",
                "parent_release_digest",
                "build_digest",
                "build_uri",
                "environment",
            )
        ),
        "deletion_attestation_plan_mismatch",
    )
    _require(
        deletion["environment"] == observation_facts["environment"],
        "deletion_attestation_environment_mismatch",
    )
    _require(
        deletion["deployment_id"] != observation_facts["compatibility_deployment_id"],
        "deletion_deployment_id_not_distinct",
    )
    _require(
        deletion["build_digest"] != observation_facts["compatibility_build_digest"],
        "deletion_build_digest_not_distinct",
    )
    _require(
        signoff_facts["signed_at"] <= deletion["deployed_at"],
        "deletion_deployment_predates_consumer_signoff",
    )

    attestor = _mapping(
        attestation.get("deployment_attestor"),
        "deployment_attestor",
    )
    _require_fields(
        attestor,
        {"attestor_id", "public_key_fingerprint", "signed_at"},
        "deployment_attestor",
    )
    attestor_id = _require_identifier(
        attestor.get("attestor_id"), "deployment_attestor.attestor_id"
    )
    _require(
        attestor_id == observation_facts["observer_id"],
        "deletion_attestor_identity_mismatch",
    )
    _require(
        attestor.get("public_key_fingerprint") == observer_fingerprint,
        "trusted_deletion_attestor_public_key_mismatch",
    )
    signed_at = _parse_utc(attestor.get("signed_at"), "deployment_attestor.signed_at")
    _require_not_future(signed_at, "deployment_attestor.signed_at")
    _require(
        deletion["deployed_at"] <= signed_at,
        "deletion_attestor_signature_predates_deployment",
    )

    deployment_evidence = _verify_external_evidence(
        attestation.get("deployment_evidence"),
        label="deployment_evidence",
    )
    _verify_evidence_retention(
        deployment_evidence,
        signed_at=signed_at,
        error_prefix="deployment_evidence",
    )
    return {
        "deployment_id": deletion["deployment_id"],
        "deployed_at": deletion["deployed_at"],
        "attestor_signed_at": signed_at,
        "deployment_evidence": deployment_evidence,
    }


def _normalize_signoff_surfaces(value: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(value):
        label = f"consumer_signoff.surfaces[{index}]"
        item = _mapping(raw, label)
        _require_fields(
            item,
            {
                "surface",
                "consumer_count",
                "owner_id",
                "disposition",
                "flat_record_read_count",
            },
            label,
        )
        surface = _required_text(item.get("surface"), f"{label}.surface")
        _require(surface in REQUIRED_SURFACES, "consumer_signoff_surface_invalid")
        _require(surface not in result, "consumer_signoff_surface_duplicate")
        result[surface] = item
    _require(
        set(result) == set(REQUIRED_SURFACES),
        "consumer_signoff_surface_coverage_incomplete",
    )
    return result


def _normalize_inventory_surfaces(value: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in _list(value, "consumer_inventory.surfaces"):
        item = _mapping(raw, "consumer_inventory.surface")
        surface = _required_text(item.get("surface"), "consumer_inventory.surface")
        result[surface] = {
            "surface": surface,
            "consumer_count": item["consumer_count"],
            "owner_id": item["owner_id"],
            "disposition": item["disposition"],
            "flat_record_read_count": item["flat_record_read_count"],
        }
    return result


def _verify_observed_at(
    value: Any,
    label: str,
    started_at: datetime,
    ended_at: datetime,
) -> datetime:
    observed_at = _parse_utc(value, f"{label}.observed_at")
    _require(started_at <= observed_at <= ended_at, "observation_outside_window")
    return observed_at


def _verify_record_checksum(
    value: Mapping[str, Any],
    label: str,
    *,
    checksum_field: str = "record_checksum",
) -> None:
    expected = _require_checksum(value.get(checksum_field), f"{label}.{checksum_field}")
    payload = dict(value)
    payload.pop(checksum_field, None)
    _require(checksum_for(payload) == expected, f"{label}_record_checksum_mismatch")


def _verify_detached_signature(
    *,
    key: Ed25519PublicKey,
    signature_path: str | Path,
    payload: bytes,
    label: str,
) -> None:
    signature = _read_signature(signature_path, label)
    try:
        key.verify(signature, payload)
    except InvalidSignature as error:
        raise CompatibilityObservationError(f"{label}_signature_invalid") from error


def _read_signature(path: str | Path, label: str) -> bytes:
    payload = _read_bounded_regular_file(path, f"{label}_signature")
    if len(payload) == 64:
        return payload
    try:
        decoded = base64.b64decode(payload.strip(), validate=True)
    except (ValueError, binascii.Error) as error:
        raise CompatibilityObservationError(f"{label}_signature_invalid") from error
    _require(len(decoded) == 64, f"{label}_signature_invalid")
    return decoded


def _coerce_public_key(value: str | Path | Ed25519PublicKey) -> Ed25519PublicKey:
    if isinstance(value, Ed25519PublicKey):
        return value
    payload = _read_bounded_regular_file(value, "trusted_public_key")
    try:
        key = serialization.load_pem_public_key(payload)
    except (ValueError, TypeError) as error:
        raise CompatibilityObservationError("trusted_public_key_invalid") from error
    _require(isinstance(key, Ed25519PublicKey), "trusted_public_key_not_ed25519")
    return key


def _public_key_fingerprint(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _require_external_uri(
    value: Any,
    field_name: str,
    *,
    content_checksum: str | None = None,
) -> str:
    text = _required_text(value, field_name)
    _require(
        len(text) <= 2048
        and all(0x20 <= ord(character) < 0x7F for character in text)
        and "\\" not in text,
        f"{field_name}_invalid",
    )
    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    _require(scheme in _ALLOWED_EXTERNAL_SCHEMES, f"{field_name}_invalid")
    _require(
        not parsed.username and not parsed.password,
        f"{field_name}_credentials_forbidden",
    )
    _require(
        not parsed.params and not parsed.query and not parsed.fragment,
        f"{field_name}_credentials_forbidden",
    )
    if scheme == "https":
        host = (parsed.hostname or "").lower()
        _require(bool(host and parsed.path), f"{field_name}_invalid")
        _require(
            host != "localhost"
            and not host.endswith(
                (
                    ".local",
                    ".localhost",
                    ".internal",
                    ".lan",
                    ".example",
                    ".invalid",
                    ".test",
                )
            ),
            f"{field_name}_not_external",
        )
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None:
            _require(
                not (
                    address.is_private
                    or address.is_loopback
                    or address.is_link_local
                    or address.is_reserved
                    or address.is_unspecified
                ),
                f"{field_name}_not_external",
            )
    else:
        _require(bool(parsed.netloc or parsed.path), f"{field_name}_invalid")
    if content_checksum is not None:
        digest = _require_checksum(content_checksum, f"{field_name}.content_checksum")
        digest_hex = digest.removeprefix("sha256:")
        if scheme in {"oci", "docker"}:
            is_content_addressed = parsed.path.lower().endswith(f"@sha256:{digest_hex}")
        else:
            final_segment = parsed.path.rstrip("/").rsplit("/", 1)[-1].lower()
            is_content_addressed = final_segment in {
                digest_hex,
                f"sha256:{digest_hex}",
            }
        _require(is_content_addressed, f"{field_name}_not_content_addressed")
    return text


def _read_bounded_regular_file(value: str | Path, label: str) -> bytes:
    maximum_size = _MAX_FILE_BYTES.get(label)
    _require(maximum_size is not None, f"{label}_size_policy_missing")
    try:
        path = Path(value).absolute()
    except (OSError, TypeError, ValueError) as error:
        raise CompatibilityObservationError(f"{label}_not_readable") from error
    before = _lstat_without_links(path, label)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CompatibilityObservationError(f"{label}_not_readable") from error
    try:
        opened = os.fstat(descriptor)
        _require(stat.S_ISREG(opened.st_mode), f"{label}_not_regular_file")
        _require(os.path.samestat(before, opened), f"{label}_changed_during_read")
        _require(
            0 < opened.st_size <= maximum_size,
            f"{label}_size_invalid",
        )
        payload = _read_descriptor(descriptor, maximum_size, label)
        after = os.fstat(descriptor)
        current = _lstat_without_links(path, label)
        _require(
            os.path.samestat(opened, after)
            and os.path.samestat(opened, current)
            and opened.st_size == after.st_size == len(payload)
            and opened.st_mtime_ns == after.st_mtime_ns,
            f"{label}_changed_during_read",
        )
    except OSError as error:
        raise CompatibilityObservationError(f"{label}_not_readable") from error
    finally:
        os.close(descriptor)
    return payload


def _lstat_without_links(path: Path, label: str) -> os.stat_result:
    final_status: os.stat_result | None = None
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    for component in (path, *path.parents):
        try:
            status = os.lstat(component)
        except OSError as error:
            raise CompatibilityObservationError(f"{label}_not_readable") from error
        is_reparse_point = bool(
            reparse_flag and getattr(status, "st_file_attributes", 0) & reparse_flag
        )
        _require(
            not stat.S_ISLNK(status.st_mode) and not is_reparse_point,
            f"{label}_symlink_forbidden",
        )
        if component == path:
            final_status = status
    _require(final_status is not None, f"{label}_not_readable")
    return final_status


def _read_descriptor(descriptor: int, maximum_size: int, label: str) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum_size + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    _require(len(payload) <= maximum_size, f"{label}_size_invalid")
    return payload


def _read_json_object(
    path: str | Path,
    label: str,
) -> tuple[bytes, dict[str, Any]]:
    payload = _read_bounded_regular_file(path, label)
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=lambda pairs: _unique_json_object(pairs, label),
            parse_constant=lambda _value: _reject_json_constant(label),
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CompatibilityObservationError(f"{label}_not_readable") from error
    _require(isinstance(value, Mapping), f"{label}_root_not_object")
    return payload, dict(value)


def _unique_json_object(
    pairs: list[tuple[str, Any]],
    label: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CompatibilityObservationError(f"{label}_duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(label: str) -> None:
    raise CompatibilityObservationError(f"{label}_nonfinite_number")


def _require_fields(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    _require(set(value) == fields, f"{label}_fields_invalid")


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping), f"{field_name}_not_object")
    return dict(value)


def _list(value: Any, field_name: str) -> list[Any]:
    _require(isinstance(value, list), f"{field_name}_not_array")
    return list(value)


def _strict_text_set(value: Any, field_name: str) -> set[str]:
    items = _list(value, field_name)
    result = {_required_text(item, f"{field_name}[]") for item in items}
    _require(len(result) == len(items), f"{field_name}_duplicate")
    return result


def _required_text(value: Any, field_name: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{field_name}_invalid")
    return value.strip()


def _require_identifier(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    _require(_SAFE_IDENTIFIER.fullmatch(text) is not None, f"{field_name}_invalid")
    return text


def _require_release_digest(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name).lower()
    _require(_RELEASE_DIGEST.fullmatch(text) is not None, f"{field_name}_invalid")
    return text


def _require_checksum(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name).lower()
    _require(_CHECKSUM.fullmatch(text) is not None, f"{field_name}_invalid")
    return text


def _nonnegative_int(value: Any, field_name: str) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0,
        f"{field_name}_invalid",
    )
    return int(value)


def _positive_int(value: Any, field_name: str) -> int:
    result = _nonnegative_int(value, field_name)
    _require(result > 0, f"{field_name}_invalid")
    return result


def _parse_utc(value: Any, field_name: str) -> datetime:
    text = _required_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise CompatibilityObservationError(f"{field_name}_invalid") from error
    _require(parsed.tzinfo is not None, f"{field_name}_invalid")
    return parsed.astimezone(UTC)


def _require_not_future(value: datetime, field_name: str) -> None:
    _require(
        value <= datetime.now(UTC) + MAX_EVIDENCE_CLOCK_SKEW,
        f"{field_name}_in_future",
    )


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise CompatibilityObservationError(reason)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.durable_event_compatibility_release",
        description="Verify signed compatibility-release deployment observation evidence.",
    )
    parser.add_argument("--policy", required=True)
    parser.add_argument("--authority-activation", required=True)
    parser.add_argument("--authority-activation-signature", required=True)
    parser.add_argument("--trusted-governance-public-key", required=True)
    parser.add_argument("--observation", required=True)
    parser.add_argument("--observation-signature", required=True)
    parser.add_argument("--trusted-observer-public-key", required=True)
    parser.add_argument("--consumer-signoff", required=True)
    parser.add_argument("--consumer-signoff-signature", required=True)
    parser.add_argument("--trusted-consumer-owner-public-key", required=True)
    parser.add_argument("--deletion-attestation", required=True)
    parser.add_argument("--deletion-attestation-signature", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = verify_compatibility_release_evidence(
            policy_path=args.policy,
            authority_activation_path=args.authority_activation,
            authority_activation_signature_path=args.authority_activation_signature,
            trusted_governance_public_key=args.trusted_governance_public_key,
            observation_path=args.observation,
            observation_signature_path=args.observation_signature,
            trusted_observer_public_key=args.trusted_observer_public_key,
            consumer_signoff_path=args.consumer_signoff,
            consumer_signoff_signature_path=args.consumer_signoff_signature,
            trusted_consumer_owner_public_key=args.trusted_consumer_owner_public_key,
            deletion_attestation_path=args.deletion_attestation,
            deletion_attestation_signature_path=args.deletion_attestation_signature,
        )
    except (CompatibilityObservationError, OSError, ValueError) as error:
        print(
            stable_json_dumps(
                {
                    "status": "failed",
                    "reason_class": type(error).__name__,
                    "reason": str(error),
                }
            ),
            file=sys.stderr,
        )
        return 1
    print(stable_json_dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
