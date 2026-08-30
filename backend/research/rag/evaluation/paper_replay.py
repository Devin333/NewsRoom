from __future__ import annotations

from dataclasses import dataclass, field

from backend.research.reading_session.models import ReadingSession
from backend.research.rag.evaluation.paper_gold_builder import QAPair


@dataclass
class ReplayCandidate:
    """A real user Q&A harvested from a reading session, pending ground-truth labeling.

    Unlike a QAPair, this has no source_chunk_id yet — it must be labeled (by a human
    or an LLM picking the most relevant of retrieved_chunk_ids) before it can join the
    golden set. This is the bridge from live traffic to the evaluation corpus.
    """
    question: str
    paper_id: str
    answer: str = ""
    retrieved_chunk_ids: list[str] = field(default_factory=list)  # chunks shown when answered
    session_id: str = ""

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "paper_id": self.paper_id,
            "answer": self.answer,
            "retrieved_chunk_ids": self.retrieved_chunk_ids,
            "session_id": self.session_id,
        }

    def to_golden_pair(self, source_chunk_id: str, *, domain: str = "") -> QAPair:
        """Promote to a golden QAPair once a ground-truth chunk has been chosen."""
        if not source_chunk_id:
            raise ValueError("source_chunk_id is required to promote a replay candidate")
        return QAPair(
            question=self.question,
            source_chunk_id=source_chunk_id,
            paper_id=self.paper_id,
            domain=domain,
        )


class ReplayHarvester:
    """Extracts real Q&A candidates from reading session event streams.

    Pairs each question_asked event with the next answer_generated event in the
    same session. Retrieved chunk ids are read from the answer event's source_refs
    (the chunks the system surfaced when it answered).
    """

    def harvest(self, session: ReadingSession) -> list[ReplayCandidate]:
        candidates: list[ReplayCandidate] = []
        pending_question: str | None = None
        for event in session.events:
            if event.event_type == "question_asked":
                pending_question = (event.text or "").strip() or None
            elif event.event_type == "answer_generated" and pending_question is not None:
                candidates.append(ReplayCandidate(
                    question=pending_question,
                    paper_id=session.paper_id,
                    answer=(event.text or "").strip(),
                    retrieved_chunk_ids=list(event.source_refs),
                    session_id=session.session_id,
                ))
                pending_question = None
        return candidates

    def harvest_many(self, sessions: list[ReadingSession]) -> list[ReplayCandidate]:
        out: list[ReplayCandidate] = []
        for session in sessions:
            out.extend(self.harvest(session))
        return out


__all__ = ["ReplayCandidate", "ReplayHarvester"]
