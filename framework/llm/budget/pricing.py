from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_usd_per_1m_tokens: float | None = None
    output_usd_per_1m_tokens: float | None = None

