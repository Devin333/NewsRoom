from __future__ import annotations

import json
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any, Callable

import psycopg

from infrastructure.storage.postgres.dsn import normalize_dsn
from framework.shared.graph_identity import GraphRunIdentity

from infrastructure.storage.conversation.models import (
    AgentIterationCheckpoint,
    AgentMessageRecord,
    CONVERSATION_SCOPE_GRAPH,
    ConversationCompactionRecord,
    ConversationCursor,
    CONVERSATION_SCOPE_STANDALONE,
    message_scope_key,
)
from infrastructure.storage.security import StorageRedactor


ConnectionFactory = Callable[[], Any]


class PostgresConversationStore:
    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: ConnectionFactory | None = None,
        redactor: StorageRedactor | None = None,
    ) -> None:
        self.dsn = dsn
        self._connection_factory = connection_factory or (lambda: psycopg.connect(normalize_dsn(dsn)))
        self.redactor = redactor or StorageRedactor()

    def append_message(self, conversation_id: str, message: AgentMessageRecord) -> None:
        _validate_id(conversation_id, "conversation_id")
        _validate_id(message.message_id, "message_id")
        if message.conversation_id != conversation_id:
            raise ValueError("message conversation_id does not match")
        safe_message = self._redacted_message(message)
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _upsert_conversation(cursor, conversation_id, safe_message)
                cursor.execute(
                    """
                    WITH next_offset AS (
                        SELECT COALESCE(MAX(message_offset) + 1, 0) AS value
                        FROM agent_conversation_messages
                        WHERE conversation_id = %s
                    )
                    INSERT INTO agent_conversation_messages (
                        conversation_id, message_id, message_offset, role, content,
                        created_at, scope_kind, agent_id, run_id, graph_id, graph_version,
                        graph_ref, graph_checksum, node_id, node_instance_id,
                        graph_checkpoint_ref, activity_id, attempt, redacted, metadata_json
                    )
                    SELECT
                        %s, %s, next_offset.value, %s, %s::jsonb,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                    FROM next_offset
                    ON CONFLICT (conversation_id, message_id) DO UPDATE SET
                        role = EXCLUDED.role,
                        content = EXCLUDED.content,
                        created_at = EXCLUDED.created_at,
                        scope_kind = EXCLUDED.scope_kind,
                        agent_id = EXCLUDED.agent_id,
                        run_id = EXCLUDED.run_id,
                        graph_id = EXCLUDED.graph_id,
                        graph_version = EXCLUDED.graph_version,
                        graph_ref = EXCLUDED.graph_ref,
                        graph_checksum = EXCLUDED.graph_checksum,
                        node_id = EXCLUDED.node_id,
                        node_instance_id = EXCLUDED.node_instance_id,
                        graph_checkpoint_ref = EXCLUDED.graph_checkpoint_ref,
                        activity_id = EXCLUDED.activity_id,
                        attempt = EXCLUDED.attempt,
                        redacted = EXCLUDED.redacted,
                        metadata_json = EXCLUDED.metadata_json,
                        indexed_at = now()
                    """,
                    (
                        conversation_id,
                        conversation_id,
                        safe_message.message_id,
                        safe_message.role,
                        _json_value(safe_message.content),
                        safe_message.created_at,
                        safe_message.scope_kind,
                        safe_message.agent_id,
                        safe_message.run_id,
                        safe_message.graph_id,
                        safe_message.graph_version,
                        safe_message.graph_ref,
                        safe_message.graph_checksum,
                        safe_message.node_id,
                        safe_message.node_instance_id,
                        safe_message.graph_checkpoint_ref,
                        safe_message.activity_id,
                        safe_message.attempt,
                        safe_message.redacted,
                        _json_object(safe_message.metadata),
                    ),
                )
                cursor.execute(
                    """
                    UPDATE agent_conversations
                    SET message_count = (
                            SELECT COUNT(*)
                            FROM agent_conversation_messages
                            WHERE conversation_id = %s
                        ),
                        updated_at = now()
                    WHERE conversation_id = %s
                    """,
                    (conversation_id, conversation_id),
                )
            connection.commit()

    def read_messages(self, conversation_id: str, limit: int | None = None) -> list[AgentMessageRecord]:
        _validate_id(conversation_id, "conversation_id")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        sql = """
            SELECT
                message_id, conversation_id, role, content, created_at, scope_kind, agent_id,
                run_id, graph_id, graph_version, graph_ref, graph_checksum,
                node_id, node_instance_id, graph_checkpoint_ref, activity_id,
                attempt, redacted, metadata_json
            FROM agent_conversation_messages
            WHERE conversation_id = %s
            ORDER BY message_offset ASC
        """
        params: tuple[Any, ...] = (conversation_id,)
        if limit is not None:
            sql = """
                SELECT
                    message_id, conversation_id, role, content, created_at, scope_kind, agent_id,
                    run_id, graph_id, graph_version, graph_ref, graph_checksum,
                    node_id, node_instance_id, graph_checkpoint_ref, activity_id,
                    attempt, redacted, metadata_json
                FROM (
                    SELECT
                        message_offset, message_id, conversation_id, role, content,
                        created_at, scope_kind, agent_id, run_id, graph_id, graph_version, graph_ref,
                        graph_checksum, node_id, node_instance_id, graph_checkpoint_ref,
                        activity_id, attempt, redacted, metadata_json
                    FROM agent_conversation_messages
                    WHERE conversation_id = %s
                    ORDER BY message_offset DESC
                    LIMIT %s
                ) limited_messages
                ORDER BY message_offset ASC
            """
            params = (conversation_id, limit)
        messages = [_message_from_row(row) for row in self._fetch_all(sql, params)]
        _assert_consistent_message_scope(messages)
        return messages

    def write_summary(self, conversation_id: str, summary: str) -> None:
        _validate_id(conversation_id, "conversation_id")
        redaction = self.redactor.redact(
            summary,
            run_id=conversation_id,
            artifact_id="conversation_summary",
        )
        metadata: dict[str, Any] = {}
        if redaction.redacted:
            metadata["redaction_report"] = redaction.report.to_dict()
        self._upsert_state(
            conversation_id,
            set_clause=(
                "summary = EXCLUDED.summary, "
                "summary_updated_at = EXCLUDED.summary_updated_at, "
                "metadata_json = agent_conversation_state.metadata_json || EXCLUDED.metadata_json"
            ),
            insert_columns="summary, summary_updated_at, metadata_json",
            insert_values="%s, %s, %s::jsonb",
            params=(str(redaction.value), datetime.now(UTC), _json_object(metadata)),
        )

    def get_summary(self, conversation_id: str) -> str | None:
        _validate_id(conversation_id, "conversation_id")
        row = self._fetch_one(
            "SELECT summary FROM agent_conversation_state WHERE conversation_id = %s",
            (conversation_id,),
        )
        if row is None or row[0] is None:
            return None
        return str(row[0])

    def compact_messages(
        self,
        conversation_id: str,
        *,
        keep_last: int = 10,
        max_summary_chars: int = 2000,
    ) -> ConversationCompactionRecord | None:
        _validate_id(conversation_id, "conversation_id")
        if keep_last < 0:
            raise ValueError("keep_last must be non-negative")
        if max_summary_chars <= 0:
            raise ValueError("max_summary_chars must be greater than zero")
        messages = self.read_messages(conversation_id)
        if len(messages) <= keep_last:
            return None
        compacted = messages[:-keep_last] if keep_last else messages
        retained = messages[-keep_last:] if keep_last else []
        summary = _build_compaction_summary(
            compacted,
            retained_count=len(retained),
            max_summary_chars=max_summary_chars,
        )
        redaction = self.redactor.redact(
            summary,
            run_id=conversation_id,
            artifact_id="conversation_compaction",
        )
        metadata: dict[str, Any] = {
            "retained_message_ids": [message.message_id for message in retained],
            "role_counts": _role_counts(messages),
        }
        if redaction.redacted:
            metadata["redaction_report"] = redaction.report.to_dict()
        marker_message = AgentMessageRecord(
            message_id=_compaction_marker_message_id(compacted[-1].message_id if compacted else "none"),
            conversation_id=conversation_id,
            role="system",
            content={
                "summary": str(redaction.value),
                "compacted_message_count": len(compacted),
                "retained_message_count": len(retained),
                "compacted_until_message_id": compacted[-1].message_id if compacted else None,
            },
            created_at=datetime.now(UTC),
            scope_kind=_compaction_scope(messages),
            run_id=_compaction_identity(messages, "run_id"),
            graph_id=_compaction_identity(messages, "graph_id"),
            graph_version=_compaction_identity(messages, "graph_version"),
            graph_ref=_compaction_identity(messages, "graph_ref"),
            graph_checksum=_compaction_identity(messages, "graph_checksum"),
            node_id=_compaction_identity(messages, "node_id"),
            node_instance_id=_compaction_identity(messages, "node_instance_id"),
            graph_checkpoint_ref=_compaction_identity(messages, "graph_checkpoint_ref"),
            activity_id=_compaction_identity(messages, "activity_id"),
            attempt=_compaction_identity(messages, "attempt"),
            redacted=True,
            metadata={
                "message_type": "conversation_compaction",
                "compacted_until_message_id": compacted[-1].message_id if compacted else None,
                "retained_message_ids": [message.message_id for message in retained],
            },
        )
        record = ConversationCompactionRecord(
            conversation_id=conversation_id,
            summary=str(redaction.value),
            original_message_count=len(messages),
            compacted_message_count=len(compacted),
            retained_message_count=len(retained),
            marker_message_id=marker_message.message_id,
            compacted_until_message_id=compacted[-1].message_id if compacted else None,
            metadata=metadata,
        )
        self._replace_messages(conversation_id, [marker_message, *retained])
        self._write_state_json(conversation_id, "compaction_json", record.to_dict())
        self.write_summary(conversation_id, record.summary)
        return record

    def get_compaction(self, conversation_id: str) -> ConversationCompactionRecord | None:
        payload = self._read_state_json(conversation_id, "compaction_json")
        if not payload:
            return None
        return ConversationCompactionRecord.from_dict(payload)

    def write_cursor(self, cursor: ConversationCursor) -> None:
        _validate_id(cursor.conversation_id, "conversation_id")
        _validate_optional_id(cursor.message_id, "message_id")
        _validate_optional_id(cursor.run_id, "run_id")
        _validate_optional_id(cursor.node_instance_id, "node_instance_id")
        _validate_optional_reference(
            cursor.graph_checkpoint_ref,
            "graph_checkpoint_ref",
        )
        metadata_redaction = self.redactor.redact(
            cursor.metadata,
            run_id=cursor.conversation_id,
            artifact_id="conversation_cursor",
        )
        metadata = dict(metadata_redaction.value)
        if metadata_redaction.redacted:
            metadata["redaction_report"] = metadata_redaction.report.to_dict()
        safe_cursor = ConversationCursor(
            conversation_id=cursor.conversation_id,
            message_offset=cursor.message_offset,
            message_id=cursor.message_id,
            run_id=cursor.run_id,
            node_instance_id=cursor.node_instance_id,
            graph_checkpoint_ref=cursor.graph_checkpoint_ref,
            updated_at=cursor.updated_at,
            metadata=metadata,
            schema_version=cursor.schema_version,
        )
        self._write_state_json(
            cursor.conversation_id,
            "cursor_json",
            safe_cursor.to_dict(),
            scope_kind=_state_scope_kind(safe_cursor.run_id),
            run_id=safe_cursor.run_id,
        )

    def read_cursor(self, conversation_id: str) -> ConversationCursor | None:
        payload = self._read_state_json(conversation_id, "cursor_json")
        if not payload:
            return None
        return ConversationCursor.from_dict(payload)

    def write_iteration_checkpoint(self, checkpoint: AgentIterationCheckpoint) -> None:
        _validate_id(checkpoint.conversation_id, "conversation_id")
        _validate_id(checkpoint.agent_id, "agent_id")
        _validate_optional_id(checkpoint.run_id, "run_id")
        _validate_optional_id(checkpoint.node_instance_id, "node_instance_id")
        _validate_optional_reference(
            checkpoint.graph_checkpoint_ref,
            "graph_checkpoint_ref",
        )
        _validate_optional_id(checkpoint.message_id, "message_id")
        metadata_redaction = self.redactor.redact(
            checkpoint.metadata,
            run_id=checkpoint.conversation_id,
            artifact_id="agent_iteration_checkpoint_metadata",
        )
        diagnostics_redaction = self.redactor.redact(
            checkpoint.diagnostics_summary,
            run_id=checkpoint.conversation_id,
            artifact_id="agent_iteration_checkpoint_diagnostics",
        )
        metadata = dict(metadata_redaction.value)
        diagnostics_summary = dict(diagnostics_redaction.value)
        reports = []
        if metadata_redaction.redacted:
            reports.append(metadata_redaction.report.to_dict())
        if diagnostics_redaction.redacted:
            reports.append(diagnostics_redaction.report.to_dict())
        if reports:
            metadata["redaction_reports"] = reports
        safe_checkpoint = AgentIterationCheckpoint(
            conversation_id=checkpoint.conversation_id,
            agent_id=checkpoint.agent_id,
            iteration=checkpoint.iteration,
            status=checkpoint.status,
            stop_reason=checkpoint.stop_reason,
            run_id=checkpoint.run_id,
            node_instance_id=checkpoint.node_instance_id,
            graph_checkpoint_ref=checkpoint.graph_checkpoint_ref,
            message_id=checkpoint.message_id,
            trace_summary=dict(checkpoint.trace_summary),
            diagnostics_summary=diagnostics_summary,
            last_tool_observation=(
                dict(checkpoint.last_tool_observation)
                if checkpoint.last_tool_observation is not None
                else None
            ),
            llm_call_artifact_ids=list(checkpoint.llm_call_artifact_ids),
            updated_at=checkpoint.updated_at,
            metadata=metadata,
            schema_version=checkpoint.schema_version,
        )
        self._write_state_json(
            checkpoint.conversation_id,
            "iteration_checkpoint_json",
            safe_checkpoint.to_dict(),
            scope_kind=_state_scope_kind(safe_checkpoint.run_id),
            run_id=safe_checkpoint.run_id,
        )

    def read_iteration_checkpoint(self, conversation_id: str) -> AgentIterationCheckpoint | None:
        payload = self._read_state_json(conversation_id, "iteration_checkpoint_json")
        if not payload:
            return None
        return AgentIterationCheckpoint.from_dict(payload)

    def _replace_messages(self, conversation_id: str, messages: list[AgentMessageRecord]) -> None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM agent_conversation_messages WHERE conversation_id = %s",
                    (conversation_id,),
                )
            connection.commit()
        for message in messages:
            self.append_message(conversation_id, message)

    def _read_state_json(self, conversation_id: str, column: str) -> dict[str, Any] | None:
        _validate_id(conversation_id, "conversation_id")
        _validate_state_column(column)
        row = self._fetch_one(
            f"SELECT {column} FROM agent_conversation_state WHERE conversation_id = %s",
            (conversation_id,),
        )
        if row is None:
            return None
        return _dict_or_none(row[0])

    def _write_state_json(
        self,
        conversation_id: str,
        column: str,
        payload: dict[str, Any],
        *,
        scope_kind: str | None = None,
        run_id: str | None = None,
    ) -> None:
        _validate_id(conversation_id, "conversation_id")
        _validate_state_column(column)
        self._upsert_state(
            conversation_id,
            set_clause=f"{column} = EXCLUDED.{column}",
            insert_columns=column,
            insert_values="%s::jsonb",
            params=(_json_object(payload),),
            scope_kind=scope_kind,
            run_id=run_id,
        )

    def _upsert_state(
        self,
        conversation_id: str,
        *,
        set_clause: str,
        insert_columns: str,
        insert_values: str,
        params: tuple[Any, ...],
        scope_kind: str | None = None,
        run_id: str | None = None,
    ) -> None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _upsert_conversation(
                    cursor,
                    conversation_id,
                    None,
                    state_scope_kind=scope_kind,
                    state_run_id=run_id,
                )
                _cursor_execute(
                    cursor,
                    f"""
                    INSERT INTO agent_conversation_state (
                        conversation_id, {insert_columns}
                    )
                    VALUES (%s, {insert_values})
                    ON CONFLICT (conversation_id) DO UPDATE SET
                        {set_clause},
                        updated_at = now()
                    """,
                    (conversation_id, *params),
                )
            connection.commit()

    def _redacted_message(self, message: AgentMessageRecord) -> AgentMessageRecord:
        content_redaction = self.redactor.redact(
            message.content,
            run_id=message.conversation_id,
            artifact_id=message.message_id,
        )
        metadata_redaction = self.redactor.redact(
            message.metadata,
            run_id=message.conversation_id,
            artifact_id=message.message_id,
        )
        metadata = dict(metadata_redaction.value)
        reports = []
        if content_redaction.redacted:
            reports.append(content_redaction.report.to_dict())
        if metadata_redaction.redacted:
            reports.append(metadata_redaction.report.to_dict())
        if reports:
            metadata["redaction_reports"] = reports
        return AgentMessageRecord(
            message_id=message.message_id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=content_redaction.value,
            created_at=message.created_at,
            agent_id=message.agent_id,
            run_id=message.run_id,
            graph_id=message.graph_id,
            graph_version=message.graph_version,
            graph_ref=message.graph_ref,
            graph_checksum=message.graph_checksum,
            node_id=message.node_id,
            node_instance_id=message.node_instance_id,
            graph_checkpoint_ref=message.graph_checkpoint_ref,
            activity_id=message.activity_id,
            attempt=message.attempt,
            scope_kind=message.scope_kind,
            redacted=True,
            metadata=metadata,
        )

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(cursor, sql, params)
                return cursor.fetchone()

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(cursor, sql, params)
                return list(cursor.fetchall())


def _upsert_conversation(
    cursor: Any,
    conversation_id: str,
    message: AgentMessageRecord | None,
    *,
    state_scope_kind: str | None = None,
    state_run_id: str | None = None,
) -> None:
    _validate_state_scope(state_scope_kind, state_run_id)
    scope_kind = (
        message.scope_kind if message is not None else CONVERSATION_SCOPE_STANDALONE
    )
    run_id = message.run_id if message is not None else None
    graph_id = message.graph_id if message is not None else None
    graph_version = message.graph_version if message is not None else None
    graph_ref = message.graph_ref if message is not None else None
    graph_checksum = message.graph_checksum if message is not None else None
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (conversation_id,),
    )
    cursor.execute(
        """
        SELECT scope_kind, run_id, graph_id, graph_version, graph_ref, graph_checksum
        FROM agent_conversations
        WHERE conversation_id = %s
        FOR UPDATE
        """,
        (conversation_id,),
    )
    existing = cursor.fetchone()
    if existing is not None:
        actual_scope = _parent_scope_key(existing)
        expected_scope = (
            message_scope_key(message)
            if message is not None
            else _state_scope_key(
                actual_scope,
                state_scope_kind=state_scope_kind,
                state_run_id=state_run_id,
            )
        )
        if actual_scope != expected_scope:
            raise ValueError("conversation Graph/standalone scope does not match")
        cursor.execute(
            """
            UPDATE agent_conversations
            SET agent_id = COALESCE(%s, agent_id),
                payload = payload || %s::jsonb,
                updated_at = now()
            WHERE conversation_id = %s
            """,
            (
                message.agent_id if message is not None else None,
                _json_object({"conversation_id": conversation_id}),
                conversation_id,
            ),
        )
        return
    if state_scope_kind == CONVERSATION_SCOPE_GRAPH:
        raise ValueError(
            "Graph conversation state requires an existing exact Graph parent"
        )
    cursor.execute(
        """
        INSERT INTO agent_conversations (
            conversation_id, scope_kind, run_id, graph_id, graph_version, graph_ref,
            graph_checksum, agent_id, message_count, payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s::jsonb)
        """,
        (
            conversation_id,
            scope_kind,
            run_id,
            graph_id,
            graph_version,
            graph_ref,
            graph_checksum,
            message.agent_id if message is not None else None,
            _json_object({"conversation_id": conversation_id}),
        ),
    )


def _cursor_execute(cursor: Any, sql: str, params: tuple[Any, ...]) -> Any:
    return cursor.execute(sql, params)


def _message_from_row(row: tuple[Any, ...]) -> AgentMessageRecord:
    return AgentMessageRecord(
        message_id=str(row[0]),
        conversation_id=str(row[1]),
        role=str(row[2]),
        content=_json_loaded(row[3]),
        created_at=_timestamp(row[4]),
        scope_kind=str(row[5]),
        agent_id=_optional_str(row[6]),
        run_id=_optional_str(row[7]),
        graph_id=_optional_str(row[8]),
        graph_version=_optional_str(row[9]),
        graph_ref=_optional_str(row[10]),
        graph_checksum=_optional_str(row[11]),
        node_id=_optional_str(row[12]),
        node_instance_id=_optional_str(row[13]),
        graph_checkpoint_ref=_optional_str(row[14]),
        activity_id=_optional_str(row[15]),
        attempt=_optional_int(row[16]),
        redacted=bool(row[17]),
        metadata=_dict_or_empty(row[18]),
    )


def _assert_consistent_message_scope(messages: list[AgentMessageRecord]) -> None:
    if len({message_scope_key(message) for message in messages}) > 1:
        raise ValueError("conversation messages have mixed Graph/standalone scope")


def _state_scope_kind(run_id: str | None) -> str:
    return (
        CONVERSATION_SCOPE_GRAPH
        if run_id is not None
        else CONVERSATION_SCOPE_STANDALONE
    )


def _validate_state_scope(
    scope_kind: str | None,
    run_id: str | None,
) -> None:
    if scope_kind is None:
        if run_id is not None:
            raise ValueError("state run_id requires an explicit Graph scope")
        return
    if scope_kind == CONVERSATION_SCOPE_GRAPH:
        if run_id is None:
            raise ValueError("Graph conversation state requires run_id")
        return
    if scope_kind == CONVERSATION_SCOPE_STANDALONE:
        if run_id is not None:
            raise ValueError("standalone conversation state cannot carry run_id")
        return
    raise ValueError("state scope_kind must be 'graph' or 'standalone'")


def _parent_scope_key(row: tuple[Any, ...]) -> tuple[str, ...]:
    if len(row) != 6:
        raise ValueError("conversation parent has an invalid live scope row")
    scope_kind, run_id, graph_id, graph_version, graph_ref, graph_checksum = row
    if scope_kind == CONVERSATION_SCOPE_STANDALONE:
        if any(
            value is not None
            for value in (run_id, graph_id, graph_version, graph_ref, graph_checksum)
        ):
            raise ValueError("standalone conversation parent carries Graph identity")
        return (CONVERSATION_SCOPE_STANDALONE,)
    if scope_kind != CONVERSATION_SCOPE_GRAPH:
        raise ValueError("conversation parent has no live Graph/standalone scope")
    identity = GraphRunIdentity(
        run_id=run_id,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_ref=graph_ref,
        graph_checksum=graph_checksum,
    )
    return (
        CONVERSATION_SCOPE_GRAPH,
        identity.run_id,
        identity.graph_ref,
        identity.graph_checksum,
    )


def _state_scope_key(
    actual_scope: tuple[str, ...],
    *,
    state_scope_kind: str | None,
    state_run_id: str | None,
) -> tuple[str, ...]:
    if state_scope_kind is None:
        return actual_scope
    if state_scope_kind == CONVERSATION_SCOPE_STANDALONE:
        return (CONVERSATION_SCOPE_STANDALONE,)
    if actual_scope[0] != CONVERSATION_SCOPE_GRAPH:
        return (CONVERSATION_SCOPE_GRAPH, str(state_run_id), "", "")
    if actual_scope[1] != state_run_id:
        return (
            CONVERSATION_SCOPE_GRAPH,
            str(state_run_id),
            actual_scope[2],
            actual_scope[3],
        )
    return actual_scope


def _compaction_scope(messages: list[AgentMessageRecord]) -> str:
    if not messages:
        return CONVERSATION_SCOPE_STANDALONE
    return messages[-1].scope_kind


def _compaction_identity(
    messages: list[AgentMessageRecord],
    field_name: str,
) -> Any:
    if not messages:
        return None
    return getattr(messages[-1], field_name)


def _json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_object(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _json_loaded(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else None
    return dict(value)


def _dict_or_empty(value: Any) -> dict[str, Any]:
    parsed = _dict_or_none(value)
    return parsed if parsed is not None else {}


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("attempt must be an integer")
    return value


def _validate_id(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid {label}: {value}")


def _validate_optional_id(value: str | None, label: str) -> None:
    if value is None:
        return
    _validate_id(value, label)


def _validate_optional_reference(value: str | None, label: str) -> None:
    if value is None:
        return
    if (
        not value
        or value.strip() != value
        or len(value) > 2048
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"invalid {label}: {value}")


def _validate_state_column(column: str) -> None:
    if column not in {"cursor_json", "compaction_json", "iteration_checkpoint_json"}:
        raise ValueError(f"invalid conversation state column: {column}")


def _build_compaction_summary(
    messages: list[AgentMessageRecord],
    *,
    retained_count: int,
    max_summary_chars: int,
) -> str:
    role_counts = _role_counts(messages)
    lines = [
        (
            "Compacted "
            f"{len(messages)} older conversation messages; "
            f"retained last {retained_count} messages."
        ),
        "Role counts: "
        + ", ".join(f"{role}={count}" for role, count in sorted(role_counts.items())),
    ]
    important = [
        message
        for message in messages
        if message.role in {"user", "judge", "diagnostic", "assistant"}
    ][-8:]
    if important:
        lines.append("Recent compacted highlights:")
        for message in important:
            lines.append(f"- {message.role}: {_preview(message.content, max_chars=180)}")
    summary = "\n".join(lines)
    if len(summary) <= max_summary_chars:
        return summary
    return summary[: max_summary_chars - 3].rstrip() + "..."


def _role_counts(messages: list[AgentMessageRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for message in messages:
        counts[message.role] = counts.get(message.role, 0) + 1
    return counts


def _preview(value: Any, *, max_chars: int) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _compaction_marker_message_id(compacted_until_message_id: str) -> str:
    safe_id = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in compacted_until_message_id
    ).strip("._-")
    return f"compaction-{safe_id or 'messages'}"
