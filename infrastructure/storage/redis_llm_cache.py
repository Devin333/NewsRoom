from __future__ import annotations

import base64
import binascii
import json
import math
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from framework.llm.cache import (
    CACHE_ENTRY_SCHEMA_VERSION,
    CacheEntry,
    CacheLookup,
    CacheLookupStatus,
    CacheResponseValidationError,
    CacheWriteResult,
    CacheWriteStatus,
    LLMCacheKey,
    SingleFlightAcquireResult,
    SingleFlightAcquireStatus,
    SingleFlightLease,
    SingleFlightReleaseResult,
    canonical_json_bytes,
)


LLM_CACHE_ENVELOPE_VERSION = "newsroom.llm-cache-envelope.v1"
_NONCE_BYTES = 12
_MAX_REDIS_KEY_BYTES = 512
_NAMESPACE_PARTS_MINIMUM = 2
_RESERVED_RUNTIME_NAMESPACES = (
    "news:runtime",
    "news:workers",
    "newsroom:artifacts",
    "newsroom:events",
    "newsroom:harness",
    "newsroom:lineage",
    "newsroom:runtime",
    "newsroom:workers",
)
_COMPARE_AND_DELETE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
""".strip()


class LLMCacheCodecError(ValueError):
    """A redacted error for an untrusted encrypted cache envelope."""


@dataclass(frozen=True)
class LLMCacheReadiness:
    available: bool
    backend: str
    reason: str
    checked_operations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "backend": self.backend,
            "reason": self.reason,
            "checked_operations": list(self.checked_operations),
        }


class LLMCacheEnvelopeCodec:
    def __init__(self, *, namespace: str, encryption_key: str | bytes) -> None:
        self.namespace = validate_llm_cache_namespace(namespace)
        self._aead = AESGCM(decode_llm_cache_encryption_key(encryption_key))

    def encode(self, key: LLMCacheKey, entry: CacheEntry) -> bytes:
        external_key = _external_key(key, namespace=self.namespace)
        try:
            entry.validate_identity(key)
            plaintext = entry.to_json_bytes()
            nonce = secrets.token_bytes(_NONCE_BYTES)
            ciphertext = self._aead.encrypt(
                nonce,
                plaintext,
                self._associated_data(external_key),
            )
            return canonical_json_bytes(
                {
                    "ciphertext": _base64url_encode(ciphertext),
                    "entry_schema_version": CACHE_ENTRY_SCHEMA_VERSION,
                    "envelope_version": LLM_CACHE_ENVELOPE_VERSION,
                    "nonce": _base64url_encode(nonce),
                }
            )
        except (CacheResponseValidationError, TypeError, ValueError) as exc:
            raise LLMCacheCodecError("cache envelope encoding failed") from exc

    def decode(self, key: LLMCacheKey, payload: bytes) -> CacheEntry:
        external_key = _external_key(key, namespace=self.namespace)
        try:
            envelope = json.loads(payload.decode("utf-8"))
            if not isinstance(envelope, dict) or set(envelope) != {
                "ciphertext",
                "entry_schema_version",
                "envelope_version",
                "nonce",
            }:
                raise LLMCacheCodecError("invalid cache envelope")
            if envelope.get("envelope_version") != LLM_CACHE_ENVELOPE_VERSION:
                raise LLMCacheCodecError("unsupported cache envelope version")
            if envelope.get("entry_schema_version") != CACHE_ENTRY_SCHEMA_VERSION:
                raise LLMCacheCodecError("unsupported cache entry schema version")
            nonce = _base64url_decode(envelope.get("nonce"))
            ciphertext = _base64url_decode(envelope.get("ciphertext"))
            if len(nonce) != _NONCE_BYTES or len(ciphertext) < 16:
                raise LLMCacheCodecError("invalid cache envelope encoding")
            plaintext = self._aead.decrypt(
                nonce,
                ciphertext,
                self._associated_data(external_key),
            )
            entry = CacheEntry.from_json_bytes(plaintext)
            entry.validate_identity(key)
            return entry
        except LLMCacheCodecError:
            raise
        except (
            binascii.Error,
            CacheResponseValidationError,
            InvalidTag,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise LLMCacheCodecError("cache envelope validation failed") from exc

    def _associated_data(self, external_key: str) -> bytes:
        return canonical_json_bytes(
            {
                "entry_schema_version": CACHE_ENTRY_SCHEMA_VERSION,
                "envelope_version": LLM_CACHE_ENVELOPE_VERSION,
                "external_key": external_key,
                "namespace": self.namespace,
            }
        )


class RedisLLMCache:
    backend_name = "redis"

    def __init__(
        self,
        redis_client: Any,
        *,
        namespace: str,
        codec: LLMCacheEnvelopeCodec,
        max_entry_bytes: int = 1_048_576,
        max_ttl_seconds: float = 86_400.0,
        max_lease_ttl_seconds: float = 600.0,
        monotonic_clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], float] | None = None,
    ) -> None:
        if redis_client is None:
            raise ValueError("redis_client is required")
        self.namespace = validate_llm_cache_namespace(namespace)
        if codec.namespace != self.namespace:
            raise ValueError("cache codec namespace must match Redis cache namespace")
        self.max_entry_bytes = _bounded_positive_int(
            max_entry_bytes,
            field="max_entry_bytes",
            maximum=16 * 1024 * 1024,
        )
        self.max_ttl_seconds = _bounded_positive_number(
            max_ttl_seconds,
            field="max_ttl_seconds",
            maximum=31 * 24 * 60 * 60,
        )
        self.max_lease_ttl_seconds = _bounded_positive_number(
            max_lease_ttl_seconds,
            field="max_lease_ttl_seconds",
            maximum=24 * 60 * 60,
        )
        self.redis = redis_client
        self.codec = codec
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._wall_clock = wall_clock or time.time

    def get(self, key: LLMCacheKey) -> CacheLookup:
        external_key = _external_key(key, namespace=self.namespace)
        try:
            raw = self.redis.get(external_key)
        except Exception as exc:
            return self._lookup_backend_error(exc)
        if raw is None:
            return CacheLookup(status=CacheLookupStatus.MISS, backend=self.backend_name)
        try:
            payload = _redis_payload_bytes(raw)
        except (TypeError, ValueError):
            self._delete_exact_best_effort(external_key)
            return self._corrupt("unsupported_redis_value")
        if len(payload) > self.max_entry_bytes:
            self._delete_exact_best_effort(external_key)
            return self._corrupt("encoded_entry_too_large")

        try:
            ttl_ms = int(self.redis.pttl(external_key))
        except Exception as exc:
            return self._lookup_backend_error(exc)
        if ttl_ms == -2:
            return CacheLookup(status=CacheLookupStatus.MISS, backend=self.backend_name)
        if ttl_ms == -1:
            self._delete_exact_best_effort(external_key)
            return self._corrupt("entry_missing_expiry")
        if ttl_ms <= 0:
            self._delete_exact_best_effort(external_key)
            return CacheLookup(status=CacheLookupStatus.EXPIRED, backend=self.backend_name)

        try:
            entry = self.codec.decode(key, payload)
        except LLMCacheCodecError:
            self._delete_exact_best_effort(external_key)
            return self._corrupt("encrypted_entry_validation_failed")
        created_at = float(entry.created_at)
        now = self._wall_clock()
        if not math.isfinite(created_at) or created_at < 0 or created_at > now + 300:
            self._delete_exact_best_effort(external_key)
            return self._corrupt("entry_creation_time_invalid")
        return CacheLookup.hit_entry(
            entry,
            age_seconds=max(0.0, now - created_at),
            backend=self.backend_name,
        )

    def put(
        self,
        key: LLMCacheKey,
        entry: CacheEntry,
        *,
        ttl_seconds: float,
    ) -> CacheWriteResult:
        ttl = _bounded_positive_number(
            ttl_seconds,
            field="ttl_seconds",
            maximum=self.max_ttl_seconds,
        )
        try:
            payload = self.codec.encode(key, entry)
        except LLMCacheCodecError:
            return CacheWriteResult(
                status=CacheWriteStatus.SKIPPED,
                reason="entry_validation_failed",
                backend=self.backend_name,
            )
        size_bytes = len(payload)
        if size_bytes > self.max_entry_bytes:
            return CacheWriteResult(
                status=CacheWriteStatus.ENTRY_TOO_LARGE,
                reason="encoded_entry_too_large",
                size_bytes=size_bytes,
                backend=self.backend_name,
            )
        external_key = _external_key(key, namespace=self.namespace)
        try:
            stored = self.redis.set(external_key, payload, ex=math.ceil(ttl))
        except Exception as exc:
            return CacheWriteResult(
                status=CacheWriteStatus.BACKEND_ERROR,
                reason=_bounded_error_class(exc),
                size_bytes=size_bytes,
                backend=self.backend_name,
            )
        if not stored:
            return CacheWriteResult(
                status=CacheWriteStatus.BACKEND_ERROR,
                reason="redis_write_rejected",
                size_bytes=size_bytes,
                backend=self.backend_name,
            )
        return CacheWriteResult(
            status=CacheWriteStatus.WRITTEN,
            size_bytes=size_bytes,
            backend=self.backend_name,
        )

    def delete(self, key: LLMCacheKey) -> bool:
        external_key = _external_key(key, namespace=self.namespace)
        try:
            return bool(self.redis.delete(external_key))
        except Exception:
            return False

    def acquire_singleflight(
        self,
        key: LLMCacheKey,
        *,
        owner_token: str,
        ttl_seconds: float,
    ) -> SingleFlightAcquireResult:
        token = _validate_owner_token(owner_token)
        ttl = _bounded_positive_number(
            ttl_seconds,
            field="ttl_seconds",
            maximum=self.max_lease_ttl_seconds,
        )
        external_key = _external_key(key, namespace=self.namespace)
        lease_key = _lease_key(external_key)
        try:
            acquired = bool(
                self.redis.set(
                    lease_key,
                    token,
                    nx=True,
                    px=math.ceil(ttl * 1_000),
                )
            )
        except Exception as exc:
            return SingleFlightAcquireResult(
                status=SingleFlightAcquireStatus.BACKEND_ERROR,
                reason=_bounded_error_class(exc),
            )
        if not acquired:
            return SingleFlightAcquireResult(status=SingleFlightAcquireStatus.BUSY)
        return SingleFlightAcquireResult(
            status=SingleFlightAcquireStatus.ACQUIRED,
            lease=SingleFlightLease(
                cache_key=external_key,
                owner_token=token,
                expires_at_monotonic=self._monotonic_clock() + ttl,
            ),
        )

    def release_singleflight(
        self,
        lease: SingleFlightLease,
    ) -> SingleFlightReleaseResult:
        try:
            external_key = _validated_external_lease_key(
                lease.cache_key,
                namespace=self.namespace,
            )
            token = _validate_owner_token(lease.owner_token)
            released = bool(
                self.redis.eval(
                    _COMPARE_AND_DELETE,
                    1,
                    _lease_key(external_key),
                    token,
                )
            )
        except (TypeError, ValueError) as exc:
            return SingleFlightReleaseResult(
                released=False,
                reason=_bounded_error_class(exc),
            )
        except Exception as exc:
            return SingleFlightReleaseResult(
                released=False,
                backend_error=True,
                reason=_bounded_error_class(exc),
            )
        return SingleFlightReleaseResult(
            released=released,
            reason=None if released else "not_owner",
        )

    def readiness(self) -> LLMCacheReadiness:
        operations = ("ping", "set", "get", "pttl", "delete", "lease_release")
        probe_id = secrets.token_hex(12)
        value_key = f"{self.namespace}:probe:value:{probe_id}"
        lease_key = f"{self.namespace}:probe:lease:{probe_id}"
        probe_value = f"probe-{probe_id}"
        try:
            if not self.redis.ping():
                raise RuntimeError("ping rejected")
            if not self.redis.set(value_key, probe_value, ex=5, nx=True):
                raise RuntimeError("probe set rejected")
            value = self.redis.get(value_key)
            if _redis_payload_bytes(value).decode("utf-8") != probe_value:
                raise RuntimeError("probe read mismatch")
            if int(self.redis.pttl(value_key)) <= 0:
                raise RuntimeError("probe expiry missing")
            if not self.redis.delete(value_key):
                raise RuntimeError("probe delete rejected")
            if not self.redis.set(lease_key, probe_value, px=5_000, nx=True):
                raise RuntimeError("probe lease rejected")
            if not self.redis.eval(_COMPARE_AND_DELETE, 1, lease_key, probe_value):
                raise RuntimeError("probe lease release rejected")
        except Exception as exc:
            self._delete_exact_best_effort(value_key)
            self._delete_exact_best_effort(lease_key)
            return LLMCacheReadiness(
                available=False,
                backend=self.backend_name,
                reason=_bounded_error_class(exc),
                checked_operations=operations,
            )
        return LLMCacheReadiness(
            available=True,
            backend=self.backend_name,
            reason="ready",
            checked_operations=operations,
        )

    def _lookup_backend_error(self, exc: Exception) -> CacheLookup:
        return CacheLookup(
            status=CacheLookupStatus.BACKEND_ERROR,
            reason=_bounded_error_class(exc),
            backend=self.backend_name,
        )

    def _corrupt(self, reason: str) -> CacheLookup:
        return CacheLookup(
            status=CacheLookupStatus.CORRUPT,
            reason=reason,
            backend=self.backend_name,
        )

    def _delete_exact_best_effort(self, external_key: str) -> None:
        try:
            self.redis.delete(external_key)
        except Exception:
            return


def validate_llm_cache_namespace(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("cache namespace must be text")
    namespace = value.strip().rstrip(":")
    if not namespace or len(namespace) > 96:
        raise ValueError("cache namespace must contain between 1 and 96 characters")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:")
    if any(character not in allowed for character in namespace):
        raise ValueError("cache namespace contains unsupported characters")
    if len([part for part in namespace.split(":") if part]) < _NAMESPACE_PARTS_MINIMUM:
        raise ValueError("cache namespace must have a dedicated multi-part prefix")
    for reserved in _RESERVED_RUNTIME_NAMESPACES:
        if (
            namespace == reserved
            or namespace.startswith(f"{reserved}:")
            or reserved.startswith(f"{namespace}:")
        ):
            raise ValueError("cache namespace overlaps a reserved runtime namespace")
    return namespace


def decode_llm_cache_encryption_key(value: str | bytes) -> bytes:
    encoded = value.encode("ascii") if isinstance(value, str) else bytes(value)
    try:
        padding = b"=" * (-len(encoded) % 4)
        decoded = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error, TypeError, ValueError) as exc:
        raise ValueError("LLM cache encryption key must be URL-safe base64") from exc
    if len(decoded) != 32:
        raise ValueError("LLM cache encryption key must decode to exactly 32 bytes")
    return decoded


def _external_key(key: LLMCacheKey, *, namespace: str) -> str:
    if not isinstance(key, LLMCacheKey):
        raise TypeError("key must be LLMCacheKey")
    if key.namespace != namespace:
        raise ValueError("cache key namespace does not match adapter namespace")
    external_key = key.to_string()
    if not external_key.startswith(f"{namespace}:"):
        raise ValueError("cache external key is outside the adapter namespace")
    if len(external_key.encode("utf-8")) > _MAX_REDIS_KEY_BYTES:
        raise ValueError("cache external key is too long")
    return external_key


def _validated_external_lease_key(value: str, *, namespace: str) -> str:
    if not isinstance(value, str) or not value.startswith(f"{namespace}:"):
        raise ValueError("lease cache key is outside the adapter namespace")
    if len(value.encode("utf-8")) > _MAX_REDIS_KEY_BYTES or value.endswith(":lease"):
        raise ValueError("lease cache key is invalid")
    return value


def _lease_key(external_key: str) -> str:
    return f"{external_key}:lease"


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: Any) -> bytes:
    if not isinstance(value, str) or len(value) > 32 * 1024 * 1024:
        raise LLMCacheCodecError("invalid cache envelope encoding")
    encoded = value.encode("ascii")
    return base64.b64decode(encoded + b"=" * (-len(encoded) % 4), altchars=b"-_", validate=True)


def _redis_payload_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError("Redis cache values must be bytes or text")


def _bounded_positive_int(value: Any, *, field: str, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    parsed = int(value)
    if parsed <= 0 or parsed > maximum or parsed != value:
        raise ValueError(f"{field} must be between 1 and {maximum}")
    return parsed


def _bounded_positive_number(value: Any, *, field: str, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite positive number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0 or parsed > maximum:
        raise ValueError(f"{field} must be greater than zero and at most {maximum}")
    return parsed


def _validate_owner_token(value: str) -> str:
    if not isinstance(value, str) or not 16 <= len(value) <= 256:
        raise ValueError("owner token must contain between 16 and 256 characters")
    if any(character.isspace() for character in value):
        raise ValueError("owner token must not contain whitespace")
    return value


def _bounded_error_class(exc: BaseException) -> str:
    name = type(exc).__name__
    return name[:64] if name else "backend_error"


__all__ = [
    "LLM_CACHE_ENVELOPE_VERSION",
    "LLMCacheCodecError",
    "LLMCacheEnvelopeCodec",
    "LLMCacheReadiness",
    "RedisLLMCache",
    "decode_llm_cache_encryption_key",
    "validate_llm_cache_namespace",
]
