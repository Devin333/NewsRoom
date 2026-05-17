from __future__ import annotations

from newsroom_sdk.models import JsonDict
from newsroom_sdk.transport import HttpTransport, quote_path_segment


class MemoryResource:
    def __init__(self, transport: HttpTransport) -> None:
        self.transport = transport

    def search(
        self,
        query: str,
        *,
        collection: str = "report_sections",
        limit: int = 5,
        filters: JsonDict | None = None,
    ) -> JsonDict:
        return self.transport.request(
            "POST",
            "/api/v1/memory/search",
            json={
                "query": query,
                "collection": collection,
                "limit": limit,
                "filters": filters or {},
            },
        )

    def get(self, document_id: str, *, collection: str = "report_sections") -> JsonDict:
        return self.transport.request(
            "GET",
            f"/api/v1/memory/{quote_path_segment(document_id)}",
            params={"collection": collection},
        )
