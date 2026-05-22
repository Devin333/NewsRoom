from typing import Any

from business.foundation import BoardCard


def has_technology_mapping(card: BoardCard) -> bool:
    return any(_object_type_value(ref.object_type) == "technology" for ref in card.related_refs)


def _object_type_value(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)
