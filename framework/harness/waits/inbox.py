from __future__ import annotations

from dataclasses import replace
from threading import RLock

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.waits.models import (
    HarnessEarlySignalRetentionPolicy,
    HarnessSignalInboxEntry,
    HarnessSignalInboxEntryStatus,
    HarnessWaitRegistrationRecord,
    HarnessWaitScope,
    HarnessWaitSignal,
    HarnessWaitSignalMatch,
    validate_signal_authorization,
    validate_signal_for_registration,
)


class InMemoryHarnessSignalInbox:
    """Thread-safe contract adapter for tests and local composition.

    Production composition must back ``HarnessSignalInboxPort`` with durable
    storage. Retention is based only on durable sequence numbers so replay never
    depends on the current clock.
    """

    def __init__(
        self,
        policy: HarnessEarlySignalRetentionPolicy | None = None,
    ) -> None:
        self.policy = policy or HarnessEarlySignalRetentionPolicy()
        if not isinstance(self.policy, HarnessEarlySignalRetentionPolicy):
            raise TypeError("policy must be HarnessEarlySignalRetentionPolicy")
        self._entries: dict[tuple[str, str], HarnessSignalInboxEntry] = {}
        self._matches: dict[str, HarnessWaitSignalMatch] = {}
        self._high_watermark = 0
        self._lock = RLock()

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return sum(
                entry.status is HarnessSignalInboxEntryStatus.EARLY
                for entry in self._entries.values()
            )

    def put_signal(
        self,
        signal: HarnessWaitSignal,
        *,
        authorized_scope: HarnessWaitScope,
    ) -> HarnessSignalInboxEntry:
        validate_signal_authorization(signal, authorized_scope)
        key = _signal_key(signal)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                if (
                    existing.signal.idempotency_projection()
                    != signal.idempotency_projection()
                ):
                    raise HarnessValidationError(
                        "Wait signal identity was reused with conflicting content",
                        code="wait_signal_identity_conflict",
                        details={"signal_id": signal.signal_id},
                    )
                return existing

            self._prune_locked(through_sequence=signal.received_sequence)
            oldest_accepted = max(
                0,
                self._high_watermark - self.policy.sequence_window,
            )
            if signal.received_sequence <= oldest_accepted and self._high_watermark:
                raise HarnessValidationError(
                    "Wait signal is outside the bounded early-signal window",
                    code="early_signal_retention_expired",
                    details={
                        "received_sequence": signal.received_sequence,
                        "oldest_accepted_sequence": oldest_accepted + 1,
                    },
                )
            self._assert_capacity(signal.scope)
            entry = HarnessSignalInboxEntry(signal=signal)
            self._entries[key] = entry
            self._high_watermark = max(
                self._high_watermark,
                signal.received_sequence,
            )
            return entry

    def consume_matching(
        self,
        registration: HarnessWaitRegistrationRecord,
        *,
        matched_sequence: int,
    ) -> HarnessWaitSignalMatch | None:
        if not isinstance(registration, HarnessWaitRegistrationRecord):
            raise TypeError("registration must be HarnessWaitRegistrationRecord")
        if isinstance(matched_sequence, bool) or not isinstance(matched_sequence, int):
            raise HarnessValidationError(
                "matched_sequence must be a non-negative integer",
                code="invalid_wait_sequence",
            )
        if matched_sequence < registration.registered_sequence:
            raise HarnessValidationError(
                "signal match cannot precede Wait registration",
                code="wait_signal_sequence_regression",
            )
        registration_ref = registration.registration_ref
        with self._lock:
            existing_match = self._matches.get(registration_ref)
            if existing_match is not None:
                return existing_match
            candidates = tuple(
                entry
                for entry in self._entries.values()
                if entry.status is HarnessSignalInboxEntryStatus.EARLY
                and entry.signal.scope == registration.scope
            )
            if not candidates:
                return None
            selected = min(
                candidates,
                key=lambda entry: (
                    entry.signal.received_sequence,
                    entry.signal.signal_id,
                    entry.signal.signal_ref,
                ),
            )
            validate_signal_for_registration(registration, selected.signal)
            if matched_sequence < selected.signal.received_sequence:
                raise HarnessValidationError(
                    "signal match cannot precede signal receipt",
                    code="wait_signal_sequence_regression",
                )
            match = HarnessWaitSignalMatch(
                scope=registration.scope,
                registration_ref=registration_ref,
                signal_ref=selected.signal.signal_ref,
                matched_sequence=matched_sequence,
            )
            self._entries[_signal_key(selected.signal)] = replace(
                selected,
                status=HarnessSignalInboxEntryStatus.MATCHED,
                match=match,
            )
            self._matches[registration_ref] = match
            self._high_watermark = max(self._high_watermark, matched_sequence)
            return match

    def get_match(
        self,
        registration_ref: str,
        *,
        authorized_scope: HarnessWaitScope,
    ) -> HarnessWaitSignalMatch | None:
        if not isinstance(authorized_scope, HarnessWaitScope):
            raise TypeError("authorized_scope must be HarnessWaitScope")
        with self._lock:
            match = self._matches.get(str(registration_ref))
            if match is None:
                return None
            if match.scope != authorized_scope:
                raise HarnessValidationError(
                    "Wait signal match belongs to another authorized scope",
                    code="wait_signal_match_scope_mismatch",
                )
            return match

    def list_entries(
        self,
        *,
        authorized_scope: HarnessWaitScope,
    ) -> tuple[HarnessSignalInboxEntry, ...]:
        if not isinstance(authorized_scope, HarnessWaitScope):
            raise TypeError("authorized_scope must be HarnessWaitScope")
        with self._lock:
            return tuple(
                sorted(
                    (
                        entry
                        for entry in self._entries.values()
                        if entry.signal.scope == authorized_scope
                    ),
                    key=lambda entry: (
                        entry.signal.received_sequence,
                        entry.signal.signal_id,
                    ),
                )
            )

    def prune_early_signals(self, *, through_sequence: int) -> tuple[str, ...]:
        if isinstance(through_sequence, bool) or not isinstance(through_sequence, int):
            raise HarnessValidationError(
                "through_sequence must be a non-negative integer",
                code="invalid_wait_sequence",
            )
        if through_sequence < 0:
            raise HarnessValidationError(
                "through_sequence must be a non-negative integer",
                code="invalid_wait_sequence",
            )
        with self._lock:
            return self._prune_locked(through_sequence=through_sequence)

    def _prune_locked(self, *, through_sequence: int) -> tuple[str, ...]:
        self._high_watermark = max(self._high_watermark, through_sequence)
        cutoff = self._high_watermark - self.policy.sequence_window
        if cutoff < 0:
            return ()
        expired_keys = tuple(
            key
            for key, entry in self._entries.items()
            if entry.signal.received_sequence <= cutoff
        )
        expired_refs: list[str] = []
        for key in expired_keys:
            entry = self._entries.pop(key)
            expired_refs.append(entry.signal.signal_ref)
            if entry.match is not None:
                self._matches.pop(entry.match.registration_ref, None)
        return tuple(sorted(expired_refs))

    def _assert_capacity(self, scope: HarnessWaitScope) -> None:
        if len(self._entries) >= self.policy.max_signals:
            raise HarnessValidationError(
                "early-signal inbox reached its total retention bound",
                code="early_signal_retention_exhausted",
                details={"max_signals": self.policy.max_signals},
            )
        scope_count = sum(
            entry.signal.scope == scope for entry in self._entries.values()
        )
        if scope_count >= self.policy.max_signals_per_scope:
            raise HarnessValidationError(
                "early-signal inbox reached its per-scope retention bound",
                code="early_signal_scope_retention_exhausted",
                details={
                    "scope_ref": scope.scope_ref,
                    "max_signals_per_scope": self.policy.max_signals_per_scope,
                },
            )


def _signal_key(signal: HarnessWaitSignal) -> tuple[str, str]:
    # Signal ids are unique within one tenant. Reuse in another exact scope is a
    # conflict instead of creating an ambiguous second logical signal.
    return (signal.scope.tenant_scope_ref, signal.signal_id)


__all__ = ["InMemoryHarnessSignalInbox"]
