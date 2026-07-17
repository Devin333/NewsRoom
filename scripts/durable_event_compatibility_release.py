from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import ipaddress
import json
import re
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


OBSERVATION_SCHEMA = "newsroom.durable-event-compatibility-observation/v1"
CONSUMER_SIGNOFF_SCHEMA = "newsroom.durable-event-compatibility-consumer-signoff/v1"
POLICY_SCHEMA = "newsroom.durable-event-compatibility-policy/v1"
RELEASE_ID = "durable-event-runtime-migration-1"
COMPATIBILITY_RELEASE = "42a8636cd72aea0c466126fc5f2d69c55db1a1d6"
COMPATIBILITY_TREE = "d6d2c55a965e47009d7dc8cf49582cb90e300c2d"
COMPATIBILITY_PARENT = "f6bce48f786d5b08cc77d226b8b993e6e6b974df"
DELETION_RELEASE = "570f840c7df3870841c93e37480d7a53a67921dd"
DELETION_TREE = "8607c510e87c7f405519f5851949f9f5b5b5203b"
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

_MAX_FILE_BYTES = {
    "policy": 64 * 1024,
    "observation": 4 * 1024 * 1024,
    "consumer_signoff": 1024 * 1024,
    "observation_signature": 4096,
    "consumer_signoff_signature": 4096,
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
    observation_path: str | Path,
    observation_signature_path: str | Path,
    trusted_observer_public_key: str | Path | Ed25519PublicKey,
    consumer_signoff_path: str | Path,
    consumer_signoff_signature_path: str | Path,
    trusted_consumer_owner_public_key: str | Path | Ed25519PublicKey,
) -> dict[str, Any]:
    policy_file = _resolve_regular_file(policy_path, "policy")
    _policy_bytes, policy = _read_json_object(policy_file, "policy")
    policy_facts = _verify_policy(policy)

    observer_key = _coerce_public_key(trusted_observer_public_key)
    owner_key = _coerce_public_key(trusted_consumer_owner_public_key)
    observer_fingerprint = _public_key_fingerprint(observer_key)
    owner_fingerprint = _public_key_fingerprint(owner_key)
    _require(
        observer_fingerprint != owner_fingerprint,
        "signing_authority_separation_missing",
    )

    observation_file = _resolve_regular_file(observation_path, "observation")
    observation_bytes, observation = _read_json_object(
        observation_file,
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
    )

    signoff_file = _resolve_regular_file(consumer_signoff_path, "consumer_signoff")
    signoff_bytes, signoff = _read_json_object(
        signoff_file,
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
    )

    _require(
        signoff_facts["signed_at"] >= observation_facts["window_ended_at"],
        "consumer_signoff_predates_observation",
    )
    _require(
        signoff_facts["signed_at"] <= observation_facts["deletion_deployed_at"],
        "deletion_deployment_predates_consumer_signoff",
    )
    _require(
        observation_facts["observer_signed_at"]
        >= observation_facts["deletion_deployed_at"],
        "observer_signature_predates_deletion_deployment",
    )

    external_evidence = _mapping(
        observation.get("external_evidence"),
        "external_evidence",
    )
    if external_evidence["retention_mode"] == "retention_locked":
        retention_until = _parse_utc(
            external_evidence.get("retention_until"),
            "external_evidence.retention_until",
        )
        _require(
            retention_until > observation_facts["observer_signed_at"],
            "external_evidence_retention_expired",
        )

    return {
        "schema": OBSERVATION_SCHEMA,
        "status": "passed",
        "release_id": policy["release_id"],
        "policy_checksum": policy["policy_checksum"],
        "compatibility_release_digest": policy["compatibility_source_commit"],
        "deletion_release_digest": policy["deletion_source_commit"],
        "observation_record_checksum": observation["record_checksum"],
        "consumer_signoff_checksum": signoff["record_checksum"],
        "observer_public_key_fingerprint": observer_fingerprint,
        "consumer_owner_public_key_fingerprint": owner_fingerprint,
        "external_evidence_uri": external_evidence["uri"],
    }


def _verify_observation_record(
    evidence: Mapping[str, Any],
    *,
    observer_fingerprint: str,
    policy: Mapping[str, Any],
    policy_facts: Mapping[str, Any],
) -> dict[str, datetime]:
    _require_fields(
        evidence,
        {
            "schema",
            "status",
            "release_id",
            "policy_checksum",
            "compatibility_release",
            "observation_window",
            "observations",
            "consumer_inventory",
            "deletion_release",
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
    _verify_record_checksum(evidence, "observation")

    compatibility = _verify_deployment(
        evidence.get("compatibility_release"),
        label="compatibility_release",
        expected_release=policy["compatibility_source_commit"],
        expected_tree=policy["compatibility_source_tree"],
        expected_parent=policy["compatibility_parent_commit"],
    )
    deletion = _verify_deployment(
        evidence.get("deletion_release"),
        label="deletion_release",
        expected_release=policy["deletion_source_commit"],
        expected_tree=policy["deletion_source_tree"],
        expected_parent=policy["deletion_parent_commit"],
    )
    _require(
        compatibility["deployment_id"] != deletion["deployment_id"],
        "deployment_ids_not_distinct",
    )
    _require(
        compatibility["build_digest"] != deletion["build_digest"],
        "build_digests_not_distinct",
    )
    _require(
        compatibility["environment"] == deletion["environment"],
        "deployment_environment_mismatch",
    )

    window = _mapping(evidence.get("observation_window"), "observation_window")
    _require_fields(
        window,
        {"started_at", "ended_at", "duration_seconds"},
        "observation_window",
    )
    started_at = _parse_utc(window.get("started_at"), "observation_window.started_at")
    ended_at = _parse_utc(window.get("ended_at"), "observation_window.ended_at")
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
        deletion["deployed_at"] >= ended_at,
        "deletion_deployment_predates_observation",
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
        required_surfaces=policy_facts["required_consumer_surfaces"],
        required_sources=policy_facts["required_inventory_sources"],
    )
    _verify_external_evidence(evidence.get("external_evidence"))

    observer = _mapping(evidence.get("deployment_observer"), "deployment_observer")
    _require_fields(
        observer,
        {"observer_id", "public_key_fingerprint", "signed_at"},
        "deployment_observer",
    )
    _require_identifier(observer.get("observer_id"), "deployment_observer.observer_id")
    _require(
        observer.get("public_key_fingerprint") == observer_fingerprint,
        "trusted_observer_public_key_mismatch",
    )
    observer_signed_at = _parse_utc(
        observer.get("signed_at"),
        "deployment_observer.signed_at",
    )
    _require_not_future(observer_signed_at, "deployment_observer.signed_at")

    return {
        "window_ended_at": ended_at,
        "deletion_deployed_at": deletion["deployed_at"],
        "observer_signed_at": observer_signed_at,
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
    _require_external_uri(
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
    _require_external_uri(
        deployment.get("deployment_uri"),
        f"{label}.deployment_uri",
    )
    return {
        "build_digest": build_digest,
        "deployment_id": deployment_id,
        "environment": environment,
        "deployed_at": deployed_at,
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
            "deletion_source_commit",
            "deletion_source_tree",
            "deletion_parent_commit",
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
        "deletion_source_commit": DELETION_RELEASE,
        "deletion_source_tree": DELETION_TREE,
        "deletion_parent_commit": COMPATIBILITY_RELEASE,
    }
    for field_name, expected in expected_git.items():
        actual = _require_release_digest(value.get(field_name), f"policy.{field_name}")
        _require(actual == expected, f"policy_{field_name}_mismatch")
    _require(
        value["deletion_parent_commit"] == value["compatibility_source_commit"],
        "policy_release_sequence_invalid",
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
    _verify_record_checksum(value, "policy", checksum_field="policy_checksum")
    return {
        "required_query_surfaces": required_query_surfaces,
        "required_consumer_surfaces": required_consumer_surfaces,
        "required_inventory_sources": required_inventory_sources,
        "minimum_observation_seconds": minimum,
        "maximum_observation_seconds": maximum,
        "maximum_observation_records": maximum_records,
    }


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

    query_sequences: dict[str, list[int]] = {}
    checkpoint_sequences: dict[str, list[int]] = {}
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
        query_sequences.setdefault(run_id, []).append(sequence)

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
        checkpoint_sequences.setdefault(run_id, []).append(sequence)

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

    common_runs = (
        set(query_sequences) & set(checkpoint_sequences) & set(projection_watermarks)
    )
    _require(bool(common_runs), "observation_run_correlation_missing")
    _require(
        any(
            max(projection_watermarks[run_id])
            >= max(query_sequences[run_id] + checkpoint_sequences[run_id])
            for run_id in common_runs
        ),
        "projection_watermark_does_not_cover_observations",
    )


def _verify_consumer_inventory(
    value: Any,
    *,
    started_at: datetime,
    ended_at: datetime,
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
    _require(
        coverage_started_at <= started_at and coverage_ended_at >= ended_at,
        "consumer_inventory_window_incomplete",
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
        _require(
            source_started <= started_at and source_ended >= ended_at,
            "consumer_inventory_source_window_incomplete",
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


def _verify_external_evidence(value: Any) -> None:
    evidence = _mapping(value, "external_evidence")
    _require_fields(
        evidence,
        {
            "uri",
            "checksum",
            "retention_mode",
            "retention_until",
            "retention_lock_id",
        },
        "external_evidence",
    )
    checksum = _require_checksum(evidence.get("checksum"), "external_evidence.checksum")
    mode = evidence.get("retention_mode")
    _require(
        mode in {"content_addressed", "retention_locked"}, "retention_mode_invalid"
    )
    _require_external_uri(
        evidence.get("uri"),
        "external_evidence.uri",
        content_checksum=checksum if mode == "content_addressed" else None,
    )
    if mode == "content_addressed":
        _require(
            evidence.get("retention_until") is None,
            "content_addressed_retention_until_invalid",
        )
        _require(
            evidence.get("retention_lock_id") is None,
            "content_addressed_lock_id_invalid",
        )
    else:
        _parse_utc(evidence.get("retention_until"), "external_evidence.retention_until")
        _require_identifier(
            evidence.get("retention_lock_id"),
            "external_evidence.retention_lock_id",
        )


def _verify_consumer_signoff(
    signoff: Mapping[str, Any],
    *,
    owner_fingerprint: str,
    observation: Mapping[str, Any],
    observation_facts: Mapping[str, datetime],
) -> dict[str, datetime]:
    _require_fields(
        signoff,
        {
            "schema",
            "decision",
            "release_id",
            "policy_checksum",
            "compatibility_release_digest",
            "deletion_release_digest",
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
    deletion = _mapping(observation.get("deletion_release"), "deletion_release")
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
        signoff.get("compatibility_release_digest") == compatibility["release_digest"],
        "consumer_signoff_candidate_mismatch",
    )
    _require(
        signoff.get("deletion_release_digest") == deletion["release_digest"],
        "consumer_signoff_deletion_mismatch",
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
    _require_identifier(
        signoff.get("registry_owner_id"), "consumer_signoff.registry_owner_id"
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
        signer_id == signoff["registry_owner_id"],
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
    return {"signed_at": signed_at}


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
    signature_file = _resolve_regular_file(signature_path, f"{label}_signature")
    signature = _read_signature(signature_file, label)
    try:
        key.verify(signature, payload)
    except InvalidSignature as error:
        raise CompatibilityObservationError(f"{label}_signature_invalid") from error


def _read_signature(path: Path, label: str) -> bytes:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise CompatibilityObservationError(
            f"{label}_signature_not_readable"
        ) from error
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
    path = _resolve_regular_file(value, "trusted_public_key")
    try:
        key = serialization.load_pem_public_key(path.read_bytes())
    except (OSError, ValueError, TypeError) as error:
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
    _require(len(text) <= 2048, f"{field_name}_invalid")
    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    _require(scheme in _ALLOWED_EXTERNAL_SCHEMES, f"{field_name}_invalid")
    _require(
        not parsed.username and not parsed.password,
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
        _require(
            digest.removeprefix("sha256:") in text.lower(),
            f"{field_name}_not_content_addressed",
        )
    return text


def _resolve_regular_file(value: str | Path, label: str) -> Path:
    unresolved = Path(value).absolute()
    _require(not unresolved.is_symlink(), f"{label}_symlink_forbidden")
    try:
        path = unresolved.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise CompatibilityObservationError(f"{label}_not_readable") from error
    _require(path.is_file(), f"{label}_not_regular_file")
    maximum_size = _MAX_FILE_BYTES.get(label)
    if maximum_size is not None:
        size = path.stat().st_size
        _require(0 < size <= maximum_size, f"{label}_size_invalid")
    return path


def _read_json_object(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        payload = path.read_bytes()
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=lambda pairs: _unique_json_object(pairs, label),
            parse_constant=lambda _value: _reject_json_constant(label),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
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
    parser.add_argument("--observation", required=True)
    parser.add_argument("--observation-signature", required=True)
    parser.add_argument("--trusted-observer-public-key", required=True)
    parser.add_argument("--consumer-signoff", required=True)
    parser.add_argument("--consumer-signoff-signature", required=True)
    parser.add_argument("--trusted-consumer-owner-public-key", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = verify_compatibility_release_evidence(
            policy_path=args.policy,
            observation_path=args.observation,
            observation_signature_path=args.observation_signature,
            trusted_observer_public_key=args.trusted_observer_public_key,
            consumer_signoff_path=args.consumer_signoff,
            consumer_signoff_signature_path=args.consumer_signoff_signature,
            trusted_consumer_owner_public_key=args.trusted_consumer_owner_public_key,
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
