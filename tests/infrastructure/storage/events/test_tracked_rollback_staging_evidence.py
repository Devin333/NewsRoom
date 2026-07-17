from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from framework.events.canonical import checksum_for
from scripts.durable_event_rollback_staging import _verify_technical_evidence


ROOT = Path(__file__).resolve().parents[4]
BUNDLE = (
    ROOT
    / "openspec"
    / "changes"
    / "durable-event-runtime"
    / "evidence"
    / "rollback-staging-fbdec37a-awaiting-approval"
)
SUPERSEDED_BUNDLE = BUNDLE.with_name(
    "rollback-staging-524afab7-awaiting-approval"
)


def test_previous_pending_bundle_is_explicitly_superseded() -> None:
    readme = (SUPERSEDED_BUNDLE / "README.md").read_text(encoding="utf-8")
    assert "Status: SUPERSEDED" in readme
    assert BUNDLE.name in readme
    assert _read_json(SUPERSEDED_BUNDLE / "manifest.json")[
        "candidate_release_digest"
    ] == "524afab7b26bdfc5945151b192b24990ab12269f"


def test_tracked_pending_approval_bundle_is_complete_and_byte_verified() -> None:
    manifest = _read_json(BUNDLE / "manifest.json")
    assert manifest["schema"] == "newsroom.durable-event-rollback-tracked-bundle/v1"
    assert manifest["status"] == "awaiting_approval"

    expected_paths: set[str] = set()
    bundle_root = BUNDLE.resolve(strict=True)
    for entry in manifest["files"]:
        relative = str(entry["path"])
        assert relative not in expected_paths
        expected_paths.add(relative)
        target = (bundle_root / relative).resolve(strict=True)
        assert target.is_relative_to(bundle_root)
        assert target.is_file()
        assert not target.is_symlink()
        payload = target.read_bytes()
        assert len(payload) == entry["size_bytes"]
        assert f"sha256:{sha256(payload).hexdigest()}" == entry["checksum"]

    actual_paths = {
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file() and path.name not in {"README.md", "manifest.json"}
    }
    assert actual_paths == expected_paths


def test_tracked_technical_bundle_remains_verifiable_and_unqualified() -> None:
    manifest = _read_json(BUNDLE / "manifest.json")
    technical = _verify_technical_evidence(
        BUNDLE / "technical" / "technical-evidence.json"
    )
    assert technical["status"] == "awaiting_approval"
    assert technical["evidence_checksum"] == manifest["technical_evidence_checksum"]
    assert technical["candidate_release_digest"] == manifest[
        "candidate_release_digest"
    ]
    assert technical["rollback_release_digest"] == manifest[
        "rollback_release_digest"
    ]

    request = _read_json(BUNDLE / "technical" / "approval-request.json")
    request_checksum = request.pop("request_checksum")
    assert checksum_for(request) == request_checksum
    assert request_checksum == manifest["approval_request_checksum"]
    assert request["status"] == "awaiting_approval"
    assert request["decision_required"] == "approved"

    forbidden_outputs = (
        "approval-record.json",
        "approval-record.sig",
        "external-evidence.json",
        "qualification.json",
    )
    assert all(not (BUNDLE / name).exists() for name in forbidden_outputs)
    assert not tuple(BUNDLE.rglob("*.pem"))
    assert not tuple(BUNDLE.rglob("*.key"))


def test_tracked_projection_bytes_match_and_contain_no_connection_secrets() -> None:
    candidate = (BUNDLE / "audit" / "projections" / "candidate" / "events.jsonl")
    rollback = (BUNDLE / "audit" / "projections" / "rollback" / "events.jsonl")
    assert candidate.read_bytes() == rollback.read_bytes()

    evidence_bytes = b"\n".join(
        path.read_bytes()
        for path in sorted(BUNDLE.rglob("*"))
        if path.is_file()
    ).lower()
    for forbidden in (
        b"postgresql://",
        b"postgres://",
        b"bearer ",
        b'"password"',
        b'"private_key"',
        b'"api_key"',
    ):
        assert forbidden not in evidence_bytes


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value
