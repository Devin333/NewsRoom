from __future__ import annotations

from typing import Any, Protocol

from framework.governance.quality.verdict import QualityVerdict


class QualityRule(Protocol):
    def evaluate(self, payload: Any) -> QualityVerdict: ...
