from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

from framework.tool.runtime.errors import ToolRuntimeError, ToolTimeoutError


class ToolTimeoutRunner:
    def run(self, fn: Any, timeout_seconds: float | None, *, operation: str = "tool") -> Any:
        return run_with_timeout(fn, timeout_seconds, operation=operation)


def run_with_timeout(fn: Any, timeout_seconds: float | None, *, operation: str = "tool") -> Any:
    if timeout_seconds is None or timeout_seconds <= 0:
        try:
            return fn()
        except ToolRuntimeError:
            raise
        except Exception:
            raise

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news-tool")
    future = pool.submit(fn)
    timed_out = False
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        timed_out = True
        future.cancel()
        raise ToolTimeoutError(
            f"{operation} exceeded timeout of {timeout_seconds:g} seconds"
        ) from exc
    finally:
        pool.shutdown(wait=not timed_out, cancel_futures=True)
