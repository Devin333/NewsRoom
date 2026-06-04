from __future__ import annotations

from typing import Any

from framework.harness.quality.verdict import HarnessQualityVerdict


class FakeQualityGate:
    def __init__(self, verdict: HarnessQualityVerdict | None = None) -> None:
        self.verdict = verdict or HarnessQualityVerdict(passed=True, score=1.0)
        self.contexts: list[dict[str, Any]] = []

    def evaluate(self, context: dict[str, Any]) -> HarnessQualityVerdict:
        self.contexts.append(dict(context))
        return self.verdict


__all__ = ["FakeQualityGate"]
