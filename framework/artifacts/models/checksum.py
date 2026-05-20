from __future__ import annotations

from framework.shared.hashing import hash_bytes


def compute_checksum(content: bytes) -> str:
    return hash_bytes(content)


def verify_checksum(content: bytes, checksum: str) -> bool:
    return compute_checksum(content) == checksum
