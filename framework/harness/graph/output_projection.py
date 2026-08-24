"""Canonical projection of Worker output into declared Graph slots.

Workers may retain auxiliary fields in their result for a deterministic VERIFY
gate.  Only declared Graph output slots are persisted and made available to
downstream nodes.  Keeping this rule in one place prevents live execution and
offline replay from producing different node-output references.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def project_graph_worker_outputs(
    worker_output: Mapping[str, Any],
    output_keys: Sequence[str],
) -> dict[str, Any] | None:
    """Project a Worker result into pinned Graph output slots.

    A single-output worker stores its complete output mapping under the
    declared slot.  This is the established Graph contract: auxiliary fields
    remain available to deterministic VERIFY logic without changing the slot
    value. Multi-output workers must explicitly provide every declared slot.
    """

    keys = tuple(output_keys)
    if not keys:
        return {}
    if len(keys) == 1:
        return {keys[0]: worker_output}
    if not set(keys).issubset(worker_output):
        return None
    return {output_key: worker_output[output_key] for output_key in keys}


__all__ = ["project_graph_worker_outputs"]
