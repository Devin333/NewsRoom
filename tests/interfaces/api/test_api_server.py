import sys
from types import SimpleNamespace

import pytest

from interfaces.api.server import run_api_server


def test_run_api_server_invokes_uvicorn_with_canonical_app(monkeypatch) -> None:
    captured = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured["kwargs"] = kwargs

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    run_api_server(host="0.0.0.0", port=8010, reload=True, log_level="debug")

    assert captured == {
        "app": "interfaces.api:app",
        "kwargs": {
            "host": "0.0.0.0",
            "port": 8010,
            "reload": True,
            "log_level": "debug",
        },
    }


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_run_api_server_rejects_invalid_ports(port) -> None:
    with pytest.raises(ValueError, match="port must be between 1 and 65535"):
        run_api_server(port=port)
