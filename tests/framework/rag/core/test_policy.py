from __future__ import annotations

import pytest

from framework.rag.core import intent_allowed, intent_budget, position_decay_score


def test_intent_allowed_uses_empty_tuple_as_allow_all():
    assert intent_allowed("method", ()) is True
    assert intent_allowed("method", ("method", "result")) is True
    assert intent_allowed("figure", ("method", "result")) is False


def test_position_decay_score_returns_alpha_at_current_index_and_decays():
    near = position_decay_score(section_index=2, current_index=2, alpha=0.2, sigma=3.0)
    far = position_decay_score(section_index=8, current_index=2, alpha=0.2, sigma=3.0)

    assert near == pytest.approx(0.2)
    assert 0.0 < far < near
    assert position_decay_score(section_index=2, current_index=2, alpha=0.0, sigma=3.0) == 0.0


def test_position_decay_score_handles_non_positive_sigma():
    assert position_decay_score(section_index=2, current_index=2, alpha=0.2, sigma=0.0) == 0.2
    assert position_decay_score(section_index=3, current_index=2, alpha=0.2, sigma=0.0) == 0.0


def test_intent_budget_clamps_to_global_limits():
    assert intent_budget(
        "table",
        intent_budgets={"table": (5, 2000)},
        default_budget=(3, 1200),
        max_chunks=4,
        max_tokens=1000,
    ) == (4, 1000)
    assert intent_budget(
        "method",
        intent_budgets={},
        default_budget=(3, 1200),
        max_chunks=4,
        max_tokens=1000,
    ) == (3, 1000)
