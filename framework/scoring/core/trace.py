from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from framework.shared.ids import generate_id
from framework.shared.json import to_jsonable
from framework.shared.time import duration_ms, format_datetime, parse_datetime, utc_now


@dataclass(frozen=True)
class ScoringStepTrace:
    step_id: str
    step_type: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: float | None = None
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", parse_datetime(self.started_at) or utc_now())
        object.__setattr__(self, "ended_at", parse_datetime(self.ended_at))
        object.__setattr__(self, "input_summary", dict(self.input_summary or {}))
        object.__setattr__(self, "output_summary", dict(self.output_summary or {}))
        object.__setattr__(self, "warnings", [str(warning) for warning in self.warnings])
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def finish(
        self,
        *,
        status: str = "succeeded",
        output_summary: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> "ScoringStepTrace":
        ended = utc_now()
        return replace(
            self,
            status=status,
            ended_at=ended,
            duration_ms=float(duration_ms(self.started_at, ended)),
            output_summary=dict(output_summary or {}),
            warnings=list(warnings or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_type": self.step_type,
            "status": self.status,
            "started_at": format_datetime(self.started_at),
            "ended_at": format_datetime(self.ended_at),
            "duration_ms": self.duration_ms,
            "input_summary": to_jsonable(self.input_summary),
            "output_summary": to_jsonable(self.output_summary),
            "warnings": list(self.warnings),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoringStepTrace":
        return cls(
            step_id=str(payload["step_id"]),
            step_type=str(payload["step_type"]),
            status=str(payload.get("status") or "pending"),
            started_at=parse_datetime(payload.get("started_at")) or utc_now(),
            ended_at=parse_datetime(payload.get("ended_at")),
            duration_ms=float(payload["duration_ms"]) if payload.get("duration_ms") is not None else None,
            input_summary=dict(payload.get("input_summary") or {}),
            output_summary=dict(payload.get("output_summary") or {}),
            warnings=[str(warning) for warning in payload.get("warnings") or []],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ScoringTrace:
    trace_id: str
    recipe_id: str
    target_id: str | None = None
    target_type: str | None = None
    steps: list[ScoringStepTrace] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "steps",
            [step if isinstance(step, ScoringStepTrace) else ScoringStepTrace.from_dict(dict(step)) for step in self.steps],
        )
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def create(
        cls,
        *,
        recipe_id: str,
        target_id: str | None = None,
        target_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ScoringTrace":
        return cls(
            trace_id=generate_id("score_trace"),
            recipe_id=recipe_id,
            target_id=target_id,
            target_type=target_type,
            metadata=dict(metadata or {}),
        )

    def add_step(self, step: ScoringStepTrace) -> "ScoringTrace":
        return replace(self, steps=[*self.steps, step])

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "recipe_id": self.recipe_id,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "steps": [step.to_dict() for step in self.steps],
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoringTrace":
        return cls(
            trace_id=str(payload["trace_id"]),
            recipe_id=str(payload["recipe_id"]),
            target_id=str(payload["target_id"]) if payload.get("target_id") is not None else None,
            target_type=str(payload["target_type"]) if payload.get("target_type") is not None else None,
            steps=[ScoringStepTrace.from_dict(dict(step)) for step in payload.get("steps") or []],
            metadata=dict(payload.get("metadata") or {}),
        )
