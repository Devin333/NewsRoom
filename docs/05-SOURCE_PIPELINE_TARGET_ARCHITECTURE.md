# 05-SOURCE_PIPELINE.md

版本：v1.0-target-architecture
适用项目：News Intelligence System
模块：Source Pipeline / Collection and Processing Layer
定位：目标态架构设计，不是 MVP 简化版
日期：2026-05-11

---

### 0.2 v1.3 Source Runner 装配边界

Source Pipeline 的主入口仍然是 `SourceConnector / SourceRegistry / SourceFetcher / SourceParser`。

Workflow-specific runner 可以根据 profile 装配真实 source、fixture source 或 source limit，但不能绕过 Source Pipeline 让 Agent 直接 fetch/search 外部来源。


## 0. 文档定位

本文档定义 News Intelligence System 的 **最终目标态 Source Pipeline**。

注意：

- 本文档不是第一版实现说明。
- 本文档不是 MVP 裁剪方案。
- 本文档先定义最终系统应该具备的 source collection、source processing、source health、source lineage、source artifact 和 source governance 能力。
- 后续 MVP、P1、P2、生产化阶段，都应该从这个目标架构中裁剪实现范围。
- 第一版实现只是目标态 Source Pipeline 的一个子集，而不是反过来用第一版限制最终设计。

Source Pipeline 是 News Intelligence System 中负责 **来源管理、抓取、解析、标准化、去重、排序、健康监控、降级、证据输入和 lineage 追踪** 的数据入口层。

它和其他模块的关系是：

```text
Workflow Runtime
  -> Source Pipeline StepRunner / FunctionStep
      -> SourceRegistry
      -> SourceFetcher
      -> SourceParser
      -> SourceNormalizer
      -> SourceDeduplicator
      -> SourceRanker
      -> SourceHealthManager
      -> RawSourceItem / NormalizedSourceItem / RankedSourceItem
          -> Evidence Pipeline
```

Source Pipeline 的目标不是“随便爬网页”，而是为情报系统提供可审计、可追踪、可治理的来源输入。

---

## 0.1 v1.1 设计审查结论：Source Pipeline 的修订边界

本次审查不删除 source registry、connector、fetch、parse、normalize、dedup、rank、health、governance 的目标态能力，而是强化 Source Pipeline 作为数据入口主路径。

需要保留：真实 source、RSS/Atom、official blog fallback、GitHub、arXiv、community source、manual source、health/cooldown、source artifact、lineage。

需要修正：Source Pipeline 的 ranking 只表示“source item 是否值得进入 evidence pipeline”，不表示 claim 被验证为真。Claim support、uncertainty、rejected claim 必须由 `06-EVIDENCE_AND_QUALITY_GATE` 负责。

需要做设计减法：

```text
不要同时维护多条默认抓取路径：
  主路径 = SourceConnector / SourceFetcher / SourceParser
  Agent tool fetch = 受限补充路径，只能在明确策略允许时使用

不要把 extraction confidence 当 evidence confidence。
不要让 WriterAgent 绕过 Source Pipeline 新增 URL。
```

跨文档一致性要求：SourceHealth 的判断逻辑归 Source Pipeline；定时触发 source_health_check 归 Worker/Scheduler；状态持久化归 Storage。

---

## 0.2 v1.2 复查修订：SourceConnector 是主入口，fetch tool 是例外入口

Source Pipeline 的主路径必须保持确定性：

```text
SourceRegistry -> SourceConnector -> Fetcher -> Parser -> Normalizer -> Deduplicator -> Ranker -> Evidence Pipeline
```

Agent 可调用的 source/search/fetch 工具只能作为受限补充能力，不能绕过 SourceRegistry、robots/rate limit、source health、artifact logging 和 lineage。

这条规则尤其约束 WriterAgent / EditorAgent：它们默认不能抓取新来源，也不能把未进入 Evidence Pipeline 的外部信息写进报告。


## 1. 为什么需要 Source Pipeline

News Intelligence System 的最终价值依赖于来源质量。

如果 source 层不稳定，后面的 Agent、Evidence、Citation、Report 都会受到影响。

Source Pipeline 要解决的问题包括：

```text
不同来源格式不一样
RSS/Atom 字段不统一
网页正文有广告和导航噪音
发布时间可能缺失或格式不一致
URL 有重复和 tracking 参数
相同新闻会出现在多个来源
source 会失败、超时、返回空内容
source 的可靠性不同
某些 source 需要降级或跳过
source 抓取需要尊重 robots / rate limit
source 内容需要可追溯到原始 URL
```

如果没有 Source Pipeline，系统会退化成：

```text
抓到什么就喂给 LLM
LLM 根据混乱来源写报告
报告引用不可控
source 失败不可解释
重复新闻堆满上下文
```

最终会导致：

- 报告重复。
- 引用不可靠。
- LLM 上下文浪费。
- source 失败难以排查。
- evidence 缺少 lineage。
- 质量门控无法判断来源可信度。
- 历史记忆写入低质量数据。

因此，Source Pipeline 是整个情报生产系统的“入口质量控制层”。

---

## 2. 参考项目的通俗解释

### 2.1 Hive：像“工具驱动的数据入口”，但不是专业爬虫

Hive 本身不是新闻采集框架，它更偏 Agent graph runtime。
它的来源获取通常通过 tools / MCP tools / external event sources 接入。

通俗理解：

```text
Hive 不负责专门做新闻采集，
它更像一个会调用工具的 Agent 执行系统。
如果 Agent 需要外部信息，就通过工具去拿。
```

值得借鉴：

```text
source fetching 可以作为 Tool / Step 接入 Workflow
不同 Agent 不应该都能随便 fetch source
外部数据获取要经过 tool allowlist
抓取结果要以 artifact / pointer 方式保存
source collection 可以作为 graph 中的确定性节点
```

不应照搬：

```text
不要让 LLM 自己决定随便抓哪些网页
不要把 source fetching 藏在 Agent prompt 里
不要让 WriterAgent 直接 fetch/search 外部来源
不要把所有 source 行为都做成 EventLoopNode
```

News 的 Source Pipeline 应该是：

```text
deterministic source collection first
Agent analysis later
```

也就是说，真实来源先由 Source Pipeline 收集、处理、产出 evidence 候选，再交给 Agent 分析。

---

### 2.2 Scrapy：像“专业采集工厂”

Scrapy 的架构非常适合参考。它有：

```text
Engine
Scheduler
Downloader
Spider
Item Pipeline
Downloader Middleware
Spider Middleware
Extensions
```

通俗理解：

```text
Spider 负责发现要抓什么
Downloader 负责下载
Middleware 负责下载前后处理
Item Pipeline 负责清洗、校验、保存
Scheduler 负责调度请求
Engine 负责协调所有组件
```

对 News 值得借鉴：

```text
fetch 和 parse 要分开
request/response 可以有 middleware
retry、redirect、robots、user-agent 应该是 fetch policy
item 清洗应该放 processing pipeline
去重应该是独立组件
source error 应该被结构化记录
```

不应照搬：

```text
News 不是通用爬虫平台
不需要一开始实现完整 Scheduler / Spider / Downloader Engine
不需要支持无限 crawl depth
不需要大规模分布式爬取
```

News 应该借鉴 Scrapy 的分层思想，但保持面向情报系统的轻量实现。

---

### 2.3 feedparser：像“RSS/Atom 翻译器”

feedparser 的价值很明确：解析 RSS、Atom 等 feed，把不同 feed 格式统一成 Python 对象。

通俗理解：

```text
不同网站的 RSS/Atom 长得不一样，
feedparser 帮你把它们翻译成统一结构。
```

对 News 值得借鉴：

```text
RSS/Atom parser 应该独立封装
parser 要保留 bozo / parse error 信息
feed-level metadata 和 entry-level metadata 都要保存
发布时间、标题、链接、摘要需要标准化
```

不应照搬：

```text
不要把 feedparser 解析结果直接当业务模型
必须转换成 RawSourceItem
必须保留 source_id、lineage、fetch metadata
```

---

### 2.4 Trafilatura：像“网页正文提取器”

Trafilatura 的价值是从 HTML 页面中提取正文、元数据和评论，并能输出 JSON、Markdown、TXT、XML 等格式。

通俗理解：

```text
网页里有导航、广告、推荐、脚本，
Trafilatura 尝试帮你提取真正的正文。
```

对 News 值得借鉴：

```text
official blog fallback
HTML page extraction
metadata extraction
Markdown / JSON output
网页正文和原始 HTML 分离
```

不应照搬：

```text
不要把 HTML extraction 当成完全可靠
需要保存 extraction confidence
需要保留原始 URL 和 extraction artifact
需要低质量正文检测
```

---

### 2.5 Newspaper4k：像“新闻文章专用解析器”

Newspaper4k 是 newspaper3k 的继任 fork，主要用于新闻文章正文、作者、发布时间、图片等提取。

通俗理解：

```text
它更懂新闻文章页面，
可以帮你从新闻网页里提正文、作者、发布日期。
```

对 News 值得借鉴：

```text
article extraction
metadata extraction
publish date extraction
top image / authors
news-specific parsing
```

不应照搬：

```text
不同网站效果不稳定
不能把 extracted publish_date 当绝对可信
需要 fallback 和 confidence
需要和 RSS metadata 对比校验
```

---

### 2.6 Airbyte / Connector 思路：像“每种来源一个插头”

虽然 Airbyte 不是新闻采集系统，但它的 connector 思想很值得参考。

通俗理解：

```text
每个数据源一个 connector，
connector 负责知道这个来源怎么读，
统一输出标准记录。
```

News 可以借鉴：

```text
RSSSourceConnector
OfficialBlogConnector
GitHubConnector
ArxivConnector
HackerNewsConnector
RedditConnector
WebPageConnector
```

每个 connector 输出统一的：

```text
RawSourceItem
SourceFetchResult
SourceError
SourceHealthUpdate
```

---

## 3. News 最终态 Source Pipeline 目标

最终态 Source Pipeline 应该支持：

```text
source registry
source config validation
source category
source reliability score
source health
source cooldown
source fallback
source probing
source fetch policy
robots policy
rate limit policy
RSS/Atom parsing
official blog parsing
HTML extraction
GitHub source collection
Arxiv source collection
HackerNews source collection
Reddit source collection
custom source connector
URL canonicalization
metadata normalization
language detection
deduplication
near-duplicate detection
topic relevance ranking
source authority ranking
recency ranking
novelty ranking
source artifact logging
raw content artifact
parsed content artifact
source error artifact
lineage propagation
source quality scoring
source coverage reporting
```

---

## 4. Source Pipeline 和其他模块的边界

### 4.1 Workflow Runtime 负责

```text
决定何时执行 collect_sources
决定 source collection 失败后怎么路由
决定是否进入 evidence pipeline
写 workflow-level artifact 和 manifest
```

### 4.2 Source Pipeline 负责

```text
管理 source
抓取 source
解析 source
标准化 source item
去重
排序
记录 source health
产出 source artifacts
产出 RawSourceItem / NormalizedSourceItem / RankedSourceItem
```

### 4.3 Tool Runtime 负责

```text
如果 source fetching 被包装成 tool，则负责工具权限、参数校验、执行审计
```

但 Source Pipeline 不应该完全依赖 Agent 工具调用。

### 4.4 AgentLoop 负责

```text
分析 evidence
验证 claim
写报告
审查报告
```

AgentLoop 不应该随意绕过 Source Pipeline 抓外部来源。

### 4.5 Evidence Pipeline 负责

```text
把 ranked source items 转成 EvidenceItem 和 EvidenceBundle
```

Source Pipeline 不负责最终 claim 验证。

---

## 5. Source 类型体系

最终态 source 类型包括：

### 5.1 RSS / Atom Feed

```text
AI company blogs
framework release feeds
research lab blogs
engineering blogs
product update feeds
security advisory feeds
```

### 5.2 Official Blog

```text
OpenAI blog
Anthropic news
Google AI blog
Microsoft AI blog
Meta AI blog
NVIDIA developer blog
framework official blog
```

Official Blog 可能有 RSS，也可能只有 HTML 页面，因此需要 fallback。

### 5.3 GitHub

```text
repository releases
repository commits
issues
pull requests
stars/trending
discussion
security advisories
```

### 5.4 Arxiv / Paper Platforms

```text
arXiv categories
paper search query
new paper alerts
author/topic tracking
```

### 5.5 Developer Communities

```text
Hacker News
Reddit
Lobsters
Stack Overflow tags
dev.to
Medium engineering tags
```

### 5.6 Web Pages

```text
official announcement page
docs changelog
release note page
benchmark page
model card
```

### 5.7 Manual / Human-curated Sources

```text
operator-added URL
reviewer-submitted article
manual source list
```

---

## 6. 核心模型设计

### 6.1 SourceDefinition

```python
class SourceDefinition(BaseModel):
    source_id: str
    name: str
    source_type: Literal[
        "rss",
        "atom",
        "official_blog",
        "github",
        "arxiv",
        "hackernews",
        "reddit",
        "web_page",
        "manual"
    ]

    url: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    language: str | None = None
    region: str | None = None
    topics: list[str] = Field(default_factory=list)

    reliability: Literal["high", "medium", "low"] = "medium"
    authority_score: float = 0.5

    enabled: bool = True
    fetch_interval_seconds: int = 3600

    respect_robots: bool = True
    user_agent: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.2 SourceFetchRequest

```python
class SourceFetchRequest(BaseModel):
    request_id: str
    source_id: str
    source_type: str

    url: str | None = None
    query: str | None = None

    timeout_seconds: int = 15
    max_bytes: int = 1_000_000

    user_agent: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    since: datetime | None = None
    limit: int | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.3 SourceFetchResult

```python
class SourceFetchResult(BaseModel):
    request_id: str
    source_id: str
    success: bool

    status_code: int | None = None
    content_type: str | None = None
    content_bytes: int | None = None
    latency_ms: int | None = None

    raw_artifact_ref: ArtifactRef | None = None

    error_type: str | None = None
    error_message: str | None = None

    skipped: bool = False
    skip_reason: str | None = None

    fetched_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.4 RawSourceItem

```python
class RawSourceItem(BaseModel):
    source_item_id: str
    source_id: str
    source_name: str
    source_type: str

    title: str
    url: str
    published_at: datetime | None = None
    fetched_at: datetime

    summary: str | None = None
    raw_content: str | None = None
    raw_artifact_ref: ArtifactRef | None = None

    authors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    language: str | None = None

    lineage: Lineage
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.5 NormalizedSourceItem

```python
class NormalizedSourceItem(BaseModel):
    normalized_item_id: str
    source_item_id: str
    source_id: str

    title: str
    normalized_title: str

    url: str
    canonical_url: str

    published_at: datetime | None = None
    fetched_at: datetime

    summary: str | None = None
    normalized_summary: str | None = None

    content_hash: str | None = None
    title_hash: str | None = None
    canonical_url_hash: str

    language: str | None = None
    source_reliability: str

    lineage: Lineage
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.6 RankedSourceItem

```python
class RankedSourceItem(BaseModel):
    ranked_item_id: str
    normalized_item_id: str

    relevance_score: float
    recency_score: float
    reliability_score: float
    novelty_score: float
    final_score: float

    rank_reason: str | None = None

    lineage: Lineage
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.7 SourceError

```python
class SourceError(BaseModel):
    source_id: str
    source_name: str
    error_type: str
    error_message: str

    retryable: bool
    occurred_at: datetime

    request_ref: ArtifactRef | None = None
    response_ref: ArtifactRef | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.8 SourceHealth

```python
class SourceHealth(BaseModel):
    source_id: str
    source_name: str
    url: str | None = None

    health_status: Literal["healthy", "degraded", "down", "disabled"] = "healthy"

    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    consecutive_failure_count: int = 0

    success_count_24h: int = 0
    failure_count_24h: int = 0
    avg_latency_ms_24h: float | None = None

    cooldown_until: datetime | None = None

    last_error_type: str | None = None
    last_error_message: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

## 7. SourceRegistry 目标态设计

### 7.1 职责

```text
加载 source config
校验 source definition
按 source_type 查找 connector
按 topic / language / reliability 过滤 source
禁用不健康 source
输出 source list 给 workflow
```

### 7.2 接口

```python
class SourceRegistry:
    def register(self, source: SourceDefinition) -> None: ...
    def get(self, source_id: str) -> SourceDefinition: ...
    def list_enabled(self) -> list[SourceDefinition]: ...
    def list_by_type(self, source_type: str) -> list[SourceDefinition]: ...
    def list_by_topic(self, topic: str) -> list[SourceDefinition]: ...
    def validate(self) -> ValidationResult: ...
```

### 7.3 配置原则

```text
source_id 必须稳定
source name 可读
默认 source 不允许 fixture://
真实 source URL 必须校验 scheme
API key 不写在 source config
source reliability 必须显式
respect_robots 必须显式
```

---

## 8. Connector / Collector 设计

### 8.1 SourceConnector Protocol

```python
class SourceConnector(Protocol):
    source_type: str

    async def fetch(
        self,
        source: SourceDefinition,
        request: SourceFetchRequest,
        context: SourceFetchContext,
    ) -> SourceFetchResult:
        ...

    async def parse(
        self,
        source: SourceDefinition,
        fetch_result: SourceFetchResult,
        context: SourceParseContext,
    ) -> list[RawSourceItem]:
        ...
```

### 8.2 Connector 类型

```text
RSSConnector
AtomConnector
OfficialBlogConnector
WebPageConnector
GitHubConnector
ArxivConnector
HackerNewsConnector
RedditConnector
ManualConnector
```

### 8.3 Connector 设计原则

```text
每个 connector 只负责一种 source_type
fetch 和 parse 分离
parse 不直接写 DataBuffer
connector 输出统一 RawSourceItem
错误统一 SourceError
原始响应写 artifact
```

---

## 9. Fetch Policy 设计

### 9.1 FetchPolicy

```python
class FetchPolicy(BaseModel):
    timeout_seconds: int = 15
    max_bytes: int = 1_000_000
    max_redirects: int = 3

    retry_times: int = 2
    retry_on_status_codes: list[int] = Field(default_factory=lambda: [429, 500, 502, 503, 504])

    respect_robots: bool = True
    rate_limit_per_domain_per_minute: int | None = None

    user_agent: str = "news-intelligence-system"
```

### 9.2 Fetcher 职责

```text
HTTP GET/HEAD
timeout
max bytes
redirect limit
content type check
robots check
rate limit
retry
latency record
raw response artifact
```

### 9.3 不建议做

```text
无限递归 crawl
自动绕过反爬
忽略 robots
抓取登录态内容
默认执行 JavaScript
```

---

## 10. Parse / Extraction 设计

### 10.1 FeedParser

用于：

```text
RSS
Atom
JSON Feed
```

输出：

```text
feed metadata
entry title
entry link
entry published_at
entry summary
entry content
entry authors
```

### 10.2 HTML Extractor

用于：

```text
official blog fallback
release note page
announcement page
docs changelog
```

提取：

```text
title
main text
metadata
published date
authors
canonical URL
language
```

### 10.3 Extraction Confidence

```python
class ExtractionResult(BaseModel):
    title: str | None
    text: str | None
    summary: str | None
    published_at: datetime | None
    authors: list[str] = Field(default_factory=list)
    canonical_url: str | None = None

    confidence: float = 0.0
    extractor_name: str
    artifact_ref: ArtifactRef | None = None
```

### 10.4 多 Extractor 策略

```text
try feed metadata
then try HTML metadata
then try Trafilatura-like extraction
then try Newspaper-like extraction
then fallback to title/url only
```

---

## 11. Normalize 设计

### 11.1 URL Canonicalization

处理：

```text
scheme lower
host lower
remove default port
remove fragment
remove utm_* query
remove fbclid / gclid
sort query params
normalize trailing slash
resolve relative URL
```

### 11.2 Text Normalize

处理：

```text
strip whitespace
collapse whitespace
normalize unicode
remove boilerplate prefix
remove repeated source name suffix
normalize title punctuation
```

### 11.3 Time Normalize

处理：

```text
timezone normalization
missing timezone fallback
published_at parse
fetched_at preserve
future timestamp detection
```

### 11.4 Language Normalize

处理：

```text
source config language
feed language
content language detection
fallback unknown
```

---

## 12. Deduplication 设计

### 12.1 Dedup Keys

```text
canonical_url_hash
title_hash
content_hash
source_item_id
near_duplicate_signature
```

### 12.2 Dedup Strategy

```text
exact URL dedup
canonical URL dedup
normalized title dedup
content hash dedup
near duplicate by fuzzy title
same event cluster
```

### 12.3 Retention Rule

重复项保留优先级：

```text
higher source reliability
newer published_at
more complete summary/content
official source preferred
canonical URL preferred
```

### 12.4 DedupResult

```python
class DedupResult(BaseModel):
    kept_items: list[NormalizedSourceItem]
    duplicate_groups: list[DuplicateGroup]
    dropped_items: list[NormalizedSourceItem]
    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

## 13. Ranking 设计

### 13.1 Ranking Signals

```text
topic relevance
keyword hit
source reliability
source authority
recency
novelty
duplicate cluster size
official source bonus
historical importance
user subscription match
```

### 13.2 Ranker

```python
class SourceRanker:
    def rank(
        self,
        items: list[NormalizedSourceItem],
        request: IntelligenceRequest,
        context: RankingContext,
    ) -> list[RankedSourceItem]:
        ...
```

### 13.3 Score Breakdown

每个 ranked item 必须保留打分解释：

```text
relevance_score
recency_score
reliability_score
novelty_score
final_score
rank_reason
```

这样 Agent 和 Reviewer 才知道为什么某条新闻被选中。

---

## 14. Source Health 设计

### 14.1 状态

```text
healthy
degraded
down
disabled
```

### 14.2 状态转换

```text
0~1 consecutive failures -> healthy
2~3 consecutive failures -> degraded
>=4 consecutive failures -> down
manual disabled -> disabled
```

### 14.3 Cooldown

```text
down source enters cooldown
cooldown expired -> probe once
probe success -> degraded or healthy
probe failure -> down again
```

### 14.4 SourceHealthManager

```python
class SourceHealthManager:
    def get_health(self, source_id: str) -> SourceHealth: ...
    def should_fetch(self, source_id: str, now: datetime) -> bool: ...
    def record_success(self, source_id: str, latency_ms: int, now: datetime) -> SourceHealth: ...
    def record_failure(self, source_id: str, error_type: str, error_message: str, now: datetime) -> SourceHealth: ...
```

---

## 15. Source Artifact 设计

### 15.1 每次 source fetch 可写

```text
sources/{source_id}/request.json
sources/{source_id}/response_headers.json
sources/{source_id}/raw_content.bin
sources/{source_id}/parsed_items.json
sources/{source_id}/error.json
```

### 15.2 Redaction

不能写入：

```text
Authorization header
Cookie
API key
signed URL token
private access token
```

### 15.3 ArtifactRef

RawSourceItem 应该保存：

```text
raw_artifact_ref
parse_artifact_ref
lineage
```

---

## 16. Source Events 与 Metrics

### 16.1 Events

```text
source_fetch_started
source_fetch_succeeded
source_fetch_failed
source_fetch_skipped
source_parse_started
source_parse_succeeded
source_parse_failed
source_normalized
source_deduplicated
source_ranked
source_health_updated
source_cooldown_started
source_probe_started
source_probe_succeeded
source_probe_failed
```

### 16.2 Metrics

```python
class SourcePipelineMetrics(BaseModel):
    sources_total: int = 0
    sources_fetched: int = 0
    sources_failed: int = 0
    sources_skipped: int = 0

    raw_items_count: int = 0
    normalized_items_count: int = 0
    deduplicated_items_count: int = 0
    ranked_items_count: int = 0

    duplicate_count: int = 0
    avg_fetch_latency_ms: float | None = None

    errors_by_type: dict[str, int] = Field(default_factory=dict)
    items_by_source: dict[str, int] = Field(default_factory=dict)
```

---

## 17. Source Error Taxonomy

建议统一错误类型：

```text
invalid_source_config
unsupported_source_type
robots_disallowed
rate_limited
fetch_timeout
fetch_connection_error
fetch_http_4xx
fetch_http_5xx
max_bytes_exceeded
unsupported_content_type
parse_error
empty_feed
empty_article
invalid_feed
invalid_published_at
normalization_error
dedup_error
ranking_error
all_sources_failed
```

每个错误标记：

```text
retryable
source_health_affecting
workflow_blocking
operator_action_required
```

---

## 18. No-source Fail-safe

真实 MVP 和最终态都必须支持 no-source fail-safe。

如果所有 source 均失败：

```text
不能生成 final report
必须写 error artifact
manifest.status = failed 或 blocked
必须记录 all_sources_failed
必须输出 source_errors
```

如果部分 source 成功：

```text
workflow 可以继续
report 必须在 source_notes 中说明失败来源
source_errors 写入 artifact
```

---

## 19. Source Governance

### 19.1 Source Reliability

每个 source 必须有初始 reliability：

```text
high
medium
low
```

### 19.2 Authority Score

长期可引入：

```text
official source bonus
historical accuracy
failure rate
citation usage frequency
duplicate cluster centrality
manual reviewer score
```

### 19.3 Source Policy

```text
官方来源优先
高失败来源降权
低可靠来源可进入 evidence，但需要低 confidence
社区来源需要 verifier 更严格
无法追溯 URL 的内容不能进入 final report
```

---

## 20. 目标态目录结构建议

```text
source_pipeline/
  __init__.py

  specs/
    source_definition.py
    fetch_policy.py
    ranking_policy.py
    source_policy.py

  registry/
    source_registry.py
    config_loader.py
    validation.py

  connectors/
    base.py
    rss_connector.py
    atom_connector.py
    official_blog_connector.py
    webpage_connector.py
    github_connector.py
    arxiv_connector.py
    hackernews_connector.py
    reddit_connector.py
    manual_connector.py

  fetch/
    http_fetcher.py
    robots.py
    rate_limiter.py
    retry.py
    response_store.py

  parse/
    feed_parser.py
    html_extractor.py
    metadata_extractor.py
    date_parser.py
    extraction_confidence.py

  processing/
    normalize.py
    canonical_url.py
    text_normalize.py
    time_normalize.py
    language.py
    deduplicate.py
    rank.py
    novelty.py

  health/
    source_health.py
    health_manager.py
    cooldown.py
    probe.py

  artifacts/
    source_artifact_writer.py
    redaction.py

  events/
    event_models.py
    event_emitter.py

  metrics/
    models.py
    collector.py

  errors/
    error_types.py
    exceptions.py

  models/
    raw_item.py
    normalized_item.py
    ranked_item.py
    fetch_result.py
    source_error.py
```

---

## 21. 和 Hive 的最终取舍

### 21.1 借鉴 Hive

```text
外部能力通过 tools / MCP 接入
source fetching 可以作为 graph step
source fetching 应该有权限控制
大结果通过 artifact pointer 传递
source step 的执行事件进入 EventBus
source errors 进入 shared state / DataBuffer
```

### 21.2 不照搬 Hive

```text
不让 LLM 自主决定全部 source fetching
不让 WriterAgent 直接 fetch source
不把 source collection 放进 prompt 隐式执行
不让 MCP tools 绕过 Source Pipeline
不把 raw source 全量塞进 conversation
不把 source fetching 做成不可审计工具调用
```

### 21.3 News 自己的目标态

```text
Source Pipeline 是独立数据入口层
SourceRegistry 是一等能力
SourceHealth 是一等能力
RawSourceItem / NormalizedSourceItem / RankedSourceItem 是标准数据模型
Source error 必须结构化
Source artifact 必须可回放
Source lineage 必须贯穿 evidence 和 report
Agent 只能消费 Source Pipeline 产物，不能绕过来源治理
```

---

## 22. 分阶段裁剪原则

本文档定义最终态。后续第一阶段可以只实现子集，但不能破坏最终架构。

裁剪原则：

```text
目标态先定完整边界
第一阶段只取最小真实 source 链路
命名、接口、目录和最终态保持兼容
后续只是补 connector、health、ranker、fallback、artifact、governance
不要推翻 Source Pipeline
```

例如第一阶段可以只实现：

```text
SourceDefinition
SourceFetchRequest
SourceFetchResult
RawSourceItem
NormalizedSourceItem
RankedSourceItem
SourceError
RSSConnector
HTTPFetcher
FeedParser
Normalizer
Deduplicator
Ranker
BasicSourceHealthManager
```

但目录和接口应与最终态兼容。

---

## 23. 最终态验收标准

Source Pipeline 最终完成时，应该满足：

```text
支持 source registry
支持 RSS/Atom source
支持 official blog fallback
支持 HTML extraction
支持 GitHub source
支持 Arxiv source
支持 developer community source
支持 source health
支持 source cooldown
支持 source probe
支持 robots policy
支持 rate limit
支持 fetch timeout
支持 max bytes
支持 source artifact
支持 source redaction
支持 URL canonicalization
支持 text normalization
支持 deduplication
支持 near-duplicate detection
支持 ranking score breakdown
支持 source error taxonomy
支持 no-source fail-safe
支持 lineage propagation
支持 source metrics
支持 source events
支持 source governance
```

---

## 24. 总结

News Source Pipeline 的最终目标不是一个简单 RSS 读取器，也不是一个通用网页爬虫。

它应该是：

```text
面向情报生产的来源治理与数据入口系统
```

它吸收 Hive 的工具化外部能力接入、事件记录和 artifact pointer 思想，也参考 Scrapy 的 fetch/parse/pipeline/middleware 分层、feedparser 的 RSS/Atom 解析、Trafilatura 和 Newspaper4k 的网页正文与元数据提取、connector 型项目的 source adapter 思维。

但 News 必须强化自己的业务约束：

```text
真实 source
source health
source failure isolation
source artifact replay
source reliability
source lineage
source-to-evidence traceability
no-source fail-safe
Agent 不绕过 Source Pipeline
```

后续 MVP、第一版、第二版都应该从这个最终态目标中裁剪实现，而不是用第一版的简单实现反向定义 Source Pipeline 的上限。

---
# 本版保留说明

以上内容为原目标态文档主体内容，已完整保留。下面追加的是 v2.0 设计书级补强，用于把原目标态说明转化为更可开发、可验收、可维护的工程设计书。

---
# v2.0 设计书级补强：Source Pipeline 工程化设计

## A. 本模块最终职责

Source Pipeline 是真实来源入口层，负责来源管理、抓取、解析、标准化、去重、排序、健康监控、lineage 和 source artifact。

它不负责：

```text
claim 是否为真
最终 report 是否可发布
Agent 自由搜索
长期调度
数据库事实建模
```

## B. 核心组件

```text
SourceConfig
SourceRegistry
SourceConnector
SourceFetcher
SourceParser
SourceNormalizer
SourceDeduplicator
SourceRanker
SourceHealthManager
SourceArtifactWriter
```

## C. 数据流

```text
SourceConfig
  -> SourceRegistry
  -> SourceConnector.fetch()
  -> RawSourceItem
  -> SourceParser.parse()
  -> ParsedSourceItem
  -> SourceNormalizer.normalize()
  -> NormalizedSourceItem
  -> SourceDeduplicator.deduplicate()
  -> DeduplicatedSourceItem
  -> SourceRanker.rank()
  -> RankedSourceItem
  -> EvidenceBuilder
```

## D. SourceConfig

```python
class SourceConfig(BaseModel):
    source_id: str
    name: str
    source_type: Literal["rss", "atom", "official_blog", "github", "arxiv", "hn", "reddit", "manual"]
    url: str

    language: str | None = None
    reliability: Literal["high", "medium", "low"] = "medium"

    fetch_interval_seconds: int = 3600
    timeout_seconds: int = 10
    max_items: int = 50
    respect_robots: bool = True
    user_agent: str = "news-intelligence-system"

    enabled: bool = True
    tags: list[str] = Field(default_factory=list)
```

## E. 真实 source 原则

默认 sources.yaml 不能使用 fixture://。

fixture 只能用于：

```text
unit test
offline regression
contract test
```

开发 smoke 和真实运行必须走真实 RSS/Atom 或官方 API。

## F. Ranking 不等于 Evidence Confidence

SourceRanker 判断：

```text
这条 source item 是否值得进入 evidence pipeline。
```

它不判断：

```text
这个 claim 是否真实。
```

claim support、uncertainty、rejected claim 归 Evidence/Quality。

## G. Source Health

SourceHealthManager 记录：

```text
last_success_at
last_failure_at
consecutive_failures
error_type
cooldown_until
average_latency_ms
item_count
content_quality_score
```

## H. 代码组织建议

初期：

```text
intelligence/sources.py
intelligence/processing.py
```

sources.py 放 connector/fetch/parser。
processing.py 放 normalize/dedup/rank。

## I. 测试矩阵

```text
test_rss_fetch_real_optional
test_parse_rss_entry_to_raw_item
test_url_canonicalization
test_deduplicate_same_url
test_deduplicate_near_same_title
test_rank_recent_authoritative_item
test_source_health_failure_cooldown
```

## J. 验收清单

```text
[ ] 默认配置没有 fixture://。
[ ] source fetch 失败有结构化 SourceError。
[ ] Raw/Parsed/Normalized/Ranked 模型分层清楚。
[ ] WriterAgent 不能绕过 Source Pipeline。
[ ] source artifact 能定位原始 URL 和解析结果。
```

## K. 当前代码进度映射：v2.1-current-code-aligned

截至 2026-05-14，仓库中的 Source Pipeline 已经具备可运行的 connector、处理、health、artifact、lineage 和治理基础。后续开发应继续基于现有 `sources/`、`domain/sources/`、`workflows/daily_intelligence/runner.py` 和 Tool Runtime source tools 收口，而不是新增一条并行抓取链路。

| 能力 | 当前状态 | 对应代码 | 说明 |
|---|---|---|---|
| Source domain models | 已实现 | `domain/sources/models.py` | 已有 Raw/Normalized/Ranked item、SourceLineage、SourceFetchResult、metadata lineage |
| Connector protocol | 已实现 | `sources/connectors/protocol.py` | 已有目标态 `SourceConnector` / `SourceFetchContext` / sync adapter |
| Source registry config | 已实现 | `sources/config.py` + `sources/registry` | 支持 sources.yaml、fixture 约束、type/reliability/filter |
| RSS/Feed connector | 已实现 | `sources/connectors/feed.py` | 支持 RSS/Atom 解析与 fetch policy |
| HTML connector | 已实现 | `sources/connectors/html.py` | 支持 multi-extractor strategy 和 stdlib fallback |
| GitHub connector | 已实现 | `sources/connectors/github.py` | 支持 releases、repositories、discussions，Discussions live 需要 token |
| arXiv connector | 已实现 | `sources/connectors/arxiv.py` | 支持论文检索 source path |
| Community connectors | 已实现 | `hackernews.py` / `reddit.py` / `community.py` | HN/Reddit/community source 基础已落地 |
| Manual connector | 已实现 | `sources/connectors/manual.py` | 支持手工 source 输入 |
| Fetch policy | 已实现 | `sources/connectors/fetch_policy.py` | 支持 robots、redirect、content-type、rate limit、retry、request interval |
| URL normalization | 已实现 | `sources/processing/normalize.py` | 支持 canonical URL、tracking 参数、default port、relative URL |
| Dedup | 已实现 | `sources/processing/deduplicate.py` | 支持 content hash、near duplicate、same-event cluster metadata |
| Ranking | 已实现 | `sources/processing/rank.py` | 支持 authority、freshness、reliability、historical/subscription、cluster signals |
| Ranking report | 已实现 | `sources/processing/ranking_report.py` | 输出 score breakdown，便于 replay/debug |
| Health checker/manager | 已实现 | `sources/health/checker.py` / `manager.py` | 支持 success/failure、down、cooldown、latency、item count、quality score |
| Health reports | 已实现 | `sources/processing/health_report.py` | 支持 source health summary/report |
| Error taxonomy | 已实现 | `sources/errors/taxonomy.py` | 已有 final-state source error taxonomy branches |
| Source artifacts | 已实现 | `core/framework/artifacts/source_artifacts.py` | 支持 raw_content.bin、headers、parsed items、fetch requests、checksums、redaction |
| Source tools | 已实现 | `core/framework/tools/source_tools.py` | source.fetch_url/search/extract/health 等作为受限补充入口 |
| Daily workflow integration | 已实现 | `workflows/daily_intelligence/runner.py` | daily runner 已接入 registry、connector dispatch、source limits、artifact/lineage |
| Tests | 较完整 | `tests/sources/*` + workflow/tool tests | 覆盖 connector、fetch policy、health、processing、taxonomy、source tools、daily runner |

总体判断：

```text
Source Pipeline 已经达到 P1 后段 / P2 前置：
  connector protocol、主要 connector、fetch policy、normalize/dedup/rank、health、artifact、lineage 均已落地；
  当前缺口主要是生产级真实 source 清单长期验收、persistent health store 深化、source governance policy 统一入口、更多 community/GitHub surfaces。
```

## L. 已完成、雏形、暂不做

### L.1 已完成能力

```text
SourceConnector / SourceFetchContext / sync adapter
Raw / Normalized / Ranked source item lineage
RSS / HTML / GitHub / arXiv / HN / Reddit / Manual connector
fetch policy: robots / rate limit / redirects / content-type / retry / interval
URL canonicalization
content hash and near duplicate dedup
same-event cluster metadata
ranking score breakdown with historical/subscription signals
source health down/cooldown state
source error taxonomy
source artifact raw_content.bin and request/response artifacts
daily workflow source registry dispatch
Tool Runtime source tools as controlled supplementary path
```

### L.2 雏形可用能力

```text
GitHub Discussions:
  已有 GraphQL path 和 injected fetcher 测试；
  live 默认需要 token，生产 rate limit / pagination / permission 仍需验收。

Community connectors:
  HN / Reddit 已有基础；
  reliability、moderation、anti-spam、API quota 仍需生产策略。

Persistent source health:
  health model 和 manager 已有；
  长期持久化、window metrics、cooldown probe event 仍需和 Storage/Worker 统一。

Source governance:
  registry validation / reliability filter 已有；
  policy report、allow/deny、topic selection、source authority 生命周期仍需继续收口。
```

### L.3 暂不做能力

```text
不让 WriterAgent / EditorAgent 默认抓取新 URL。
不把 source ranking 当 evidence confidence。
不让 Tool Runtime source.fetch_url 取代 deterministic connector 主路径。
不把 SourceHealth 的长期持久化 canonical model 放进 Source Pipeline。
不默认启用需要 credential 的 live connector 测试。
不把 generic web crawler 作为默认 source path。
```

## M. 后续落地建议

优先级：

```text
P1:
  归档 source-pipeline-final-target-closure。
  将 docs/05 与当前代码长期保持同步。
  对 daily workflow 的真实 source profile 做 smoke/preflight。

P2:
  完成 source-governance-boundary-policy。
  完成 source-health-persistent-store。
  收口 GitHub surfaces / community connectors / source events taxonomy。

P3:
  长期运行 source health worker。
  source cluster report 和 governance report 对齐 Interface 展示。
  source artifact replay 与 lineage 反查接入 Run Inspection。
```

## N. 本轮验证记录

本轮针对 final target closure 补跑：

```text
pytest tests/sources tests/domain/sources tests/core/framework/artifacts/test_source_artifacts.py tests/core/framework/tools/test_source_tools.py tests/workflows/test_daily_intelligence_runner.py tests/workflows/test_daily_intelligence_steps.py -q
  247 passed, 2 warnings

pytest -q
  1142 passed, 2 warnings

openspec validate source-pipeline-final-target-closure --strict
openspec validate --all --strict
```
