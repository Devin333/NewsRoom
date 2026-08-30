from __future__ import annotations

from backend.foundation import Signal


def deduplicate_signals(signals: list[Signal]) -> tuple[list[Signal], int]:
    seen: set[tuple[str, str]] = set()
    deduped: list[Signal] = []
    duplicate_count = 0
    for signal in signals:
        marker = (signal.canonical_key, signal.content_hash)
        if marker in seen:
            duplicate_count += 1
            continue
        seen.add(marker)
        deduped.append(signal)
    return deduped, duplicate_count
