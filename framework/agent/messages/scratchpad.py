from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scratchpad:
    entries: list[tuple[str, str]] = field(default_factory=list)

    def add_thought(self, text: str) -> None:
        self.entries.append(("thought", text))

    def add_observation(self, text: str) -> None:
        self.entries.append(("observation", text))

    def render(self) -> str:
        return "\n".join(f"{kind}: {text}" for kind, text in self.entries)

    def clear(self) -> None:
        self.entries.clear()
