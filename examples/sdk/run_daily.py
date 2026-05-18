from __future__ import annotations

import json
import os

from newsroom_sdk import NewsRoomClient


def main() -> None:
    client = NewsRoomClient(
        os.getenv("NEWSROOM_API_BASE_URL", "http://localhost:8000"),
        api_key=os.getenv("NEWSROOM_API_TOKEN") or None,
    )
    run = client.runs.create_daily(
        topic="AI",
        profile="live-offline",
        source_limit=3,
    )
    print(json.dumps(run, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
