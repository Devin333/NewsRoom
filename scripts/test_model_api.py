#!/usr/bin/env python3
"""
Test an OpenAI-compatible model API for NewsRoom.

Recommended usage from the NewsRoom project root:

  python scripts/test_model_api.py

Common examples:

  # Use NewsRoom config route, default route is writer-primary
  python scripts/test_model_api.py --route writer-primary

  # Use a specific config file
  python scripts/test_model_api.py --config configs/models.yaml --route writer-primary

  # Raw OpenAI-compatible HTTP test without importing NewsRoom framework
  python scripts/test_model_api.py --raw \
    --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
    --model deepseek-v4-flash \
    --api-key-env DASHSCOPE_API_KEY

  # Test JSON output
  python scripts/test_model_api.py --json

Environment notes:
  - Project config mode uses framework.llm.build_openai_compatible_client_from_config.
  - Direct raw mode needs --base-url, --model, and --api-key-env or environment defaults.
  - Never put the real API key in this script. Put it in an environment variable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_PROMPT = "Reply with exactly: model api ok"


def main() -> int:
    args = parse_args()

    if args.raw:
        return run_raw_http_test(args)

    try:
        return run_newsroom_framework_test(args)
    except ModuleNotFoundError as exc:
        print(f"[warn] Could not import NewsRoom framework: {exc}", file=sys.stderr)
        print("[warn] Falling back to raw OpenAI-compatible HTTP test.", file=sys.stderr)
        return run_raw_http_test(args)
    except Exception as exc:
        print(f"[error] Framework test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        if args.no_fallback:
            return 1
        print("[warn] Falling back to raw OpenAI-compatible HTTP test.", file=sys.stderr)
        return run_raw_http_test(args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test NewsRoom/OpenAI-compatible model API.")
    parser.add_argument("--config", default=None, help="Path to model config, e.g. configs/models.yaml.")
    parser.add_argument("--route", default=os.getenv("NEWS_MODEL_ROUTE", "writer-primary"), help="Model route id.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="User prompt for the test request.")
    parser.add_argument("--system", default="You are a concise API health-check assistant.", help="System prompt.")
    parser.add_argument("--max-tokens", type=int, default=64, help="Max output tokens.")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature.")
    parser.add_argument("--json", action="store_true", help="Ask the model to return JSON.")
    parser.add_argument("--stream", action="store_true", help="Test streaming in framework mode when supported.")
    parser.add_argument("--raw", action="store_true", help="Force raw OpenAI-compatible HTTP mode.")
    parser.add_argument("--no-fallback", action="store_true", help="Do not fallback to raw mode when framework mode fails.")

    # Raw OpenAI-compatible options.
    parser.add_argument("--base-url", default=os.getenv("NEWS_LLM_BASE_URL") or os.getenv("DASHSCOPE_BASE_URL"))
    parser.add_argument("--model", default=os.getenv("NEWS_LLM_MODEL", "deepseek-v4-flash"))
    parser.add_argument("--api-key-env", default=os.getenv("NEWS_LLM_API_KEY_ENV", "DASHSCOPE_API_KEY"))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("NEWS_LLM_TIMEOUT", "90")))
    return parser.parse_args()


def run_newsroom_framework_test(args: argparse.Namespace) -> int:
    """
    Test through the project's LLM abstraction.

    This is the preferred mode inside NewsRoom because it validates:
      - config loading
      - route selection
      - env-var API key resolution
      - OpenAI-compatible client normalization
    """
    ensure_project_root_on_path()

    from framework.llm import (  # type: ignore
        LLMConfigurationError,
        LLMProviderError,
        LLMRequest,
        build_openai_compatible_client_from_config,
        load_openai_compatible_deployment,
    )

    started = time.perf_counter()
    try:
        deployment = load_openai_compatible_deployment(args.config, route_id=args.route)
        client = build_openai_compatible_client_from_config(args.config, route_id=args.route)
    except LLMConfigurationError as exc:
        print(f"[fail] Configuration error: {exc}", file=sys.stderr)
        return 2

    print("[config]")
    print(f"  route_id:      {deployment.route_id}")
    print(f"  deployment_id: {deployment.deployment_id}")
    print(f"  provider:      {deployment.config.provider}")
    print(f"  base_url:      {deployment.config.base_url}")
    print(f"  model:         {deployment.config.model}")
    print(f"  api_key_env:   {deployment.config.api_key_env}")
    print(f"  key_present:   {'yes' if os.getenv(deployment.config.api_key_env) else 'no'}")

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": args.system},
        {"role": "user", "content": json_prompt(args.prompt) if args.json else args.prompt},
    ]

    request = LLMRequest(
        messages=messages,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        response_format={"type": "json_object"} if args.json else None,
    )

    if args.stream:
        print("\n[stream]")
        try:
            content_parts: list[str] = []
            for event in client.stream(request):
                event_type = getattr(event, "event_type", "")
                delta = getattr(event, "delta", None)
                if delta:
                    content_parts.append(str(delta))
                    print(str(delta), end="", flush=True)
                elif event_type in {"message_start", "message_complete"}:
                    print(f"\n  event: {event_type}")
            print()
            content = "".join(content_parts).strip()
        except (LLMConfigurationError, LLMProviderError) as exc:
            print(f"\n[fail] Stream request failed: {format_llm_error(exc)}", file=sys.stderr)
            return 3
    else:
        print("\n[request]")
        print(f"  prompt: {args.prompt!r}")
        try:
            response = client.complete(request)
        except (LLMConfigurationError, LLMProviderError) as exc:
            print(f"[fail] Completion request failed: {format_llm_error(exc)}", file=sys.stderr)
            return 3

        content = str(getattr(response, "content", "") or "").strip()
        usage = getattr(response, "usage", None)
        metadata = getattr(response, "metadata", {}) or {}

        print("\n[response]")
        print(content)
        if usage is not None:
            print("\n[usage]")
            print(to_json_safe(usage))
        if metadata:
            print("\n[metadata]")
            print(json.dumps(redact(metadata), ensure_ascii=False, indent=2))

    elapsed = time.perf_counter() - started
    print(f"\n[ok] Model API test succeeded in {elapsed:.2f}s.")
    if args.json:
        validate_json_response(content)
    return 0


def run_raw_http_test(args: argparse.Namespace) -> int:
    """
    Direct OpenAI-compatible /chat/completions test.

    This mode is useful when the project framework cannot be imported.
    """
    started = time.perf_counter()

    base_url = args.base_url
    model = args.model
    api_key_env = args.api_key_env

    if not base_url:
        print("[fail] --base-url is required in raw mode, or set NEWS_LLM_BASE_URL.", file=sys.stderr)
        return 2
    if not model:
        print("[fail] --model is required in raw mode, or set NEWS_LLM_MODEL.", file=sys.stderr)
        return 2
    if not api_key_env:
        print("[fail] --api-key-env is required in raw mode.", file=sys.stderr)
        return 2

    api_key = os.getenv(api_key_env)
    if not api_key:
        print(f"[fail] Missing API key environment variable: {api_key_env}", file=sys.stderr)
        return 2

    url = f"{base_url.rstrip('/')}/chat/completions"
    messages = [
        {"role": "system", "content": args.system},
        {"role": "user", "content": json_prompt(args.prompt) if args.json else args.prompt},
    ]
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
    }
    if args.json:
        payload["response_format"] = {"type": "json_object"}

    print("[config]")
    print("  mode:        raw-http")
    print(f"  base_url:    {base_url}")
    print(f"  endpoint:    {url}")
    print(f"  model:       {model}")
    print(f"  api_key_env: {api_key_env}")
    print("  key_present: yes")

    request = Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=args.timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        body = safe_read_error_body(exc)
        print(f"[fail] HTTP {exc.code}: {body}", file=sys.stderr)
        return 3
    except (URLError, TimeoutError, OSError) as exc:
        print(f"[fail] Network error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    try:
        response_payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        print(f"[fail] Response is not valid JSON: {exc}", file=sys.stderr)
        print(raw[:1000], file=sys.stderr)
        return 3

    content = extract_openai_compatible_content(response_payload)
    print("\n[response]")
    print(content)

    usage = response_payload.get("usage")
    if usage:
        print("\n[usage]")
        print(json.dumps(usage, ensure_ascii=False, indent=2))

    elapsed = time.perf_counter() - started
    print(f"\n[ok] Raw model API test succeeded in {elapsed:.2f}s.")
    if args.json:
        validate_json_response(content)
    return 0


def ensure_project_root_on_path() -> None:
    cwd = Path.cwd()
    candidates = [cwd, *cwd.parents]
    for candidate in candidates:
        if (candidate / "framework").exists():
            sys.path.insert(0, str(candidate))
            return
    sys.path.insert(0, str(cwd))


def json_prompt(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        'Return a compact JSON object with keys: "status", "message". '
        'The "status" value must be "ok".'
    )


def validate_json_response(content: str) -> None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        print("[warn] --json was requested, but response content is not valid JSON.", file=sys.stderr)
        return
    print("\n[json-check]")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def extract_openai_compatible_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    first = choices[0]
    if not isinstance(first, dict):
        return json.dumps(first, ensure_ascii=False)
    message = first.get("message") or {}
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    return json.dumps(first, ensure_ascii=False, indent=2)


def safe_read_error_body(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:2000]
    except Exception:
        return str(exc)


def format_llm_error(exc: Exception) -> str:
    to_dict = getattr(exc, "to_dict", None)
    if callable(to_dict):
        try:
            return json.dumps(to_dict(), ensure_ascii=False, indent=2)
        except Exception:
            pass
    return f"{type(exc).__name__}: {exc}"


def to_json_safe(value: Any) -> str:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return json.dumps(to_dict(), ensure_ascii=False, indent=2)
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return str(value)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in ("key", "token", "secret", "authorization", "password")):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
