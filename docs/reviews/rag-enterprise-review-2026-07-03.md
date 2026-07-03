# NewsRoom 企业级 RAG 全面复审报告（第二轮）

审查日期：2026-07-03
审查基准：main @ `060a8757`（Merge PRD 16 and 17 RAG runtime branches）
前次审查：`docs/reviews/rag-enterprise-review-2026-07-02.md`（62/100，基于 `f9f7aaae`）
本轮重点：验证 PRD 16（检索流水线重构 + 解析级联）与 PRD 17（验证驱动 Agentic 循环）的实现质量，并按企业级标准全维度重评。

审查环境说明：本轮开始前工作区存在 64 个损坏文件（写入截断/null 字节）及损坏的 `.git/HEAD`，已备份后恢复至 main 干净状态；本环境无法运行 pytest（Windows venv 不可用于审查容器），测试结论基于测试代码静态审读，**未经运行验证**——这是本报告的已声明局限。

---

## A. 一句话总评

两份 PRD 的绝大部分已按设计高质量落地——恒真收敛消除、gated 答案路径成为默认、3208 行 god class 拆为通道/融合/扩展器流水线、BM25 生产接通、三级解析级联建成——NewsRoom 的 RAG 内核已经"真验证、真收敛、真装配"；但复审发现**两处关键接线缺口（relevance scorer 未装配进生产、unsupported-claims 补查回路未实现）**，加上 eval 仍未进 CI、观测/租户/memory 接线依旧为零，企业外环仍未闭合。

## B. 当前 RAG 成熟度分数

**74 / 100**（前次 62，+12）

提升来源：grounded generation 与 abstention 入 gate 体系（+4）、检索层工程形态与 hybrid/BM25（+4）、解析级联与打标真实化（+3）、citation 验证进主路径（+1）。未动分项：观测（0）、多租户（0）、eval CI（0）、memory 接线（0）。

---

## C. 已实现能力清单（附证据路径）

### C1. 本轮新增：已完成且有测试证明

| 能力 | 实现证据 | 测试证据 |
|---|---|---|
| **E1 内容驱动 evidence 打标**：`EvidenceTypeResolver` Protocol + `MetadataKeyEvidenceTypeResolver`（有序映射、标量/列表值均处理）；adapter 三态标记 `content_resolved / requested_fallback / requested_default` | `framework/harness/rag/evidence_typing.py`、`kernel_evidence_adapter.py` L53-91、business 映射 `business/research/rag/evidence_typing.py` 经 `retrieval_port.py` L49 接线 | `tests/framework/harness/rag/test_evidence_typing.py`（4 用例：标量/列表/键序/未命中）|
| **E2 相关性 gate（framework 层）**：`RelevanceScorerPort` + `RAGRelevanceGate`（阈值判定、score 数量不匹配即 fail——比 PRD 更严）；`SourceVerifier` 注入 scorer、按 `source_policy.min_relevance` 拒绝并记 `low_relevance` 原因 | `framework/harness/rag/relevance.py`、`source_verifier.py` L31-70 | `test_source_verifier_relevance.py`（5 用例，含 scorer=None 回归保护、错误 score 数拒绝）|
| **E3 WorkerRAGPlanner 强化**：`min_round_index` 门槛 + `executed_queries` 透传进 LLM request；business 适配器 `ResearchRAGPlanWorker` 就位 | `framework/harness/rag/planner.py` L23-102、`business/research/rag/adapters/plan_worker.py` | `test_rag_session_controller.py`（改造）|
| **E4 生成相位**：`GroundedAnswerCandidate`/`AnswerClaim` 模型、`AnswerWorkerPort`、`RAGAnswerGate`（citation integrity / claim coverage / answer shape / abstention shape 四项全 deterministic）；session 增加 `_run_generation_phase`，产出 ANSWERED / ABSTAINED 状态与 `rag_answer_candidate_created / rag_answer_verified / rag_answer_returned / rag_abstained` 事件；`generation_policy` 默认空 = 相位关闭（兼容性保证成立） | `framework/harness/rag/answer_gate.py`（90 行）、`answer_worker.py`、`models.py` L29-30/L141/L630-670、`session.py` L223-299 | `test_rag_answer_gate.py`、`test_rag_generation_phase.py`（4 用例：默认关闭/通过/gate 失败弃答/verified abstention）|
| **T5 gated rag_ask 成为默认**：`gated: bool = True`，`generate=True` 走 `_gated_ask` → `build_paper_rag_session(with_answer_worker=True)` → bounded 循环 + answer gate；返回体含 status/`generation_mode: gated_harness`；旧直连路径显式降级为 `legacy_direct` 标记 | `interfaces/services/paper_rag_service.py` L29-63/L119-134、factory L116-139 | `tests/interfaces/services/test_paper_rag_service.py`（4 用例：retrieve-only 不建 session / gated answered / gated abstained 无答案文本 / legacy 标记）|
| **S1 sparse 生产断线修复**：`ChunkStorePort.list_chunks` 进 Port 契约；两个生产 adapter 实现；`_list_store_chunks` getattr 反射已消失（grep 零命中） | `business/research/ports/chunk_store.py` L33、`chunk_storage.py` L83/L108 | `test_sparse_lexical_channel.py`、`test_candidate_recall_stage.py` |
| **S9 BM25 索引**：`PaperBM25Index`（真 BM25 打分 `_score`、build/持久化/加载），sparse 通道查索引而非全量扫描，索引缺失时"可观测降级"（fallback 记入 trace） | `business/research/rag/retrieval/bm25_index.py`、`channels/sparse_lexical.py` L14/L121-147 | `test_bm25_index.py`、`test_sparse_lexical_channel.py`（3 用例含降级可观测与 formula fallback）|
| **S4-S6 检索流水线重构**：`paper_retriever.py` 3208 行 → **89 行薄入口**；五通道类化（`channels/` dense_text/sparse_lexical/field_embedding/claim_index/visual）；`fusion.py` 唯一融合点；七个 expander 类化（`expanders/`）；`pipeline.py`/`plan.py`/`planner.py`/`rerank.py`/`trace.py` 齐备 | `business/research/rag/retrieval/` 全目录 | `test_dense_text_channel.py` 等五通道测试、`test_retrieval_fusion.py`、`test_rerank_cascade.py`、`test_retrieval_pipeline_entrypoint.py`、`test_retriever_pipeline_factory.py` |
| **S2 Marker backend + S3 解析级联**：`PdfParserBackendName` 扩为 `nougat|mineru|marker|cascade`；`CascadeDocumentParser`（`ParserAttempt` 追溯 + `DocumentQualityProbe` deterministic 探针 + `PyMuPDFTextDocumentParser` 保底 + `CascadeArxivDocumentParser` 保持 LaTeX 优先路由 + 环境变量配置级联序） | `business/research/document/cascade_parser.py`（parse L202-299）、`marker_pdf_parser.py`、`pdf_parser_backend.py` L9-39 | `test_cascade_parser.py`（7 用例：一级通过/解析错误降级/质量拒绝降级/全失败保底/gzip PDF 保底/LaTeX 路由保持/env 校验）|
| **孤儿删除**：`infrastructure/storage/hybrid_search.py` 已从 git 删除（`2bb955e6`，含 OpenSpec change 归档），主树 grep 仅剩 `.claude/worktrees` 副本 | commit `2bb955e6` | — |
| **AskPaperUseCase 充实**：`build_paper_ask_goal` 按 intent 映射 required_evidence_types（复用 `classify_query_intent`，未新写分类器，符合 PRD） | `business/research/application/ask_paper.py` | `tests/business/research/application/test_ask_paper_use_case.py` |
| **policy 版本指纹**：`policy_config_hash`（sha256 稳定序列化）供评测绑定策略版本 | `business/research/rag/retrieval/policy_config.py` | — |

OpenSpec 佐证：`fix-sparse-channel-production-wiring`(12/12)、`rag-relevance-verification`(12/12)、`rag-generation-phase-and-answer-gate`(14/14)、`gated-rag-ask-endpoint`(15/15)、`sparse-bm25-index`(10/10) 等 change 任务全部勾选完成。

### C2. 前次已确认、本轮维持的能力

bounded PLAN→EXECUTE→VERIFY 状态机 + gate suite、deterministic planner、RAGTranscript、Qdrant 三 collection、CrossEncoder reranker 单例、chunk pipeline + PaperChunk 模型、离线评测体系（hit@k/MRR/faithfulness/abstention accuracy/judge P-R/promotion thresholds）、67 条 golden set、reader repair 记忆闭环、导入边界测试。证据同前次报告 C1 节，不再重列。

---

## D. 未完成能力清单（附证据）

### D1. 本轮新发现的接线缺口（P0 级）

1. **relevance scorer 未装配进生产**。framework 侧 `SourceVerifier(relevance_scorer=...)` 完整可用，但：`business/research/application/paper_rag_session.py` 构造 controller 时**不传 source_verifier**；`paper_rag_factory.py` 无任何 scorer 装配；PRD 17 规定的 `RerankerRelevanceScorer`（business adapter）**不存在**——`business/research/rag/adapters/` 下只有 answer_worker/plan_worker，grep `RerankerRelevanceScorer` 全仓库零命中。**结果：生产 RAG 循环的相关性验证实际关闭，E2 只完成了 framework 一半。** OpenSpec `rag-relevance-verification` 却已全勾选——勾选状态与生产装配现状不符。
2. **unsupported-claims 补查回路未实现**。PRD 17 E4 的核心机制"answer gate 失败 → unsupported claims 回注 gap_report → `_supplemental_round` 受控补查 → 重试生成"没有落地：`session.py` 的 `_run_generation_phase` 单次生成、gate 失败直接 ABSTAINED（L291-299），无循环、无 `_supplemental_round`（grep 零命中）；`answer_gate.py` 提供了 `unsupported_claims_from_answer_gate` 辅助函数但**无调用方**；`policy.py` L105 的 `max_generation_attempts` 属性存在但 session 从不读取。**结果：生成失败不驱动补查，Agentic RAG 的"生成反馈驱动检索"价值未兑现，abstention 会偏保守。**
3. **plan_worker 生产默认未接**。factory `build_paper_rag_session(plan_worker=None)` 为默认，`_gated_ask` 调 factory 时不传 plan_worker——生产问答的 replan 仍是 deterministic 字符串拼接。适配器已备好，差一行装配 + 环境开关（PRD 17 规定的 `NEWS_RAG_LLM_PLANNER` 未找到证据）。

### D2. 持续未完成（与前次一致）

4. **恒真收敛的判决性测试缺失**：PRD 17 验收标准 1（"required=experiment 但语料只有 method → 必须 INSUFFICIENT_EVIDENCE"）未找到对应集成测试（grep `insufficient` 在 evidence_typing/integration 测试零命中）。E1 单元测试只测 resolver 本身。
5. **eval 未进 CI**：`.github/workflows/ci.yml` grep eval/golden 零命中；golden set 仍为 67 条旧格式（无 gold answer/expected_behavior 字段扩展）。
6. **bakeoff 惩罚性口径未加**：grep `penalized` 在 evaluation 目录零命中（PRD 16 的公平性修正未做）。
7. **RetrievalPolicy 未配置化**：`policy_config.py` 只是 hash 指纹，无 YAML 加载（PRD 16 S7 部分完成——trace 有了，配置文件没有）。
8. **memory 未接进 RAG 循环**：`paper_rag_session.py` 不传 memory port，`_execute_memory_recall` 生产恒走 "memory port is not configured" 分支；reader repair memory 仍 in-memory。
9. **观测 / 多租户 / 权限**：grep OpenTelemetry/prometheus/tenant 在 RAG 路径零命中，与前次一致。
10. **测试运行验证缺失**：本审查环境无法执行 pytest；CI 状态未知（本地 venv 为 Windows 布局）。64 个文件曾损坏后 restore，建议本机跑全量测试确认。

---

## E. 企业级差距矩阵（0-5，括号为前次分）

| 维度 | 分 | 变化依据 |
|---|---|---|
| 数据接入与文档解析 | 4.5 (4) | 级联 + Marker + 质量探针 + PyMuPDF 保底，`cascade_parser.py` 有 7 用例；扣 0.5：级联未在真实 20 篇 bakeoff 上验收（无 penalized 报告）|
| chunking 与结构化表示 | 4 (4) | 不变 |
| embedding 与向量存储 | 4 (4) | 不变 |
| hybrid retrieval | 3.5 (1) | 真 BM25 索引 + RRF 唯一融合点 + 生产接线修复 + 降级可观测；扣分：无 SPLADE/稠密-稀疏联合调优报告 |
| query understanding / expansion | 2.5 (2) | intent → required_evidence_types 映射进 ask 路径；expansion 仍无实现 |
| reranking | 4 (4) | 不变，rerank cascade 类化 |
| evidence pack / context assembly | 4 (4) | 不变 |
| grounded generation | 4 (3) | 生成入 bounded 循环 + answer gate + 默认 gated；扣分：无补查重试、单次生成 |
| citation / span verification | 3 (2) | citation integrity 进主路径 gate（evidence_id 级）；span 级仍缺 |
| hallucination control / abstention | 3.5 (2.5) | ABSTAINED 显式状态 + abstention shape gate + 服务层无答案文本返回；扣分：无补查导致弃答偏保守、abstention 回归未跑 |
| deterministic quality gates | 5 (5) | 新增 4 个 answer gate 仍全纯函数 |
| evaluation dataset / golden set | 3.5 (3.5) | 未变 |
| offline eval metrics | 4.5 (4.5) | 未变 |
| online observability | 1 (1) | 未变 |
| trace / transcript / replay | 3.5 (3) | 新事件族入 transcript + RetrievalTrace 结构化；replay 接口仍缺 |
| latency / cost / budget control | 3.5 (3.5) | 未变（generation attempts 预算属性存在但未消费）|
| multi-tenant / security | 0 (0) | 未找到证据 |
| failure recovery / retry / replan | 3.5 (4) | **降 0.5**：生成相位无重试/补查，弱于检索相位的 replan 能力 |
| production vs fake adapters | 4 (4) | fake 仍隔离良好；relevance scorer 缺装配属"没有"而非"用 fake" |
| architecture boundary cleanliness | 4 (3.5) | retrieval 拆包边界清晰、framework 新文件零向上依赖；business→framework 实现类依赖依旧 |
| enterprise deployment readiness | 2 (2) | 未变 |

---

## 3. 架构风险审查（更新）

- **R1 business 依赖 framework 实现类**：依旧存在（`BoundedRAGSessionController` 直接构造），本轮未处理，风险维持中等。
- **R2 interfaces 绕过 gate**：**已修复为默认 gated**，但 `gated=False` + `generate=True` 的 legacy 直连路径仍在（`paper_rag_service.py` L46-63，带 `legacy_direct` 标记）。作为显式降级可接受，建议设删除期限。
- **R3 deterministic work 交给 agent**：未发现，新增 answer gate 保持纯函数。
- **R4 完整闭环**：retrieval → evidence → grounded answer → citation verification 四段**首次全部在一条生产路径上**；但 verification 失败的反馈回路（补查）断在最后一步（D1-2）。
- **R5 fake 当生产**：未发现。集成测试仍以 fake runtime 为主（`test_research_rag_loop_fake_runtime.py` 等），真实 e2e 仍只有条件 skip 的 `test_chunk_paper_e2e.py`。
- **R6 memory 治理**：framework 完备、业务接线为零，与前次一致。
- **R7 gate 是否形式化**：answer gate 有真实阻断力（服务层测试断言 abstained 时无答案文本）；但 relevance gate 因 D1-1 在生产中实际不运行——**存在"gate 代码真实、生产装配缺席"的新形态形式化风险**。
- **R8 eval 覆盖失败模式**：离线体系未变；新能力（gated/abstention/级联）尚无对应 golden 回归。
- **R9 遗留/捷径**：hybrid_search 孤儿已删；`.claude/worktrees/` 下留有多份旧副本（建议清理）；未发现 merge 冲突残留（grep `<<<<<<<` 零命中）。

## 4. 真实端到端能力判断（更新）

- **能否算企业级？** 尚不能，但已从"内核优秀、外环未闭"进到"闭环成形、三根线未接"。差距收敛为：relevance 装配、补查回路、eval CI、观测、租户。
- **最接近生产的路径**：`paper ask --generate`（CLI）→ `rag_ask(gated=True)` → `build_paper_rag_session(with_answer_worker=True)` → bounded 循环（真实 Qdrant/Postgres/CrossEncoder/BM25）→ answer gate → ANSWERED/ABSTAINED。**这已是一条带 gate 的真实路径**——质变于前次。
- **P0 风险**：relevance scorer 未装配（低质证据可无阻拦进 context pack，向下污染 generation 与 citation 的可信度）；其次是生成无补查导致的过度弃答（影响可用性而非安全性）。
- **基础设施存在但无闭环**：`RerankerRelevanceScorer`（缺失待写）、`unsupported_claims_from_answer_gate`（无调用方）、`max_generation_attempts`（无消费方）、`ResearchRAGPlanWorker`（默认不装配）、framework/memory 全家族。
- **最能证明能力的测试**：`test_rag_generation_phase.py` + `test_rag_answer_gate.py`（生成相位正确性）、`test_paper_rag_service.py`（服务层 gated 契约）、`test_cascade_parser.py`（级联七态）、`test_sparse_lexical_channel.py`（BM25 生产装配 + 可观测降级）、`test_source_verifier_relevance.py`（相关性判定，含回归保护）。
- **还缺的测试**：恒真收敛判决性集成测试；relevance 装配后的端到端拒绝测试；golden set gated 路径 abstention 回归；补查回路测试（待实现后）；真实 Qdrant 的 sparse 非空 nightly 测试；全量测试套件的实际运行验证（本轮环境无法执行）。

---

## F. P0/P1/P2 优化路线图

### P0-A 装配 relevance scorer（预计半天，收益最大）
- 新增 `business/research/rag/adapters/relevance_scorer.py`：`RerankerRelevanceScorer`（RerankerPort → RelevanceScorerPort，sigmoid 归一，按 PRD 17 E2 原设计）。
- `paper_rag_session.py` 增加 `relevance_scorer` 参数，构造 `SourceVerifier(relevance_scorer=...)` 传入 controller；factory 用 `get_reranker()` 装配；`ResearchRAGPolicyBuilder` 写入 `min_relevance`（含 `min_relevance_by_type` 分层，formula/table 放宽至 0.20）。
- 测试：`test_paper_rag_session.py` 断言 verifier 注入；集成测试低相关证据被拒且 gap_report 含 rejection_summary。
- 验收：生产 `_gated_ask` 路径上 relevance gate 结果出现在 transcript。

### P0-B 补查回路（`_supplemental_round` + attempts 循环）
- `session.py`：`_run_generation_phase` 改为 `for attempt in range(policy.max_generation_attempts)` 循环；gate 失败且 `unsupported_claims_from_answer_gate` 非空且可 replan 时，claims 回注 `state.gap_report["unsupported_claims"]`，执行一轮受控补查（复用主循环单轮逻辑）后重组 pack 重试；预算耗尽 ABSTAINED。
- factory `generation_policy = {"enabled": True, "max_attempts": 2}`。
- 测试：`test_rag_generation_phase.py` 增补查成功/补查后仍失败/预算耗尽三用例。

### P0-C 判决性测试 + golden 回归
- 新增 `tests/business/research/integration/test_evidence_typing_convergence.py`（required=experiment、语料只有 method → INSUFFICIENT_EVIDENCE）。
- golden set 上跑 gated 路径 abstention 回归，产出基线报告。

### P1（顺延前次）
- P1-a plan_worker 默认装配 + `NEWS_RAG_LLM_PLANNER` 开关；P1-b eval 进 CI（PR 级 retrieval 指标 + promotion thresholds）；P1-c bakeoff penalized 口径 + 级联 20 篇验收；P1-d reader repair memory Postgres 化；P1-e MemoryPort 接进 PaperRAGSession（episodic 先行）；P1-f RetrievalPolicy YAML 配置化收尾；P1-g RAG session replay 接口。

### P2
- span 级 citation、观测（OTel）、多租户 payload 过滤、legacy_direct 路径删除、新闻主路径 RAG 化、`.claude/worktrees` 清理。

改造顺序：P0-A → P0-B → P0-C（一周内）→ P1 并行推进。

## G. 推荐目标架构

前次报告 G 节架构不变，本轮已兑现其中：hybrid(dense+sparse+RRF)、AnswerGenerator 纳入循环、CitationVerifier(id 级)、AbstentionPolicy 雏形、解析级联。剩余待建：span verifier、replay、observability、tenant filter、feedback loop、memory 接线——均已在 F 节排期。

## H. 推荐评测体系

前次报告 H 节设计不变。本轮补充两条：(1) golden set 需扩展 `expected_behavior` 字段以回归 gated abstention；(2) failure taxonomy 增加 `abstained_over_conservative` 类（补查缺失期的主要失败形态），与 `abstention_wrong` 区分统计。

## I. 最小可上线标准（更新勾选）

1. ~~问答全流量经 bounded 循环 + answer gate~~ ✅（本轮完成，legacy 路径待删）
2. abstention accuracy ≥ 0.9 —— ⬜ 未回归验证
3. eval 进 CI —— ⬜
4. memory 持久化 —— ⬜
5. RAG 路径基础 metrics —— ⬜
6. transcript 落盘 + replay —— 半 ✅（事件完整，replay 接口缺）
7. 真实数据 e2e 进 CI 常跑 —— ⬜
8. **新增：relevance 验证在生产路径生效** —— ⬜（P0-A）

## J. 建议下一步 OpenSpec change 拆分

1. `wire-relevance-scorer-production`（P0-A）
2. `answer-gate-supplemental-round`（P0-B）
3. `evidence-convergence-regression-tests`（P0-C）
4. `wire-llm-planner-default`（P1-a）
5. `eval-ci-promotion-gates`（P1-b，沿用前次未启动）
6. `parser-cascade-bakeoff-acceptance`（P1-c）

另：`rag-relevance-verification` change 建议补一条勾选修正说明——framework 完成、生产装配移入新 change，避免"全勾选但未生效"的状态误导。

## K. 需要进一步确认的问题

1. relevance scorer 未装配是有意分期（先观察 gated 路径稳定性）还是遗漏？决定 P0-A 是直接做还是先加开关灰度。
2. 生成单次即弃答的保守策略是否为有意的第一版？若线上弃答率可接受，P0-B 可降为 P1。
3. `gated=False` legacy 路径计划保留多久？建议给出删除的版本/日期。
4. 本机全量测试套件当前是否全绿？（审查环境无法运行 pytest，且此前发生过工作区文件损坏，需要你本地确认 `python -m scripts.dev test-prd-daily` 等 CI 命令通过。）
5. `.claude/worktrees/` 下的多份历史副本（含已删除的 hybrid_search.py）是否可以清理？

---

*结论基于 main @ `060a8757` 的静态代码审读与 OpenSpec/测试代码核对；测试未实际运行（环境限制已声明）。*
