from __future__ import annotations

import json
from pathlib import Path

import pytest

from business.boards._artifact_publisher import BOARD_ARTIFACTS
from business.boards._runner import runner_for_board_type
from tests.fixtures.business.productized_signals import (
    sample_ai_news_productized_signals,
    sample_community_pulse_productized_signals,
    sample_paper_radar_productized_signals,
    sample_project_radar_productized_signals,
)


BOARD_FIXTURES = {
    "ai_news": sample_ai_news_productized_signals,
    "project_radar": sample_project_radar_productized_signals,
    "paper_radar": sample_paper_radar_productized_signals,
    "community_pulse": sample_community_pulse_productized_signals,
}
REQUIRED_ARTIFACTS = (
    "board_output.json",
    "cards.json",
    "detail_pages.json",
    "insights.json",
    "quality_summary.json",
    "subscription_payload.json",
    "feedback_events.json",
    "learning_signals.json",
    "improvement_recommendations.json",
    "improvement_proposals.json",
    "applied_overrides.json",
    "improvement_measurement.json",
    "summary.md",
    "manifest.json",
)


@pytest.mark.parametrize("board_type", sorted(BOARD_FIXTURES))
def test_productized_board_artifact_schema_acceptance(board_type: str, tmp_path) -> None:
    run_id = f"schema-{board_type}"
    result = runner_for_board_type(board_type, artifact_root=tmp_path).run(
        signals=BOARD_FIXTURES[board_type](),
        topic="Agent Memory",
        run_id=run_id,
    )
    run_dir = Path(result.artifact_dir)

    for file_name in REQUIRED_ARTIFACTS:
        assert (run_dir / file_name).exists(), file_name

    manifest = _json(run_dir / "manifest.json")
    metadata = manifest["business_productization"]
    assert metadata["schema_version"] == "business.board.productized.v1"
    assert metadata["run_id"] == run_id
    assert metadata["board_type"] == board_type
    assert metadata["subscription_ready"] is True
    assert metadata["improvement_ready"] is True

    for artifact_key, file_name in BOARD_ARTIFACTS.items():
        assert manifest["artifacts"][artifact_key] == file_name
        _json(run_dir / file_name)

    board_output = _json(run_dir / "board_output.json")
    assert board_output["board_type"] == board_type
    assert board_output["metadata"]["skill_trace_metadata"]

    subscription = _json(run_dir / "subscription_payload.json")
    assert subscription["targets"]

    quality = _json(run_dir / "quality_summary.json")
    assert quality["score"] is not None
    assert quality["status"]

    proposals = _json(run_dir / "improvement_proposals.json")
    assert isinstance(proposals, list)
    assert all(proposal.get("status") for proposal in proposals)

    assert (run_dir / "summary.md").read_text(encoding="utf-8").strip()


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
