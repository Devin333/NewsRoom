from __future__ import annotations

import os

from newsroom_sdk import NewsRoomAPIError, NewsRoomClient


def main() -> None:
    client = NewsRoomClient(
        os.getenv("NEWSROOM_API_BASE_URL", "http://localhost:8000"),
        api_key=os.getenv("NEWSROOM_API_TOKEN") or None,
    )
    try:
        report = client.reports.latest()
    except NewsRoomAPIError as exc:
        raise SystemExit(f"{exc.code}: {exc.message} request_id={exc.request_id}") from exc

    print(report.get("report_markdown") or report.get("title") or report)


if __name__ == "__main__":
    main()
