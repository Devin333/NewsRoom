"""Skill trace recording."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class SkillTraceEvent(BaseModel):
    event_type: str
    timestamp: str
    skill_name: str
    message: str
    data: dict = Field(default_factory=dict)


class SkillTraceRecorder:
    def __init__(self):
        self.events: list[SkillTraceEvent] = []

    def record(self, event_type: str, skill_name: str, message: str, data: dict | None = None) -> None:
        self.events.append(
            SkillTraceEvent(
                event_type=event_type,
                timestamp=datetime.now(timezone.utc).isoformat(),
                skill_name=skill_name,
                message=message,
                data=data or {},
            )
        )

    def to_dict(self) -> dict:
        return {"events": [event.model_dump(mode="json") for event in self.events]}
