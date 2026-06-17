"""阶段B：加载黄金集 → 跑检索 → 输出 Hit@K / MRR / NDCG 报告。可反复跑/CI。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from framework.shared.env import load_root_env

load_root_env()

from infrastructure.storage.vector.qdrant_store import qdrant_store_from_env
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore
from business.research.document.chunk_storage import PaperChunkStoreAdapter
from business.research.rag.retriever import ResearchRetriever
from business.research.rag.eval import RetrievalEvaluator, load_golden_set

GOLDEN = Path("data/eval/golden_set.json")


def main() -> None:
    pairs = load_golden_set(GOLDEN)
    store = PaperChunkStoreAdapter(PaperChunkStore(qdrant_store_from_env()))
    evaluator = RetrievalEvaluator(ResearchRetriever(store))
    result = evaluator.evaluate(pairs)
    print(result.report())


if __name__ == "__main__":
    main()
