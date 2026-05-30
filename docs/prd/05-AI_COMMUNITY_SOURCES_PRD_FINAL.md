# NewsRoom AI Community Sources PRD

> Document status: FINAL
> Version: v1.0
> Scope: NewsRoom final implementation target, not an MVP
> Runtime config path: `configs/sources.yaml`
> Goal: build NewsRoom's AI community signal-source system through the unified Source Pipeline.

## 0. One-Line Conclusion

AI Community Sources is not a new Agent and not temporary code under `agents/daily_news`. It is the NewsRoom signal source registration, collection, governance, and standardization system.

Final landing shape:

```text
docs/prd/05-AI_COMMUNITY_SOURCES_PRD_FINAL.md
configs/sources.yaml
business/foundation/models/source.py
business/foundation/registry/source_registry.py
business/layers/signal/source_config.py
business/layers/signal/source_router.py
business/layers/signal/source_catalog.py
infrastructure/external/sources/
interfaces/services/source_service.py
interfaces/cli/commands/sources.py
tests/...
```

Core rules:

```text
category means information type
language means language
region means geography
metadata.group means product-side grouping
metadata.priority means collection priority
metadata.signal_kind means signal semantics
```

There must not be a top-level `chinese_ai_media` category. Chinese sources belong to their semantic category:

```yaml
category: research
language: zh
region: cn
```

## 1. Background

NewsRoom is a news intelligence runtime. AI information sources contain several signal layers: papers, open source projects, model platforms, official releases, Agent frameworks, developer discussions, and engineering practice. These sources must enter the Source Pipeline instead of being scattered across Agents.

Existing foundation:

```text
configs/sources.yaml
business/foundation/models/source.py
business/foundation/registry/source_registry.py
business/layers/signal/source_config.py
business/layers/signal/source_health/
infrastructure/external/sources/
interfaces/services/source_service.py
interfaces/cli/commands/sources.py
```

## 2. Product Goal

NewsRoom must continuously and governably discover:

```text
new papers
new models and datasets
new Spaces / demos
new open source projects
GitHub trends and releases
framework issues and discussions
official model and product releases
developer-community discussions
Chinese engineering practice
domestic model and cloud-vendor updates
```

This serves Daily Report, Weekly Report, Research Board, Open Source Board, Model Platform Board, Agent Framework Board, Engineering Practice Board, Trend Hunter, Timeline / Evidence Memory, and alerting flows.

## 3. Non-Goals

This module does not:

1. Hard-code sources in `agents/daily_news`.
2. Add a top-level `chinese_ai_media` category.
3. Let Agents call Reddit, GitHub, arXiv, or Hugging Face APIs directly.
4. Let `WorkflowExecutor` depend on concrete connectors.
5. Store tokens, cookies, API keys, secrets, or credentials in source config.
6. Give low-quality tutorial sources the same authority as first-party official sources.
7. Scatter RSS/API/HTML extraction rules across business nodes.
8. Bypass `SourceRegistry.validate()`.
9. Bypass `SourceHealthManager`.
10. Bypass fetch policy, robots, rate limit, or retry policy.

## 4. Final Taxonomy

```text
AI_COMMUNITY_SOURCES
├── research
├── open_source
├── model_platform
├── official_blog
├── agent_framework
├── developer_discussion
└── engineering_practice
```

No other first-level category is allowed for this source family.

## 5. Category Definitions

`research` covers papers, paper digests, benchmarks, and SOTA updates. Examples: arXiv, Papers with Code, Hugging Face Papers, PaperWeekly, and machine-intelligence paper columns.

`open_source` covers repositories, trends, releases, issues, pull requests, security advisories, and maintainer discussions. Examples: GitHub Trending, Releases, Discussions, Issues, Pull Requests.

`model_platform` covers model releases, datasets, demos, model cards, platform updates, and deployment signals. Examples: Hugging Face Models, Hugging Face Spaces, ModelScope Models.

`official_blog` covers first-party company, lab, cloud vendor, and model vendor releases. Examples: OpenAI, Anthropic, Google DeepMind, Meta AI, Microsoft Research, Alibaba Cloud, Tencent Cloud, Baidu.

`agent_framework` covers Agent runtimes, tool calling, workflow runtime, memory, RAG, multi-agent orchestration, human-in-the-loop, evaluation, docs updates, releases, and discussions. Examples: LangChain, LlamaIndex, CrewAI, AutoGen.

`developer_discussion` covers heat, feedback, controversy, early adoption signals, and community discussion. It is a trend and feedback source, not a high-trust factual source. Examples: Reddit, Hacker News, Product Hunt, X researcher lists, Zhihu, V2EX.

`engineering_practice` covers tutorials, deployment practice, troubleshooting, local inference, cloud integration, and engineering case studies. These sources usually require quality filtering.

## 6. Source Registry Model

Every source must enter `SourceDefinition`:

```yaml
source_id: string
name: string
source_type: rss | atom | arxiv | github | official_blog | hackernews | reddit | lobsters | html | web_page | manual | stackoverflow | devto | medium
url: string
reliability: high | medium | low
authority_score: float
enabled: boolean
fetch_interval_seconds: integer
respect_robots: boolean
user_agent: string | null
topics: list[string]
category: string
language: en | zh | multi
region: global | us | cn | eu | jp
metadata: object
```

Standard metadata:

```yaml
metadata:
  group: research | open_source | model_platform | official_blog | agent_framework | developer_discussion | engineering_practice
  priority: p0 | p1 | p2 | p3
  signal_kind: string
  trust_policy: official | research | official_project | curated_media | community | mixed | low_confidence
  dedup_strategy: paper_id | repository_name | model_id | canonical_url | title_hash | content_hash
  freshness_window_hours: integer
  quality_filter_required: boolean
  connector_todo: string | null
```

## 7. Priority

`p0` is core first-party or high-value structured signal and must enter production monitoring.
`p1` is high-value supplemental signal.
`p2` is engineering-practice and community supplemental signal and often needs quality filtering.
`p3` is experimental, manual, or low-stability signal and should default to disabled unless explicitly enabled.

## 8. Config Structure

The final design keeps one main file:

```text
configs/sources.yaml
```

Supported sections:

```yaml
fetch: {}
official_blogs: []
rss_feeds: []
atom_feeds: []
arxiv_categories: []
github_lists: []
hackernews_sources: []
reddit_sources: []
stackoverflow_tags: []
devto_tags: []
medium_feeds: []
web_pages: []
manual_sources: []
```

## 9. SourceConnectorRouter

`business/layers/signal/source_router.py` routes `SourceDefinition.source_type` to the correct connector:

```text
rss, atom, official_blog -> FeedConnector
arxiv -> ArxivConnector
github -> GithubConnector
hackernews -> HackerNewsConnector
reddit -> RedditConnector
lobsters -> LobstersConnector
stackoverflow -> StackOverflowConnector
devto -> DevToConnector
medium -> MediumConnector
html, web_page -> HtmlConnector
manual -> ManualConnector
```

Future specialized connectors can route by explicit `source_type` or compatibility metadata such as `metadata.connector_todo`.

## 10. SourceApplicationService

The service exposes:

```python
fetch_source(source_id, limit=10, query=None, force=False)
fetch_category(category, limit_per_source=5, enabled_only=True, priority=None, language=None, region=None, force=False)
fetch_priority(priority, limit_per_source=5, enabled_only=True, force=False)
fetch_topic_sources(topic, limit_per_source=5, enabled_only=True, category=None, priority=None, language=None, region=None, force=False)
```

The service uses `SourceRegistry` for lookup and selection, `SourceConnectorRouter` for fetch, and source health decisions for skip/cooldown behavior.

## 11. CLI

Final CLI commands:

```bash
news sources list --json
news sources validate --json
news sources health --json
news sources check-health --limit 10 --json
news sources fetch --source-id arxiv-cs-ai --limit 10 --json
news sources fetch-category --category research --limit-per-source 5 --json
news sources fetch-priority --priority p0 --limit-per-source 5 --json
news sources fetch-topic --topic "AI agents" --limit-per-source 5 --json
news sources inspect --source-id huggingface-models --json
news sources categories --json
news sources priorities --json
```

Batch JSON shape:

```json
{
  "ok": true,
  "source_count": 3,
  "item_count": 15,
  "error_count": 0,
  "skipped_count": 0,
  "results": []
}
```

## 12. Quality Governance

Reliability and authority scoring distinguish first-party sources, high-quality platforms, community sources, engineering articles, high-noise platforms, and experimental sources. Sources such as CSDN, Juejin, Zhihu, V2EX, Medium, Dev.to, Product Hunt, and unstable web pages must use `metadata.quality_filter_required: true`.

Health states:

```text
healthy
degraded
cooling_down
down
disabled
```

In the current runtime, cooling-down sources are represented by `down` with `cooldown_until`.

## 13. Dedup And Lineage

Each `RawSourceItem` must include lineage with:

```text
source_id
source_item_id
raw_url
canonical_url
fetched_at
published_at
raw_artifact_ref
parse_artifact_ref
metadata
```

Dedup strategies include `paper_id`, `repository_name`, `model_id`, `canonical_url`, `title_hash`, and `content_hash`.

## 14. Agent Boundary

Correct chain:

```text
Agent / Workflow
  -> SourceApplicationService
  -> SourceRegistry
  -> SourceConnectorRouter
  -> infrastructure.external.sources.*
  -> RawSourceItem
  -> Normalize
  -> Dedup
  -> Rank
  -> Cluster
  -> Agent Analysis
  -> Report / Board / Timeline / Memory
```

Agents do not fetch external sources directly.

## 15. Acceptance

Config acceptance:

```bash
news sources validate
news sources list --json
```

Expected:

```text
is_valid=true
error_count=0
source_count >= 30
```

Focused checks:

```bash
python -m compileall -q business infrastructure interfaces tests
python -m interfaces.cli.news sources validate
python -m interfaces.cli.news sources list --json
python -m interfaces.cli.news sources categories --json
python -m interfaces.cli.news sources priorities --json
pytest tests/business/layers/signal -q
pytest tests/infrastructure/external/sources -q
pytest tests/interfaces -q
```

## 16. Codex Task Breakdown

Recommended implementation sequence:

```text
Task 01: Expand AI Community Sources config
Task 02: Add Source Catalog constants
Task 03: Enhance SourceRegistry validation
Task 04: Add SourceConnectorRouter
Task 05: Extend SourceApplicationService
Task 06: Extend Sources CLI
Task 07: Add Hugging Face connector
Task 08: Add ModelScope connector
Task 09: Add Papers with Code connector
Task 10: Add Product Hunt connector
Task 11: Wire specialized connectors
Task 12: Expose API / MCP / SDK
Task 13: Add quality-filter metadata propagation
Task 14: Documentation update
Task 15: End-to-end source smoke
```

This tranche implements Tasks 01-06 plus Task 14 documentation. Tasks 07-13 and 15 are later changes.

## 17. Final Category List

```text
research
open_source
model_platform
official_blog
agent_framework
developer_discussion
engineering_practice
```

## 18. Final Priority List

```text
p0: core first-party / high-value structured source
p1: high-value supplemental source
p2: engineering practice and community supplemental source
p3: experimental / manual / low-stability source
```

## 19. Recommended Signal Kinds

```text
paper
paper_digest
benchmark
sota_update
repository_trend
release
issue
pull_request
discussion
model_release
dataset_release
demo_release
model_platform_update
official_release
official_research
product_update
policy_update
framework_release
framework_discussion
issue_hotspot
docs_update
community_discussion
community_trend
user_feedback
product_trend
tutorial
engineering_case
troubleshooting
deployment
developer_article
```
