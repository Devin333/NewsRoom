from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from business.research.application.chunk_paper_pipeline import ChunkPaperPipeline
from business.research.ports.chunk_indexer import ChunkIndexerPort
from business.research.ports.chunk_repository import ChunkRepositoryPort

logger = logging.getLogger(__name__)


@dataclass
class IngestOutcome:
    arxiv_id: str
    status: str                      # "ok" | "failed"
    total_chunks: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        d = {"arxiv_id": self.arxiv_id, "status": self.status}
        if self.status == "ok":
            d.update(total_chunks=self.total_chunks, by_type=self.by_type)
        else:
            d["error"] = self.error
        return d


@dataclass
class BatchIngestResult:
    outcomes: list[IngestOutcome] = field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "ok")

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "failed")

    @property
    def total_chunks(self) -> int:
        return sum(o.total_chunks for o in self.outcomes if o.status == "ok")

    def to_dict(self) -> dict:
        return {
            "succeeded": self.succeeded,
            "failed": self.failed,
            "total_chunks": self.total_chunks,
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


class BatchIngestService:
    """Batch paper ingestion: fault-tolerant, idempotent, re-runnable.

    Each paper is deleted-then-reinserted so re-running the same ids is safe.
    A single paper failing does not abort the batch.
    """

    def __init__(
        self,
        pipeline: ChunkPaperPipeline,
        chunk_store: ChunkIndexerPort,
        chunk_repo: ChunkRepositoryPort,
        *,
        polite_delay_seconds: float = 1.0,
    ) -> None:
        self._pipeline = pipeline
        self._store = chunk_store
        self._repo = chunk_repo
        self._delay = polite_delay_seconds

    def run(self, arxiv_ids: list[str], *, on_progress=None) -> BatchIngestResult:
        result = BatchIngestResult()
        for idx, arxiv_id in enumerate(arxiv_ids, 1):
            outcome = self._ingest_one(arxiv_id)
            result.outcomes.append(outcome)
            if on_progress is not None:
                on_progress(idx, len(arxiv_ids), outcome)
            if self._delay and idx < len(arxiv_ids):
                time.sleep(self._delay)
        return result

    def _ingest_one(self, arxiv_id: str) -> IngestOutcome:
        paper_id = arxiv_id.replace("/", "_")
        try:
            # idempotent: clear stale chunks first
            self._store.delete_paper_chunks(paper_id)
            self._repo.delete_paper_chunks(paper_id)
            res = self._pipeline.run(arxiv_id)
            return IngestOutcome(
                arxiv_id=arxiv_id, status="ok",
                total_chunks=res.total_chunks, by_type=res.by_type,
            )
        except Exception as exc:
            logger.warning("ingest failed for %s: %s", arxiv_id, exc)
            return IngestOutcome(
                arxiv_id=arxiv_id, status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )


__all__ = ["BatchIngestResult", "BatchIngestService", "IngestOutcome"]
