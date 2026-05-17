from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


API_BASE_URL = os.getenv("NEWSROOM_API_BASE_URL", "http://localhost:8000").rstrip("/")
API_TOKEN = os.getenv("NEWSROOM_API_TOKEN")


def main() -> None:
    query = urllib.parse.urlencode({"limit": 10})
    request = urllib.request.Request(
        f"{API_BASE_URL}/api/v1/reports?{query}",
        method="GET",
        headers=_headers(),
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        envelope = json.loads(response.read().decode("utf-8"))
    if not envelope["success"]:
        raise SystemExit(envelope["error"])
    print(json.dumps(envelope["data"], indent=2, sort_keys=True))


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    return headers


if __name__ == "__main__":
    main()
