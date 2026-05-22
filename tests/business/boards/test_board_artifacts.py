from __future__ import annotations

import json
from pathlib import Path

from business.boards.ai_news.runner import AINewsRunner
from business.evaluation.fixtures import sample_signal


def test_board_artifact_payloads_include_metadata_and_cards(tmp_path) -> None:
    result = AINewsRunner(artifact_root=tmp_path).run(
        signals=[sample_signal("ai_news")],
        topic="Agent Memory",
        run_id="artifact-schema-ai",
    )
    run_dir = Path(result.artifact_dir)

    cards = json.loads((run_dir / "cards.json").read_text(encoding="utf-8"))
    quality = json.loads((run_dir / "quality_summary.json").read_text(encoding="utf-8"))
    subscription = json.loads((run_dir / "subscription_payload.json").read_text(encoding="utf-8"))

    assert cards[0]["title"]
    assert quality["skill_trace_metadata"]
    assert subscription["delivery_hints"]["subscription_ready"]
