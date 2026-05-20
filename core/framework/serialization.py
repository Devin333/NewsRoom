from __future__ import annotations

from typing import Any

from framework.shared.json import to_jsonable


def to_json_safe(value: Any) -> Any:
    return to_jsonable(value)
