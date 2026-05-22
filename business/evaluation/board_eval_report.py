from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from business.evaluation.board_eval_result import BoardEvalResult


@dataclass(frozen=True)
class BoardEvalReport:
    results: list[BoardEvalResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def score(self) -> float:
        if not self.results:
            return 0.0
        return round(sum(result.score for result in self.results) / len(self.results), 4)

    @property
    def case_count(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["passed"] = self.passed
        payload["score"] = self.score
        payload["case_count"] = self.case_count
        return payload


__all__ = ["BoardEvalReport"]
