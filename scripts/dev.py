from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from framework.workflow.operations import (
    LocalWorkflowRunOperationService,
    OperationActor,
)
from framework.shared.env import env_values_from_root


COMPILE_PATHS = [
    "business",
    "framework",
    "infrastructure",
    "interfaces",
    "scripts",
]

SMOKE_TOPIC = "AI agents"
AGENT_LOOP_SMOKE_ARTIFACT_ROOT = ".newsroom/smoke"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = _command_env()

    if args.command == "compile":
        return _run(_compile_command(), env=env)
    if args.command == "test":
        return _run(_pytest_command("-q"), env=env)
    if args.command == "test-workflows":
        return _run(
            _pytest_command(
                "tests/framework/harness",
                "tests/framework/workflow",
                "-q",
            ),
            env=env,
        )
    if args.command == "test-workflow-runtime-contracts":
        return _run(
            _pytest_command(
                "tests/framework/workflow",
                "-q",
            ),
            env=env,
        )
    if args.command == "test-workflow-domain":
        return _run(
            _pytest_command(
                "tests/framework/harness",
                "tests/business/research",
                "-q",
            ),
            env=env,
        )
    if args.command == "test-services":
        return _run(_pytest_command("tests/interfaces/services", "-q"), env=env)
    if args.command == "test-rag-eval-gate":
        return _run(_rag_eval_gate_command(), env=env)
    if args.command == "check-live-answer-readiness":
        return _run(_rag_live_answer_readiness_command(args), env=env)
    if args.command == "ingest-golden-set-papers":
        return _run(_rag_ingest_golden_set_papers_command(args), env=env)
    if args.command == "run-live-answer-eval":
        return _run(_rag_live_answer_eval_command(args), env=env)
    if args.command == "replay-rag":
        return _replay_rag(args)
    if args.command == "test-rag-live-e2e":
        return _run(_rag_live_e2e_command(), env=env)
    if args.command == "test-interfaces":
        return _run(
            _pytest_command(
                "tests/interfaces",
                "-q",
            ),
            env=env,
        )
    if args.command == "test-api":
        return _run(_pytest_command("tests/interfaces/api", "-q"), env=env)
    if args.command == "test-cli":
        return _run(_pytest_command("tests/interfaces/cli", "-q"), env=env)
    if args.command == "test-mcp":
        return _run(_pytest_command("tests/interfaces/mcp", "-q"), env=env)
    if args.command == "test-sdk":
        return _run(_pytest_command("tests/sdk", "-q"), env=env)
    if args.command == "test-prd-research":
        return _run(_prd_research_regression_command(), env=env)
    if args.command == "test-prd-daily":
        return _run(_prd_research_regression_command(), env=env)
    if args.command == "test-api-contracts":
        return _run(
            _pytest_command(
                "tests/interfaces/api/test_api_contracts.py",
                "tests/interfaces/api/test_openapi_contract.py",
                "-q",
            ),
            env=env,
        )
    if args.command == "export-openapi":
        return _run(_export_openapi_command(), env=env)
    if args.command == "web-check":
        return _run(_web_check_command(), env=env)
    if args.command == "interface-smoke":
        commands = [
            _compile_command(),
            _pytest_command(
                "tests/interfaces/api/test_api_current_baseline.py",
                "tests/interfaces/mcp/test_mcp_current_baseline.py",
                "-q",
            ),
            _pytest_command(
                "tests/interfaces/api/test_api_contracts.py",
                "tests/interfaces/api/test_openapi_contract.py",
                "-q",
            ),
            _export_openapi_command(),
            _pytest_command(
                "tests/interfaces/cli/test_cli_current_baseline.py",
                "-q",
            ),
            _mcp_smoke_command(),
            _api_smoke_command(),
            _web_check_command(),
        ]
        return _run_many(commands, env=env, keep_going=args.keep_going)
    if args.command == "sources-validate":
        return _run(_news_command("sources", "validate"), env=env)
    if args.command == "diagnose":
        return _run(_news_command("diagnose"), env=env)
    if args.command == "smoke-test-agent-loop":
        return _run(_agent_loop_smoke_command(args), env=env)
    if args.command == "run-cancel":
        return _run_operation(args, "cancel")
    if args.command == "run-rerun-from-step":
        return _run_operation(args, "rerun_from_step")
    if args.command == "run-resume-with-patch":
        return _run_operation(args, "resume_with_patch")
    if args.command == "run-skip-step":
        return _run_operation(args, "skip_step")
    if args.command == "run-mark-blocked-resolved":
        return _run_operation(args, "mark_blocked_resolved")
    if args.command == "smoke":
        commands = [
            _compile_command(),
            _pytest_command(
                "tests/framework/harness",
                "tests/business/research",
                "tests/interfaces/api/test_research_api.py",
                "tests/interfaces/services/test_research_service.py",
                "tests/interfaces/composition/test_research_recorded_transport.py",
                "tests/architecture",
                "-q",
            ),
            _agent_loop_smoke_command(),
            _news_command("sources", "validate"),
        ]
        return _run_many(commands, env=env, keep_going=args.keep_going)

    parser.error(f"unknown command: {args.command}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("compile", help="Compile project Python modules")
    subparsers.add_parser("test", help="Run the full pytest suite")
    subparsers.add_parser("test-workflows", help="Run workflow tests")
    subparsers.add_parser(
        "test-workflow-runtime-contracts",
        help="Run workflow runtime contract tests",
    )
    subparsers.add_parser("test-workflow-domain", help="Run workflow domain tests")
    subparsers.add_parser("test-services", help="Run interface service tests")
    subparsers.add_parser("test-rag-eval-gate", help="Run the deterministic Paper RAG eval CI gate")
    live_answer_eval_parser = subparsers.add_parser(
        "run-live-answer-eval",
        help="Run the live Paper RAG answer eval",
    )
    live_answer_eval_parser.add_argument("--output-dir", default=None)
    live_answer_eval_parser.add_argument("--golden-set", default=None)
    live_answer_eval_parser.add_argument("--papers-dir", default=None)
    live_answer_eval_parser.add_argument("--retrieval-policy", default=None)
    live_answer_eval_parser.add_argument("--max-pairs-per-type", type=int, default=None)
    live_answer_eval_parser.add_argument("--answer-eval-limit", type=int, default=None)
    live_answer_eval_parser.add_argument("--threshold", action="append", default=[])
    readiness_parser = subparsers.add_parser(
        "check-live-answer-readiness",
        help="Write Paper RAG live answer eval readiness artifacts",
    )
    readiness_parser.add_argument("--output-dir", default=None)
    readiness_parser.add_argument("--golden-set", default=None)
    readiness_parser.add_argument("--papers-dir", default=None)
    readiness_parser.add_argument("--require-fixture", action="store_true")
    readiness_parser.add_argument("--require-real-corpus", action="store_true")
    golden_ingest_parser = subparsers.add_parser(
        "ingest-golden-set-papers",
        help="Fetch and parse missing Paper RAG golden-set corpus artifacts",
    )
    golden_ingest_parser.add_argument("--golden-set", default=None)
    golden_ingest_parser.add_argument("--papers-dir", default=None)
    golden_ingest_parser.add_argument("--manifest", default=None)
    golden_ingest_parser.add_argument("--max-papers", type=int, default=None)
    golden_ingest_parser.add_argument("--force", action="store_true")
    golden_ingest_parser.add_argument("--pdf-parser-backend", default=None)
    golden_ingest_parser.add_argument("--with-pdf-sidecar", action="store_true")
    golden_ingest_parser.add_argument("--pdf-sidecar-mode", default=None)
    golden_ingest_parser.add_argument("--no-merge-pdf-visuals", action="store_true")
    replay_rag_parser = subparsers.add_parser("replay-rag", help="Replay a persisted Paper RAG transcript")
    replay_rag_parser.add_argument("transcript", help="Transcript id or transcript artifact path")
    replay_rag_parser.add_argument("--transcript-root", default=".newsroom/rag/transcripts")
    subparsers.add_parser("test-rag-live-e2e", help="Run the opt-in live Paper RAG Qdrant/Postgres e2e")
    subparsers.add_parser("test-interfaces", help="Run interface acceptance tests")
    subparsers.add_parser("test-api", help="Run HTTP API interface tests")
    subparsers.add_parser("test-cli", help="Run CLI interface tests")
    subparsers.add_parser("test-mcp", help="Run MCP interface tests")
    subparsers.add_parser("test-sdk", help="Run SDK tests")
    subparsers.add_parser("test-prd-research", help="Run the PRD-aligned Harness and Research regression sweep")
    subparsers.add_parser("test-prd-daily", help="Run the PRD-aligned daily regression sweep used by CI")
    subparsers.add_parser("export-openapi", help="Export docs/api/openapi.json")
    subparsers.add_parser("test-api-contracts", help="Run API contract tests")
    subparsers.add_parser("web-check", help="Check Web Console skeleton files")
    subparsers.add_parser("sources-validate", help="Validate configured source registry")
    subparsers.add_parser("diagnose", help="Run local diagnostics")
    agent_loop_smoke_parser = subparsers.add_parser(
        "smoke-test-agent-loop",
        help="Run the offline AgentLoop Graph smoke fixture",
    )
    agent_loop_smoke_parser.add_argument("--topic", default=SMOKE_TOPIC)
    agent_loop_smoke_parser.add_argument(
        "--artifact-root",
        default=AGENT_LOOP_SMOKE_ARTIFACT_ROOT,
    )
    agent_loop_smoke_parser.add_argument("--run-id", default=None)

    interface_smoke_parser = subparsers.add_parser(
        "interface-smoke",
        help="Run interface-layer acceptance smoke commands",
    )
    interface_smoke_parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Run all smoke commands even after a failure",
    )

    smoke_parser = subparsers.add_parser("smoke", help="Run fixed offline smoke commands")
    smoke_parser.add_argument("--keep-going", action="store_true", help="Run all commands even after a failure")

    _add_run_operation_parsers(subparsers)

    return parser


def _add_run_operation_parsers(subparsers: argparse._SubParsersAction) -> None:
    cancel_parser = subparsers.add_parser("run-cancel", help="Cancel a workflow run")
    _add_operation_base_args(cancel_parser)
    cancel_parser.add_argument("--reason", required=True)

    rerun_parser = subparsers.add_parser(
        "run-rerun-from-step",
        help="Rerun a workflow run from a step",
    )
    _add_operation_base_args(rerun_parser)
    rerun_parser.add_argument("--step-id", required=True)

    resume_parser = subparsers.add_parser(
        "run-resume-with-patch",
        help="Resume a workflow run with a JSON patch",
    )
    _add_operation_base_args(resume_parser)
    resume_parser.add_argument("--patch-json", required=True)

    skip_parser = subparsers.add_parser("run-skip-step", help="Skip a workflow step")
    _add_operation_base_args(skip_parser)
    skip_parser.add_argument("--step-id", required=True)
    skip_parser.add_argument("--reason", required=True)

    blocked_parser = subparsers.add_parser(
        "run-mark-blocked-resolved",
        help="Record that a blocked run has been externally resolved",
    )
    _add_operation_base_args(blocked_parser)
    blocked_parser.add_argument("--resolution-json", required=True)


def _add_operation_base_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-root", default="outputs/runs")
    parser.add_argument("--actor-id", default=None)


def _compile_command() -> list[str]:
    return [sys.executable, "-m", "compileall", "-q", *COMPILE_PATHS]


def _pytest_command(*args: str) -> list[str]:
    if importlib.util.find_spec("pytest") is not None:
        return [sys.executable, "-m", "pytest", *args]
    return ["pytest", *args]


def _export_openapi_command() -> list[str]:
    return [sys.executable, "-m", "scripts.export_openapi"]


def _web_check_command() -> list[str]:
    return [sys.executable, "-m", "scripts.check_web_console"]


def _api_smoke_command() -> list[str]:
    return [sys.executable, "-m", "scripts.smoke.api_smoke"]


def _mcp_smoke_command() -> list[str]:
    return [sys.executable, "-m", "scripts.smoke.mcp_smoke"]


def _agent_loop_smoke_command(
    args: argparse.Namespace | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "interfaces.cli.news",
        "dev",
        "run-test-agent-loop",
        "--topic",
        SMOKE_TOPIC if args is None else str(args.topic),
        "--artifact-root",
        (
            AGENT_LOOP_SMOKE_ARTIFACT_ROOT
            if args is None
            else str(args.artifact_root)
        ),
        "--json",
    ]
    if args is not None and args.run_id:
        command.extend(["--run-id", str(args.run_id)])
    return command


def _rag_eval_gate_command() -> list[str]:
    return [sys.executable, "-m", "business.research.rag.cli.run_ci_eval_gate"]


def _rag_live_answer_eval_command(args: argparse.Namespace | None = None) -> list[str]:
    command = [sys.executable, "-m", "business.research.rag.cli.run_live_answer_eval"]
    if args is None:
        return command
    if args.output_dir:
        command.extend(["--output-dir", str(args.output_dir)])
    if args.golden_set:
        command.extend(["--golden-set", str(args.golden_set)])
    if args.papers_dir:
        command.extend(["--papers-dir", str(args.papers_dir)])
    if args.retrieval_policy:
        command.extend(["--retrieval-policy", str(args.retrieval_policy)])
    if args.max_pairs_per_type is not None:
        command.extend(["--max-pairs-per-type", str(args.max_pairs_per_type)])
    if getattr(args, "answer_eval_limit", None) is not None:
        command.extend(["--answer-eval-limit", str(args.answer_eval_limit)])
    for threshold in args.threshold or []:
        command.extend(["--threshold", str(threshold)])
    return command


def _rag_live_answer_readiness_command(args: argparse.Namespace | None = None) -> list[str]:
    command = [sys.executable, "-m", "business.research.rag.cli.check_live_answer_readiness"]
    if args is None:
        return command
    if args.output_dir:
        command.extend(["--output-dir", str(args.output_dir)])
    if args.golden_set:
        command.extend(["--golden-set", str(args.golden_set)])
    if args.papers_dir:
        command.extend(["--papers-dir", str(args.papers_dir)])
    if getattr(args, "require_fixture", False):
        command.append("--require-fixture")
    if getattr(args, "require_real_corpus", False):
        command.append("--require-real-corpus")
    return command


def _rag_ingest_golden_set_papers_command(args: argparse.Namespace | None = None) -> list[str]:
    command = [sys.executable, "-m", "business.research.rag.cli.ingest_golden_set_papers"]
    if args is None:
        return command
    if args.golden_set:
        command.extend(["--golden-set", str(args.golden_set)])
    if args.papers_dir:
        command.extend(["--papers-dir", str(args.papers_dir)])
    if args.manifest:
        command.extend(["--manifest", str(args.manifest)])
    if args.max_papers is not None:
        command.extend(["--max-papers", str(args.max_papers)])
    if args.force:
        command.append("--force")
    if args.pdf_parser_backend:
        command.extend(["--pdf-parser-backend", str(args.pdf_parser_backend)])
    if args.with_pdf_sidecar:
        command.append("--with-pdf-sidecar")
    if args.pdf_sidecar_mode:
        command.extend(["--pdf-sidecar-mode", str(args.pdf_sidecar_mode)])
    if args.no_merge_pdf_visuals:
        command.append("--no-merge-pdf-visuals")
    return command


def _rag_live_e2e_command() -> list[str]:
    return _pytest_command(
        "tests/business/research/document/test_arxiv_latex_integration.py",
        "tests/business/research/integration/test_chunk_paper_e2e.py",
        "tests/interfaces/composition/test_research_live_e2e.py",
        "-m",
        "live_research_e2e",
        "-q",
    )


def _prd_research_regression_command() -> list[str]:
    return _pytest_command(
        "tests/framework/harness",
        "tests/business/research",
        "tests/interfaces/api/test_research_api.py",
        "tests/interfaces/services/test_research_service.py",
        "tests/interfaces/services/test_report_service.py",
        "tests/interfaces/services/test_mcp_application_service.py",
        "tests/business/layers/relation/evidence/test_claim_verifier.py",
        "tests/business/layers/analysis/quality/test_citation_editor.py",
        "tests/business/layers/analysis/quality/test_support_scoring.py",
        "tests/infrastructure/storage/test_artifact_store.py",
        "tests/infrastructure/storage/test_backup_restore.py",
        "-q",
    )


def _news_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "interfaces.cli.news", *args]


def _run_operation(args: argparse.Namespace, operation: str) -> int:
    service = LocalWorkflowRunOperationService(artifact_root=args.artifact_root)
    actor = OperationActor(actor_id=args.actor_id) if args.actor_id else None
    if operation == "cancel":
        result = service.cancel_run(args.run_id, args.reason, actor=actor)
    elif operation == "rerun_from_step":
        result = service.rerun_from_step(args.run_id, args.step_id, actor=actor)
    elif operation == "resume_with_patch":
        result = service.resume_with_patch(
            args.run_id,
            _read_json_argument(args.patch_json),
            actor=actor,
        )
    elif operation == "skip_step":
        result = service.skip_step(
            args.run_id,
            args.step_id,
            args.reason,
            actor=actor,
        )
    elif operation == "mark_blocked_resolved":
        result = service.mark_blocked_resolved(
            args.run_id,
            _read_json_argument(args.resolution_json),
            actor=actor,
        )
    else:  # pragma: no cover - parser dispatch prevents this
        raise ValueError(f"unknown run operation: {operation}")
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.status.value in {"accepted", "applied"} else 1


def _replay_rag(args: argparse.Namespace) -> int:
    from framework.harness.rag.replay import replay_rag_session
    from interfaces.services.paper_rag_transcript_store import PaperRagTranscriptFileStore

    store = PaperRagTranscriptFileStore(args.transcript_root)
    transcript = store.transcript_payload(args.transcript)
    replay = replay_rag_session(transcript)
    print(json.dumps(replay.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if replay.replayable else 1


def _read_json_argument(value: str) -> dict:
    path = Path(value)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("JSON argument must be an object")
    return payload


def _run_many(commands: Sequence[Sequence[str]], *, env: dict[str, str], keep_going: bool) -> int:
    exit_code = 0
    for command in commands:
        result = _run(command, env=env)
        if result != 0:
            exit_code = result
            if not keep_going:
                return result
    return exit_code


def _run(command: Sequence[str], *, env: dict[str, str]) -> int:
    print(f"+ {_format_command(command)}", flush=True)
    completed = subprocess.run(list(command), env=env, check=False)
    return int(completed.returncode)


def _format_command(command: Sequence[str]) -> str:
    return " ".join(_quote(part) for part in command)


def _quote(part: str) -> str:
    if not part:
        return '""'
    if any(char.isspace() for char in part):
        return '"' + part.replace('"', '\\"') + '"'
    return part


def _command_env() -> dict[str, str]:
    env = env_values_from_root()
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


if __name__ == "__main__":
    raise SystemExit(main())
