from __future__ import annotations

from pathlib import Path

from core.framework import RunResult
from workflows.daily_intelligence.test_no_llm import run_test_no_llm


class RunApplicationService:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)

    def run_test_no_llm(self, *, topic: str, run_id: str | None = None) -> RunResult:
        return run_test_no_llm(
            artifact_root=self.artifact_root,
            request={"topic": topic},
            run_id=run_id,
        )
