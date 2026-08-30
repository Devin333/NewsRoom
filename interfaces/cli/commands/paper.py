from __future__ import annotations

import argparse
import json

from framework.shared.env import load_root_env


def register(subparsers: argparse._SubParsersAction) -> None:
    paper_parser = subparsers.add_parser("paper", help="Paper RAG: ingest papers and ask questions")
    paper_subparsers = paper_parser.add_subparsers(dest="paper_command", required=True)

    ingest_parser = paper_subparsers.add_parser("ingest", help="Chunk + index arXiv papers")
    ingest_parser.add_argument("arxiv_ids", nargs="+", help="One or more arXiv ids")
    ingest_parser.add_argument(
        "--with-propositions",
        action="store_true",
        help="Run LLM proposition decomposition (slower, needs LLM)",
    )
    ingest_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    ingest_parser.set_defaults(handler=ingest_papers)

    ask_parser = paper_subparsers.add_parser("ask", help="Retrieve and optionally answer a question about a paper")
    ask_parser.add_argument("paper_id", help="Paper id (arXiv id)")
    ask_parser.add_argument("question", help="The question to ask")
    ask_parser.add_argument("--section", type=int, default=0, help="Current reading section index")
    ask_parser.add_argument("--limit", type=int, default=5, help="Number of passages to retrieve")
    ask_parser.add_argument("--no-rerank", action="store_true", help="Disable cross-encoder reranking")
    ask_parser.add_argument("--answer", action="store_true", help="Generate an answer from retrieved context")
    ask_parser.add_argument("--tenant-id", default=None, help="Tenant id for scoped gated RAG memory and evidence checks")
    ask_parser.add_argument("--user-id", default=None, help="User id for scoped gated RAG memory")
    ask_parser.add_argument("--memory-namespace", default=None, help="Explicit scoped memory namespace")
    ask_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    ask_parser.set_defaults(handler=ask_paper)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def ingest_papers(args: argparse.Namespace) -> int:
    load_root_env()
    from backend.research.application.batch_ingest import BatchIngestService
    from interfaces.services.paper_rag_factory import (
        build_chunk_pipeline,
        build_chunk_repository,
        build_chunk_store,
    )

    source_runtime_provider = getattr(args, "source_runtime_provider", None)
    pipeline = build_chunk_pipeline(
        with_propositions=args.with_propositions,
        source_runtime=(
            source_runtime_provider.get() if source_runtime_provider is not None else None
        ),
    )
    service = BatchIngestService(pipeline, build_chunk_store(), build_chunk_repository())

    def _progress(index: int, total: int, outcome) -> None:
        if args.json:
            return
        mark = "OK " if outcome.status == "ok" else "FAIL"
        detail = f"{outcome.total_chunks} chunks" if outcome.status == "ok" else outcome.error[:60]
        print(f"[{index}/{total}] {mark} {outcome.arxiv_id}: {detail}")

    result = service.run(list(args.arxiv_ids), on_progress=_progress)
    payload = result.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"\nIngest complete: {result.succeeded} succeeded / {result.failed} failed, {result.total_chunks} chunks")
    return 0 if result.failed == 0 else 1


def ask_paper(args: argparse.Namespace) -> int:
    load_root_env()
    from interfaces.services.paper_rag_service import PaperRagApplicationService

    service = PaperRagApplicationService(with_reranker=not args.no_rerank)
    payload = service.rag_ask(
        args.paper_id,
        args.question,
        section_index=args.section,
        limit=args.limit,
        generate=args.answer,
        tenant_id=args.tenant_id,
        user_id=args.user_id,
        memory_namespace=args.memory_namespace,
    )

    if args.json:
        _print_json(payload)
        return 0

    status = payload.get("status")
    status_text = f"   status: {status}" if status else ""
    passages = list(payload.get("passages", []))
    print(f"intent: {payload.get('intent', '')}{status_text}   passages: {len(passages)}\n")
    for index, passage in enumerate(passages, 1):
        snippet = str(passage.get("content", ""))[:200].replace("\n", " ")
        print(f"[{index}] ({passage.get('chunk_type', '')}) {passage.get('section_title', '')}\n    {snippet}\n")
    if args.answer:
        answer = payload.get("answer")
        print(f"\nanswer:\n{answer}" if answer else f"\nanswer: {payload.get('status', 'abstained')}")
    return 0
