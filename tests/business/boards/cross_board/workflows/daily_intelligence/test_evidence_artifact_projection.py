from __future__ import annotations

from dataclasses import dataclass

from business.boards.cross_board.workflows.daily_intelligence.evidence_artifact_projection import (
    evidence_source_map_from_bundle,
    project_daily_evidence_artifacts,
)


@dataclass(frozen=True)
class EvidenceBundle:
    source_map: dict[str, list[str]]


def test_evidence_artifacts_project_namespaced_bundle_and_fallback_source_map() -> None:
    artifacts = project_daily_evidence_artifacts(
        {
            "evidence.bundle": {
                "bundle_id": "bundle-1",
                "source_map": {"ev-1": ["https://example.com/source"]},
            },
            "evidence.verified_findings": {"claims": []},
        }
    )

    assert [(artifact.artifact_key, artifact.relative_path) for artifact in artifacts] == [
        ("evidence_bundle", "evidence_bundle.json"),
        ("evidence_source_map", "evidence_source_map.json"),
        ("verified_findings", "verified_findings.json"),
    ]
    assert artifacts[1].payload == {"ev-1": ["https://example.com/source"]}


def test_evidence_artifacts_prefer_explicit_source_map() -> None:
    artifacts = project_daily_evidence_artifacts(
        {
            "evidence_bundle": {
                "source_map": {"bundle": ["https://example.com/bundle"]},
            },
            "evidence_source_map": {"explicit": ["https://example.com/explicit"]},
        }
    )

    assert artifacts[1].artifact_key == "evidence_source_map"
    assert artifacts[1].payload == {"explicit": ["https://example.com/explicit"]}


def test_evidence_artifacts_publish_standalone_source_map() -> None:
    artifacts = project_daily_evidence_artifacts(
        {
            "evidence.source_map": {"ev-1": ["https://example.com/source"]},
        }
    )

    assert len(artifacts) == 1
    assert artifacts[0].artifact_key == "evidence_source_map"
    assert artifacts[0].relative_path == "evidence_source_map.json"


def test_evidence_source_map_from_bundle_projects_object_source_map() -> None:
    assert evidence_source_map_from_bundle(
        EvidenceBundle(source_map={"ev-1": ["https://example.com/source"]})
    ) == {"ev-1": ["https://example.com/source"]}


def test_evidence_source_map_from_bundle_skips_missing_source_map() -> None:
    assert evidence_source_map_from_bundle({"items": []}) is None
