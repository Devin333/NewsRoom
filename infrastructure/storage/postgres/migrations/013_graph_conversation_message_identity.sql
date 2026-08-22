-- Graph-only conversation/message identity cutover.
-- Existing rows remain unvalidated and therefore fail closed in the live reader.
-- Operators must rewrite or quarantine them; this migration never guesses scope.

ALTER TABLE agent_conversations
    ADD COLUMN IF NOT EXISTS scope_kind TEXT,
    ADD COLUMN IF NOT EXISTS graph_version TEXT,
    ADD COLUMN IF NOT EXISTS graph_ref TEXT,
    ADD COLUMN IF NOT EXISTS graph_checksum TEXT;

ALTER TABLE agent_conversation_messages
    ADD COLUMN IF NOT EXISTS scope_kind TEXT,
    ADD COLUMN IF NOT EXISTS graph_id TEXT,
    ADD COLUMN IF NOT EXISTS graph_version TEXT,
    ADD COLUMN IF NOT EXISTS graph_ref TEXT,
    ADD COLUMN IF NOT EXISTS graph_checksum TEXT,
    ADD COLUMN IF NOT EXISTS node_id TEXT,
    ADD COLUMN IF NOT EXISTS node_instance_id TEXT,
    ADD COLUMN IF NOT EXISTS graph_checkpoint_ref TEXT,
    ADD COLUMN IF NOT EXISTS activity_id TEXT,
    ADD COLUMN IF NOT EXISTS attempt INTEGER;

ALTER TABLE agent_conversations
    DROP COLUMN IF EXISTS step_id;

ALTER TABLE agent_conversation_messages
    DROP COLUMN IF EXISTS step_id;

ALTER TABLE agent_conversations
    DROP CONSTRAINT IF EXISTS agent_conversations_live_scope_check;
ALTER TABLE agent_conversations
    ADD CONSTRAINT agent_conversations_live_scope_check CHECK (
        scope_kind IS NOT NULL
        AND (
            (
                scope_kind = 'standalone'
                AND run_id IS NULL
                AND graph_id IS NULL
                AND graph_version IS NULL
                AND graph_ref IS NULL
                AND graph_checksum IS NULL
            )
            OR
            (
                scope_kind = 'graph'
                AND run_id IS NOT NULL
                AND graph_id IS NOT NULL
                AND graph_version IS NOT NULL
                AND lower(graph_version) NOT IN ('current', 'default', 'latest', 'stable')
                AND graph_ref = graph_id || '@' || graph_version
                AND graph_checksum ~ '^sha256:[0-9a-f]{64}$'
            )
        )
    ) NOT VALID;

ALTER TABLE agent_conversation_messages
    DROP CONSTRAINT IF EXISTS agent_conversation_messages_live_scope_check;
ALTER TABLE agent_conversation_messages
    ADD CONSTRAINT agent_conversation_messages_live_scope_check CHECK (
        scope_kind IS NOT NULL
        AND (
            (
                scope_kind = 'standalone'
                AND run_id IS NULL
                AND graph_id IS NULL
                AND graph_version IS NULL
                AND graph_ref IS NULL
                AND graph_checksum IS NULL
                AND node_id IS NULL
                AND node_instance_id IS NULL
                AND graph_checkpoint_ref IS NULL
                AND activity_id IS NULL
                AND attempt IS NULL
            )
            OR
            (
                scope_kind = 'graph'
                AND run_id IS NOT NULL
                AND graph_id IS NOT NULL
                AND graph_version IS NOT NULL
                AND lower(graph_version) NOT IN ('current', 'default', 'latest', 'stable')
                AND graph_ref = graph_id || '@' || graph_version
                AND graph_checksum ~ '^sha256:[0-9a-f]{64}$'
                AND node_id IS NOT NULL
                AND node_instance_id IS NOT NULL
                AND graph_checkpoint_ref IS NOT NULL
                AND activity_id IS NOT NULL
                AND attempt > 0
            )
        )
    ) NOT VALID;

CREATE OR REPLACE FUNCTION enforce_agent_conversation_message_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    parent_scope_kind TEXT;
    parent_run_id TEXT;
    parent_graph_ref TEXT;
    parent_graph_checksum TEXT;
BEGIN
    SELECT scope_kind, run_id, graph_ref, graph_checksum
    INTO parent_scope_kind, parent_run_id, parent_graph_ref, parent_graph_checksum
    FROM agent_conversations
    WHERE conversation_id = NEW.conversation_id
    FOR SHARE;

    IF NOT FOUND
       OR NEW.scope_kind IS DISTINCT FROM parent_scope_kind
       OR NEW.run_id IS DISTINCT FROM parent_run_id
       OR NEW.graph_ref IS DISTINCT FROM parent_graph_ref
       OR NEW.graph_checksum IS DISTINCT FROM parent_graph_checksum THEN
        RAISE EXCEPTION 'conversation message Graph/standalone scope mismatch';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_conversation_message_scope
    ON agent_conversation_messages;
CREATE TRIGGER trg_agent_conversation_message_scope
BEFORE INSERT OR UPDATE OF
    conversation_id, scope_kind, run_id, graph_ref, graph_checksum
ON agent_conversation_messages
FOR EACH ROW
EXECUTE FUNCTION enforce_agent_conversation_message_scope();

CREATE OR REPLACE FUNCTION enforce_agent_conversation_message_identity_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.scope_kind IS DISTINCT FROM OLD.scope_kind
       OR NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.graph_id IS DISTINCT FROM OLD.graph_id
       OR NEW.graph_version IS DISTINCT FROM OLD.graph_version
       OR NEW.graph_ref IS DISTINCT FROM OLD.graph_ref
       OR NEW.graph_checksum IS DISTINCT FROM OLD.graph_checksum
       OR NEW.node_id IS DISTINCT FROM OLD.node_id
       OR NEW.node_instance_id IS DISTINCT FROM OLD.node_instance_id
       OR NEW.graph_checkpoint_ref IS DISTINCT FROM OLD.graph_checkpoint_ref
       OR NEW.activity_id IS DISTINCT FROM OLD.activity_id
       OR NEW.attempt IS DISTINCT FROM OLD.attempt THEN
        RAISE EXCEPTION 'conversation message execution identity is immutable';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_conversation_message_identity_immutable
    ON agent_conversation_messages;
CREATE TRIGGER trg_agent_conversation_message_identity_immutable
BEFORE UPDATE ON agent_conversation_messages
FOR EACH ROW
EXECUTE FUNCTION enforce_agent_conversation_message_identity_immutable();

CREATE OR REPLACE FUNCTION enforce_agent_conversation_scope_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.scope_kind IS DISTINCT FROM OLD.scope_kind
       OR NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.graph_id IS DISTINCT FROM OLD.graph_id
       OR NEW.graph_version IS DISTINCT FROM OLD.graph_version
       OR NEW.graph_ref IS DISTINCT FROM OLD.graph_ref
       OR NEW.graph_checksum IS DISTINCT FROM OLD.graph_checksum THEN
        RAISE EXCEPTION 'conversation Graph/standalone scope is immutable';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_conversation_scope_immutable
    ON agent_conversations;
CREATE TRIGGER trg_agent_conversation_scope_immutable
BEFORE UPDATE ON agent_conversations
FOR EACH ROW
EXECUTE FUNCTION enforce_agent_conversation_scope_immutable();

DROP INDEX IF EXISTS idx_agent_conversations_run;
CREATE INDEX IF NOT EXISTS idx_agent_conversations_graph
    ON agent_conversations(run_id, graph_ref, graph_checksum);

DROP INDEX IF EXISTS idx_agent_conversation_messages_run;
CREATE INDEX IF NOT EXISTS idx_agent_conversation_messages_graph_node
    ON agent_conversation_messages(
        run_id, graph_ref, graph_checksum, node_instance_id, activity_id, attempt
    );
