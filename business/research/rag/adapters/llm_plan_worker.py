from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from threading import Thread
from typing import Any

from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.graph_identity import GraphExecutionIdentity


class LLMResearchRAGPlanCandidateWorker:
    """LLM-backed Research candidate worker for Harness RAG plan candidates."""

    def __init__(self, llm_call: Callable[[str], Any]) -> None:
        self._llm_call = llm_call

    def generate_candidate(
        self,
        *,
        task: str,
        payload: dict[str, Any],
        execution_identity: GraphExecutionIdentity | None = None,
    ) -> dict[str, Any]:
        if task != "rag_plan_candidate":
            raise ValueError(f"unsupported RAG planner task: {task}")
        prompt = _planner_prompt(payload)
        if execution_identity is None:
            response = _run_maybe_async(self._llm_call(prompt))
        else:
            response = _run_maybe_async(
                self._llm_call(prompt, execution_identity=execution_identity)
            )
        parsed = _extract_json_object(str(response or ""))
        candidate = parsed.get("candidate") or parsed.get("retrieval_plan_candidate")
        if not isinstance(candidate, dict):
            raise ValueError("RAG planner LLM response must contain a candidate object")
        return {"candidate": candidate}


def _planner_prompt(payload: dict[str, Any]) -> str:
    safe_payload = to_jsonable(payload)
    return (
        "You are a bounded RAG retrieval planner worker. "
        "Return only JSON with one top-level key named candidate. "
        "The candidate must be a RetrievalPlanCandidate for Harness validation. "
        "Do not include workflow routing, quality pass/fail, memory writes, publication, "
        "tool authorization, or halt decisions. Avoid repeated queries listed in executed_queries.\n\n"
        "Planner request JSON:\n"
        f"{stable_json_dumps(safe_payload)}\n\n"
        "Required response shape:\n"
        '{"candidate":{"candidate_id":"...","queries":[{"step_id":"...",'
        '"operation":"search_corpus","query":"...","corpus":"research-papers",'
        '"max_results":3,"metadata":{"evidence_type":"..."}}],'
        '"expected_evidence":["..."],"expected_gaps":["..."],'
        '"confidence":0.0,"metadata":{"planner":"llm"}}}'
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("RAG planner LLM response is empty")
    for candidate in (stripped, _strip_fenced_json(stripped), _slice_json_object(stripped)):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            raise ValueError("RAG planner LLM response must be a JSON object")
        return payload
    raise ValueError("RAG planner LLM response is not valid JSON")


def _strip_fenced_json(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _slice_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return ""
    return text[start:end + 1]


def _run_maybe_async(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)

    result: dict[str, Any] = {}

    def _target() -> None:
        try:
            result["value"] = asyncio.run(value)
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            result["error"] = exc

    thread = Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result["value"]


__all__ = ["LLMResearchRAGPlanCandidateWorker"]
