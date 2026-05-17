from __future__ import annotations

from newsroom_sdk.models import JsonDict
from newsroom_sdk.transport import HttpTransport, quote_path_segment


class SourcesResource:
    def __init__(self, transport: HttpTransport) -> None:
        self.transport = transport

    def health(self, include_disabled: bool = False) -> JsonDict:
        return self.transport.request(
            "GET",
            "/api/v1/sources/health",
            params={"include_disabled": include_disabled},
        )

    def list(self, include_disabled: bool = False) -> JsonDict:
        return self.transport.request(
            "GET",
            "/api/v1/sources",
            params={"include_disabled": include_disabled},
        )

    def get(self, source_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v1/sources/{quote_path_segment(source_id)}")

    def probe(
        self,
        source_id: str,
        *,
        force: bool = False,
        include_disabled: bool = False,
        limit: int = 1,
    ) -> JsonDict:
        return self.transport.request(
            "POST",
            f"/api/v1/sources/{quote_path_segment(source_id)}/probe",
            json={
                "force": force,
                "include_disabled": include_disabled,
                "limit": limit,
            },
        )
