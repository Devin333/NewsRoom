from __future__ import annotations

import json
import os

from interfaces.sdk.python_client import NewsApiError, NewsClient


def main() -> None:
    client = NewsClient(
        os.getenv("NEWSROOM_API_BASE_URL", "http://localhost:8000"),
        api_key=os.getenv("NEWSROOM_API_TOKEN") or None,
    )
    try:
        result = client.research.analyze_paper(
            paper_id=os.getenv("NEWSROOM_RESEARCH_PAPER_ID", "arxiv:2501.00001"),
            source_url=os.getenv("NEWSROOM_RESEARCH_SOURCE_URL") or None,
            pdf_url=os.getenv("NEWSROOM_RESEARCH_PDF_URL") or None,
        )
    except NewsApiError as exc:
        raise SystemExit(f"{exc.code}: {exc.message} request_id={exc.request_id}") from exc

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
