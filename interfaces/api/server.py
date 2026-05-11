from __future__ import annotations


DEFAULT_API_APP = "interfaces.api:app"
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8000
DEFAULT_API_LOG_LEVEL = "info"


def run_api_server(
    *,
    host: str = DEFAULT_API_HOST,
    port: int = DEFAULT_API_PORT,
    reload: bool = False,
    log_level: str = DEFAULT_API_LOG_LEVEL,
    app: str = DEFAULT_API_APP,
) -> None:
    if port <= 0 or port > 65535:
        raise ValueError("port must be between 1 and 65535")

    import uvicorn

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )
