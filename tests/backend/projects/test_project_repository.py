from __future__ import annotations

import json

from backend.projects.repository import ProjectArtifactRepository


def test_project_artifact_repository_rejects_manifest_paths_outside_run_dir(tmp_path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "real-data-business-20260529-project_radar"
    run_dir.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps(
            {
                "board_type": "project_radar",
                "cards": [
                    {
                        "card_id": "project-outside",
                        "title": "outside-project",
                        "github_url": "https://github.com/acme/outside-project",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "business_productization": {"board_type": "project_radar"},
                "artifacts": {"board_output": "../outside.json"},
            }
        ),
        encoding="utf-8",
    )

    dataset = ProjectArtifactRepository(runs_root=runs_root).load_dataset()

    assert dataset.source == "none"
    assert dataset.projects == []
