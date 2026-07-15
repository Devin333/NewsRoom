from __future__ import annotations

from hashlib import sha256

from framework.shared.json import stable_json_dumps


def delivery_id_for(
    event_id: str,
    subscription_id: str,
    subscription_version: int,
    delivery_generation: int = 1,
) -> str:
    """Return the backend-neutral identity for one delivery generation."""

    event_id = _required_text(event_id, "event_id")
    subscription_id = _required_text(subscription_id, "subscription_id")
    subscription_version = _positive_int(
        subscription_version,
        "subscription_version",
    )
    delivery_generation = _positive_int(
        delivery_generation,
        "delivery_generation",
    )
    projection = {
        "delivery_generation": delivery_generation,
        "event_id": event_id,
        "identity_schema": "newsroom.delivery-identity/v1",
        "subscription_id": subscription_id,
        "subscription_version": subscription_version,
    }
    digest = sha256(stable_json_dumps(projection).encode("utf-8")).hexdigest()
    return f"delivery:{digest}"


def dead_letter_id_for(delivery_id: str, delivery_generation: int) -> str:
    """Return the backend-neutral dead-letter identity for a delivery."""

    projection = {
        "dead_letter_schema": "newsroom.dead-letter-identity/v1",
        "delivery_generation": _positive_int(
            delivery_generation,
            "delivery_generation",
        ),
        "delivery_id": _required_text(delivery_id, "delivery_id"),
    }
    digest = sha256(stable_json_dumps(projection).encode("utf-8")).hexdigest()
    return f"dead-letter:{digest}"


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _positive_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


__all__ = ["dead_letter_id_for", "delivery_id_for"]
