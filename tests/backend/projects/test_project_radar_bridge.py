from __future__ import annotations

import json

from backend.projects.bridge import ProjectRadarBridge


def test_project_radar_bridge_maps_real_card_shape_and_sanitizes_metadata() -> None:
    dataset = ProjectRadarBridge().map_payload(
        {
            "board_type": "project_radar",
            "generated_at": "2026-05-29T08:00:00Z",
            "cards": [
                {
                    "card_id": "card_tool",
                    "title": "toolkit",
                    "summary": "Workflow API toolkit. https://github.com/acme/toolkit",
                    "github_url": "https://github.com/acme/toolkit",
                    "tags": ["agent", "api"],
                    "stars": 1000,
                    "star_growth_7d": 50,
                    "ranking_features": {"activity": 0.8, "implementation_evidence": 0.7, "repo_health": 0.6},
                    "confidence": {"value": 0.9},
                    "module_case": {
                        "problem": "Teams need an API-first workflow toolkit.",
                        "design_summary": "Study the public API and CLI workflow shape.",
                    },
                    "evidence_refs": [
                        {
                            "source_name": "GitHub",
                            "source_type": "github",
                            "url": "https://github.com/acme/toolkit",
                            "raw_payload": {"api_key": "secret"},
                            "access_token": "secret",
                            "github-token": "secret",
                            "cookie": "secret",
                        }
                    ],
                }
            ],
        },
        source_run_id="run-1",
    )

    assert dataset.source == "artifact"
    assert dataset.source_run_id == "run-1"
    assert dataset.projects[0].github_url == "https://github.com/acme/toolkit"
    assert dataset.metric_snapshots[0].github_stars == 1000
    assert dataset.growth_snapshots[0].stars_delta == 50
    assert dataset.tool_profiles[0].project_id == dataset.projects[0].id
    assert dataset.cases[0].project_id == dataset.projects[0].id
    assert dataset.collections[0].item_count == 1
    assert "secret" not in json.dumps(dataset.to_dict())


def test_project_radar_bridge_returns_empty_without_synthetic_projects() -> None:
    dataset = ProjectRadarBridge().map_payload({"cards": []}, source_run_id="empty-run")

    assert dataset.projects == []
    assert dataset.tool_profiles == []
    assert dataset.cases == []
    assert "No Project Radar cards" in " ".join(dataset.notices)


def test_project_radar_bridge_skips_cards_without_public_url() -> None:
    dataset = ProjectRadarBridge().map_payload(
        {"cards": [{"card_id": "bad", "title": "private", "summary": "No URL here."}]}
    )

    assert dataset.projects == []
    assert "no public project entities" in " ".join(dataset.notices)


def test_project_radar_bridge_derives_missing_name_from_real_url() -> None:
    dataset = ProjectRadarBridge().map_payload(
        {
            "cards": [
                {
                    "card_id": "nameless",
                    "summary": "Public repository evidence only.",
                    "github_url": "https://github.com/acme/real-tool",
                }
            ]
        }
    )

    assert dataset.projects[0].name == "real-tool"
    assert dataset.projects[0].slug == "acme-real-tool"


def test_project_radar_bridge_does_not_fabricate_cases_or_mentions_without_evidence() -> None:
    dataset = ProjectRadarBridge().map_payload(
        {
            "cards": [
                {
                    "card_id": "thin",
                    "title": "thin-tool",
                    "summary": "Public repository evidence only.",
                    "github_url": "https://github.com/acme/thin-tool",
                    "tags": ["agent"],
                }
            ]
        }
    )

    assert dataset.projects[0].name == "thin-tool"
    assert dataset.metric_snapshots[0].source_mentions == 0
    assert dataset.growth_snapshots[0].mentions_delta == 0
    assert dataset.cases == []
