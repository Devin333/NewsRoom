from __future__ import annotations

import argparse
import json

from framework.shared.env import load_root_env


def register(subparsers: argparse._SubParsersAction) -> None:
    paper_parser = subparsers.add_parser("paper", help="Paper RAG: ingest papers and ask questions")
    paper_subparsers = paper_parser.add_subparsers(dest="paper_command", required=True)

    ingest_parser = paper_subparsers.add_parser("ingest", help="Chunk + index arXiv papers")
    ingest_parser.add_argument("arxiv_ids", nargs="+", help="One or more arXiv ids")
    ingest_parser.add_argument("--with-propositions", action="store_true",
                               help="Run LLM proposition decomposition (slower, needs LLM)")
    ingest_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    ingest_parser.set_defaults(handler=ingest_papers)

    ask_parser = paper_subparsers.add_parser("ask", help="Retrieve (and optionally answer) a question about a paper")
    ask_parser.add_argument("paper_id", help="Paper id (arXiv id)")
    ask_parser.add_argument("question", help="The question to ask")
    ask_parser.add_argument("--section", type=int, default=0, help="Current reading section index")
    ask_parser.add_argument("--limit", type=int, default=5, help="Number of passages to retrieve")
    ask_parser.add_argument("--no-rerank", action="store_true", help="Disable cross-encoder reranking")
    ask_parser.add_argument("--answer", action="store_true", help="Generate an LLM answer from retrieved context")
    ask_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    ask_parser.set_defaults(handler=ask_paper)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def ingest_papers(args: argparse.Namespace) -> int:
    load_root_env()
    from interfaces.services.paper_rag_factory import (
        build_chunk_pipeline, build_chunk_store, build_chunk_repository,
    )
    from business.research.application.batch_ingest import BatchIngestService

    pipeline = build_chunk_pipeline(with_propositions=args.with_propositions)
    service = BatchIngestService(pipeline, build_chunk_store(), build_chunk_repository())

    def _progress(i: int, total: int, outcome) -> None:
        if not args.json:
            mark = "OK " if outcome.status == "ok" else "FAIL"
            detail = f"{outcome.total_chunks} chunks" if outcome.status == "ok" else outcome.error[:60]
            print(f"[{i}/{total}] {mark} {outcome.arxiv_id}: {detail}")

    result = service.run(list(args.arxiv_ids), on_progress=_progress)
    payload = result.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"\n入库完成: {result.succeeded} 成功 / {result.failed} 失败, 共 {result.total_chunks} chunks")
    return 0 if result.failed == 0 else 1


def ask_paper(args: argparse.Namespace) -> int:
    load_root_env()
    from interfaces.services.paper_rag_factory import build_research_retriever
    from business.research.rag.retriever import RetrievalRequest

    retriever = build_research_retriever(with_reranker=not args.no_rerank)
    result = retriever.retrieve(RetrievalRequest(
        paper_id=args.paper_id,
        question=args.question,
        current_section_index=args.section,
        limit=args.limit,
    ))

    passages = [
        {"chunk_id": c.chunk_id, "section_title": c.section_title,
         "chunk_type": c.chunk_type, "content": c.content}
        for c in result.child_chunks
    ]
    answer = None
    if args.answer:
        answer = _generate_answer(args.question, result)

    if args.json:
        _print_json({"intent": result.intent, "passages": passages, "answer": answer})
        return 0

    print(f"意图: {result.intent}   命中 {len(passages)} 段\n")
    for i, p in enumerate(passages, 1):
        snippet = p["content"][:200].replace("\n", " ")
        print(f"[{i}] ({p['chunk_type']}) {p['section_title']}\n    {snippet}\n")
    if answer is not None:
        print(f"\n答案:\n{answer}")
    return 0


def _generate_answer(question, retrieval) -> str:
    import asyncio
    from business.research.rag.generator import AnswerGenerator
    from business.research.application.llm_client import build_unity_llm_call

    generator = AnswerGenerator(build_unity_llm_call(max_tokens=600))
    ans = asyncio.run(generator.generate(question, retrieval))
    return ans.answer
