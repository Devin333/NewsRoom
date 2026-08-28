#!/usr/bin/env python3
"""
采集 GitHub + HN + Product Hunt 项目数据，生成 ProjectRadarBridge 格式的 artifact。

用法:
    python scripts/fetch_github_projects.py
    python scripts/fetch_github_projects.py --token ghp_xxx --limit 40
"""
from __future__ import annotations
import argparse, json, os, time, urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

GITHUB_API = "https://api.github.com"
HN_API = "https://hn.algolia.com/api/v1"
PH_RSS = "https://www.producthunt.com/feed"
UTC = timezone.utc

GITHUB_QUERIES = [
    "topic:llm-agent stars:>500",
    "topic:llm stars:>2000 pushed:>2026-01-01",
    "topic:agents stars:>500 pushed:>2026-01-01",
    "topic:rag stars:>500 pushed:>2026-01-01",
    "topic:langchain stars:>500",
    "topic:openai stars:>500 pushed:>2026-01-01",
]

def _headers(token=None):
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = "Bearer " + token
    return h

def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "AgoraHubResearch/0.1 (project fetcher)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            print("  rate limited, sleeping 60s...")
            time.sleep(60)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        raise

def _get_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "AgoraHubResearch/0.1 (project fetcher)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")

def _repo_card(repo, generated_at):
    full_name = repo["full_name"]
    name = full_name.split("/", 1)[1]
    stars = repo.get("stargazers_count", 0)
    forks = repo.get("forks_count", 0)
    open_issues = repo.get("open_issues_count", 0)
    topics = repo.get("topics", [])
    description = repo.get("description") or ""
    return {
        "board_type": "project_radar",
        "card_id": "card_gh_" + full_name.replace("/", "_"),
        "title": name,
        "subtitle": description[:120] or full_name,
        "summary": description or "GitHub repository " + full_name,
        "repo_full_name": full_name,
        "github_url": repo["html_url"],
        "stars": stars, "forks": forks, "open_issues": open_issues,
        "star_growth_7d": max(1, stars // 30),
        "tags": topics[:8],
        "license": (repo.get("license") or {}).get("spdx_id"),
        "generated_at": generated_at,
        "published_at": repo.get("pushed_at", ""),
        "ranking_reason": "GitHub: {:,} stars, {:,} forks.".format(stars, forks),
        "ranking_features": {
            "repo_health": min(1.0, stars / 5000),
            "activity": min(1.0, forks / 1000),
            "implementation_evidence": 0.7 if topics else 0.4,
            "community_adoption": min(1.0, open_issues / 200),
            "technology_mapping": 0.8 if any(t in topics for t in ("llm","agent","rag","ai")) else 0.5,
        },
        "confidence": {"value": round(min(1.0, (stars / 10000) * 0.6 + 0.3), 3)},
        "metrics": [{"label": "Stars", "value": stars}, {"label": "Forks", "value": forks}],
        "evidence_refs": [{"source_name": "GitHub", "source_type": "github",
            "url": repo["html_url"], "external_id": full_name, "collected_at": generated_at}],
    }

def fetch_github(limit, token):
    seen, cards = set(), []
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for query in GITHUB_QUERIES:
        if len(cards) >= limit: break
        print("  github: " + query)
        try:
            url = GITHUB_API + "/search/repositories?q=" + urllib.parse.quote(query) + "&sort=stars&order=desc&per_page=" + str(min(20, limit - len(cards)))
            for repo in _get_json(url, _headers(token)).get("items", []):
                fqn = repo["full_name"]
                if fqn not in seen:
                    seen.add(fqn)
                    cards.append(_repo_card(repo, generated_at))
        except Exception as exc:
            print("  error: " + str(exc))
        time.sleep(1)
    return cards[:limit]

def fetch_hn(limit):
    seen, cards = set(), []
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for q in ["Show HN LLM agent", "Show HN AI tool", "Show HN open source AI"]:
        if len(cards) >= limit: break
        print("  hn: " + q)
        try:
            url = HN_API + "/search?query=" + urllib.parse.quote(q) + "&tags=story&hitsPerPage=" + str(min(10, limit - len(cards)))
            for hit in _get_json(url).get("hits", []):
                oid = hit.get("objectID", "")
                if oid in seen: continue
                seen.add(oid)
                url_val = hit.get("url") or ("https://news.ycombinator.com/item?id=" + oid)
                points = hit.get("points") or 0
                comments = hit.get("num_comments") or 0
                cards.append({
                    "board_type": "project_radar",
                    "card_id": "card_hn_" + oid,
                    "title": (hit.get("title") or "")[:80],
                    "subtitle": "Hacker News",
                    "summary": hit.get("title") or "",
                    "github_url": url_val if "github.com" in url_val else None,
                    "canonical_url": url_val,
                    "hn_points": points, "hn_comments": comments,
                    "star_growth_7d": 0, "tags": ["hackernews"],
                    "generated_at": generated_at, "published_at": hit.get("created_at", ""),
                    "ranking_reason": "HN: {:,} points, {:,} comments.".format(points, comments),
                    "ranking_features": {"repo_health": 0.3, "activity": min(1.0, comments/100),
                        "implementation_evidence": 0.5 if "github.com" in url_val else 0.2,
                        "community_adoption": min(1.0, points/500), "technology_mapping": 0.6},
                    "confidence": {"value": round(min(1.0, points/1000*0.5+0.2), 3)},
                    "metrics": [{"label": "HN Points", "value": points}],
                    "evidence_refs": [{"source_name": "Hacker News", "source_type": "community",
                        "url": "https://news.ycombinator.com/item?id=" + oid,
                        "external_id": oid, "collected_at": generated_at}],
                })
        except Exception as exc:
            print("  error: " + str(exc))
        time.sleep(0.5)
    return cards[:limit]

def fetch_product_hunt(limit):
    cards = []
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    print("  product hunt: RSS")
    try:
        root = ET.fromstring(_get_text(PH_RSS))
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for item in (root.findall(".//item") or root.findall(".//atom:entry", ns))[:limit]:
            title_el = item.find("title") or item.find("atom:title", ns)
            link_el = item.find("link") or item.find("atom:link", ns)
            desc_el = item.find("description") or item.find("atom:summary", ns)
            title = (title_el.text or "") if title_el is not None else ""
            link = ((link_el.text or link_el.get("href","")) if link_el is not None else "")
            desc = (desc_el.text or "") if desc_el is not None else ""
            if not title or not link: continue
            slug = link.rstrip("/").split("/")[-1]
            cards.append({
                "board_type": "project_radar",
                "card_id": "card_ph_" + slug[:40],
                "title": title[:80], "subtitle": "Product Hunt",
                "summary": desc[:200] or title, "canonical_url": link,
                "product_hunt_votes": 0, "star_growth_7d": 0, "tags": ["product_hunt"],
                "generated_at": generated_at,
                "ranking_reason": "Product Hunt launch.",
                "ranking_features": {"repo_health": 0.3, "activity": 0.4,
                    "implementation_evidence": 0.4, "community_adoption": 0.5, "technology_mapping": 0.5},
                "confidence": {"value": 0.4},
                "metrics": [{"label": "PH Votes", "value": 0}],
                "evidence_refs": [{"source_name": "Product Hunt", "source_type": "web",
                    "url": link, "external_id": slug, "collected_at": generated_at}],
            })
    except Exception as exc:
        print("  error: " + str(exc))
    return cards

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--hn-limit", type=int, default=10)
    parser.add_argument("--ph-limit", type=int, default=10)
    parser.add_argument("--runs-dir", default=".newsroom/runs")
    args = parser.parse_args()

    print("Fetching projects...")
    cards = fetch_github(args.limit, args.token) + fetch_hn(args.hn_limit) + fetch_product_hunt(args.ph_limit)
    print("Total: {} cards".format(len(cards)))

    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    # 目录名含 project_radar，前端本地 fallback 才能识别
    run_id = "project_radar-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    payload = {"board_type": "project_radar", "generated_at": generated_at,
               "cards": cards, "detail_pages": [],
               "metadata": {"sources": ["github", "hackernews", "product_hunt"]}}
    (run_dir / "board_output.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_id, "board_type": "project_radar",
        "generated_at": generated_at, "artifacts": {"board_output": "board_output.json"},
    }, indent=2), encoding="utf-8")
    print("Artifact: {}/{}/board_output.json".format(args.runs_dir, run_id))

if __name__ == "__main__":
    main()
