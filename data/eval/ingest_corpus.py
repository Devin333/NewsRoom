"""一次性批量入库脚本：检索测评的 30 篇语料。with_propositions=False 加速。

用法: E:/Anaconda3/python.exe data/eval/ingest_corpus.py
失败的论文记录到 ingest_report.json，可单独重跑。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ensure project root on sys.path (script lives under data/eval/)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from framework.shared.env import load_root_env

load_root_env()
# .env ships a jdbc:-prefixed, password-less DSN; force the psycopg form for this script.
os.environ["NEWS_DATABASE_DSN"] = "postgresql://root:root@localhost:5432/NewsRoom"

from infrastructure.external.sources.arxiv import ArxivSourceConnector
from infrastructure.storage.vector.qdrant_store import qdrant_store_from_env
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore
from infrastructure.storage.postgres.paper_chunk_repository import PaperChunkRepository
from business.research.document.chunk_storage import (
    PaperChunkRepositoryAdapter,
    PaperChunkStoreAdapter,
)
from business.research.document.latex_compiler import LatexSourceParser
from business.research.application.chunk_paper_pipeline import ChunkPaperPipeline

CORPUS: dict[str, list[str]] = {
    "nlp_transformer": ["1706.03762", "1810.04805", "1907.11692", "1910.10683", "2005.14165"],
    "cv":              ["2010.11929", "1512.03385", "2103.00020", "2111.06377", "1505.04597"],
    "generative":      ["2006.11239", "1406.2661", "1312.6114", "2112.10752", "2105.05233"],
    "retrieval":       ["2005.11401", "2004.04906", "2002.08909", "2208.03299", "2212.10496"],
    "llm_alignment":   ["2203.02155", "2302.13971", "2305.18290", "2201.11903", "2204.02311"],
    "agent":           ["2210.03629", "2302.04761", "2303.11366", "2304.03442", "2308.08155"],
}

OUT_DIR = Path("data/eval")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    store = PaperChunkStoreAdapter(PaperChunkStore(qdrant_store_from_env()))
    store.ensure_collection()
    repo = PaperChunkRepositoryAdapter(PaperChunkRepository(os.environ["NEWS_DATABASE_DSN"]))
    pipeline = ChunkPaperPipeline(
        store, repo, ArxivSourceConnector(), LatexSourceParser(),
        with_propositions=False,
    )

    report: list[dict] = []
    for domain, ids in CORPUS.items():
        for arxiv_id in ids:
            entry: dict = {"arxiv_id": arxiv_id, "domain": domain}
            try:
                paper_id = arxiv_id.replace("/", "_")
                store.delete_paper_chunks(paper_id)   # idempotent re-ingest: clear stale chunks first
                repo.delete_paper_chunks(paper_id)
                result = pipeline.run(arxiv_id)
                entry.update(status="ok", total_chunks=result.total_chunks, by_type=result.by_type)
                print(f"[OK] {domain}/{arxiv_id}: {result.total_chunks} chunks")
            except Exception as exc:
                entry.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                print(f"[FAIL] {domain}/{arxiv_id}: {exc}", file=sys.stderr)
            report.append(entry)
            time.sleep(1)  # be polite to arXiv

    (OUT_DIR / "ingest_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ok = sum(1 for e in report if e["status"] == "ok")
    print(f"\n入库完成: {ok}/{len(report)} 成功，报告写入 {OUT_DIR / 'ingest_report.json'}")


if __name__ == "__main__":
    main()
