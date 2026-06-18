"""阶段A：对 30 篇语料 LLM 合成问答对，固化黄金集到 data/eval/golden_set.json。
跑一次，之后人工抽检修正，评估阶段反复加载复用。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from framework.shared.env import load_root_env

load_root_env()
os.environ["NEWS_DATABASE_DSN"] = "postgresql://root:root@localhost:5432/NewsRoom"

from infrastructure.storage.vector.qdrant_store import qdrant_store_from_env
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore
from business.research.document.chunk_storage import PaperChunkStoreAdapter
from business.research.application.chunk_paper_pipeline import _build_llm_call
from business.research.rag.eval import GoldenSetBuilder, save_golden_set

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


async def main() -> None:
    store = PaperChunkStoreAdapter(PaperChunkStore(qdrant_store_from_env()))
    builder = GoldenSetBuilder(
        store, _build_llm_call(),
        questions_per_chunk=2,
        max_chunks_per_paper=4,   # ~4 chunk × 2 q × 30 paper ≈ 240 QA
        max_concurrency=3,
    )
    pairs = await builder.build(CORPUS)
    save_golden_set(pairs, OUT)
    print(f"\n黄金集生成完成: {len(pairs)} 个问答对 → {OUT}")
    # 按领域统计
    by_dom: dict[str, int] = {}
    for qa in pairs:
        by_dom[qa.domain] = by_dom.get(qa.domain, 0) + 1
    for d in sorted(by_dom):
        print(f"  {d}: {by_dom[d]}")


if __name__ == "__main__":
    asyncio.run(main())
