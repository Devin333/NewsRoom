from __future__ import annotations

import json
from pathlib import Path

import pytest

from business.boards._artifact_publisher import BOARD_ARTIFACTS
from business.boards._runner import runner_for_board_type
from business.evaluation.fixtures import sample_signal


REQUIRED_RUNTIME_ARTIFACTS = {
    "request.json",
    "workflow_spec.json",
    "output.json",
    "manifest.json",
    "summary.md",
}


@pytest.mark.parametrize("board_type", ["ai_news", "project_radar", "paper_radar", "community_pulse"])
def test_board_run_writes_required_productized_artifacts(board_type: str, tmp_path) -> None:
    result = runner_for_board_type(board_type, artifact_root=tmp_path).run(
        signals=[
            sample_signal("ai_news"),
            sample_signal("github_project"),
            sample_signal("paper"),
            sample_signal("community_discussion"),
        ],
        topic="Agent Memory",
        run_id=f"artifact-{board_type}",
    )
    run_dir = Path(result.artifact_dir)

    for file_name in {*REQUIRED_RUNTIME_ARTIFACTS, *BOARD_ARTIFACTS.values()}:
        assert (run_dir / file_name).exists(), file_name

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    metadata = manifest["business_productization"]
    assert metadata["board_type"] == board_type
    assert metadata["schema_version"] == "business.board.productized.v1"
    assert metadata["source_count"] == 4
    assert metadata["subscription_ready"] is True
    assert metadata["improvement_ready"] is True
