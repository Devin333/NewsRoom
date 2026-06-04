from __future__ import annotations

from typing import Any

from framework.harness.context.models import ContextEnvelope


def context_payload(envelope: ContextEnvelope | dict[str, Any]) -> dict[str, Any]:
    if isinstance(envelope, ContextEnvelope):
        return envelope.to_dict()
    return dict(envelope)


__all__ = ["context_payload"]
