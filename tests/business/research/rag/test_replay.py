from __future__ import annotations

import pytest

from business.research.reading_session.models import ReadingEvent, ReadingSession
from business.research.rag.evaluation.paper_replay import ReplayHarvester
from tests.business.research.helpers import FIXED_NOW


def _event(event_id, event_type, *, text=None, source_refs=None):
    return ReadingEvent(
        event_id=event_id,
        event_type=event_type,  # type: ignore[arg-type]
        paper_id="paper-1",
        user_id="user-1",
        text=text,
        source_refs=source_refs or [],
        created_at=FIXED_NOW,
    )


def _session(events):
    return ReadingSession(
        session_id="sess-1",
        paper_id="paper-1",
        user_id="user-1",
        events=events,
        source_refs=["paper://paper-1"],
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


def test_harvest_pairs_question_with_next_answer():
    session = _session([
        _event("e1", "question_asked", text="How does attention work?"),
        _event("e2", "answer_generated", text="It scales queries.", source_refs=["chunk-a", "chunk-b"]),
    ])
    candidates = ReplayHarvester().harvest(session)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.question == "How does attention work?"
    assert c.answer == "It scales queries."
    assert c.retrieved_chunk_ids == ["chunk-a", "chunk-b"]
    assert c.paper_id == "paper-1"


def test_harvest_ignores_unanswered_question():
    session = _session([_event("e1", "question_asked", text="dangling?")])
    assert ReplayHarvester().harvest(session) == []


def test_harvest_multiple_qa_in_order():
    session = _session([
        _event("e1", "question_asked", text="Q1"),
        _event("e2", "answer_generated", text="A1"),
        _event("e3", "highlight_created", text="noise"),
        _event("e4", "question_asked", text="Q2"),
        _event("e5", "answer_generated", text="A2"),
    ])
    candidates = ReplayHarvester().harvest(session)
    assert [c.question for c in candidates] == ["Q1", "Q2"]
    assert [c.answer for c in candidates] == ["A1", "A2"]


def test_promote_to_golden_pair():
    session = _session([
        _event("e1", "question_asked", text="What is the F1 score?"),
        _event("e2", "answer_generated", text="92.", source_refs=["chunk-x"]),
    ])
    candidate = ReplayHarvester().harvest(session)[0]
    qa = candidate.to_golden_pair("chunk-x", domain="nlp")
    assert qa.question == "What is the F1 score?"
    assert qa.source_chunk_id == "chunk-x"
    assert qa.paper_id == "paper-1"
    assert qa.domain == "nlp"


def test_promote_requires_source_chunk():
    session = _session([
        _event("e1", "question_asked", text="q"),
        _event("e2", "answer_generated", text="a"),
    ])
    candidate = ReplayHarvester().harvest(session)[0]
    with pytest.raises(ValueError):
        candidate.to_golden_pair("")


def test_harvest_many_aggregates():
    s1 = _session([_event("e1", "question_asked", text="Q1"), _event("e2", "answer_generated", text="A1")])
    candidates = ReplayHarvester().harvest_many([s1, s1])
    assert len(candidates) == 2
