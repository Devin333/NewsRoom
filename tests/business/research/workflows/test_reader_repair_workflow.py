from __future__ import annotations

from business.research.workflows import build_reader_repair_workflow_spec


def test_reader_repair_workflow_does_not_publish_skill_or_write_memory_directly() -> None:
    spec = build_reader_repair_workflow_spec()
    payload = spec.to_dict()

    assert payload["metadata"]["publishes_skill"] is False
    assert payload["metadata"]["writes_memory_directly"] is False
    assert payload["metadata"]["memory_write_owner"] == "framework.harness"
    assert "commit_repair_episode_memory" in spec.step_ids
    assert len(spec.step_ids) == len(set(spec.step_ids))
