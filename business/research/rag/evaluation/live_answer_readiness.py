from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from business.research.rag.evaluation.paper_evidence_eval import load_evidence_golden_set


DEFAULT_OUTPUT_DIR = Path(".newsroom/eval/live-answer-readiness")
DEFAULT_GOLDEN_SET_PATH = Path("data/eval/golden_set.json")
DEFAULT_PAPERS_DIR = Path(".newsroom/papers")

_REQUIRED_LLM_ENV = ("OPENAI_BASE_URL", "OPENAI_API_KEY")
_OPTIONAL_LLM_ENV = ("OPENAI_MODEL",)


@dataclass(frozen=True)
class LiveAnswerReadinessResult:
    output_dir: Path
    json_path: Path
    markdown_path: Path
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "payload": self.payload,
        }


def build_live_answer_readiness(
    *,
    golden_set_path: str | Path = DEFAULT_GOLDEN_SET_PATH,
    papers_dir: str | Path = DEFAULT_PAPERS_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env_values = env if env is not None else os.environ
    golden = _golden_set_summary(Path(golden_set_path))
    papers = _papers_summary(Path(papers_dir))
    llm = _llm_summary(env_values)
    eligibility = _eligibility_summary(llm=llm, golden_set=golden, papers=papers)
    payload = {
        "schema_version": 1,
        "baseline_status": _baseline_status(eligibility),
        "output_dir": str(Path(output_dir)),
        "llm": llm,
        "golden_set": golden,
        "papers": papers,
        "eligibility": eligibility,
        "commands": {
            "fixture_live_answer_eval": "python -m scripts.dev run-live-answer-eval",
            "real_corpus_live_answer_eval": (
                "python -m scripts.dev run-live-answer-eval "
                f"--golden-set {Path(golden_set_path)} "
                f"--papers-dir {Path(papers_dir)} "
                "--output-dir .newsroom/eval/live-answer-real"
            ),
        },
        "notes": [
            "Readiness artifacts describe whether live answer evaluation can run.",
            "They are not live answer baseline metrics and do not prove production quality.",
            "Secret values are intentionally omitted.",
        ],
    }
    return payload


def write_live_answer_readiness(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    golden_set_path: str | Path = DEFAULT_GOLDEN_SET_PATH,
    papers_dir: str | Path = DEFAULT_PAPERS_DIR,
    env: Mapping[str, str] | None = None,
) -> LiveAnswerReadinessResult:
    output = Path(output_dir)
    payload = build_live_answer_readiness(
        golden_set_path=golden_set_path,
        papers_dir=papers_dir,
        output_dir=output,
        env=env,
    )
    json_path = output / "readiness.json"
    markdown_path = output / "readiness.md"
    output.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_readiness_markdown(payload), encoding="utf-8")
    return LiveAnswerReadinessResult(
        output_dir=output,
        json_path=json_path,
        markdown_path=markdown_path,
        payload=payload,
    )


def readiness_gate_exit_code(
    payload: Mapping[str, Any],
    *,
    require_fixture: bool = False,
    require_real_corpus: bool = False,
) -> int:
    eligibility = dict(payload.get("eligibility") or {})
    if require_fixture and not _is_eligible(eligibility, "fixture_live_answer_eval"):
        return 1
    if require_real_corpus and not _is_eligible(eligibility, "real_corpus_live_answer_eval"):
        return 1
    return 0


def _is_eligible(eligibility: Mapping[str, Any], key: str) -> bool:
    return bool(dict(eligibility.get(key) or {}).get("eligible"))


def _llm_summary(env: Mapping[str, str]) -> dict[str, Any]:
    required = {name: _env_presence(env, name) for name in _REQUIRED_LLM_ENV}
    optional = {name: _env_presence(env, name, include_value=name == "OPENAI_MODEL") for name in _OPTIONAL_LLM_ENV}
    missing_required = [name for name, item in required.items() if not item["present"]]
    return {
        "required": required,
        "optional": optional,
        "required_present": not missing_required,
        "missing_required": missing_required,
    }


def _env_presence(env: Mapping[str, str], name: str, *, include_value: bool = False) -> dict[str, Any]:
    value = str(env.get(name) or "")
    item: dict[str, Any] = {
        "present": bool(value.strip()),
        "length": len(value),
    }
    if include_value:
        item["value"] = value if value.strip() else ""
    return item


def _golden_set_summary(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "pair_count": 0,
        "expected_behavior_counts": {},
        "qa_type_counts": {},
        "distinct_paper_ids": 0,
        "paper_ids": [],
        "load_error": "",
    }
    if not path.exists():
        return summary
    try:
        pairs = load_evidence_golden_set(path)
    except Exception as exc:  # pragma: no cover - exact parser exceptions are not the contract
        summary["load_error"] = f"{type(exc).__name__}: {exc}"
        return summary
    paper_ids = sorted({pair.paper_id for pair in pairs})
    summary.update({
        "pair_count": len(pairs),
        "expected_behavior_counts": dict(sorted(Counter(pair.expected_behavior for pair in pairs).items())),
        "qa_type_counts": dict(sorted(Counter(pair.qa_type for pair in pairs).items())),
        "distinct_paper_ids": len(paper_ids),
        "paper_ids": paper_ids,
    })
    return summary


def _papers_summary(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "research_document_file_count": 0,
        "research_document_count": 0,
        "distinct_paper_ids": 0,
        "paper_ids": [],
        "load_error_count": 0,
        "load_errors": [],
    }
    if not path.exists():
        return summary
    document_paths = sorted(path.glob("*/research_document.json"))
    paper_ids: set[str] = set()
    errors: list[dict[str, str]] = []
    parsed_count = 0
    for document_path in document_paths:
        try:
            payload = json.loads(document_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - exact parser exceptions are not the contract
            errors.append({"path": str(document_path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        parsed_count += 1
        paper_id = str(payload.get("paper_id") or document_path.parent.name).strip()
        if paper_id:
            paper_ids.add(paper_id)
    summary.update({
        "research_document_file_count": len(document_paths),
        "research_document_count": parsed_count,
        "distinct_paper_ids": len(paper_ids),
        "paper_ids": sorted(paper_ids),
        "load_error_count": len(errors),
        "load_errors": errors[:10],
    })
    return summary


def _eligibility_summary(
    *,
    llm: Mapping[str, Any],
    golden_set: Mapping[str, Any],
    papers: Mapping[str, Any],
) -> dict[str, Any]:
    fixture_reasons: list[str] = []
    missing = list(llm.get("missing_required") or [])
    if missing:
        fixture_reasons.append("missing_llm_secrets:" + ",".join(missing))

    real_reasons = list(fixture_reasons)
    if not golden_set.get("exists"):
        real_reasons.append("missing_golden_set")
    elif golden_set.get("load_error"):
        real_reasons.append("invalid_golden_set")
    elif int(golden_set.get("pair_count") or 0) <= 0:
        real_reasons.append("empty_golden_set")

    if not papers.get("exists"):
        real_reasons.append("missing_papers_dir")
    elif int(papers.get("research_document_count") or 0) <= 0:
        real_reasons.append("missing_research_documents")

    missing_paper_ids = sorted(set(golden_set.get("paper_ids") or []) - set(papers.get("paper_ids") or []))
    if missing_paper_ids:
        real_reasons.append("golden_set_papers_missing_from_corpus")

    return {
        "fixture_live_answer_eval": {
            "eligible": not fixture_reasons,
            "reasons": fixture_reasons,
        },
        "real_corpus_live_answer_eval": {
            "eligible": not real_reasons,
            "reasons": real_reasons,
            "missing_paper_id_count": len(missing_paper_ids),
            "missing_paper_ids_sample": missing_paper_ids[:20],
        },
    }


def _baseline_status(eligibility: Mapping[str, Any]) -> str:
    fixture = dict(eligibility.get("fixture_live_answer_eval") or {})
    real = dict(eligibility.get("real_corpus_live_answer_eval") or {})
    real_reasons = list(real.get("reasons") or [])
    if real.get("eligible"):
        return "ready"
    if any(reason.startswith("missing_llm_secrets") for reason in real_reasons):
        return "missing_llm_secrets"
    if fixture.get("eligible"):
        return "fixture_ready_real_corpus_not_ready"
    return "not_ready"


def _readiness_markdown(payload: Mapping[str, Any]) -> str:
    llm = dict(payload.get("llm") or {})
    golden = dict(payload.get("golden_set") or {})
    papers = dict(payload.get("papers") or {})
    eligibility = dict(payload.get("eligibility") or {})
    fixture = dict(eligibility.get("fixture_live_answer_eval") or {})
    real = dict(eligibility.get("real_corpus_live_answer_eval") or {})
    lines = [
        "# Live Answer Eval Readiness",
        "",
        f"**Status:** `{payload.get('baseline_status')}`",
        "",
        "This artifact is a readiness and skip diagnostic. It is not a live answer baseline report.",
        "",
        "## LLM Configuration",
        "",
    ]
    for name, item in sorted(dict(llm.get("required") or {}).items()):
        lines.append(f"- `{name}`: present=`{bool(item.get('present'))}`, length=`{item.get('length')}`")
    for name, item in sorted(dict(llm.get("optional") or {}).items()):
        value = item.get("value")
        suffix = f", value=`{value}`" if value else ""
        lines.append(f"- `{name}`: present=`{bool(item.get('present'))}`, length=`{item.get('length')}`{suffix}")
    lines.extend([
        "",
        "## Golden Set",
        "",
        f"- path: `{golden.get('path')}`",
        f"- exists: `{bool(golden.get('exists'))}`",
        f"- pair_count: `{golden.get('pair_count')}`",
        f"- expected_behavior_counts: `{json.dumps(golden.get('expected_behavior_counts') or {}, sort_keys=True)}`",
        f"- distinct_paper_ids: `{golden.get('distinct_paper_ids')}`",
        "",
        "## Papers",
        "",
        f"- path: `{papers.get('path')}`",
        f"- exists: `{bool(papers.get('exists'))}`",
        f"- research_document_count: `{papers.get('research_document_count')}`",
        f"- research_document_file_count: `{papers.get('research_document_file_count')}`",
        "",
        "## Eligibility",
        "",
        f"- fixture_live_answer_eval: `{bool(fixture.get('eligible'))}`",
        f"- fixture_reasons: `{json.dumps(fixture.get('reasons') or [])}`",
        f"- real_corpus_live_answer_eval: `{bool(real.get('eligible'))}`",
        f"- real_corpus_reasons: `{json.dumps(real.get('reasons') or [])}`",
        f"- real_corpus_missing_paper_id_count: `{real.get('missing_paper_id_count')}`",
        "",
        "## Commands",
        "",
    ])
    for name, command in sorted(dict(payload.get("commands") or {}).items()):
        lines.append(f"- `{name}`: `{command}`")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "DEFAULT_GOLDEN_SET_PATH",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_PAPERS_DIR",
    "LiveAnswerReadinessResult",
    "build_live_answer_readiness",
    "readiness_gate_exit_code",
    "write_live_answer_readiness",
]
