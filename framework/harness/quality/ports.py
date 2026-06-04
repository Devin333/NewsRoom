from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from framework.harness.quality.verdict import HarnessQualityVerdict


@runtime_checkable
class QualityGatePort(Protocol):
    def evaluate(self, context: dict[str, Any]) -> HarnessQualityVerdict:
        ...


__all__ = ["QualityGatePort"]
