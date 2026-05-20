from __future__ import annotations

from framework.shared import hash_bytes, hash_text, short_hash, stable_hash


def test_hash_text_and_hash_bytes_match_for_utf8_text() -> None:
    assert hash_text("hello") == hash_bytes(b"hello")


def test_stable_hash_uses_canonical_json() -> None:
    assert stable_hash({"b": 2, "a": 1}) == stable_hash({"a": 1, "b": 2})


def test_short_hash_truncates_stable_hash() -> None:
    assert short_hash({"a": 1}, length=8) == stable_hash({"a": 1})[:8]
