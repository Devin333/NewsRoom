from core.framework.workflow import RedactionStatus, ScopedDataBuffer, StepDataScope


def test_api_key_is_redacted_by_default() -> None:
    buffer = ScopedDataBuffer()
    buffer.seed_request_key("api_key", "real-secret")

    snapshot = buffer.snapshot()

    assert snapshot["api_key"] == "***REDACTED***"


def test_token_is_redacted_by_default() -> None:
    buffer = ScopedDataBuffer({"session_token": "real-token"})

    assert buffer.snapshot()["session_token"] == "***REDACTED***"


def test_password_is_redacted_by_default() -> None:
    buffer = ScopedDataBuffer({"password": "real-password"})

    assert buffer.snapshot()["password"] == "***REDACTED***"


def test_plain_key_is_not_redacted() -> None:
    buffer = ScopedDataBuffer({"topic": "ai"})

    assert buffer.snapshot()["topic"] == "ai"


def test_unredacted_snapshot_can_show_raw_secret() -> None:
    buffer = ScopedDataBuffer({"api_key": "real-secret"})

    assert buffer.snapshot(redacted=False)["api_key"] == "real-secret"


def test_internal_read_still_returns_original_sensitive_value() -> None:
    buffer = ScopedDataBuffer({"api_key": "real-secret"})
    buffer.register_scope(StepDataScope(step_id="x", read_keys={"api_key"}))

    assert buffer.read(step_id="x", key="api_key") == "real-secret"


def test_write_history_records_sensitive_redaction_status() -> None:
    buffer = ScopedDataBuffer()
    buffer.register_scope(StepDataScope(step_id="secrets", write_keys={"api_key"}))

    buffer.write(step_id="secrets", key="api_key", value="real-secret")

    history = buffer.write_history("api_key")
    assert history[-1].redaction_status == RedactionStatus.SENSITIVE
