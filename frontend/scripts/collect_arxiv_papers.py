#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ATOM = {"atom": "http://www.w3.org/2005/Atom"}
DEFAULT_QUERY = "cat:cs.AI OR cat:cs.CL OR cat:cs.CV OR cat:cs.LG OR cat:stat.ML"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "papers" / "arxiv-papers.json"
ARXIV_API = "https://export.arxiv.org/api/query"


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect real paper metadata from arXiv for the Papers module.")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sleep", type=float, default=3.0)
    args = parser.parse_args()

    papers: list[dict[str, Any]] = []
    seen: set[str] = set()

    for start in range(0, args.limit, args.batch_size):
        batch_size = min(args.batch_size, args.limit - start)
        feed = fetch_arxiv_feed(args.query, start, batch_size)
        entries = feed.findall("atom:entry", ATOM)
        if not entries:
            break

        for entry in entries:
            paper = entry_to_paper(entry)
            if not paper or paper["id"] in seen:
                continue
            seen.add(paper["id"])
            papers.append(paper)
            if len(papers) >= args.limit:
                break

        print(f"collected {len(papers)} papers", flush=True)
        if len(papers) >= args.limit or len(entries) < batch_size:
            break
        time.sleep(args.sleep)

    payload = {
        "source": "arxiv",
        "query": args.query,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(papers),
        "papers": papers,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(papers)} papers to {args.output}", flush=True)


def fetch_arxiv_feed(query: str, start: int, max_results: int) -> ET.Element:
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": start,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    request = urllib.request.Request(
        f"{ARXIV_API}?{params}",
        headers={"User-Agent": "AgoraHubResearch/0.1 (local paper collection)"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return ET.fromstring(response.read())


def entry_to_paper(entry: ET.Element) -> dict[str, Any] | None:
    paper_url = text(entry.find("atom:id", ATOM))
    title = normalize_space(text(entry.find("atom:title", ATOM)))
    summary = normalize_space(text(entry.find("atom:summary", ATOM)))
    published_at = text(entry.find("atom:published", ATOM))
    updated_at = text(entry.find("atom:updated", ATOM))
    arxiv_id = arxiv_id_from_url(paper_url)

    if not arxiv_id or not title or not summary:
        return None

    authors = [
        normalize_space(text(author.find("atom:name", ATOM)))
        for author in entry.findall("atom:author", ATOM)
    ]
    authors = [author for author in authors if author]
    categories = [
        category.attrib.get("term", "").strip()
        for category in entry.findall("atom:category", ATOM)
        if category.attrib.get("term", "").strip()
    ]

    pdf_url = pdf_url_from_entry(entry, arxiv_id)
    clean_arxiv_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)

    return {
        "id": f"arxiv-{clean_arxiv_id.replace('/', '-')}",
        "slug": slugify(f"{title}-{clean_arxiv_id}"),
        "title": title,
        "abstractSnippet": summary,
        "authors": authors or ["arXiv"],
        "publishedAt": published_at or updated_at or datetime.now(timezone.utc).isoformat(),
        "venue": "arXiv",
        "citationDoi": f"10.48550/arxiv.{clean_arxiv_id}",
        "tags": categories[:4],
        "taskRefs": [],
        "methodRefs": [],
        "paperUrl": paper_url,
        "arxivUrl": f"https://arxiv.org/abs/{arxiv_id}",
        "pdfUrl": pdf_url,
        "isPublished": True,
    }


def pdf_url_from_entry(entry: ET.Element, arxiv_id: str) -> str:
    for link in entry.findall("atom:link", ATOM):
        href = link.attrib.get("href", "")
        title = link.attrib.get("title", "")
        link_type = link.attrib.get("type", "")
        if href and (title == "pdf" or link_type == "application/pdf"):
            return href.replace("http://", "https://")
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def arxiv_id_from_url(value: str) -> str:
    match = re.search(r"arxiv\.org/abs/([^?#]+)", value)
    return match.group(1).strip("/") if match else ""


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:96] or "paper"


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def text(node: ET.Element | None) -> str:
    return node.text.strip() if node is not None and node.text else ""


if __name__ == "__main__":
    main()
