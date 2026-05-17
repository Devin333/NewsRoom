from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NewsRoomConfig:
    base_url: str
    api_key: str | None = None
    timeout: float | None = 30

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
