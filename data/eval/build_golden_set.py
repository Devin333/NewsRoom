"""Build the repository evidence golden set from indexed paper chunks.

Run manually after refreshing the real paper corpus, then review the generated
questions before committing `data/eval/golden_set.json`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from business.research.document.models import PaperChunk
from business.research.ports.chunk_store import ChunkStorePort
from business.research.rag.evaluation.paper_evidence_eval import (
    EvidenceGoldenSetBuilder,
    EvidenceQAPair,
    save_evidence_golden_set,
)

# paper_id -> domain（与入库语料一致）
CORPUS: dict[str, str] = {
    "1706.03762": "nlp_transformer", "1810.04805": "nlp_transformer", "1907.11692": "nlp_transformer",
    "1910.10683": "nlp_transformer", "2005.14165": "nlp_transformer",
    "2010.11929": "cv", "1512.03385": "cv", "2103.00020": "cv", "2111.06377": "cv", "1505.04597": "cv",
    "2006.11239": "generative", "1406.2661": "generative", "1312.6114": "generative",
    "2112.10752": "generative", "2105.05233": "generative",
    "2005.11401": "retrieval", "2004.04906": "retrieval", "2002.08909": "retrieval",
    "2208.03299": "retrieval", "2212.10496": "retrieval",
    "2203.02155": "llm_alignment", "2302.13971": "llm_alignment", "2305.18290": "llm_alignment",
    "2201.11903": "llm_alignment", "2204.02311": "llm_alignment",
    "2210.03629": "agent", "2302.04761": "agent", "2303.11366": "agent",
    "2304.03442": "agent", "2308.08155": "agent",
}

OUT = Path("data/eval/golden_set.json")


def build_pairs(
    store: ChunkStorePort,
    corpus: dict[str, str] = CORPUS,
    *,
    max_pairs_per_type: int = 20,
    include_negative: bool = True,
) -> list[EvidenceQAPair]:
    pairs: list[EvidenceQAPair] = []
    for paper_id, domain in corpus.items():
        chunks = _load_paper_chunks(store, paper_id)
        built = EvidenceGoldenSetBuilder(
            max_pairs_per_type=max_pairs_per_type,
            include_negative=include_negative,
        ).build(chunks, domain=domain)
        pairs.extend(built)
    return pairs


def _load_paper_chunks(store: ChunkStorePort, paper_id: str) -> list[PaperChunk]:
    chunks = store.list_chunks(paper_id)
    if chunks:
        return chunks
    return store.search_chunks(
        paper_id,
        "method experiment result conclusion background",
        limit=200,
    )


def main() -> None:
    from business.research.document.chunk_storage import PaperChunkStoreAdapter
    from framework.shared.env import load_root_env
    from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore
    from infrastructure.storage.vector.qdrant_store import qdrant_store_from_env

    load_root_env()
    os.environ["NEWS_DATABASE_DSN"] = "postgresql://root:root@localhost:5432/NewsRoom"

    store = PaperChunkStoreAdapter(PaperChunkStore(qdrant_store_from_env()))
    pairs = build_pairs(store)
    save_evidence_golden_set(pairs, OUT)
    print(f"\nEvidence golden set generated: {len(pairs)} pairs -> {OUT}")
    by_dom: dict[str, int] = {}
    for qa in pairs:
        by_dom[qa.domain] = by_dom.get(qa.domain, 0) + 1
    for d in sorted(by_dom):
        print(f"  {d}: {by_dom[d]}")


if __name__ == "__main__":
    main()
