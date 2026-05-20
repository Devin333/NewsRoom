from __future__ import annotations

import json
from typing import Any


class ArtifactContent:
    def __init__(self, content: bytes | str | dict[str, Any]) -> None:
        self.content = content

    def as_bytes(self) -> bytes:
        if isinstance(self.content, bytes):
            return self.content
        if isinstance(self.content, str):
            return self.content.encode("utf-8")
        return json.dumps(
            self.content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def as_text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return self.as_bytes().decode("utf-8")

    def as_json(self) -> Any:
        if isinstance(self.content, dict):
            return dict(self.content)
        return json.loads(self.as_text())
