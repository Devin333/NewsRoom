import interfaces.cli.news as news_cli
import interfaces.api.server as api_server


def test_news_cli_api_serve_maps_arguments(monkeypatch) -> None:
    calls = []

    def fake_run_api_server(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(api_server, "run_api_server", fake_run_api_server)

    exit_code = news_cli.main(
        [
            "api",
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "8010",
            "--reload",
            "--log-level",
            "debug",
        ]
    )

    assert exit_code == 0
    assert calls == [
        {
            "host": "0.0.0.0",
            "port": 8010,
            "reload": True,
            "log_level": "debug",
        }
    ]


def test_news_cli_api_serve_reports_invalid_port(monkeypatch, capsys) -> None:
    def fake_run_api_server(**kwargs) -> None:
        raise ValueError("port must be between 1 and 65535")

    monkeypatch.setattr(api_server, "run_api_server", fake_run_api_server)

    exit_code = news_cli.main(["api", "serve", "--port", "0"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "port must be between 1 and 65535" in captured.out
