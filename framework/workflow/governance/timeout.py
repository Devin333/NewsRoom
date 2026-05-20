from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, TypeVar


T = TypeVar("T")


class TimeoutController:
    def run_with_timeout(self, fn: Callable[[], T], timeout_seconds: float | None) -> T:
        if timeout_seconds is None:
            return fn()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fn)
            try:
                return future.result(timeout=timeout_seconds)
            except FutureTimeoutError as exc:
                raise TimeoutError("workflow operation timed out") from exc


