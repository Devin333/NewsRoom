#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "data" / "papers" / "arxiv-papers.json"
GITHUB_REPO_PATTERN = re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
OPENALEX_WORKS_API = "https://api.openalex.org/works"
GITHUB_REPO_API = "https://api.github.com/repos"


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich cached Papers module data with real public metrics.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--openalex-batch-size", type=int, default=50)
    parser.add_argument("--github-sleep", type=float, default=0.35)
    args = parser.parse_args()

    path = args.input
    payload = json.loads(path.read_text(encoding="utf-8"))
    papers = payload.get("papers") if isinstance(payload, dict) else None
    if not isinstance(papers, list):
      raise SystemExit(f"invalid papers cache: {path}")

    selected = papers[: args.limit] if args.limit else papers
    extract_repo_urls(selected)
    enrich_openalex_citations(selected, batch_size=args.openalex_batch_size)
    enrich_github_stars(selected, sleep_seconds=args.github_sleep)

    output = args.output or path
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote enriched metrics for {len(selected)} papers to {output}", flush=True)


def extract_repo_urls(papers: list[dict[str, Any]]) -> None:
    count = 0
    for paper in papers:
        if paper.get("repoUrl"):
            continue
        repo_url = github_repo_url_from_text(str(paper.get("abstractSnippet") or ""))
        if repo_url:
            paper["repoUrl"] = repo_url
            count += 1
    print(f"repo urls extracted: {count}", flush=True)


def enrich_openalex_citations(papers: list[dict[str, Any]], *, batch_size: int) -> None:
    candidates = [paper for paper in papers if paper.get("citationDoi")]
    updated = 0
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start : start + batch_size]
        doi_to_paper = {normalize_doi(str(paper["citationDoi"])): paper for paper in batch}
        filter_value = "doi:" + "|".join(doi_to_paper)
        url = f"{OPENALEX_WORKS_API}?filter={urllib.parse.quote(filter_value)}&per-page={len(batch)}"
        data = fetch_json(url, headers={"User-Agent": "NewsRoomResearch/0.1 (paper metrics)"})
        for item in data.get("results", []):
            doi = normalize_doi(str(item.get("doi") or ""))
            paper = doi_to_paper.get(doi)
            cited_by_count = item.get("cited_by_count")
            if paper is not None and isinstance(cited_by_count, int):
                paper["citationCount"] = cited_by_count
                updated += 1
        print(f"openalex citations: {min(start + batch_size, len(candidates))}/{len(candidates)}", flush=True)
    print(f"citation counts updated: {updated}", flush=True)


def enrich_github_stars(papers: list[dict[str, Any]], *, sleep_seconds: float) -> None:
    repos: dict[str, str] = {}
    for paper in papers:
        repo_url = paper.get("repoUrl")
        if isinstance(repo_url, str):
            slug = github_slug(repo_url)
            if slug:
                repos[slug] = repo_url

    stars_by_slug: dict[str, int] = {}
    for index, slug in enumerate(sorted(repos), start=1):
        try:
            data = fetch_json(
                f"{GITHUB_REPO_API}/{slug}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "NewsRoomResearch/0.1 (paper metrics)",
                },
            )
        except Exception as exc:  # noqa: BLE001 - batch enrichment should keep going.
            print(f"github skipped {slug}: {exc}", flush=True)
            continue
        stars = data.get("stargazers_count")
        html_url = normalize_github_repo_url(str(data.get("html_url") or repos[slug]))
        if isinstance(stars, int) and html_url:
            stars_by_slug[slug] = stars
            repos[slug] = html_url
        print(f"github stars: {index}/{len(repos)}", flush=True)
        time.sleep(sleep_seconds)

    updated = 0
    for paper in papers:
        slug = github_slug(str(paper.get("repoUrl") or ""))
        if slug and slug in stars_by_slug:
            paper["githubStars"] = stars_by_slug[slug]
            paper["repoUrl"] = repos[slug]
            updated += 1
    print(f"github stars updated: {updated}", flush=True)


def fetch_json(url: str, *, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def github_repo_url_from_text(value: str) -> str | None:
    match = GITHUB_REPO_PATTERN.search(value)
    return normalize_github_repo_url(match.group(0)) if match else None


def normalize_github_repo_url(value: str) -> str | None:
    text = value.strip().rstrip(".,;:)]}>'\"")
    if not text:
        return None
    parsed = urllib.parse.urlparse(text.replace("http://", "https://", 1))
    if parsed.scheme != "https" or parsed.netloc.lower().removeprefix("www.") != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner = parts[0].strip().rstrip(".,;:)]}>'\"")
    repo = parts[1].strip().removesuffix(".git").rstrip(".,;:)]}>'\"")
    return f"https://github.com/{owner}/{repo}" if owner and repo else None


def github_slug(value: str) -> str | None:
    repo_url = normalize_github_repo_url(value)
    if not repo_url:
        return None
    parsed = urllib.parse.urlparse(repo_url)
    parts = [part for part in parsed.path.split("/") if part]
    return "/".join(parts[:2]) if len(parts) >= 2 else None


def normalize_doi(value: str) -> str:
    return value.strip().lower().removeprefix("https://doi.org/")


if __name__ == "__main__":
    main()
