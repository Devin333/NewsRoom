# PRD：Research Paper Intelligence Backend v1

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 产品名称 | Research Paper Intelligence Backend |
| 版本 | v1 |
| 所属产品 | Agora Hub |
| 负责模块 | `backend/research` |
| 文档落点 | `openspec/changes/research-paper-catalog-backend-v1/prd.md` |
| 业务参考 | Papers with Code 的 paper/task/method/dataset/benchmark 组织方式 |
| 前端范围 | 本变更不修改 `frontend` |
| 默认存储 | durable filesystem artifact/catalog store |
| 调用模式 | 有界同步 application call，返回 durable `run_id` |
| 外部依赖边界 | 不依赖 Papers with Code 实时数据库或 API，不执行第三方代码 |

本文是 `research-paper-catalog-backend-v1` 的产品需求文档，约束后续领域模型、application service、ports、infrastructure adapter、HTTP API、CLI、artifact 和测试的实现边界。它描述的是后端业务闭环，不是前端页面设计，也不替换当前 framework/Harness 的基础契约。

## 2. 产品定位

Research Paper Intelligence Backend 将来自 arXiv、OpenReview、DOI/Crossref、publisher、local artifact 和 GitHub 的论文输入，转换为可追溯的结构化论文文档、证据包以及 Paper-with-Code Catalog。

Catalog 借鉴 Papers with Code 的信息组织方式，把 `paper` 连接到 `task`、`method`、`dataset`、`benchmark`、`metric`、`score` 和 `code_repository`。它只把 Papers with Code 作为产品信息架构参考，不抓取或复制其实时数据库，不把其站点或 API 当作事实来源。Agora Hub 的事实来源必须能回溯到自身保存的 `ResearchSourceSnapshot`、document locator、artifact checksum 和 provenance。

业务结果的最低保证不是“模型生成了一段论文摘要”，而是：

1. 输入来源和论文身份可识别、可合并、可审计。
2. 解析结果能够定位回原始来源中的章节、页码、图表、公式或文本范围。
3. Catalog 关系、benchmark score 和 SOTA claim 有明确状态；候选内容不会伪装成事实。
4. 失败、降级、冲突、重试和隔离都能通过 durable run/event trace 解释。
5. API、CLI 和后续前端使用同一 application contract，不绕过业务编排层。

参考信息架构：[Papers with Code 论文页面示例](https://paperswithcode.com/paper/measuring-coding-challenge-competence-with)。相关论文入口当前可能跳转到 Hugging Face：[Hugging Face Papers](https://huggingface.co/papers/trending)。这些链接只用于说明交互和信息组织，不构成本系统的运行时依赖。

## 3. 产品目标

### 3.1 v1 目标

- 支持 `arxiv`、`openreview`、`doi`/`crossref`、`publisher`、`local`、`github` 等输入类型。
- 对同一论文完成跨来源 identity resolution，保留版本、快照和冲突，而不是静默覆盖。
- 通过统一的 `ParsePaperUseCase` 复用现有解析能力，得到结构化 `ResearchDocument`、chunk manifest、evidence pack、parser attempts 和 quality report。
- 建立 typed Paper-with-Code Catalog，使 paper 与任务、方法、数据集、benchmark、metric、score 和代码仓库成为可查询的关系。
- 从论文表格、正文、caption、代码链接和来源元数据抽取 benchmark/score/SOTA 候选，并用确定性规则验证可比较性。
- 补充 GitHub 仓库的 README、安装、license、examples、training、inference、checkpoint 等可复现性观察，但不执行仓库代码或自动推断“可运行”。
- 为 API、CLI、artifact 和后续 RAG/阅读/问答能力提供稳定、带 provenance 的 JSON contract。
- 在 tenant/user scope 内提供幂等 ingest、故障诊断、重试、降级、历史快照和 durable event trace。

### 3.2 成功指标

| 指标 | 验收目标 |
| --- | --- |
| 论文身份归并 | 同一论文的 arXiv、DOI、publisher 输入归并为同一 canonical identity；不同版本保留独立 snapshot |
| 受限来源行为 | 全文被拒绝或不可访问时只返回 `metadata_only`，不创建虚假的 `parsed` |
| 解析可追溯性 | 每次 parser attempt、fallback、质量分数、失败原因和 source locator 均可读取 |
| 结构保真 | 复杂 LaTeX/PDF fixture 保留 sections、figures、tables、equations、references 和 chunks |
| 幂等性 | 相同 actor scope、canonical identity、source checksum 重复 ingest 不产生重复实体、关系或 artifact |
| Catalog 可信度 | 无 evidence 的关系/score/SOTA claim 不得 `verified`；candidate/conflicting 不进入 leaderboard |
| 协议可比性 | split、unit、direction、dataset version 或 evaluation protocol 不兼容的 score 不横向比较 |
| 隔离 | 不同 tenant/user 不能读取或修改对方的 paper、source、document、catalog、artifact 和 event |
| 接口边界 | API/CLI 只调用 application service，不直接依赖 parser、repository 或具体 infrastructure adapter |
| 变更范围 | `frontend` 无文件变更，`backend/research` 不依赖 legacy `backend/boards/paper_radar` |

## 4. 用户与权限范围

### 4.1 用户角色

| 角色 | 主要任务 | 关键权限 |
| --- | --- | --- |
| 研究人员 | 提交和阅读论文、查看证据、代码观察和 benchmark 候选 | 在自己的 actor scope 内 parse、查询、refresh、导出 |
| Research Engineer | 调查解析质量、修正 source、检查关系和协议兼容性 | 访问被授权 scope，查看 parser attempts、diagnostics 和 candidate |
| 运营人员 | 批量 ingest、重试失败、监控 artifact 和 Catalog | 仅在明确授权的 tenant/project scope 内执行批处理 |
| 集成客户端 | 通过 API/SDK 消费结构化论文和 Catalog | 只能使用公开的 JSON contract，不接触 prompt、secret 或未授权原文 |

### 4.2 Actor scope

所有 application request 都必须解析出不可伪造的 `actor_scope`。v1 的持久化隔离维度固定为 `tenant_id`、`user_id` 和派生的 `memory_namespace`；`project_id`、`workspace_id` 与 service-account 权限属于后续授权层扩展，不在本变更中作为可写入的 Catalog key。请求体中的 scope 只能作为校验输入，不能覆盖认证上下文。

scope 是 identity merge、幂等键、artifact path、查询过滤和 event 写入的一部分。跨 tenant 的相同 DOI 或 URL 只表示外部事实相同，不表示数据可以合并或互读。

## 5. 核心业务场景

### 场景 A：从 arXiv 解析论文

研究人员提交 arXiv URL 或 id。系统解析 arXiv metadata，尝试获取 LaTeX source 或 PDF，创建 source snapshot，解析文档和 chunks，抽取 evidence 与 Catalog candidate，返回 `run_id`、`paper_id`、状态、quality report 和 artifact refs。若 source 下载受限，仍可返回结构化 metadata，但状态必须为 `metadata_only` 或 `degraded`。

### 场景 B：用 DOI/出版社来源补充同一论文

用户提交 DOI 或 publisher URL。系统首先解析 DOI/Crossref metadata，再按照 canonical URL 和可解释的标题/作者/年份指纹与现有 identity 匹配。冲突字段保留来源和诊断，不能覆盖已有值。若 publisher 全文受到 robots、登录、大小或超时策略限制，则只新增 source snapshot 和 metadata observation。

### 场景 C：复杂论文的结构化阅读

用户提交 local PDF 或 LaTeX archive。系统使用对应 parser，持久化 sections、figures、tables、equations、references、source locator 和 chunk manifest。PDF cascade 必须保留所有尝试，即使最终使用降级后端。质量不足时返回 `degraded`，不能以空 document 标记 `parsed`。

### 场景 D：从表格发现 benchmark 结果

系统从正文、表格、caption 和脚注生成 score candidate。每个 candidate 记录 paper、dataset、benchmark、metric、split、unit、direction、evaluation protocol、数值和 evidence refs。确定性 gate 检查实体完整性和协议兼容性；缺字段或有冲突的 candidate 不进入 verified leaderboard。

### 场景 E：检查代码仓库可复现性信号

论文包含一个或多个 GitHub URL。系统获取仓库 metadata 和允许范围内的 README/文件清单，记录 branch、commit/release、安装说明、依赖文件、examples、training、inference、checkpoint、license 等 observation。系统不执行第三方代码、不自动安装依赖，也不把 README 中的承诺直接当作“复现成功”。

### 场景 F：重复 ingest 与 refresh

相同来源重复提交时，系统依据 actor scope、canonical identity、source key 和 checksum 幂等返回既有结果。`refresh` 是真实的重新获取、重新解析和重新构建 Catalog candidate 的 application operation；它不能只复制一条“成功”记录，也不能删除历史 snapshot 和旧 leaderboard observation。

## 6. 范围

### 6.1 必须交付

- Source resolver、source snapshot、content checksum 和 provenance。
- `ResearchPaperIdentity`、identity resolution/merge、版本和冲突诊断。
- `ParsePaperRequest`、`ParsePaperResult`、`ParsePaperUseCase`。
- LaTeX、PDF、HTML/OpenReview、publisher 和 local artifact 的分层解析与降级。
- `ResearchDocument`、sections、figures、tables、equations、references、chunks、evidence pack、parser attempts、quality report 的持久化。
- `ResearchPaperCatalogEntry`、`ResearchPaperRelation`、Catalog query/repository ports。
- Paper 与 task、method、dataset、benchmark、metric、score、code repository 的 typed 关系。
- 复用已有 `ResearchBenchmark`、`ResearchDataset`、`ResearchMetric`、`ResearchScore`、`ResearchBaseline`、`ResearchSOTAClaim`、`ResearchMethod` 和 `MethodGraph` 的稳定领域语义；若现有模型缺少本 PRD 所需的 provenance、scope、version 或 verification 字段，必须做向后兼容的 contract migration，不能把缺口藏进 `metadata`。
- GitHub repository enrichment 与可复现性 observations。
- benchmark candidate、conflicting、verified gate，协议兼容性和 leaderboard filtering。
- application facade、HTTP API、CLI、JSON/OpenAPI contract、统一错误 envelope。
- tenant/user isolation、幂等 ingest、durable run/event transcript 和 filesystem artifact/catalog store。
- fixture、unit、contract、architecture、integration 和端到端验收测试。

### 6.2 明确不包含

- 不修改 `frontend`，不添加前端专用兼容字段以掩盖后端模型缺失。
- 不重新实现已有 parser cascade、RAG retrieval、arXiv connector、GitHub basic connector、Paper Card 或 Reader；新 application use case 只复用它们提供的能力，通过 ports 注入。现有组件不是完整的 v1 闭环：source resolver、跨来源 identity、durable Catalog store、统一 `ParsePaperUseCase` 和新的 provenance/quality contract 仍需建设。
- 不执行第三方仓库代码，不自动安装未知依赖，不建设代码复现平台。
- 不直接抓取或依赖 Papers with Code 实时数据库、排行榜或 API。
- 不允许 LLM 决定 workflow routing、parser fallback、quality pass/fail、leaderboard ranking、publication、memory write 或 actor scope。
- 不把所有 Catalog 关系塞进 `ResearchPaper.metadata`、`ResearchPaperCard` 字符串字段或不可查询的 JSON blob。
- 普通 business run 不直接更新 active skill package 或 memory；repair experience 按现有 Harness/memory workflow 处理。
- v1 不承诺异步分布式调度；application call 有界同步，保留后续接入 scheduler 的扩展点。

## 7. 架构原则与模块边界

### 7.1 运行路径

```text
HTTP API / CLI / SDK
        |
        v
interfaces/services (request mapping, actor context, response envelope)
        |
        v
application (ParsePaperUseCase, CatalogQuery, Refresh, Compare)
        |
        v
domain (identity, document, relation, evidence, score, validation gates)
        |
        v
ports (source, parser, artifact, catalog, event, GitHub, clock)
        |
        v
infrastructure adapters (arXiv/OpenReview/DOI/publisher/local/GitHub/filesystem)
```

既有的业务运行路径仍遵循 `source collection -> evidence -> agent analysis -> report -> quality gate -> artifacts/storage`。本 PRD 增加论文结构化和 Catalog 投影，但不把 parser 或 store 直接暴露给接口层。

### 7.2 模块职责

| 模块 | 允许职责 | 禁止职责 |
| --- | --- | --- |
| `backend/research/domain` | 值对象、实体、状态、确定性规范化、identity merge、relation/score gate | HTTP、文件路径拼接、网络请求、LLM prompt |
| `backend/research/application` | 用例编排、事务边界、幂等、phase transition、权限 gate、错误映射 | 直接依赖具体 HTTP client、filesystem SDK 或 parser 实现 |
| `backend/research/ports` | source/parser/artifact/catalog/event/GitHub 的抽象接口 | 业务决策和绕过 application 的快捷实现 |
| `backend/research/document` | document model、locator、chunk/evidence projection、parser result normalization | source fetch、leaderboard ranking |
| `backend/research/benchmark` | score/claim candidate、protocol compatibility、verification 和 leaderboard filtering | 以 LLM 结果替代 deterministic gate |
| `infrastructure` | 具体 fetch、parser adapter、GitHub/HTML/PDF/LaTeX、filesystem store、retry policy | 私自改变业务状态或 actor scope |
| `interfaces/services` | DTO mapping、actor context、调用 application、统一 response/error | 直接调用 parser、repository 或 infrastructure |
| API router / CLI | 参数解析、序列化、退出码、分页/过滤参数 | 业务编排、identity merge、score verification |

本表描述的是 v1 的目标边界，不等同于当前代码已经全部满足。兼容性审查以 `HEAD 43e0f6896a` 为基线；审查结论和迁移动作见第 27 节。实现时保留现有 analyze/reader/RAG 路径，在其旁边增加独立的 Parse/Catalog application facade，避免用新 contract 破坏既有调用者。

### 7.3 Harness 与 LLM 边界

Harness 是流程控制者，遵循有界 `PLAN -> EXECUTE -> VERIFY` 状态机，记录每次 phase transition、retry、degrade、conflict、quarantine 和 publication event。LLM 只能生成候选的 method、taxonomy、benchmark claim、code alignment 或实体链接；它不能决定：

- 是否走哪个 source/parser/fallback 路由；
- quality report 是否通过、paper 是否 `parsed`；
- score 是否 verified、谁是 SOTA、leaderboard 排名；
- 是否写入 memory、发布 Catalog 或改变 actor scope；
- 是否授权工具、读取 secret、执行代码或跳过 evidence gate。

确定性函数/service 负责 identity resolution、normalization、schema 校验、lineage、metric compatibility、relation validation、leaderboard filtering 和所有状态转移。

## 8. 领域模型

以下模型是 v1 的目标 typed entity/value object contract，不能退化为 `ResearchPaper.metadata` 中的字符串集合。字段名称是 JSON contract 的逻辑名称；具体 Python 类型和存储实现由 change tasks 决定。第 27 节会标出哪些字段可以直接复用当前模型、哪些字段必须通过 migration 新增；未标为“已有”的字段不能在实现计划或发布说明中写成现成功能。

### 8.1 `ResearchSourceSnapshot`

记录某次获取到的来源事实，创建后不可原地修改，refresh 通过新 snapshot 表示。

| 字段 | 说明 |
| --- | --- |
| `snapshot_id` | source snapshot 唯一标识 |
| `paper_id` | 关联 canonical paper |
| `source_type` | `arxiv`、`openreview`、`doi`、`crossref`、`publisher`、`local`、`github`、`manual` |
| `canonical_url` | 规范化 URL；local source 可使用受控 artifact URI |
| `external_id` | arXiv/DOI/OpenReview/repository 等外部 id |
| `content_type` | `latex`、`pdf`、`html`、`json`、`metadata`、`repository_snapshot` 等 |
| `source_hash` / `checksum` | 内容或 metadata snapshot 的完整性校验值 |
| `fetched_at` | 获取时间；与论文发布时间区分 |
| `access_status` | canonical coarse status：`available`、`metadata_only`、`denied`、`failed` |
| `diagnostic.reason_code` | 细分原因，如 `rate_limited`、`not_found`、`unsupported_format`、`timeout`、`robots_disallowed`、`size_exceeded`；不能把细分原因伪装成新的 canonical status |
| `lineage` | 上游来源、resolver、parent snapshot、request/run 信息 |
| `artifact_refs` | 原始内容和派生 artifact 的引用 |
| `metadata` | 非核心、受 schema 约束的来源观察 |
| `actor_scope` | 目标 contract 中的规范化 `tenant_id`、`user_id`、`memory_namespace`；当前部分旧模型仍把 scope 放在 `metadata`/`lineage`，迁移后必须提升为可过滤的 typed scope |

### 8.2 `ResearchPaperIdentity`

统一表示论文身份，不等同于某一个来源快照。现有基线已经有基础 identity/fingerprint 类型，但 canonical version、source snapshot refs、conflict diagnostics 和 typed actor scope 的完整生命周期仍属于本 change 的目标 contract。

至少包含：`paper_id`、`canonical_title`、`authors`、`publication_year`、`canonical_url`、`arxiv_id`、`doi`、`openreview_id`、`versions`、`external_links`、`source_snapshot_refs`、`title_author_year_fingerprint`、`metadata_conflicts` 和 `actor_scope`。

identity merge 规则：

1. 同 actor scope 内，优先依据相同 external id（DOI、arXiv、OpenReview）合并。
2. external id 缺失时，依据 canonical URL 合并。
3. 仍无法匹配时，才使用规范化标题、作者集合和年份的可解释指纹；指纹匹配必须记录规则和相似度/缺失字段。
4. 版本号、发布日期或内容 checksum 不同时，保留独立 source snapshot；如果产品需要区分版本，使用 `paper_id + version_id` 查询，不能覆盖历史版本。
5. 标题、作者、年份、摘要等字段冲突必须记录 `conflict_diagnostics` 以及每个值的 provenance，不得静默选择“最后写入者”。
6. 不同 actor scope 永不合并，也不允许用查询结果推断对方 scope 的存在。

### 8.3 `ResearchDocument`

表示某个 source snapshot 解析得到的结构化论文文档，至少包含：

- `document_id`、`paper_id`、`source_snapshot_id`、`source_hash`；
- `title`、`abstract`、`authors`、`sections`、`figures`、`tables`、`equations`、`references`；
- 每个元素的稳定 id、顺序、父子关系、原始 locator、文本和 content hash；
- parser backend、parser version、normalization version、language 和 extraction metadata；
- source lineage、artifact refs、created_at、observed_at 和 actor scope。

locator 至少支持 source type 对应的 `page`、`section_path`、`figure_id`、`table_id`、`equation_id`、`line_start/line_end`、HTML anchor 或 LaTeX source file/offset。无法精确定位时必须显式标记 `locator_precision=coarse`。

### 8.4 `ParserAttempt`

每个 parser backend 的尝试都必须持久化，不论成功、失败还是被跳过：

`attempt_id`、`document_id`、`backend`、`input_format`、`started_at`、`finished_at`、`duration_ms`、`status`、`quality_score`、`selected`、`fallback_reason`、`error_code`、`diagnostics`、`artifact_refs` 和 `actor_scope`。当前 `CascadeDocumentParser` 已能产生基础 attempt/quality 信息，但 attempt 的 durable schema、document 关联和 actor scope 需要由 Parse application 持久化。

禁止吞掉异常或只保留最终 backend。诊断中不得包含 secret、prompt、访问 token 或未授权的原始代码内容。

### 8.5 `ResearchEvidencePack`

证据包把结构化 claim 连接回来源：

`evidence_id`、`paper_id`、`claim_type`、`claim_text`、`source_snapshot_id`、`document_id`、`element_ref`、`locator`、`quote_or_span`、`claim_refs`、`confidence`、`lineage`、`created_at`、`actor_scope`。

证据可以来自标题/摘要、正文段落、表格单元格、caption、脚注、代码链接、metadata 或 GitHub observation。没有 evidence ref 的关系、score、SOTA claim 和 method graph edge 一律不能进入 `verified`。现有 evidence/domain builder 可复用其基础结构，但本 change 要补齐 source snapshot、document/element locator、checksum 和 durable pack ref。

### 8.6 `ChunkManifest`

chunk 是 RAG、阅读和问答的可复用投影，不是 document 的替代品。每项至少包含：`chunk_id`、`paper_id`、`document_id`、`source_hash`、`chunk_type`、`section_path`、`parent_element_ref`、`content_hash`、`content_ref`、`source_locators`、`semantic_key`、`parse_source`、`stale_of` 和 `actor_scope`。

source hash 变化时，旧 chunk 保留为历史，新的 manifest 通过 `stale_of` 或版本关系标记，不能让同一个 chunk id 指向不同内容。现有 chunk pipeline 主要服务 arXiv/RAG 重建；v1 必须在 Parse application 中把 manifest 作为带 scope、source snapshot 和 artifact ref 的持久化投影，而不是把一次重建当作完整历史。

### 8.7 `ResearchPaperCatalogEntry`

Catalog entry 是一个 paper 的聚合查询投影，至少包含：`entry_id`、`paper_id`、`identity_ref`、`status`、`relation_refs`、`source_snapshot_refs`、`evidence_coverage`、`created_at`、`observed_at`、`last_refresh_run_id`、`metadata` 和 `actor_scope`。

`ResearchPaperCard` 只能作为展示 projection。Catalog 的事实必须来自 typed entities 和 typed relations；卡片字段丢失的信息不能反向作为 Catalog 事实。

### 8.8 `ResearchPaperRelation`

关系字段：`relation_id`、`paper_id`、`relation_type`、`target_id`/`target_ref`、`status`、`confidence`、`source_snapshot_refs`、`evidence_refs`、`created_at`、`observed_at`、`observed_by`、`metadata`、`actor_scope`。当前关系模型对 refs 的约束偏向“所有状态都必须有 refs”，v1 需要迁移为 candidate-first 语义：候选可以暂缺 evidence，但必须保留缺失诊断；只有 verified 才强制 source/evidence refs。

v1 至少支持：

- `paper -> task`
- `paper -> method`
- `paper -> dataset`
- `paper -> benchmark`
- `paper -> metric`
- `paper -> score`
- `paper -> code_repository`

relation status 至少包括 `candidate`、`verified`、`rejected`、`conflicting`。candidate 不代表产品认定事实；conflicting 不得被查询层默认为 verified。

### 8.9 `CodeRepositoryProfile`

支持一个 paper 对多个 repository：

`repository_url`、`canonical_repo_id`、`owner`、`name`、`default_branch`、`observed_branch`、`commit_sha`、`release`、`observed_at`、`stars`、`forks`、`watchers`、`license`、`readme_ref`、`requirements_ref`、`install_signal`、`examples_signal`、`training_signal`、`inference_signal`、`checkpoint_signal`、`observations`、`source_snapshot_refs` 和 `actor_scope`。

这些字段表示 observation/evidence，不表示代码已经安装、运行或复现论文结果。缺少 README、依赖或 checkpoint 是“未观察到信号”，不能直接判定项目不可复现。

## 9. Source、snapshot 与身份解析

### 9.1 输入类型

| `source_type` | 典型输入 | 主要事实 |
| --- | --- | --- |
| `arxiv` | arXiv URL/id | metadata、PDF、可选 LaTeX source、版本 |
| `openreview` | forum/note URL/id | note metadata、HTML、评论/版本观察（按授权） |
| `doi`/`crossref` | DOI URL 或 DOI 字符串 | DOI metadata、publisher link、发表信息 |
| `publisher` | publisher URL | 页面 metadata、HTML/PDF（受访问策略约束） |
| `local` | 受控 local path 或 contentRef | local PDF/LaTeX/archive，需 path/size 校验 |
| `github` | repository URL | repository profile 和 code observation |
| `manual` | 已授权的结构化输入 | 人工确认或外部导入的 provenance |

### 9.2 Source resolver 行为

1. 规范化 URL、external id 和 content reference。
2. 检查 actor scope、robots、访问策略、超时、重试、最大响应大小和 content type。
3. 先获取可用 metadata，再决定是否请求全文或 repository snapshot。
4. 每次获取生成不可变 `ResearchSourceSnapshot`，并记录 lineage 和 checksum。
5. 访问拒绝、限流、缺失、unsupported format 和网络错误都返回明确 `access_status`/diagnostic。
6. 全文不可访问时，允许后续 Catalog 使用 metadata candidate，但状态只能是 `metadata_only`，不能伪装为 `parsed`。
7. 复用现有 infrastructure policy；`backend/research` 不复制一套 robots/rate-limit/retry 规则。

canonical status 的映射固定为：权限/robots 或明确拒绝使用 `denied`；仅有元数据使用 `metadata_only`；可重试的限流、超时和临时网络故障使用 `failed` 并在 diagnostics 标记 `retryable=true`；格式不支持、资源不存在或永久错误使用 `failed` 并标记对应 `reason_code`。这样 API/CLI 可以同时稳定地按 status 过滤，又不会丢失运维诊断粒度。

### 9.3 Snapshot 生命周期

- snapshot 是事实快照，refresh 创建新 snapshot。
- 同一 checksum 的重复 snapshot 可以被幂等复用，但必须能关联新的 run 请求。
- 内容或 metadata checksum 变化时创建新 snapshot，旧 snapshot 保留历史并标记 superseded/observed history。
- parser、document、chunk、evidence 和 Catalog relation 都要写入使用的 snapshot ref。
- snapshot artifact 缺失或 checksum 不一致时，读取返回 `store_corrupt`/`artifact_missing` 诊断，不静默重新生成历史事实。

### 9.4 与现有 source connector 的兼容

当前代码已有 arXiv metadata/source provider、fetch policy、robots/rate-limit/retry 和 GitHub 基础 client。它们可作为 infrastructure adapter 的输入，但不能直接充当 v1 的 source resolver contract：现有 arXiv provider 不覆盖 OpenReview、DOI/Crossref、publisher 和 local artifact，也不会替代跨来源 identity merge。新增 resolver 必须把各 adapter 的异常映射为本节定义的 canonical `access_status` 加 `diagnostic.reason_code`，并由 application 统一创建 snapshot；adapter 不得自行写 Catalog 或改变 paper status。

## 10. 论文解析与质量策略

### 10.1 Application use case

新增：

- `ParsePaperRequest`
- `ParsePaperResult`
- `ParsePaperUseCase`

它与已有完整分析流程分离，但输出可以被后续分析、阅读、RAG 和 Harness run 消费。application 负责顺序、权限、幂等和持久化；parser 只负责把输入转成 parser result，不直接写 Catalog 或改变 workflow 状态。当前代码没有统一的 `ParsePaperUseCase`；已有 `BatchIngestService`/chunk pipeline 是 arXiv 特化的 RAG 入库路径，不能直接当作本节 use case。新 use case 应通过 ports 编排 source resolver、LaTeX/PDF/HTML parser、document/evidence/catalog repositories 和 event sink。

### 10.2 请求处理流程

```text
received
  -> resolving
  -> identity resolution / merge
  -> source snapshot persistence
  -> metadata_only 或 parsing
  -> parser attempts / fallback
  -> document persistence
  -> chunk manifest projection
  -> evidence pack persistence
  -> Catalog candidate projection
  -> deterministic gates
  -> catalog_partial 或 catalog_ready
```

每个箭头都要产生 durable event；异常通过受控 retry、degrade 或 halt 处理。application call 必须有最大执行时长、最大 source size、最大 parser attempts 和 retry budget。

### 10.3 Parser 路由

| 输入 | 首选 parser | fallback/结果 |
| --- | --- | --- |
| LaTeX source/archive | `LatexSourceParser` | 失败后尝试可用 PDF；仍失败则 `degraded`/`metadata_only` |
| PDF URL/artifact | `CascadeDocumentParser` | 保留每个 backend attempt；低质量则 `degraded` |
| HTML | `HtmlDocumentParser`（新增确定性 adapter） | document adapter 或 metadata-only |
| OpenReview | OpenReview HTML/document adapter（新增 source adapter） | metadata-only；按授权处理 revision |
| publisher HTML/PDF | publisher/document adapter（新增 source adapter） | robots/登录/大小受限时 metadata-only |
| local PDF | 同一 `CascadeDocumentParser` | local path/size/format 校验失败时明确失败 |
| local LaTeX | `LatexSourceParser` | 可选 PDF fallback |
| 不支持的二进制 | 无 | `failed`，`unsupported_format` |

### 10.4 Quality report

质量报告至少包含：

- parser backend、attempt 列表和选中原因；
- section/figure/table/equation/reference/chunk 数量；
- locator 覆盖率和 source hash；
- metadata、abstract、正文和表格的缺失项；
- quality score、质量阈值、degraded 标记；
- fallback、拒绝或不支持原因；
- 可重试性、用户行动建议和诊断 id。

质量策略：

1. 低质量 document 只能标记 `degraded`，不能创建空的 `parsed`。
2. 只得到 metadata 时使用 `metadata_only`，并明确说明没有全文结构。
3. parser exception 必须可见；不得在 catch 后返回默认空列表。
4. 质量 gate 是 deterministic service，LLM 输出只能作为 candidate 或补充 evidence。
5. Catalog 允许在有 metadata 的情况下进入 `catalog_partial`，但只有所有必需关系和 gate 通过时才能 `catalog_ready`。

## 11. Paper-with-Code Catalog

### 11.1 Catalog 构建

Catalog projection 从以下事实产生：

- paper identity 和 metadata；
- document sections/tables/captions；
- evidence pack；
- 现有 method/dataset/benchmark/metric/score/baseline/SOTA domain entities（复用其稳定字段，补齐本 change 所需的 typed refs/scope/protocol）；
- GitHub repository observations；
- 人工确认或外部导入的 provenance。

所有自动抽取关系默认 `candidate`。candidate 可以在证据尚未补齐时保留，但必须带 `evidence_missing` 或其他缺口诊断；只有 schema、identity、lineage、evidence、actor scope 和 domain compatibility gate 通过后，关系才可变为 `verified`。gate 失败时使用 `rejected` 或 `conflicting`，并保留原 candidate 和 diagnostics。

### 11.2 关系查询语义

- 单篇论文查询返回所有关系，默认按 status 分组而不是隐藏 candidate/conflicting。
- `verified` 查询只能返回 source/evidence refs 完整且在当前 actor scope 内的关系；candidate、rejected、conflicting 必须可查询并保留其诊断。
- relation target 必须存在或有明确 external reference；悬空 target 不能 verified。
- 同一 paper、relation type、target、source snapshot 和 observation time 的重复关系幂等。
- 不同 source 对同一关系给出不同 target/value 时，保留多个 observations，并创建 conflict diagnostic。

## 12. Benchmark、score 与排行榜可信度

### 12.1 Score 字段

`ResearchScore` 至少包含（目标 v1 contract）：

`score_id`、`paper_id`、`benchmark_id`、`dataset_id`、`metric_id`、`value`、`baseline_ref`、`status`、`split`、`unit`、`direction`、`evaluation_protocol`、`dataset_version`、`source_snapshot_refs`、`evidence_refs`、`observed_at` 和 `actor_scope`。

### 12.2 Candidate-first

论文正文、表格、caption、脚注和 metadata 中出现的 benchmark 结果先生成 `candidate`。候选至少要保留原始显示值、单位、表头/列名、表格 locator、抽取规则和 normalization diagnostics。LLM 可提出实体映射或 claim，但不能直接生成 verified score。

### 12.3 Verified gate

`verified` 需要同时满足：

1. `paper`、`dataset`、`benchmark` 和 `metric` 都有稳定实体或经人工确认的 external reference。
2. 存在至少一个有效 `evidence_ref`，可定位到正文、表格、caption 或授权 metadata。
3. `split`、`unit`、`direction`、`dataset_version` 和 `evaluation_protocol` 完整。
4. 数值可解析、单位可规范化，且不存在同一来源的 unresolved conflict。
5. actor scope、source lineage、schema 和 relation integrity gate 通过。
6. verified 来源是 deterministic gate 或明确的人工确认，不能由模型置信度单独触发。

缺少任一项保持 `candidate`，并记录缺失字段；同一实体组合出现不可解释的不同值时标记 `conflicting`。`candidate` 和 `conflicting` 永远不得进入 verified leaderboard。已有 score gate 的基础 evidence 校验可以复用，但 source snapshot refs、dataset version、协议字段和 scope 传播需要按本 contract 补齐。

### 12.4 比较兼容性

以下条件任一不兼容，就不能横向比较或合并排名：

- `higher_is_better` 与 `lower_is_better` 方向不同；
- dataset 或 benchmark version 不同；
- split 不同（例如 `test` 与 `validation`）；
- unit 不同且没有确定性转换；
- evaluation protocol、预处理、样本范围或任务定义不一致；
- metric 名称相同但定义、聚合方式或方向不同。

兼容性判断结果要返回具体 `incompatibility_reason`，而不是简单过滤掉结果。

### 12.5 Leaderboard

leaderboard 只展示 verified 且协议兼容的 score，并保留 `observed_at` 快照时间。默认排序依据 metric direction：higher-is-better 降序，lower-is-better 升序。不同 dataset version、split、unit 或 protocol 必须分组展示，不能混成一个排名。

查询结果应包含 `included_scores`、`excluded_scores` 以及每个排除原因。candidate、rejected、conflicting、scope forbidden、缺 evidence 和不兼容 score 都应可诊断。refresh 不覆盖历史结果，历史快照可按时间查询。

### 12.6 SOTA claim

`ResearchSOTAClaim` 只有在关联到 `score`、`benchmark`、`dataset`、`metric`、兼容的 protocol 和 evidence 时才有机会 `verified`。只包含“we achieve state of the art”文字、没有可核对数值或协议的 claim 必须保持 `candidate`；缺少 benchmark/dataset/metric 的不完整 claim 也必须作为 candidate 保留，不能在抽取阶段直接丢弃。SOTA 的认定不能由论文自称或 LLM 判断单独完成。

## 13. GitHub Repository Enrichment

### 13.1 观察范围

允许读取的内容由现有 source/robots/size/授权 policy 决定，至少支持：

- repository metadata、default branch、selected branch、commit SHA、release/tag 和 observed_at；
- README、license、依赖声明或安装说明的受控 artifact ref；
- examples、training、inference、checkpoint/model download 的路径或关键词观察；
- 论文正文中的代码 URL 与 repository canonical id 的对应关系。

### 13.2 安全与语义

- 可存在多个 repository；不能把第一个 URL 当作唯一代码来源。
- 记录 branch/commit/release，避免“当前 main”覆盖论文发表时的历史上下文。
- observations 是 evidence，不代表安装成功、训练成功、推理成功或结果复现。
- 不执行 shell、workflow、container、notebook 或 repository test。
- 不自动安装未知依赖，不读取 secrets，不返回未授权的原始代码内容。
- 访问失败、限流、私有仓库或受限路径要保留 diagnostics 和 source snapshot 状态。

当前 `GithubResearchRepositoryAdapter` 已能读取基础 repository profile/observation（例如 stars、forks、default branch 和 commit/release 的部分信息），但尚未提供 README、安装、examples、training、inference、checkpoint 的 typed observations，也没有把这些观察统一绑定到 paper 的 `ResearchSourceSnapshot`。v1 的 enrichment 应扩展现有 adapter 和 GitHub connector，在受控读取范围内生成 observation/evidence artifact；不能把已有基础 profile 当作完整的可复现性判断。

## 14. API 需求

### 14.1 通用规则

- HTTP router 只负责认证上下文、参数校验、application 调用、状态码和序列化。
- router 不得直接调用 parser、store、GitHub client 或具体 infrastructure adapter。
- 所有 endpoint 返回 `run_id`（若操作产生 durable run），以及 `status`、`diagnostics`、`provenance` 和 `artifact_refs`（按权限过滤）。
- 分页、排序和过滤必须是显式参数；默认不跨 actor scope 查询。
- 不向公开 API 返回 prompt、secret、token、内部绝对路径、未脱敏异常堆栈或未授权原始代码。

### 14.2 Parse request

`POST /api/v1/research/papers/parse`

请求支持：

- `source`：URL、external id 或受控 source descriptor；
- `sourceType`：可选，缺省时由 resolver 确定并记录推断；
- `contentRef`：已上传或已授权的 local artifact ref；
- `runId`：调用方提供的关联 run id（若允许）；
- `options`：parser preference、refresh、includeCode、includeCatalog、quality profile 等；
- `metadata`：用户提供的非权威提示，必须标记为 caller-provided；
- actor scope 由认证上下文提供，不接受客户端覆盖。

响应至少包含：

`runId`、`paperId`、`status`、`paper`、`identity`、`sourceSnapshots`、`document`（可为 ref）、`parserAttempts`、`qualityReport`、`evidencePackRef`、`chunkManifestRef`、`catalogEntry`/`catalogStatus`、`artifactRefs`、`diagnostics`、`provenance`、`idempotent`。

### 14.3 查询与 refresh endpoints

| 方法 | 路径 | 语义 |
| --- | --- | --- |
| `GET` | `/api/v1/research/papers/{paper_id}/sources` | 当前 scope 的 source snapshots、访问状态、checksum、lineage |
| `GET` | `/api/v1/research/papers/{paper_id}/document` | document、结构元素、locators、parser attempts 和 quality |
| `GET` | `/api/v1/research/papers/{paper_id}/catalog` | typed relations、status、confidence、evidence/provenance |
| `GET` | `/api/v1/research/papers/{paper_id}/code` | 多仓库 profile、branch/commit/release 和 observations |
| `GET` | `/api/v1/research/papers/{paper_id}/benchmarks` | score、claim、candidate/verified/conflicting 和兼容性诊断 |
| `GET` | `/api/v1/research/catalog/papers` | 按 query/task/method/dataset/status/scope 分页搜索 |
| `GET` | `/api/v1/research/catalog/leaderboards` | 只按兼容协议聚合 verified score；返回排除原因 |
| `POST` | `/api/v1/research/catalog/refresh` | 对一个或多个 paper 真实重取、重解析、重建 Catalog |

`leaderboards` 至少支持 `benchmarkId`、`metricId`、`datasetId`、`datasetVersion`、`split` 和 `evaluationProtocol` 过滤。refresh 请求必须有权限和 retry budget，并返回新 `run_id` 及历史 snapshot refs。

以上 parse/Catalog endpoints 是 v1 新增 contract；当前 research router 主要提供 `analyze`、`analysis`、`reader`、`ask`、`rag-ask` 和 run trace。新路由必须接入 `ResearchApplicationService` 的新 facade 方法，保持旧路由响应兼容，不把现有 `analyze` handler 改写成 parse handler。

### 14.4 错误 envelope

所有 endpoint 使用统一结构：

`code`、`message`、`details`、`retryable`、`userActionRequired`、`runId`、`paperId`、`provenance`、`diagnosticRefs`。

错误码至少包括：

`invalid_request`、`source_not_found`、`source_denied`、`source_rate_limited`、`source_timeout`、`unsupported_format`、`metadata_only`、`identity_conflict`、`parser_failed`、`parser_quality_rejected`、`catalog_not_found`、`catalog_relation_conflict`、`metric_incompatible`、`scope_forbidden`、`artifact_missing`、`store_corrupt`、`research_runtime_unavailable`。

错误码要区分用户可修复、可重试和系统故障，不能用 `500` 包装所有 source denial 或质量降级。

## 15. CLI 需求

新增命令：

```text
paper parse <source>
paper ingest <source>...
paper refresh <paper_id>
paper catalog show <paper_id>
paper catalog search [query]
paper benchmark compare
paper code inspect <paper_id>
```

所有命令支持 `--json`，并使用与 API 相同的 `status`、错误、provenance、diagnostics、run id 和 artifact ref 字段。批量 ingest 需要逐项返回结果，单项失败不得隐藏其他项的成功或降级状态。

常用参数包括：`--tenant`/`--project`（只能与认证 scope 校验）、`--refresh`、`--source-type`、`--quality-profile`、`--include-code`、`--include-catalog`、`--status`、`--benchmark`、`--dataset`、`--metric`、`--split`、`--protocol`、`--limit`、`--cursor` 和 `--json`。CLI 只调用 application facade，不直接 import parser 或 store 实现。

退出码应区分：参数错误、scope 禁止、source 不可用、metadata-only/degraded、解析失败、Catalog gate 失败、存储错误和成功；`--json` 输出仍要包含完整错误 envelope。

这些是 v1 目标命令。当前 CLI 已有的 `paper ingest`/`paper ask` 仍服务既有 arXiv/RAG 流程；迁移时应新增 parse/catalog 子命令并把旧 ingest 逐步改为 application facade，不能让新命令直接实例化 `BatchIngestService`、chunk store 或 GitHub client。

## 16. 状态机与 durable event

### 16.1 统一状态

论文 run/aggregate 的状态固定为：

`received`、`resolving`、`metadata_only`、`parsing`、`parsed`、`degraded`、`catalog_partial`、`catalog_ready`、`failed`。

### 16.2 合法路径

- 正常全文路径：`received -> resolving -> parsing -> parsed -> catalog_partial -> catalog_ready`。
- metadata 路径：`received -> resolving -> metadata_only -> catalog_partial`。
- 解析降级路径：`parsing -> degraded -> catalog_partial`。
- 可重试 source/parser 错误：当前状态记录失败诊断，按 retry budget 回到允许的 phase；耗尽后 `failed`。
- 不支持、scope forbidden、artifact corrupt 或不可恢复错误：进入 `failed`，不伪造 `parsed`。

状态转移必须由 application/Harness 控制，domain service 校验合法性。LLM 输出不能改变状态。

### 16.3 Event schema

每个 phase transition、retry、degrade、conflict、quarantine、verification 和 publication event 至少包含：

`event_id`、`run_id`、`event_type`、`from_status`、`to_status`、`occurred_at`、`paper_id`、`source_snapshot_id`、`actor_scope`、`attempt_id`、`diagnostics`、`artifact_refs`、`causation_id` 和 `correlation_id`。

event log append-only，可用于 replay/review。event 写入失败是 durable runtime error，不得静默忽略。

## 17. 幂等、持久化与 artifact

### 17.1 幂等键

默认幂等键由以下字段规范化后组成：

`actor_scope + canonical identity key + source type + external id/canonical URL + source checksum`。

同一 key 重复 ingest 应返回既有 paper/run/artifact 结果或明确的 in-progress run，而不是复制实体。不同 checksum 或明确 refresh 生成新 snapshot 和新派生 artifact，但不删除历史。

### 17.2 默认 filesystem store

v1 使用 durable filesystem artifact/catalog store，具体布局由 infrastructure 实现决定，但必须满足以下条件。当前已有 `filesystem_run_store`、artifact store 和 local chunk store 只能作为底层原语，不能视为已经存在的 Catalog persistence；本 change 仍需新增 typed Catalog/document/source/evidence store 及 schema migration：

- JSON/JSONL 或等效结构化格式可检查、可备份、可恢复；
- paper、identity、snapshot、document、chunk、evidence、relation、score、catalog 和 run/event 有稳定 refs；
- artifact 记录 checksum、content type、schema version、created_at、source lineage 和 actor scope；
- event/transcript append-only，历史 snapshot 不被新 refresh 覆盖；
- 读取时校验 checksum、scope 和 schema version；损坏返回 `store_corrupt`；
- repository port 与 filesystem adapter 分离，后续可替换数据库而不改 application/domain。

### 17.3 事务与恢复

application 必须先持久化 source/run intent，再写派生 artifact 和状态 event。中途失败后可以通过 durable run 恢复、重试或明确标记失败，不留下“catalog_ready 但没有 document/evidence”的不可解释状态。跨 artifact 的最终一致性要由 event 和 idempotency key 保证。

## 18. 安全、隐私与隔离

- actor scope 从认证上下文解析；客户端不能伪造 tenant/user/project。
- 所有读写、merge、refresh、artifact download、event query 都执行 scope gate。
- source fetch 遵守 robots、rate-limit、timeout、size、content-type、retry 和许可策略。
- local path 必须限制在允许 root，拒绝路径穿越、符号链接逃逸和超大文件。
- 不执行第三方代码、仓库 workflow、notebook 或未知安装脚本。
- secrets、token、prompt、原始未授权代码、内部绝对路径和未脱敏堆栈不得进入公开 API、artifact export 或 diagnostics。
- GitHub/private/publisher 访问失败只暴露可行动的 sanitized reason。
- artifact ref 是 capability-like reference，下载前再次验证 actor scope 和授权。
- 不因解析内容中的 prompt injection 改变 workflow、工具授权、quality gate、publication 或 memory write。

## 19. 可观测性与诊断

至少记录并可按 `run_id`/`paper_id` 查询：

- source fetch 成功、metadata-only、denied、rate-limited、retry 和 timeout；
- identity match、merge、version separation 和 field conflict；
- parser backend、attempt duration、fallback、quality score、degraded 和 rejected；
- document element/chunk/evidence coverage；
- candidate、verified、rejected、conflicting relation/score/claim；
- metric/dataset/split/protocol 不兼容与 leaderboard exclusion；
- GitHub repository enrichment 和 observation 缺失；
- duplicate ingest、scope forbidden、artifact missing、checksum mismatch 和 event write failure；
- Harness phase transition、retry/replan/halt（按现有 durable transcript contract）。

诊断信息要区分 `cause`、`impact`、`retryable`、`user_action` 和 `provenance`。错误报告可以详细，但必须在接口边界做脱敏。

## 20. 非功能需求

| 类别 | 要求 |
| --- | --- |
| 性能 | v1 为有界同步调用；配置最大 source size、parser attempts、单次 run 时长和 retry budget |
| 可靠性 | source、parser、artifact、Catalog 和 event 失败均有显式状态与可恢复诊断 |
| 可追溯性 | 每个派生结果能回到 source snapshot、document locator、checksum 和 run |
| 一致性 | identity、relation、score、artifact 和 event 的写入使用稳定 idempotency key |
| 可测试性 | domain gate 可纯函数测试；ports 可用 fake；application 可用 in-memory store；不依赖网络才能运行核心测试 |
| 可替换性 | parser、source、GitHub、catalog store 通过 ports 替换，application 不绑定具体实现 |
| 安全 | actor isolation、路径/大小/robots policy、敏感信息脱敏和禁止代码执行 |
| 可演进性 | schema version、artifact refs、事件 replay 和未来异步 scheduler 扩展点 |
| 兼容性 | 保留 framework Graph/Harness contracts；不引入 legacy `paper_radar` 依赖 |
| 前端 | 本变更不得修改 `frontend` |
| 外部服务 | 不依赖 Papers with Code 实时服务；外部 source adapter 可失败且必须可诊断 |

## 21. 测试与验收标准

### 21.1 Source 与 identity

- arXiv、DOI 和 publisher 指向同一论文时归并为一个 canonical identity。
- 同一论文不同版本保留独立 snapshot，历史 checksum 和 provenance 可查询。
- 标题/作者/年份冲突产生 diagnostics，不静默覆盖。
- 受限 publisher 返回 `metadata_only`/`denied`，不产生虚假 `parsed`。
- 不同 actor scope 的相同 external id 不合并，且不能互查。
- 重复 ingest 不重复创建 paper、identity、snapshot、document、relation、evidence、chunk 或 artifact。
- 同一 checksum 的重复请求可以复用已有 snapshot，但必须新增 run 关联；refresh 不能删除历史 snapshot。

### 21.2 Parser 与 document

- 复杂 LaTeX fixture 保留章节、图、表、公式、引用、source locators 和 source hash。
- PDF cascade 记录所有 attempts、选中 backend、fallback reason 和 quality report。
- 低质量或 unsupported format 进入 `degraded`/`metadata_only`/`failed`，不返回空 `parsed`。
- HTML/OpenReview/publisher adapter 能保留可用 metadata、正文 locator 和访问限制诊断。
- chunk manifest 的 content hash、parent ref 和 stale version 正确；evidence 能定位正文、表格、figure/caption。
- 受限全文、unsupported format 和 parser denial 都保留 parser/source diagnostics，不以空 document 伪装成 `parsed`。

### 21.3 Catalog 与 benchmark

- Catalog 使用 typed entities/relations，不把关系塞进 metadata/card 字符串。
- 自动抽取 relation、score、SOTA claim 默认 candidate。
- candidate relation 可以暂时没有 evidence refs，但必须保留 source context（若可得）和 `evidence_missing` 诊断；只有 verified relation 强制 evidence refs。
- 无 evidence refs 的 score、SOTA claim 和 method graph edge 一律不能 verified。
- candidate/conflicting/rejected score 不进入 leaderboard，排除原因可查询。
- higher/lower direction、dataset version、split、unit 和 protocol 不兼容时不能横向比较。
- leaderboard 只展示 verified 且兼容的历史快照；排序符合 metric direction。
- SOTA claim 缺少 score、benchmark、dataset、metric 或 evidence 时保持 candidate。
- 缺少 benchmark/dataset/metric 的 SOTA 文本不会被抽取器静默丢弃，能够在 candidate 查询中定位其缺口。

### 21.4 Code enrichment

- 同一论文的多个 repository 都能保存并查询。
- branch、commit、release、observed_at 和 README/install/examples/training/inference/checkpoint signals 可追溯。
- 只记录 observation/evidence，不执行第三方代码、不自动安装依赖、不宣称复现成功。

### 21.5 Interface 与架构

- API/CLI 通过 application service 工作，不 import/调用具体 parser、store 或 infrastructure adapter。
- API 和 CLI 使用相同 status、error、provenance、run 和 artifact 字段。
- `catalog refresh` 会产生真实新 run/snapshot 或明确失败，不返回静态成功。
- 旧 arXiv-specific batch ingest 不能删除历史 source snapshot、document 或 relation；迁移后的 ingest 必须通过同一 application facade。
- durable event 能解释 phase transition、retry、degrade、conflict 和 verification。
- `frontend` 无文件变更。
- `backend/research` 不依赖 legacy `backend/boards/paper_radar`、旧 `interfaces` 或具体 `infrastructure` 路径。

## 22. 交付阶段

### 阶段 1：契约阶段

- 创建并维护 OpenSpec change。
- 冻结 DTO、status、error、provenance、actor scope、artifact ref 和 event schema。
- 准备 LaTeX/PDF/HTML/OpenReview/publisher/multi-source/restricted/duplicate fixture。
- 完成 `openspec validate research-paper-catalog-backend-v1 --strict`。

### 阶段 2：解析阶段

- 完成 source resolver、identity merge、source snapshot、`ParsePaperUseCase`。
- 接通 parser ports 和现有 LaTeX/PDF/HTML adapter。
- 持久化 parser attempts、quality report、document、chunks、evidence、artifact 和 events。
- 完成 metadata-only、degraded、unsupported、retry 和 idempotency 测试。

### 阶段 3：Catalog 阶段

- 完成 Catalog entry/relation aggregate 和 query repository。
- 接入已有 benchmark/dataset/metric/score/method domain entities。
- 完成 GitHub enrichment、多仓库、snapshot 和 observation schema。
- 完成 candidate/verified/conflicting gates、协议兼容性和 leaderboard history。

### 阶段 4：接口阶段

- 完成 application facade、HTTP endpoints、CLI、OpenAPI/JSON contract。
- 完成统一错误 envelope、分页/过滤、actor isolation 和 API/CLI 一致性。
- 验证 API/CLI 不绕过 application service。

### 阶段 5：发布阶段

- 运行端到端回归、故障降级、重复 ingest、scope isolation 和 artifact recovery。
- 检查 durable transcript/event replay、文档同步和 schema version。
- 运行全部本地检查并进行 strict OpenSpec validation。
- 保证 `frontend` 无文件变更后再发布后端 change。

## 23. 验证命令

```powershell
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
openspec validate research-paper-catalog-backend-v1 --strict
```

`smoke` 是代码变更的必过门槛，应覆盖 compile、Harness/Research/API/service smoke、`tests/architecture` 和 source validation。文档变更至少执行 Markdown/结构检查、OpenSpec strict validation，并在涉及代码时追加上述完整检查。

## 24. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| publisher 访问受限 | 无全文、结构化结果不完整 | metadata-only、明确 access status、保留 snapshot 和可重试诊断 |
| PDF 解析质量不稳定 | 表格/公式/locators 缺失 | cascade attempts、quality gate、degraded 状态和人工复查入口 |
| 同名论文或元数据冲突 | identity 错合并、事实覆盖 | external id 优先、解释性指纹、版本独立、冲突 provenance |
| benchmark 表格语义复杂 | leaderboard 错排 | candidate-first、协议完整性 gate、兼容性分组、排除原因可见 |
| GitHub 内容变化 | 复现信号过时 | branch/commit/release snapshot、observed_at、历史保留 |
| LLM 产生无证据结论 | 错误关系进入 Catalog | LLM 只产 candidate，deterministic evidence/lineage gate |
| artifact 损坏或路径漂移 | 结果不可追溯 | checksum、immutable refs、store_corrupt 诊断和 event recovery |
| scope 泄漏 | 租户数据暴露 | application 统一 scope gate、artifact 二次校验、跨 scope 禁止 merge |
| 业务逻辑泄漏到接口 | API/CLI 行为分叉 | 单一 application facade、architecture tests、ports 依赖规则 |

## 25. 默认决策与后续扩展

v1 默认决策如下：

- 使用有界同步 application call，返回 durable `run_id`；后续可接入异步 scheduler。
- 使用 durable filesystem artifact/catalog store；repository port 保留数据库替换空间。
- parser、identity、normalization、relation、metric compatibility 和 leaderboard filter 使用 deterministic service。
- LLM 只生成 candidate，不决定 workflow、quality、verification、ranking、publication 或 memory write。
- benchmark 采用 candidate-first；verified leaderboard 只接受 evidence 完整且协议兼容的结果。
- source refresh 创建新 snapshot，保留历史，不覆盖旧事实。
- actor scope 是所有 identity、artifact、query、event 和幂等行为的强制边界。
- `frontend` 保持不变；先通过 API、CLI、fixture 和 artifact 验证后端闭环。
- 不执行第三方代码，不自动安装未知依赖，不依赖 Papers with Code 实时服务。

后续版本可以在不破坏 v1 contract 的前提下增加异步调度、人工 review UI、更多 publisher adapter、数据库 catalog store、受控复现 sandbox 和跨项目公开 Catalog，但这些能力不属于本 PRD。

## 26. 术语表

| 术语 | 定义 |
| --- | --- |
| Source | 用户提交或系统发现的外部论文/仓库入口 |
| Snapshot | 某次获取的不可变来源事实及其 checksum/lineage |
| Identity | 跨 source/version 归并后的 canonical paper 身份 |
| Document | 对某个 snapshot 的结构化解析结果 |
| Evidence | 可回溯到 source locator 的 claim 支撑 |
| Catalog | paper 与 task/method/dataset/benchmark/metric/score/code 的 typed graph/projection |
| Candidate | 已抽取但尚未通过确定性验证的内容 |
| Verified | 通过 schema、evidence、lineage、scope 和兼容性 gate 的内容 |
| Conflicting | 同一语义目标存在未解决来源或协议冲突的内容 |
| Observation | 对代码仓库或外部来源的事实观察，不等于复现成功 |
| Provenance | 描述内容来自哪个 source、artifact、parser、run 和 actor 的链路 |
| Durable run/event | 可以恢复、回放和审计的运行记录与状态转移日志 |

## 27. 与现有代码基线的兼容性审查（2026-08-30）

### 27.1 审查口径

本节以提交 `43e0f6896a`（`fix(research): enforce deterministic benchmark leaderboards`）作为可复现的代码基线。审查结论区分三种状态：

- **可复用**：基线中已有、可以通过 port 或 adapter 接入 v1 的能力；不代表已经满足 v1 的持久化、scope 或 provenance 要求。
- **需扩展**：已有相邻实现，但字段、生命周期、错误语义或调用边界不足以满足本 PRD。
- **新增**：基线没有统一实现，必须在本 change 中设计和交付。

当前工作树中若存在未提交的 Research 草稿，只能视为实现候选或迁移输入，不能替代基线证据，也不能在发布说明中写成“已完成”。

### 27.2 能力映射

| 现有代码路径 | 基线已验证能力 | v1 复用方式 | 必须补齐的缺口/迁移动作 |
| --- | --- | --- | --- |
| `backend/research/document/cascade_parser.py` | 已有 PDF parser cascade、fallback、`ParserAttempt` 基础记录和 quality probe | 作为 PDF parser adapter，由 Parse application 注入 | 统一 `ParserAttempt` durable schema、attempt artifact、locator 覆盖率、质量阈值和 actor scope；低质量必须可降级而不是返回空 `parsed` |
| `backend/research/document/latex_compiler.py`、`arxiv_parser.py`、`source_format.py` | 已有 LaTeX/arXiv 解析和格式探测 | 作为 LaTeX/arXiv adapter 与 parser fixture 基础 | 增加统一 format router、HTML/OpenReview/publisher adapter、source hash/lineage 传递；不要把 arXiv 特化接口暴露给 API |
| `backend/research/document/models.py`、`domain/document.py` | 已有 sections、figures、tables、equations、references、基础 lineage 与 document model | 保留结构元素和稳定 id 的既有语义 | 增加 `document_id`、snapshot 绑定、element locator、parser/version metadata、quality report、artifact refs 和 typed actor scope；当前模型不能直接当作完整 v1 document contract |
| `backend/research/document/chunker.py`、`chunk_manifest.py`、`chunk_paper_pipeline.py` | 已有稳定 chunk id、manifest 检查和 arXiv/RAG chunk pipeline | 作为 chunk projection 和 RAG 兼容输入 | Parse application 要持久化 manifest、source hash、content ref、stale history 和 scope；现有 batch pipeline 是 arXiv-specific 重建路径，不能替代多来源 Parse 或删除历史 snapshot |
| `backend/research/domain/evidence.py`、`services/evidence_builder.py` | 已有 claim/evidence pack 基础结构和部分 document evidence 构建 | 复用 evidence 基础实体与 builder 逻辑 | 增加 snapshot/document/element locator、quote/span、artifact ref、checksum、scope 和 durable pack repository；无 evidence 的 candidate 要保留缺口诊断 |
| `infrastructure/research/source_provider.py`、`infrastructure/external/sources/arxiv.py` | 已有 arXiv metadata/source provider，以及 robots、限流、大小和 retry policy | 作为 `arxiv` source adapter，并复用 fetch policy | 新增 OpenReview、DOI/Crossref、publisher、local resolver；由统一 resolver 生成 snapshot、canonical status 和 lineage。adapter 不得直接写 Catalog 或状态 |
| `backend/research/domain/paper.py`、`backend/research/domain/catalog.py` | 已有基础 `ResearchPaper`、paper source record、identity/source snapshot/relation typed model | 复用 identity/relation 的稳定命名和 fingerprint 语义 | 补齐版本生命周期、跨来源 merge、冲突 diagnostics、snapshot history、scope key 和可解释的 canonical URL/external id 规则 |
| `backend/research/application/catalog.py` | 已有 `ResearchPaperCatalogService`、候选抽取、关系查询和 deterministic leaderboard 比较的 application 级基础 | 抽取其纯业务决策，作为新 facade 的内部服务 | 当前主要是内存/服务级编排，缺少 durable Catalog/document/source/evidence store、统一 Parse 输入、完整 actor scope port 和 SOTA candidate 保留策略；不能把 service 当作持久化层 |
| `backend/research/benchmark/models.py`、`benchmark/gates.py` | 已有 benchmark/dataset/metric/score/baseline/SOTA 基础类型、evidence gate 和部分兼容性判断 | 复用实体语义、方向排序和 compatibility key | score 需要 typed snapshot refs、dataset version、split/unit/protocol/scope；candidate/conflicting 不能进入 leaderboard；不完整 SOTA 必须留在 candidate，而不是抽取时丢弃 |
| `backend/research/method_graph/models.py`、`method_graph/gates.py` | 已有 `ResearchMethod`、`MethodGraph` 和 edge/gate 基础 | 将 paper-to-method 关系映射到 typed method graph，并复用其 gate 语义 | method graph edge 也必须绑定 source/evidence refs、identity 和 actor scope；不能因为 graph 已存在就跳过 Catalog relation 的 candidate/verified 生命周期 |
| `backend/research/domain/code_repository.py`、`infrastructure/research/github_repository.py` | 已有 GitHub 基础 profile/observation、repository URL、部分 branch/commit/release 和指标读取 | 扩展为 GitHub source adapter 和 code relation target | 增加 README/license/install/examples/training/inference/checkpoint 的受控 observations、source snapshot/evidence refs、历史 observed_at 和 scope；基础 profile 不等于可运行或复现成功 |
| `infrastructure/external/sources/github.py` | 已有 GitHub API connector 与访问错误处理 | 复用 HTTP/client policy，不执行仓库代码 | 增加允许读取的文件/README artifact 边界、响应大小与脱敏规则；禁止 workflow、notebook、安装脚本和 secret 读取 |
| `interfaces/services/research_service.py` | 已有 analyze、reader、ask、RAG 和 run trace 的 application facade，以及旧流程 actor/error mapping | 保留旧方法，在同一 service 增加 Parse/Catalog facade 方法 | 不能让新接口直接访问 parser/store；新增方法必须接收规范化 actor scope、返回统一 run/status/diagnostic/provenance，并与旧分析流程解耦 |
| `interfaces/api/routers/research.py`、`interfaces/api/routers/__init__.py` | 已有 research analyze/analysis/reader/ask/rag-ask/trace 路由 | 保持旧路由兼容，新增 PRD 第 14 节 endpoints | parse、sources、document、catalog、code、benchmarks、search、leaderboards、refresh 全部经 application service；不能把旧 `analyze` handler 改名伪装成 parse |
| `interfaces/cli/commands/paper.py` | 已有 arXiv/RAG `paper ingest` 和 `paper ask` | 保持旧命令输出兼容，新增 parse/catalog/benchmark/code 命令 | 所有新命令和迁移后的 ingest 都经 application facade；补 `--json`、scope、过滤、退出码和逐项失败诊断，不能直接实例化 batch/chunk store |
| `infrastructure/research/filesystem_run_store.py`、artifact/chunk stores | 已有 durable run、artifact 和 local chunk 存储原语 | 复用锁、原子写入、checksum 和 artifact ref 约定 | 新增 typed Catalog/source/document/evidence/relation/score store、schema version、scope 查询、历史 snapshot 与 event append-only；旧 run/chunk store 不是 Catalog repository |
| `tests/architecture/test_no_legacy_paper_radar.py` 及现有边界测试 | 已有 legacy `paper_radar` 禁止依赖和部分 interface/infrastructure 边界检查 | 扩展为 Parse/Catalog caller inventory 和 frontend 变更检查 | 增加 API/CLI 不绕过 application、backend/research 不反向依赖 interfaces/infrastructure、scope 传播、durable store 和新 contract fixtures 的测试 |

### 27.3 兼容性结论

本 PRD 与现有代码是**增量扩展兼容**关系，不是“把几个 DTO 接上即可”的文档同步：

1. parser、arXiv fetch policy、document element、chunk/evidence 基础结构和 benchmark 方向排序可以复用。
2. source resolver、跨来源 identity、完整 document/evidence provenance、durable Catalog repository、统一 Parse use case、GitHub reproducibility observation 和新 interfaces 属于新增或明显扩展范围。
3. 既有 analyze/reader/RAG/Harness runtime 必须保持运行；Research Catalog 不能通过修改 `ResearchPaperCard` 或 `ResearchPaper.metadata` 绕过 typed domain。
4. `frontend` 不在迁移边界内；API/CLI/artifact contract 先独立验证，再由后续前端消费。

### 27.4 必须显式处理的 contract 冲突

| 冲突 | 基线行为 | v1 决策 |
| --- | --- | --- |
| relation evidence 约束 | 当前 `ResearchPaperRelation` 校验倾向要求所有状态都有 `source_snapshot_refs` 和 `evidence_refs` | 改为 candidate/rejected/conflicting 可保留不完整 refs，并记录 `evidence_missing`；仅 verified 强制完整 source/evidence refs。需要 schema migration 和回归测试 |
| source access status | 当前 snapshot literal 以 `available`、`metadata_only`、`denied`、`failed` 为主 | 保持四个 canonical status；`rate_limited`、`not_found`、`unsupported_format`、`timeout`、`robots_disallowed` 等下沉到 `diagnostic.reason_code` |
| actor scope | 旧 application service 有部分 actor 绑定，但不是所有 Catalog/domain/store 都是 typed scope | 将规范化 `tenant_id`、`user_id`、`memory_namespace` 贯穿 request、identity、snapshot、artifact、repository、query、event 和 idempotency key；客户端 scope 只能校验，不能覆盖认证上下文 |
| SOTA claim 完整性 | 当前基础 SOTA 模型/抽取逻辑可能要求 benchmark/dataset/metric 才创建 | 不完整文本仍创建 candidate，标出缺失依赖；verified gate 再要求 score、benchmark、dataset、metric、protocol 和 evidence |
| batch ingest 历史 | 旧 arXiv batch/chunk 流程面向重建，可能清理 stale chunks | 新 Parse/refresh 以 immutable snapshot 和 `stale_of` 保留历史；不得因重复 ingest 删除旧 document/evidence/relation |
| GitHub 复现语义 | 基础 adapter 只有仓库 metadata/指标观察 | 新增 signals 仍只能是 observation/evidence；没有代码执行、依赖安装或“复现成功”推断 |

### 27.5 推荐迁移顺序

1. **Contract migration**：先冻结 actor scope、canonical access status、document locator、relation candidate 规则、score/SOTA refs 和 schema version；为现有模型加向后兼容读取与明确诊断。
2. **Source/Parse path**：新增 resolver ports、multi-source adapters、统一 `ParsePaperRequest/Result/UseCase`，把已有 LaTeX/PDF cascade 接入并持久化 attempts/quality。
3. **Durable persistence**：实现 source/document/evidence/catalog/relation/score/event repositories，先写 intent/run，再写派生 artifact；用 checksum、scope 和 schema 校验恢复。
4. **Catalog/gates**：接入 method/dataset/benchmark/metric/code typed relations，补 candidate-first、SOTA candidate 保留、协议兼容性和历史 leaderboard。
5. **Interfaces**：在 `ResearchApplicationService` 和 composition 中接线，再添加 HTTP/CLI/OpenAPI contract；用 architecture tests 禁止直连 parser/store。
6. **Regression/release**：运行 fixture、scope isolation、metadata-only、fallback、重复 ingest、store corruption、leaderboard exclusion、API/CLI parity 和 `frontend` no-change 检查，最后再做 strict OpenSpec validation。
