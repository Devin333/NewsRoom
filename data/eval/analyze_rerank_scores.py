"""分析 reranker 分数分布：命中 chunk vs 非命中 chunk 各自的得分，用于选阈值。"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from framework.shared.env import load_root_env
load_root_env()

from infrastructure.storage.vector.qdrant_store import qdrant_store_from_env
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore
from infrastructure.external.reranker import CrossEncoderReranker
from backend.research.document.chunk_storage import PaperChunkStoreAdapter
from backend.research.rag.routing import build_retrieval_route
from backend.research.rag.eval import load_golden_set

store = PaperChunkStoreAdapter(PaperChunkStore(qdrant_store_from_env()))
reranker = CrossEncoderReranker()
pairs = load_golden_set(Path("data/eval/golden_set.json"))

hit_scores, miss_scores = [], []
for qa in pairs:
    route = build_retrieval_route(qa.question)
    cands = store.search_with_scores(qa.paper_id, qa.question, filters={}, limit=18)
    if not cands:
        continue
    passages = [c.content for c, _ in cands]
    scores = reranker.score(qa.question, passages)
    for (chunk, _), s in zip(cands, scores):
        (hit_scores if chunk.chunk_id == qa.source_chunk_id else miss_scores).append(s)

def stats(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n: return "empty"
    p = lambda q: xs[min(n-1, int(q*n))]
    return f"n={n} min={xs[0]:.3f} p10={p(0.1):.3f} p25={p(0.25):.3f} median={p(0.5):.3f} p75={p(0.75):.3f} max={xs[-1]:.3f}"

print("命中 chunk 分数:", stats(hit_scores))
print("非命中 chunk 分数:", stats(miss_scores))
# 不同阈值下：保留多少命中、丢掉多少噪声
print("\n阈值\t保留命中%\t丢弃噪声%")
for th in (0.0, 0.01, 0.05, 0.1, 0.2, 0.3, 0.5):
    keep_hit = sum(1 for s in hit_scores if s >= th) / len(hit_scores) if hit_scores else 0
    drop_miss = sum(1 for s in miss_scores if s < th) / len(miss_scores) if miss_scores else 0
    print(f"{th}\t{keep_hit:.1%}\t\t{drop_miss:.1%}")
