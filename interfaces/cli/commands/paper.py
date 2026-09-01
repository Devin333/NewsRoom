from __future__ import annotations

import argparse
import json

from framework.shared.env import load_root_env


def register(subparsers: argparse._SubParsersAction) -> None:
    paper_parser = subparsers.add_parser("paper", help="Paper RAG: ingest papers and ask questions")
    paper_subparsers = paper_parser.add_subparsers(dest="paper_command", required=True)

    ingest_parser = paper_subparsers.add_parser("ingest", help="Parse and catalog one or more paper sources")
    ingest_parser.add_argument("sources", nargs="+", help="Paper URL, DOI, local path, or GitHub URL")
    ingest_parser.add_argument("--source-type", default=None, help="Explicit source type for all inputs")
    ingest_parser.add_argument(
        "--with-propositions",
        action="store_true",
        help="Run LLM proposition decomposition (slower, needs LLM)",
    )
    _add_parse_options(ingest_parser)
    _add_scope_flags(ingest_parser)
    ingest_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    ingest_parser.set_defaults(handler=ingest_papers_application)

    parse_parser = paper_subparsers.add_parser("parse", help="Parse one paper into the Research Catalog")
    parse_parser.add_argument("source", help="Paper URL, DOI, local path, or GitHub URL")
    parse_parser.add_argument("--source-type", default=None, help="Explicit source type")
    parse_parser.add_argument("--content-ref", default=None, help="Local content or artifact reference")
    parse_parser.add_argument("--run-id", default=None, help="Durable parse run id")
    _add_parse_options(parse_parser)
    _add_scope_flags(parse_parser)
    parse_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parse_parser.set_defaults(handler=parse_paper)

    refresh_parser = paper_subparsers.add_parser("refresh", help="Refresh one paper Catalog projection")
    refresh_parser.add_argument("paper_id")
    _add_scope_flags(refresh_parser)
    refresh_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    refresh_parser.set_defaults(handler=refresh_paper)

    catalog_parser = paper_subparsers.add_parser("catalog", help="Query the typed Paper Catalog")
    catalog_subparsers = catalog_parser.add_subparsers(dest="catalog_command", required=True)
    show_parser = catalog_subparsers.add_parser("show", help="Show one paper Catalog entry")
    show_parser.add_argument("paper_id")
    _add_scope_flags(show_parser)
    show_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    show_parser.set_defaults(handler=catalog_show)
    search_parser = catalog_subparsers.add_parser("search", help="Search Catalog papers")
    search_parser.add_argument("query", nargs="?", default="")
    search_parser.add_argument("--limit", type=int, default=50)
    search_parser.add_argument("--cursor", default=None)
    search_parser.add_argument("--sort", default="observed_at desc, stable_id asc")
    search_parser.add_argument("--include-diagnostics", action="store_true")
    _add_scope_flags(search_parser)
    search_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    search_parser.set_defaults(handler=catalog_search)

    benchmark_parser = paper_subparsers.add_parser("benchmark", help="Inspect verified benchmark leaderboards")
    benchmark_subparsers = benchmark_parser.add_subparsers(dest="benchmark_command", required=True)
    compare_parser = benchmark_subparsers.add_parser("compare", help="Compare verified scores")
    compare_parser.add_argument("--paper-id", default=None)
    compare_parser.add_argument("--benchmark-id", default=None)
    compare_parser.add_argument("--metric-id", default=None)
    compare_parser.add_argument("--dataset-id", default=None)
    compare_parser.add_argument("--dataset-version", default=None)
    compare_parser.add_argument("--split", default=None)
    compare_parser.add_argument("--evaluation-protocol", default=None)
    _add_scope_flags(compare_parser)
    compare_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    compare_parser.set_defaults(handler=benchmark_compare)

    code_parser = paper_subparsers.add_parser("code", help="Inspect paper code repository observations")
    code_subparsers = code_parser.add_subparsers(dest="code_command", required=True)
    inspect_parser = code_subparsers.add_parser("inspect", help="Inspect repositories linked to a paper")
    inspect_parser.add_argument("paper_id")
    _add_scope_flags(inspect_parser)
    inspect_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    inspect_parser.set_defaults(handler=code_inspect)

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
    """Backward-compatible alias; all CLI ingest calls the application facade."""

    return ingest_papers_application(args)


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


def parse_paper(args: argparse.Namespace) -> int:
    from interfaces.services.research_service import ResearchParseInput

    return _run_application_call(
        lambda: _research_service(args).parse_paper(
            ResearchParseInput(
                source=args.source,
                source_type=args.source_type,
                content_ref=args.content_ref,
                run_id=args.run_id,
                tenant_id=args.tenant_id,
                user_id=args.user_id,
                memory_namespace=args.memory_namespace,
                options=_parse_options_from_args(args),
            )
        ),
        args=args,
        label="Parse failed",
    )


def ingest_papers_application(args: argparse.Namespace) -> int:
    outcomes = []
    from interfaces.services.research_service import ResearchParseInput, ResearchServiceError

    service = _research_service(args)
    for source in args.sources:
        try:
            outcomes.append(service.parse_paper(ResearchParseInput(
                source=source,
                source_type=getattr(args, "source_type", None),
                tenant_id=args.tenant_id,
                user_id=args.user_id,
                memory_namespace=args.memory_namespace,
                options=_parse_options_from_args(args),
            )))
        except ResearchServiceError as exc:
            outcomes.append(_application_error_payload(source, exc, args=args))
        except Exception as exc:
            outcomes.append(_unexpected_error_payload(source, exc, args=args))
    statuses = [str(item.get("status") or "failed") for item in outcomes]
    failed = sum(status == "failed" for status in statuses)
    metadata_only = sum(status == "metadata_only" for status in statuses)
    degraded = sum(status in {"degraded", "catalog_partial", "metadata_only"} for status in statuses)
    succeeded = sum(status in {"parsed", "catalog_ready"} for status in statuses)
    payload = {
        "status": "failed" if failed else ("degraded" if degraded else "completed"),
        "summary": {
            "total": len(outcomes),
            "succeeded": succeeded,
            "metadataOnly": metadata_only,
            "degraded": degraded,
            "failed": failed,
        },
        "outcomes": outcomes,
        # Preserve the original flat counters for existing scripts.
        "succeeded": succeeded,
        "metadataOnly": metadata_only,
        "degraded": degraded,
        "failed": failed,
        "provenance": {"actorScope": _actor_scope_payload(args)},
    }
    return _emit_command_payload(payload, json_output=args.json, label="Ingest complete")


def refresh_paper(args: argparse.Namespace) -> int:
    return _run_application_call(
        lambda: _research_service(args).refresh_catalog(
            args.paper_id,
            actor=_actor_input(args),
        ),
        args=args,
        label="Refresh failed",
    )


def catalog_show(args: argparse.Namespace) -> int:
    return _run_application_call(
        lambda: _research_service(args).get_catalog(args.paper_id, actor=_actor_input(args)),
        args=args,
        label="Catalog failed",
    )


def catalog_search(args: argparse.Namespace) -> int:
    return _run_application_call(
        lambda: _research_service(args).list_catalog_papers(
            query=args.query,
            limit=args.limit,
            cursor=args.cursor,
            sort=args.sort,
            include_diagnostics=args.include_diagnostics,
            actor=_actor_input(args),
        ),
        args=args,
        label="Catalog search failed",
    )


def benchmark_compare(args: argparse.Namespace) -> int:
    def call():
        service = _research_service(args)
        if args.paper_id:
            return service.get_benchmarks(
                args.paper_id,
                actor=_actor_input(args),
                benchmark_id=args.benchmark_id,
                metric_id=args.metric_id,
                dataset_id=args.dataset_id,
                dataset_version=args.dataset_version,
                split=args.split,
                evaluation_protocol=args.evaluation_protocol,
            )
        return service.get_leaderboards(
            actor=_actor_input(args),
            benchmark_id=args.benchmark_id,
            metric_id=args.metric_id,
            dataset_id=args.dataset_id,
            dataset_version=args.dataset_version,
            split=args.split,
            evaluation_protocol=args.evaluation_protocol,
        )

    return _run_application_call(call, args=args, label="Benchmark comparison failed")


def code_inspect(args: argparse.Namespace) -> int:
    return _run_application_call(
        lambda: _research_service(args).get_code(args.paper_id, actor=_actor_input(args)),
        args=args,
        label="Code observations failed",
    )


def _add_scope_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--memory-namespace", default=None)


def _add_parse_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--parser-backend", default=None)
    parser.add_argument("--quality-profile", choices=("metadata", "reading", "catalog"), default=None)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--include-code", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--include-catalog", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--include-chunks", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--include-evidence", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--timeout-seconds", type=float, default=None)


def _parse_options_from_args(args: argparse.Namespace) -> dict[str, object]:
    mapping = {
        "parser_backend": getattr(args, "parser_backend", None),
        "quality_profile": getattr(args, "quality_profile", None),
        "refresh": True if getattr(args, "refresh", False) else None,
        "include_code": getattr(args, "include_code", None),
        "include_catalog": getattr(args, "include_catalog", None),
        "include_chunks": getattr(args, "include_chunks", None),
        "include_evidence": getattr(args, "include_evidence", None),
        "max_attempts": getattr(args, "max_attempts", None),
        "timeout_seconds": getattr(args, "timeout_seconds", None),
    }
    return {key: value for key, value in mapping.items() if value is not None}


def _actor_input(args: argparse.Namespace):
    from interfaces.services.research_service import ResearchActorInput

    return ResearchActorInput(
        tenant_id=getattr(args, "tenant_id", None),
        user_id=getattr(args, "user_id", None),
        memory_namespace=getattr(args, "memory_namespace", None),
    )


def _research_service(args: argparse.Namespace):
    load_root_env()
    from interfaces.composition.research import build_research_application_service

    provider = getattr(args, "source_runtime_provider", None)
    return build_research_application_service(
        source_runtime_provider=(provider.get() if provider is not None else None),
    )


def _emit_command_payload(payload: dict, *, json_output: bool, label: str) -> int:
    if json_output:
        _print_json(payload)
    else:
        print(f"{label}: {payload.get('status', 'ok')}")
        if payload.get("paperId"):
            print(f"paper: {payload['paperId']}")
    return _command_exit_code(payload)


def _command_exit_code(payload: dict) -> int:
    """Return the stable CLI exit code for one result or a batch envelope."""

    outcomes = payload.get("outcomes")
    if isinstance(outcomes, list):
        codes = [_command_exit_code(item) for item in outcomes if isinstance(item, dict)]
        if codes:
            return max(codes)

    status = str(payload.get("status") or "").casefold()
    error = payload.get("error")
    error_map = error if isinstance(error, dict) else {}
    code = str(error_map.get("code") or payload.get("errorCode") or "").casefold()
    status_code = error_map.get("statusCode", payload.get("statusCode"))
    try:
        status_code = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        status_code = None
    retryable = bool(error_map.get("retryable", payload.get("retryable", False)))

    if status in {"invalid_request", "validation_error"} or code in {
        "invalid_request",
        "validation_error",
        "parse_options_invalid",
    }:
        return 2
    if status_code in {401, 403} or any(
        marker in code
        for marker in ("forbidden", "permission", "scope", "actor_unauthorized", "tenant_unauthorized")
    ):
        return 3
    if code.startswith(("source_", "remote_source", "github_source")) or code in {
        "source_denied",
        "source_fetch_failed",
        "source_rate_limited",
        "source_timeout",
    }:
        return 4
    if status == "catalog_partial" or code.startswith(("catalog_", "benchmark_", "leaderboard_", "relation_")):
        return 6
    if any(
        marker in code
        for marker in ("persist", "recovery", "artifact", "event_", "run_intent", "run_final")
    ):
        return 7
    if status == "degraded" and not error:
        return 0
    if status == "failed" or code.startswith(("parse_", "quality_", "parser_")):
        return 5
    if payload.get("error") or payload.get("failed", 0):
        return 5 if not retryable else 4
    return 0


def _run_application_call(call, *, args: argparse.Namespace, label: str) -> int:
    """Project application failures into the same safe JSON shape as HTTP."""

    try:
        payload = call()
    except Exception as exc:
        from interfaces.services.research_service import ResearchServiceError

        if isinstance(exc, ResearchServiceError):
            payload = _application_error_payload(None, exc, args=args)
        else:
            payload = _unexpected_error_payload(None, exc, args=args)
    return _emit_command_payload(payload, json_output=args.json, label=label)


def _application_error_payload(source: str | None, exc: Exception, *, args: argparse.Namespace) -> dict:
    from interfaces.services.research_service import ResearchServiceError

    if isinstance(exc, ResearchServiceError):
        payload = {
            "status": "failed",
            "error": {
                "code": exc.code,
                "message": exc.public_message,
                "details": dict(exc.details),
                "retryable": bool(exc.retryable),
                "userActionRequired": bool(exc.user_action_required),
            },
        }
    else:
        payload = _unexpected_error_payload(source, exc, args=args)
    if source is not None:
        payload["source"] = source
    payload["provenance"] = {"actorScope": _actor_scope_payload(args)}
    return payload


def _unexpected_error_payload(source: str | None, exc: Exception, *, args: argparse.Namespace) -> dict:
    payload = {
        "status": "failed",
        "error": {
            "code": "research_command_failed",
            "message": "Research paper command failed",
            "details": {"error_type": type(exc).__name__},
            "retryable": True,
            "userActionRequired": False,
        },
        "provenance": {"actorScope": _actor_scope_payload(args)},
    }
    if source is not None:
        payload["source"] = source
    return payload


def _actor_scope_payload(args: argparse.Namespace) -> dict[str, str]:
    return {
        key: str(value).strip()
        for key, value in {
            "tenant_id": getattr(args, "tenant_id", None),
            "user_id": getattr(args, "user_id", None),
            "memory_namespace": getattr(args, "memory_namespace", None),
        }.items()
        if value is not None and str(value).strip()
    }
