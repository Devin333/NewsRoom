from __future__ import annotations

import copy
import hmac
import json
import math
import os
import re
import stat
import tempfile
import threading
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any


LOCAL_CHUNK_STORE_SCHEMA_VERSION = 1
DEFAULT_LOCAL_CHUNK_COLLECTION = "research_paper_chunks"
DEFAULT_LOCAL_CHUNK_STORE_MAX_BYTES = 256 * 1024 * 1024

_COLLECTION_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")
_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_CHECKSUM = re.compile(r"^sha256:[0-9a-f]{64}$")
_SEARCHABLE_FIELDS = (
    "content",
    "section_title",
    "formula_latex",
    "formula_description",
)
_SEARCHABLE_METADATA_FIELDS = (
    "caption",
    "visual_description",
    "table_text",
    "section",
    "section_title",
)
_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, Any] = {}

class LocalChunkStoreError(RuntimeError):
    """Base error for the durable local chunk payload boundary."""


class LocalChunkStoreCorruptionError(LocalChunkStoreError):
    """Persisted chunk data failed integrity or identity validation."""


class LocalChunkStoreValidationError(ValueError):
    """A caller supplied an invalid collection, payload, filter, or limit."""


class LocalChunkPayloadStore:
    """Atomic, checksum-verified lexical chunk storage for one local host.

    The store deliberately speaks JSON-compatible payload dictionaries only.
    Business-layer adapters remain responsible for converting those payloads
    to and from domain chunk models.

    ``delete_paper_chunks`` implements the existing payload-port contract and
    deletes every persisted run for that paper. Run-scoped callers must not use
    it as single-run cleanup. Instances in one process share a path-scoped lock;
    the production composition therefore owns one process-scoped store.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        collection: str = DEFAULT_LOCAL_CHUNK_COLLECTION,
        max_bytes: int = DEFAULT_LOCAL_CHUNK_STORE_MAX_BYTES,
    ) -> None:
        self._root = _validated_root(root)
        self._collection = _validated_collection(collection)
        self._max_bytes = _validated_max_bytes(max_bytes)
        self._path = self._root / f"{self._collection}.json"
        self._lock_path = self._root / f".{self._collection}.lock"
        self._lock = _path_lock(self._path)
        _assert_descendant(self._root, self._path)
        _assert_descendant(self._root, self._lock_path)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def collection(self) -> str:
        return self._collection

    @property
    def path(self) -> Path:
        return self._path

    def ensure_collection(self) -> None:
        with self._mutation_lock():
            payloads = self._read_payloads()
            if payloads is None:
                self._write_payloads([])

    def index_payloads(self, payloads: list[dict[str, Any]]) -> None:
        if not isinstance(payloads, list):
            raise LocalChunkStoreValidationError("payloads must be a list")
        if not payloads:
            return
        normalized = [_validated_payload(payload) for payload in payloads]
        incoming_ids = [payload["chunk_id"] for payload in normalized]
        if len(incoming_ids) != len(set(incoming_ids)):
            raise LocalChunkStoreValidationError(
                "payload batch contains duplicate chunk_id values"
            )

        with self._mutation_lock():
            current = self._read_payloads() or []
            by_id = {payload["chunk_id"]: payload for payload in current}
            for payload in normalized:
                by_id[payload["chunk_id"]] = payload
            selected = [by_id[chunk_id] for chunk_id in sorted(by_id)]
            if selected != current:
                self._write_payloads(selected)

    def delete_paper_chunks(self, paper_id: str) -> None:
        expected_paper_id = _required_text(paper_id, "paper_id")
        with self._mutation_lock():
            current = self._read_payloads()
            if current is None:
                return
            selected = [
                payload
                for payload in current
                if payload["paper_id"] != expected_paper_id
            ]
            if selected != current:
                self._write_payloads(selected)

    @contextmanager
    def _mutation_lock(self) -> Iterator[None]:
        with self._lock:
            _ensure_directory(self._root)
            with _exclusive_file_lock(self._lock_path):
                yield

    def _read_snapshot(self) -> list[dict[str, Any]] | None:
        with self._lock:
            if not _directory_exists(self._root):
                return None
            with _exclusive_file_lock(self._lock_path):
                return self._read_payloads()

    def search_payloads_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> list[tuple[dict[str, Any], float]]:
        expected_paper_id = _required_text(paper_id, "paper_id")
        query_tokens = _tokenize(_required_text(query_text, "query_text"))
        selected_limit = _validated_limit(limit)
        selected_offset = _validated_offset(offset)
        selected_filters = _validated_filters(filters)
        if not query_tokens:
            return []

        payloads = self._read_snapshot() or []
        candidates = [
            payload
            for payload in payloads
            if payload["paper_id"] == expected_paper_id
            and _matches_filters(payload, selected_filters)
        ]
        scored = _lexical_scores(candidates, query_tokens)
        return [
            (copy.deepcopy(payload), score)
            for payload, score in scored[
                selected_offset : selected_offset + selected_limit
            ]
        ]

    def search_payloads(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        selected_limit = _validated_limit(limit)
        threshold = _validated_score_threshold(score_threshold)
        scored = self.search_payloads_with_scores(
            paper_id,
            query_text,
            filters=filters,
            limit=selected_limit,
            offset=_validated_offset(offset),
        )
        return [
            payload
            for payload, score in scored
            if threshold is None or score >= threshold
        ]

    def get_payload(self, chunk_id: str) -> dict[str, Any] | None:
        expected_chunk_id = _required_text(chunk_id, "chunk_id")
        payloads = self._read_snapshot() or []
        for payload in payloads:
            if payload["chunk_id"] == expected_chunk_id:
                return copy.deepcopy(payload)
        return None

    def list_paper_payloads(self, paper_id: str) -> list[dict[str, Any]]:
        expected_paper_id = _required_text(paper_id, "paper_id")
        payloads = self._read_snapshot() or []
        return [
            copy.deepcopy(payload)
            for payload in payloads
            if payload["paper_id"] == expected_paper_id
        ]

    def _read_payloads(self) -> list[dict[str, Any]] | None:
        _assert_descendant(self._root, self._path)
        if not _directory_exists(self._root):
            return None
        state = _read_json_file(self._path, max_bytes=self._max_bytes)
        if state is None:
            return None
        expected_keys = {"schema_version", "collection", "payloads", "checksum"}
        if set(state) != expected_keys:
            raise LocalChunkStoreCorruptionError(
                "local chunk store schema fields are invalid"
            )
        version = state.get("schema_version")
        if isinstance(version, bool) or version != LOCAL_CHUNK_STORE_SCHEMA_VERSION:
            raise LocalChunkStoreCorruptionError(
                "local chunk store schema version is unsupported"
            )
        if state.get("collection") != self._collection:
            raise LocalChunkStoreCorruptionError(
                "local chunk store collection identity mismatch"
            )
        checksum = state.get("checksum")
        if not isinstance(checksum, str) or _CHECKSUM.fullmatch(checksum) is None:
            raise LocalChunkStoreCorruptionError(
                "local chunk store checksum is invalid"
            )
        unsigned = {
            "schema_version": state["schema_version"],
            "collection": state["collection"],
            "payloads": state["payloads"],
        }
        if not _constant_time_equal(checksum, _state_checksum(unsigned)):
            raise LocalChunkStoreCorruptionError(
                "local chunk store checksum mismatch"
            )
        raw_payloads = state.get("payloads")
        if not isinstance(raw_payloads, list):
            raise LocalChunkStoreCorruptionError(
                "local chunk store payload collection is invalid"
            )
        try:
            payloads = [_validated_payload(payload) for payload in raw_payloads]
        except LocalChunkStoreValidationError as exc:
            raise LocalChunkStoreCorruptionError(
                "local chunk store contains an invalid payload"
            ) from exc
        chunk_ids = [payload["chunk_id"] for payload in payloads]
        if chunk_ids != sorted(chunk_ids) or len(chunk_ids) != len(set(chunk_ids)):
            raise LocalChunkStoreCorruptionError(
                "local chunk store payload identity index is invalid"
            )
        return payloads

    def _write_payloads(self, payloads: list[dict[str, Any]]) -> None:
        _ensure_directory(self._root)
        _assert_descendant(self._root, self._path)
        _assert_missing_or_regular_file(self._path)
        unsigned = {
            "schema_version": LOCAL_CHUNK_STORE_SCHEMA_VERSION,
            "collection": self._collection,
            "payloads": payloads,
        }
        state = {**unsigned, "checksum": _state_checksum(unsigned)}
        encoded = (
            json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        if len(encoded) > self._max_bytes:
            raise LocalChunkStoreValidationError(
                "local chunk store snapshot exceeds max_bytes"
            )
        _write_atomic(self._path, encoded)


def _validated_root(value: str | os.PathLike[str]) -> Path:
    try:
        raw = os.fspath(value)
        if not raw or "\x00" in raw:
            raise ValueError
        root = Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise LocalChunkStoreValidationError(
            "local chunk store root is invalid"
        ) from exc
    if root.exists() and not root.is_dir():
        raise LocalChunkStoreValidationError(
            "local chunk store root must be a directory"
        )
    return root


def _path_lock(path: Path) -> Any:
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[path] = lock
        return lock


def _validated_collection(value: Any) -> str:
    if not isinstance(value, str) or _COLLECTION_NAME.fullmatch(value) is None:
        raise LocalChunkStoreValidationError(
            "local chunk store collection is invalid"
        )
    return value


def _validated_max_bytes(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LocalChunkStoreValidationError("max_bytes must be a positive integer")
    return value


def _validated_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LocalChunkStoreValidationError("limit must be a positive integer")
    return value


def _validated_offset(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LocalChunkStoreValidationError(
            "offset must be a non-negative integer"
        )
    return value


def _validated_score_threshold(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LocalChunkStoreValidationError("score_threshold must be finite")
    threshold = float(value)
    if not math.isfinite(threshold):
        raise LocalChunkStoreValidationError("score_threshold must be finite")
    return threshold


def _validated_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LocalChunkStoreValidationError("chunk payload must be an object")
    payload = dict(value)
    _required_text(payload.get("chunk_id"), "chunk_id")
    _required_text(payload.get("paper_id"), "paper_id")
    _required_text(payload.get("content"), "content")
    try:
        canonical = _canonical_json(payload)
        normalized = json.loads(canonical, parse_constant=_reject_json_constant)
    except (TypeError, ValueError) as exc:
        raise LocalChunkStoreValidationError(
            "chunk payload must contain only finite JSON values"
        ) from exc
    if not isinstance(normalized, dict):
        raise LocalChunkStoreValidationError("chunk payload must be an object")
    return normalized


def _validated_filters(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise LocalChunkStoreValidationError("filters must be an object")
    filters: dict[str, Any] = {}
    for raw_key, expected in value.items():
        key = _required_text(raw_key, "filter key")
        if any(part in {"", ".", ".."} for part in key.split(".")):
            raise LocalChunkStoreValidationError("filter key is invalid")
        try:
            filters[key] = json.loads(
                _canonical_json(expected),
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError) as exc:
            raise LocalChunkStoreValidationError(
                "filter values must be finite JSON values"
            ) from exc
    return filters


def _required_text(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise LocalChunkStoreValidationError(f"{field} is invalid")
    return value


def _matches_filters(payload: dict[str, Any], filters: dict[str, Any]) -> bool:
    missing = object()
    for key, expected in filters.items():
        actual = _filter_value(payload, key, missing)
        if actual is missing:
            return False
        if isinstance(actual, list) and not isinstance(expected, list):
            if not any(_json_equal(item, expected) for item in actual):
                return False
            continue
        if not _json_equal(actual, expected):
            return False
    return True


def _filter_value(payload: dict[str, Any], key: str, missing: object) -> Any:
    parts = key.split(".")
    current: Any = payload
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            current = missing
            break
        current = current[part]
    if current is not missing:
        return current
    if len(parts) == 1:
        metadata = payload.get("metadata")
        if isinstance(metadata, dict) and key in metadata:
            return metadata[key]
    return missing


def _json_equal(left: Any, right: Any) -> bool:
    return _canonical_json(left) == _canonical_json(right)


def _lexical_scores(
    payloads: list[dict[str, Any]],
    query_tokens: list[str],
) -> list[tuple[dict[str, Any], float]]:
    documents = [_tokenize(_searchable_text(payload)) for payload in payloads]
    document_frequency: Counter[str] = Counter()
    for tokens in documents:
        document_frequency.update(set(tokens))
    average_length = (
        sum(len(tokens) for tokens in documents) / len(documents)
        if documents
        else 0.0
    )
    query_frequency = Counter(query_tokens)
    scored: list[tuple[dict[str, Any], float]] = []
    for payload, tokens in zip(payloads, documents, strict=True):
        if not tokens:
            continue
        term_frequency = Counter(tokens)
        score = 0.0
        for token, query_count in query_frequency.items():
            frequency = term_frequency.get(token, 0)
            if frequency == 0:
                continue
            frequency_in_documents = document_frequency[token]
            inverse_document_frequency = math.log(
                1.0
                + (len(documents) - frequency_in_documents + 0.5)
                / (frequency_in_documents + 0.5)
            )
            denominator = frequency + 1.5 * (
                0.25 + 0.75 * len(tokens) / max(average_length, 1e-9)
            )
            score += query_count * inverse_document_frequency * (
                frequency * 2.5 / denominator
            )
        if score > 0.0:
            scored.append((payload, round(score, 12)))
    scored.sort(key=lambda item: (-item[1], item[0]["chunk_id"]))
    return scored


def _searchable_text(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get(field) or "")
        for field in _SEARCHABLE_FIELDS
    ]
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        for field in _SEARCHABLE_METADATA_FIELDS:
            value = metadata.get(field)
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            elif value is not None:
                parts.append(str(value))
    return "\n".join(part for part in parts if part)


def _tokenize(value: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN.finditer(value)]


def _state_checksum(unsigned: Mapping[str, Any]) -> str:
    digest = sha256(_canonical_json(unsigned).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _read_json_file(path: Path, *, max_bytes: int) -> dict[str, Any] | None:
    try:
        inspected = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LocalChunkStoreCorruptionError(
            "local chunk store path cannot be inspected"
        ) from exc
    if not stat.S_ISREG(inspected.st_mode):
        raise LocalChunkStoreCorruptionError(
            "local chunk store path is not a regular file"
        )
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise LocalChunkStoreCorruptionError(
                    "local chunk store path is not a regular file"
                )
            if not os.path.samestat(inspected, opened):
                raise LocalChunkStoreCorruptionError(
                    "local chunk store file identity changed while opening"
                )
            if opened.st_size > max_bytes:
                raise LocalChunkStoreCorruptionError(
                    "local chunk store snapshot exceeds max_bytes"
                )
            encoded = handle.read(max_bytes + 1)
    except LocalChunkStoreCorruptionError:
        raise
    except OSError as exc:
        raise LocalChunkStoreCorruptionError(
            "local chunk store snapshot cannot be read"
        ) from exc
    if len(encoded) > max_bytes:
        raise LocalChunkStoreCorruptionError(
            "local chunk store snapshot exceeds max_bytes"
        )
    try:
        state = json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise LocalChunkStoreCorruptionError(
            "local chunk store JSON is invalid"
        ) from exc
    if not isinstance(state, dict):
        raise LocalChunkStoreCorruptionError(
            "local chunk store root must be an object"
        )
    return state


def _directory_exists(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise LocalChunkStoreCorruptionError(
            "local chunk store root cannot be inspected"
        ) from exc
    if not stat.S_ISDIR(mode):
        raise LocalChunkStoreCorruptionError(
            "local chunk store root is not a directory"
        )
    return True


def _ensure_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LocalChunkStoreError(
            "local chunk store root cannot be created"
        ) from exc
    if not _directory_exists(path):
        raise LocalChunkStoreCorruptionError(
            "local chunk store root is not a directory"
        )


def _assert_missing_or_regular_file(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as exc:
        raise LocalChunkStoreCorruptionError(
            "local chunk store path cannot be inspected"
        ) from exc
    if not stat.S_ISREG(mode):
        raise LocalChunkStoreCorruptionError(
            "local chunk store path is not a regular file"
        )


def _assert_descendant(root: Path, path: Path) -> None:
    try:
        resolved_path = path.resolve(strict=False)
        resolved_path.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise LocalChunkStoreCorruptionError(
            "local chunk store path escaped its configured root"
        ) from exc


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    _assert_missing_or_regular_file(path)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise LocalChunkStoreError(
            "local chunk store lock cannot be opened"
        ) from exc

    try:
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise LocalChunkStoreCorruptionError(
                "local chunk store lock is not a regular file"
            )
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as exc:
        os.close(descriptor)
        raise LocalChunkStoreError(
            "local chunk store lock operation failed"
        ) from exc
    except Exception:
        os.close(descriptor)
        raise

    try:
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            # Closing the descriptor releases the process lock even if an
            # explicit unlock reports an OS-level cleanup race.
            pass
        finally:
            os.close(descriptor)


def _write_atomic(path: Path, encoded: bytes) -> None:
    descriptor, raw_temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "DEFAULT_LOCAL_CHUNK_COLLECTION",
    "DEFAULT_LOCAL_CHUNK_STORE_MAX_BYTES",
    "LOCAL_CHUNK_STORE_SCHEMA_VERSION",
    "LocalChunkPayloadStore",
    "LocalChunkStoreCorruptionError",
    "LocalChunkStoreError",
    "LocalChunkStoreValidationError",
]
