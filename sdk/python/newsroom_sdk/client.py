from __future__ import annotations

from newsroom_sdk.config import NewsRoomConfig
from newsroom_sdk.resources.approvals import ApprovalsResource
from newsroom_sdk.resources.mcp import MCPResource
from newsroom_sdk.resources.memory import MemoryResource
from newsroom_sdk.resources.reports import ReportsResource
from newsroom_sdk.resources.runs import RunsResource
from newsroom_sdk.resources.sources import SourcesResource
from newsroom_sdk.resources.workers import WorkersResource
from newsroom_sdk.transport import HttpTransport, RequestFunc


class NewsRoomClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float | None = 30,
        transport: HttpTransport | None = None,
        request_func: RequestFunc | None = None,
    ) -> None:
        config = NewsRoomConfig(base_url=base_url, api_key=api_key, timeout=timeout)
        self.transport = transport or HttpTransport(config, request_func=request_func)
        self.runs = RunsResource(self.transport)
        self.reports = ReportsResource(self.transport)
        self.memory = MemoryResource(self.transport)
        self.sources = SourcesResource(self.transport)
        self.workers = WorkersResource(self.transport)
        self.approvals = ApprovalsResource(self.transport)
        self.mcp = MCPResource(self.transport)
