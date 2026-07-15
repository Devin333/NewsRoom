from __future__ import annotations

from collections.abc import Callable

import pytest

from framework.events.runtime.identity import dead_letter_id_for, delivery_id_for


def test_delivery_identity_is_stable_and_generation_scoped() -> None:
    first = delivery_id_for("evt-1", "projection", 2, 1)

    assert first == delivery_id_for("evt-1", "projection", 2, 1)
    assert first.startswith("delivery:")
    assert len(first) == len("delivery:") + 64
    assert first != delivery_id_for("evt-1", "projection", 2, 2)
    assert first != delivery_id_for("evt-1", "projection", 3, 1)


def test_dead_letter_identity_is_stable_and_delivery_scoped() -> None:
    delivery_id = delivery_id_for("evt-1", "projection", 1)
    first = dead_letter_id_for(delivery_id, 1)

    assert first == dead_letter_id_for(delivery_id, 1)
    assert first.startswith("dead-letter:")
    assert len(first) == len("dead-letter:") + 64
    assert first != dead_letter_id_for(delivery_id, 2)


@pytest.mark.parametrize(
    "call",
    [
        lambda: delivery_id_for("", "subscription", 1),
        lambda: delivery_id_for("event", "", 1),
        lambda: delivery_id_for("event", "subscription", 0),
        lambda: dead_letter_id_for("", 1),
        lambda: dead_letter_id_for("delivery:id", 0),
    ],
)
def test_runtime_identity_rejects_invalid_material(call: Callable[[], str]) -> None:
    with pytest.raises((TypeError, ValueError)):
        call()
