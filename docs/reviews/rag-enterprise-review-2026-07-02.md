# NewsRoom 企业级 RAG / Agentic RAG 全面审查报告

审查日期：2026-07-02
审查范围：framework/rag、framework/harness/rag、framework/harness/retrieval、framework/memory、business/research/*、infrastructure/storage/*、interfaces/services/paper_rag_*、data/eval、tests、openspec、docs/prd/harness-research-runtime
审查方法：基于当前仓库真实代码、测试与规范文档的静态审查 + 导入边界分析，所有结论附路径证据。

---

## A. 一句话总评

NewsRoom 已经建成了一个**控制面设计明显高于行业平均水平的 bounded Agentic RAG 框架**（deterministic planner + 11 个 deterministic gate + budget + transcript），且 paper RAG 有真实的 Qdrant/Postgres/CrossEncoder/CLI 生产装配路径和罕见完善的离线评测体系；但**generation 与 citation verification 未纳入 bounded 循环、集成测试全部依赖 FakeResearchRAGRuntime、hybrid search 无真实 BM25、eval 未接 CI、可观测/多租户/权限完全缺失**——它是一个"优秀的 RAG 内核 + 尚未闭合的企业外环"。

## B. 当前 RAG 成熟度分数

**总分：62 / 100**

计分口径：控制面与状态机 9/10，检索与索引 7/10，grounded generation 与 citation 5/10，评测体系 8/10（离线强、CI 缺）、可观测与回放 5/10、安全与多租户 0/10、真实端到端验证 4/10、架构边界 7/10、memory 治理 6/10、部署就绪 5/10（按权重折算）。

---

## C. 已实现能力清单（附证据路径）

### C1. 已完成且有测试证明

| 能力 | 实现证据 | 测试证据 |
|---|---|---|
| Bounded PLAN→EXECUTE→VERIFY 状态机（max_rounds/max_replans 循环，预算耗尽即停） | `framework/harness/rag/session.py`（`BoundedRAGSessionController.run`，约 L110-181 主循环） | `tests/framework/harness/rag/test_rag_session_controller.py` |
| 11 个 deterministic gate（PlanSchema/ToolAllowlist/QueryDedup/Scope/Budget/SourceQuality/EvidenceCoverage/EvidenceConflict/ContextSize/MemoryRelevance/Lineage），全部集合/阈值判据，无 LLM 判分 | `framework/harness/rag/gates.py` | `tests/framework/harness/rag/test_rag_plan_gates.py` |
| Deterministic planner（LLM 仅作 fallback，routing 不由 LLM 决定） | `framework/harness/rag/planner.py`（`DeterministicRAGPlanner`） | `tests/framework/harness/rag/test_rag_session_controller.py` |
| RAG transcript：每个 phase 事件与 gate 结果入 transcript | `framework/harness/rag/session.py` + `models.py`（`RAGTranscript`） | `tests/framework/harness/rag/test_rag_transcript.py` |
| Evidence pack / context pack 组装（含 size gate） | `framework/harness/rag/context_pack_assembler.py`、`framework/harness/retrieval/evidence_pack.py` | `tests/framework/harness/rag/test_rag_context_pack_assembler.py` |
| business→framework 检索适配链（ResearchRetriever→PaperChunkRetrievalPort→KernelRAGRetrieverHarnessAdapter） | `business/research/rag/retrieval_port.py`（L24-107）、`framework/harness/rag/kernel_evidence_adapter.py`（L43-73） | `tests/business/research/rag/test_retrieval_port.py`、`tests/framework/harness/rag/test_kernel_evidence_adapter.py` |
| 多路检索器（child/ref/parent chunks，field index、visual index、reranker 可插拔） | `business/research/rag/retrieval/paper_retriever.py`（`ResearchRetriever`） | `tests/business/research/rag/test_retriever.py`、`test_routing.py` |
| CrossEncoder reranker 真实实现（进程级单例，预热接口） | `infrastructure/external/reranker.py`（`CrossEncoderReranker`）、`interfaces/services/paper_rag_factory.py`（`get_reranker`/`preload_reranker`） | `tests/business/research/rag/test_lightweight_reranker.py`（启发式版） |
| Qdrant 向量存储 + 多 collection（chunk/field/visual） | `infrastructure/storage/vector/qdrant_store.py`、`paper_chunk_store.py`、`paper_field_chunk_store.py`、`paper_visual_chunk_store.py` | `tests/business/research/rag/adapters/` 下适配器测试 |
| 结构化 chunk model（PaperChunk：chunk_id/section/source_ref/metadata/multi-embedding） | `business/research/document/models.py`、`business/research/application/chunk_paper_pipeline.py` | `tests/business/research/rag/test_benchmark_paper_ingest.py`、`tests/business/research/integration/test_chunk_paper_e2e.py`（需 NEWS_DATABASE_DSN，无环境自动 skip） |
| 生产装配 composition root（真实 Qdrant+Postgres+ArxivConnector+CrossEncoder，无 fake） | `interfaces/services/paper_rag_factory.py`（`build_paper_rag_session`/`build_chunk_pipeline`，grep 确认无 Fake 引用） | 由 CLI smoke 间接覆盖 |
| CLI 端到端命令（`paper ingest` / `paper ask --generate`） | `interfaces/cli/commands/paper.py`（L9-95） | — |
| 离线评测体系：retrieval（strict/equivalent hit@k、MRR）、generation（faithfulness、context_precision、citation_ok）、abstention accuracy、judge precision/recall、baseline 对比与 promotion thresholds | `business/research/rag/evaluation/paper_benchmark_suite.py`（L60、L86、L1669-1671、L2030-2174、L2424+）、`paper_answer_eval.py`（L56-373）、`paper_evidence_eval.py`、`data/eval/run_eval.py`/`run_generation_eval.py`/`run_system_eval.py` | `tests/business/research/rag/test_answer_eval.py`、`test_generation_eval.py`、`test_evidence_eval.py`、`test_benchmark_suite.py`、`test_evaluation_report.py` |
| Golden set：67 条真实问题（question + source_chunk_id + paper_id + domain） | `data/eval/golden_set.json`、`build_golden_set.py` | `test_run_evidence_eval.py` |
| Reader repair 记忆闭环（issue detect→memory recall→repair→gate verify→commit case→consolidate strategy，且验证"never publishes skill"） | `business/research/reader_repair/repair_service.py`（L58-201）、`repair_memory.py` | `tests/business/research/integration/test_reader_repair_rag_loop.py`（`test_reader_repair_loop_writes_memory_and_never_publishes_skill`） |
| Memory 框架治理：write policy、consolidation、invalidation（软删）、versioning | `framework/memory/policy/`、`framework/memory/runtime/`、`framework/memory/stores/` | `tests/framework/`（memory 相关套件） |
| 导入边界守卫测试 | `tests/framework/rag/test_import_boundaries.py` | 自身即测试 |
| Claim 级 evidence_id 覆盖验证 + 业务 quality gate（deterministic，missing RAG evidence 会 fail gate） | `business/research/application/single_paper_runtime.py`（`_verify_claims` L435-448、`_quality_gate` L450+，含 `ResearchRAGEvidenceNeedGate`） | `tests/business/research/integration/test_single_paper_loop_fake_runtime.py` |

### C2. 部分完成

| 能力 | 现状 | 证据 |
|---|---|---|
| Hybrid retrieval | `HybridSearchService` 只做 report keyword 匹配 + 向量结果的字典合并排序，**无 BM25/sparse 向量、无 RRF**，且 grep 全仓库无任何生产调用方（孤儿代码） | `infrastructure/storage/hybrid_search.py`（L36-80）；`grep -rn HybridSearch` 除定义外零引用 |
| Grounded generation | `AnswerGenerator` 有 context role 分桶（primary_evidence/interpretation_context）、required_ids 校验、context_chunk_ids 追踪，但**运行在 bounded 循环之外**，`rag_ask` 直接 retriever→generate，不经过 gate suite | `business/research/rag/retrieval/paper_answer_generator.py`（L104-180）、`interfaces/services/paper_rag_service.py`（`rag_ask` L21-60） |
| Citation verification | `CitationVerifier.verify_claims` 是 deterministic 的 evidence_id 集合验证，但**仅在 `__init__.py` 导出，未被任何生产路径调用**；single_paper_runtime 内联了等价逻辑但只到 evidence_id 级，无 span 级文本核对 | `business/research/services/citation_verifier.py`；grep 确认无生产调用点 |
| Abstention | eval 侧有完整 abstention accuracy 指标与 `_ABSTAIN_MARKERS`，harness 侧有 `INSUFFICIENT_EVIDENCE` halt 状态，但**生成侧没有策略化的 abstention policy 对象**（靠 prompt 约定 + eval 事后检测） | `business/research/rag/evaluation/paper_answer_eval.py`（L227、L373）、`framework/harness/rag/session.py` |
| Replay | transcript/event 记录完整，framework/events 有 `EventReplay`、context snapshot 有 checksum replay，但**RAG session 无 deterministic 重演接口**（没有"给定 transcript 复现一次 run"的入口） | `framework/events/replay.py`、`framework/harness/context/snapshot.py`（L39-43）、`tests/business/research/rag/test_replay.py`（仅覆盖局部） |
| Query understanding / routing | intent 路由存在（`rag_ask` 返回 `result.intent`），`test_routing.py` 有测试；query expansion 只有元数据结构，无实现 | `business/research/rag/retrieval/paper_retriever.py`、`tests/business/research/rag/test_routing.py` |
| 真实数据 e2e | `test_chunk_paper_e2e.py` 是真 e2e（真 Qdrant+Postgres+arXiv 1706.03762），但依赖 `NEWS_DATABASE_DSN`，无环境即 skip，**CI 不跑** | `tests/business/research/integration/test_chunk_paper_e2e.py`（pytestmark skipif，L33-36）；`.github/workflows/ci.yml` grep "eval|golden" 零命中 |
| Memory 持久化 | framework/memory 治理逻辑完备，但 stores 的持久化实现主要在内存；vector memory store 存在于 `infrastructure/storage/memory/vector_memory_store.py`，reader repair memory 为 `InMemoryReaderRepairMemory` 且是**生产路径当前唯一实现** | `framework/memory/stores/`、`business/research/memory/reader_repair_memory.py` |

### C3. 只有框架/模型，缺真实运行闭环

- **AskPaperUseCase**：纯 pass-through（`business/research/application/ask_paper.py`，全文 11 行），application 层的 ask 用例没有业务逻辑，真实问答走的是 interfaces 层 `PaperRagApplicationService.rag_ask`。
- **Query expansion**：`framework/rag` 有元数据结构，无实现（framework 探查确认）。
- **framework/memory 高级 store**（vector/graph/temporal 接口）：接口定义存在、无实现。
- **新闻主路径的 RAG 化**：PRD 预期的 source collection→evidence→analysis→report→gate→artifacts 主路径中，source items 的 evidence 检索未接 bounded RAG（OpenSpec 探查结论：主新闻路径完成度约 65-70%，`infrastructure/retrieval/rag/` 适配层不存在）。

### C4. 只有测试 fake，不算生产能力

- `framework/harness/rag/fake.py`、`framework/harness/retrieval/fake.py`、`infrastructure/storage/vector/fake_store.py`、`FakeResearchRAGRuntime`——grep 确认均未被 factory/service 生产路径引用，仅测试使用。**这点做得干净**。
- 但反过来：`tests/business/research/integration/` 中除 `test_chunk_paper_e2e.py` 外，`test_research_rag_loop_fake_runtime.py`、`test_single_paper_loop_fake_runtime.py`、`test_paper_rag_harness_kernel_integration.py` 全部基于 fake runtime——**集成层证明力不足**。

### C5. 完全缺失

- 多租户 / 权限 / ACL：RAG 路径上零实现（infra 探查确认）。
- 生产可观测性：无 OpenTelemetry/Prometheus，仅基础 logging。
- Eval 接 CI：`.github/workflows/ci.yml` 无任何 eval/golden 步骤。
- BM25/sparse 检索与融合算法（RRF）。
- Freshness / conflict-across-sources 评测维度（新闻场景关键）。
- 在线反馈学习回路（除 reader repair 外，无用户反馈→golden set 的通道）。

---

## D. 未完成能力清单（汇总，附证据）

1. Generation 未纳入 bounded 循环，无统一 budget/gate 管控 —— `interfaces/services/paper_rag_service.py:56`（`_generate` 直接 `asyncio.run`）。
2. CitationVerifier 未接线 —— `business/research/services/citation_verifier.py` 无调用方。
3. Span 级 citation 验证缺失 —— 现有验证止于 evidence_id 集合，未核对引用文本与源 span。
4. HybridSearchService 为孤儿代码且非真 hybrid —— `infrastructure/storage/hybrid_search.py`。
5. RAG session replay 入口缺失 —— `framework/events/replay.py` 有通用机制但未接 RAG transcript。
6. Reader repair memory 生产实现是 in-memory —— `business/research/memory/reader_repair_memory.py`，进程重启即失忆。
7. Eval/e2e 不在 CI —— `.github/workflows/ci.yml`。
8. 观测、租户、权限、部署配额 —— 未找到证据。
9. business 层直接实例化 framework 实现类 `BoundedRAGSessionController`、`KernelRAGRetrieverHarnessAdapter` —— `business/research/application/paper_rag_session.py:5-6, L72+`、`business/research/rag/retrieval_port.py:3-7`。

---

## E. 企业级差距矩阵（0-5 分）

| 维度 | 分 | 依据 |
|---|---|---|
| 数据接入与文档解析 | 4 | ArxivSourceConnector + ArxivDocumentParser 真实可用，parser bakeoff 体系活跃（git log：MinerU/Nougat/PDF bakeoff 系列提交）；但源类型局限 arXiv/PDF，新闻源接入未 RAG 化 |
| chunking 与结构化表示 | 4 | `chunk_paper_pipeline.py` + PaperChunk（section-aware、多 embedding、propositions 可选、visual chunk），有真 e2e 测试（条件 skip） |
| embedding 与向量存储 | 4 | `embeddings.py` 配置化、Qdrant 三 collection 完整实现；扣分：无索引版本管理/重建流程 |
| hybrid retrieval | 1 | `hybrid_search.py` 非真 hybrid 且零调用方；主检索是多路 dense + field index，无 sparse |
| query understanding / expansion | 2 | intent 路由有实现有测试；expansion 仅元数据结构 |
| reranking | 4 | CrossEncoder 真实实现 + 单例 + 预热 + `analyze_rerank_scores.py` 分析工具；扣分：无 rerank 级联策略与延迟预算 |
| evidence pack / context assembly | 4 | framework 级 assembler + size gate + business 投影，测试齐 |
| grounded generation | 3 | AnswerGenerator 有 context role/required_ids 机制，但在 gate 体系外运行 |
| citation / span verification | 2 | evidence_id 级 deterministic 验证存在；span 级缺失；CitationVerifier 未接线 |
| hallucination control / abstention | 2.5 | eval 侧 abstention accuracy 完整、harness 有 INSUFFICIENT_EVIDENCE；生成侧无 runtime abstention policy |
| deterministic quality gates | 5 | 11 gate 全 deterministic、失败驱动 replan/halt、business 层 gate 会真实 fail（missing RAG evidence → fail），测试齐 |
| evaluation dataset / golden set | 3.5 | 67 条真实 golden、含 domain 分层与 expected_behavior=abstain；扣分：规模小、无多租户/新闻域样本、无 gold answer span |
| offline eval metrics | 4.5 | hit@k/MRR/faithfulness/context_precision/citation_ok/abstention/judge P-R/baseline delta/promotion thresholds，罕见完整 |
| online observability | 1 | 仅 logging；无 metrics/tracing/dashboard |
| trace / transcript / replay | 3 | transcript 完整入档；replay 机制存在但未接 RAG session |
| latency / cost / budget control | 3.5 | RAGBudget + BudgetGate 贯穿循环；无 token 成本核算、无生成侧预算 |
| multi-tenant / permission / security | 0 | 未找到证据 |
| failure recovery / retry / replan | 4 | replan/gap_report/halt 逻辑完整有测试；无跨进程 checkpoint 恢复 |
| production vs fake adapters | 4 | factory 全真实装配，fake 严格限于测试；扣分：集成测试主体是 fake |
| architecture boundary cleanliness | 3.5 | 有边界测试、factory 注释明确分层规则；扣分：business 直接依赖 framework 实现类（见 F 节） |
| enterprise deployment readiness | 2 | docker-compose 存在、CLI 可用；无租户/观测/eval CI/SLA |

---

## 3. 架构风险审查（对应任务3）

**R1 business 泄漏 framework 实现（中风险，确认存在）**：`paper_rag_session.py` 直接 `from framework.harness.rag.session import BoundedRAGSessionController` 并在 `run()` 中构造 controller；`retrieval_port.py` 直接 import `KernelRAGRetrieverHarnessAdapter`。DTO 级依赖（RAGBudget、RAGContextPack）可接受，实现类依赖使 business 无法脱离 harness 具体实现替换。

**R2 interfaces 层部分绕过 application（中风险，确认存在）**：`PaperRagApplicationService.rag_ask` 直接持有 retriever 并调用 `AnswerGenerator`，绕过 `PaperRAGSession`/bounded controller；`AskPaperUseCase` 形同虚设。即：**带 gate 的路径（PaperRAGSession）和实际服务的问答路径（rag_ask）是两条不同的路**，后者无 gate。这是当前最实质的架构风险。

**R3 deterministic work 交给 agent？** 未发现。planner/gate/quality 判分全 deterministic，LLM 仅做 worker（claim 抽取、summary、answer），符合 Harness 原则。

**R4 RAG 是否只是 vector search？** 不是——retrieval→evidence pack→gate 闭环真实存在；但 grounded answer→citation verification 段落断裂（R2 + CitationVerifier 未接线），完整四段闭环未闭合。

**R5 fake 被当生产？** 未发现（factory 干净）。但集成测试证明力被 fake 稀释（见 C4）。

**R6 memory 治理**：framework 层有 write/consolidate/invalidate/version；**rollback 未找到证据**；业务层 reader repair memory 是 in-memory，无持久化、无版本、无回滚——生产会失忆。

**R7 quality gate 是否形式化？** 不是形式化：`_quality_gate` 中 missing RAG evidence、无 claims、无 evidence_refs 都会真实 fail（`single_paper_runtime.py` L450+）。但 **`rag_ask` 服务路径完全不经过它**，所以对最终用户的问答而言 gate 目前形同虚设。

**R8 eval 覆盖失败模式？** 覆盖较好：abstention、judge 误判、gold_evidence_ok、失败分类（`paper_benchmark_suite.py` L97 `"abstention_wrong": "fix_answer_prompt"` 失败归因表）。缺：对抗性 query、跨源冲突、freshness。

**R9 compatibility layer / 跨层捷径**：`hybrid_search.py` 是孤儿遗留（依赖 LocalJsonRepository 旧存储形态）；OpenSpec 探查指出 `retrieval_port.py` 的位置争议（承担 infrastructure adapter 职责却放在 business）。未发现显式 compat/shim 层。

---

## 4. 真实端到端能力判断（对应任务4）

**能否算企业级 RAG？** 不能，目前是"企业级内核、单机级外环"。差距集中在：问答主路径绕过 gate 体系（R2）、citation span 验证缺失、eval 不在 CI、零观测、零租户、memory 不持久。

**最接近生产可用的路径**：`interfaces/cli/commands/paper.py` → `paper_rag_factory.build_chunk_pipeline / build_research_retriever` → Qdrant+Postgres+CrossEncoder → `rag_ask(generate=True)`。这条路真实数据、真实模型、可跑通，但无 gate。

**带 gate 的正确路径**（`build_paper_rag_session` → `PaperRAGSession.run` → BoundedRAGSessionController）基础设施齐备，但止步于 context_pack，不含 generation。

**P0 风险**：生产问答路径（rag_ask）没有任何 quality gate、citation 验证和 abstention 控制——坏答案可以无阻拦地到达用户。

**"基础设施已存在但无业务闭环"**：CitationVerifier、HybridSearchService、framework query expansion 元数据、EventReplay、framework/memory 高级 store 接口、visual chunk 描述（有 pipeline 但下游消费弱）。

**最能证明当前能力的测试**：`test_chunk_paper_e2e.py`（真实全链路 ingest）、`test_rag_session_controller.py` + `test_rag_plan_gates.py`（控制面正确性）、`test_reader_repair_rag_loop.py`（memory 闭环 + 权限不变量）、`test_benchmark_suite.py` + `data/eval/run_system_eval.py`（质量度量）。

**还缺的测试**：带真实 Qdrant 的 retrieval→gate→generation→citation 全链路集成测试（非 fake runtime）；rag_ask 经过 gate 后的对抗测试（不可回答问题必须 abstain）；golden set 回归接 CI 的门槛测试；memory 持久化重启恢复测试；并发/预算耗尽/超时故障注入测试；replay 一致性测试（同 transcript 重演结果一致）。

---

## F. P0/P1/P2 优化路线图（对应任务5）

### P0-1 将生产问答路径纳入 bounded 循环与 gate 体系
- 目标：`rag_ask` 不再绕过 gate；answer 必须经过 citation verify + abstention 判定才能返回。
- 目录：`interfaces/services/paper_rag_service.py`、`business/research/application/ask_paper.py`（充实为真实 use case：goal→PaperRAGSession→generation→verify→gate）、`business/research/rag/retrieval/paper_answer_generator.py`。
- 新增模块：`business/research/services/answer_gate.py`（组合 CitationVerifier + abstention policy）；generation 步骤注册进 workflow spec。
- 新增测试：`tests/business/research/integration/test_ask_paper_gated_loop.py`（含"证据不足必须 abstain"、"引用缺失必须 fail"用例）。
- 验收：CLI `paper ask --generate` 返回体中含 gate_results 与 citations；不可回答的 golden 样本 100% 走 abstain 分支。
- 风险：延迟增加（gate + verify 串行）；用 budget gate 控制轮次。

### P0-2 接线 CitationVerifier 并升级到 span 级
- 目标：answer 中每条 claim 的 citation 能定位到 chunk 内文本 span 且做 deterministic 包含/相似校验。
- 目录：`business/research/services/citation_verifier.py`（扩展 span 校验）、`business/research/rag/adapters/paper_source_locator.py`（已有 source_locator 可复用）。
- 测试：`tests/business/research/rag/test_citation_span_verify.py`。
- 验收：eval 的 citation_ok 从 id 级升级为 span 级，指标可回归。

### P0-3 Eval 接入 CI + golden 回归门槛
- 目标：每次 PR 跑 retrieval eval（fake embedding 或缓存向量），nightly 跑全量 system eval。
- 目录：`.github/workflows/ci.yml`、`scripts/dev`、`data/eval/`。
- 验收：MRR / strict_hit@10 / abstention_accuracy 低于 `PROMOTION_THRESHOLDS`（`paper_benchmark_suite.py` L2424+ 已有阈值表）即 CI fail。
- 风险：CI 需要 Qdrant service container；用 docker-compose service 或缓存索引解决。

### P1-1 Reader repair memory 持久化
- 目标：用 Postgres/Qdrant 实现 `ReaderRepairMemoryPort`，替换 InMemory 为生产默认，含版本与回滚。
- 目录：`infrastructure/storage/postgres/`（新增 repair_memory_repository.py）、`business/research/ports/repair_memory.py`。
- 测试：重启恢复测试 + 版本回滚测试。

### P1-2 真正的 hybrid retrieval
- 目标：Qdrant sparse vector（BM25/SPLADE）+ dense + RRF 融合，替换孤儿 `hybrid_search.py`（删除或重写）。
- 目录：`infrastructure/storage/vector/`（新增 sparse 编码与融合）、`business/research/rag/retrieval/paper_retriever.py`（策略开关）。
- 验收：benchmark suite 上 MRR/hit@10 相对 dense-only baseline 有可复现提升（套件已支持 baseline delta，L2155-2174）。

### P1-3 RAG session replay 接口
- 目标：给定 RAGTranscript + 固定检索快照可重演一次 session，gate 结果一致。
- 目录：`framework/harness/rag/`（新增 replay.py，复用 `framework/events/replay.py`）。
- 测试：`tests/framework/harness/rag/test_rag_session_replay.py`。

### P1-4 观测性
- 目标：RAG 路径打 OpenTelemetry span（retrieve/rerank/gate/generate），暴露延迟、轮次、abstain 率、gate fail 率指标。
- 目录：`framework/observability/`（新增）、factory 注入。

### P2-1 多租户与权限
- 目标：chunk payload 带 tenant_id/ACL，检索强制过滤，interfaces 层鉴权。
- 目录：`infrastructure/storage/vector/models.py`、`interfaces/services/auth_service.py`（已有雏形）。

### P2-2 新闻主路径 RAG 化
- 目标：source items evidence 检索走 bounded RAG，打通 PRD 主路径（`docs/prd/harness-research-runtime/10-real-data-agentic-rag.md` 范围）。

### P2-3 Query expansion 落地 + 反馈学习回路
- 目标：expansion 实现 + 用户反馈写入 golden set 的治理流程。

改造顺序：P0-1 → P0-2 → P0-3（三者两周内可并行推进）→ P1-1/P1-2 → P1-3/P1-4 → P2。

---

## G. 推荐目标架构（对应任务6）

```
[Ingestion]
  SourceConnector(arXiv/news/web) → DocumentParser(bakeoff 择优, 已有)
  → ChunkPipeline(section-aware + propositions + visual, 已有)
  → Embedding(dense + sparse) → Qdrant(chunk/field/visual, tenant_id payload)
  → Postgres(chunk registry + lineage + index version)

[Serving]
  Query → QueryUnderstanding(intent 路由, 已有; +expansion)
  → RetrievalPlanner(DeterministicRAGPlanner, 已有)
  → HybridRetriever(dense+sparse+RRF) → CrossEncoderReranker(已有)
  → EvidencePackAssembler + ContextBudgeter(已有 size/budget gate)
  → AnswerGenerator(纳入 bounded 循环, required_ids 机制已有)
  → CitationVerifier(span 级) → QualityGate(11 gate + answer gate)
  → AbstentionPolicy(deterministic: coverage/conflict/confidence 阈值)
  → 全程 RAGTranscript → EventLog(可 replay)

[Governance]
  EvalHarness(现有 benchmark suite) → CI 门槛 → promotion thresholds
  FeedbackLoop(用户反馈 → golden set 候选 → 人审 → 入库)
  Memory(持久化 store + write policy + version + rollback, framework 治理已有)
  Observability(OTel span + metrics) / Security(tenant filter + ACL + audit)
  ArtifactStore(现有 artifact service) 存 answer+evidence+transcript 供审计
```

核心原则维持现状优点：Harness 控流、LLM 只做 worker、gate 全 deterministic、fake 只进测试。

## H. 推荐评测体系（对应任务7）

- **Golden set 格式**：现有 `{question, source_chunk_id, paper_id, domain}` 扩展为 `{question, gold_evidence: [{chunk_id, span}], gold_answer, expected_behavior: answer|abstain, difficulty, tenant, freshness_date, conflict_group}`。
- **Retrieval**：strict/equivalent hit@k、MRR（已有）、+ recall@k、NDCG。
- **Answer**：answer_ok、faithfulness、context_precision（已有）、+ completeness。
- **Groundedness**：claim→span 支持率（P0-2 后可测）。
- **Citation**：id 级 citation_ok（已有）→ span precision/recall。
- **Abstention**：abstention_accuracy（已有）+ over-abstain 率。
- **Freshness/conflict/completeness**：新闻场景新增——同 conflict_group 内答案必须标注冲突来源。
- **Regression suite**：benchmark suite baseline delta（已有）作为每次索引/prompt/模型变更的强制回归。
- **Failure taxonomy**：扩展现有归因表（`paper_benchmark_suite.py` L97）为 retrieval_miss / rerank_error / generation_hallucination / citation_broken / abstention_wrong / budget_exhausted 六类，eval 报告按类聚合。
- **Replay workflow**：失败样本→取 transcript→P1-3 replay→定位失败 phase→归类→修复→重跑。
- **CI 门槛**：PR 级跑 retrieval eval（阈值用 PROMOTION_THRESHOLDS），nightly 全量，低于阈值 block merge。
- **人审闭环**：judge 判 fail 的样本进人审队列，人审结论回写 golden set（judge precision/recall 已有度量基础，L2052-2053）。

## I. 最小可上线标准

1. `paper ask` 全流量经过 bounded 循环 + answer gate + citation verify（P0-1/P0-2）。
2. 不可回答问题 abstention accuracy ≥ 0.9（golden set 上）。
3. Eval 在 CI，promotion thresholds 生效。
4. Memory 持久化，重启不失忆。
5. RAG 路径有基础 metrics（延迟、abstain 率、gate fail 率）与结构化日志。
6. transcript 落盘且任一失败请求可 replay 定位。
7. 至少一条真实数据 e2e 集成测试在 CI（Qdrant service container）常跑不 skip。

## J. 建议下一步 OpenSpec change 拆分

1. `gated-answer-loop`：generation 纳入 bounded 循环 + answer gate + abstention policy（对应 P0-1）。
2. `citation-span-verification`：span 级引用验证 + eval 指标升级（P0-2）。
3. `eval-ci-promotion-gates`：eval 接 CI + 阈值门禁（P0-3）。
4. `repair-memory-persistence`：repair memory Postgres 化 + 版本/回滚（P1-1）。
5. `hybrid-sparse-retrieval`：sparse+RRF，删除孤儿 hybrid_search.py（P1-2）。
6. `rag-session-replay`：transcript 重演接口（P1-3）。
7. `rag-observability`：OTel + metrics（P1-4）。
8. `tenant-scoped-retrieval`：多租户过滤与 ACL（P2-1）。

## K. 需要进一步确认的问题

1. 产品优先级：paper RAG 是终态产品，还是新闻主路径 RAG 化（PRD 10 号文档）才是真目标？这决定 P2-2 是否应提前。
2. `rag_ask` 的无 gate 快速路径是有意的低延迟 tradeoff，还是历史遗留？若有意，是否接受"gated 与 ungated 双路径"并显式命名？
3. `hybrid_search.py` 可否直接删除（当前零调用方）？
4. eval 的 LLM judge 使用什么模型、成本预算多少？影响 CI 门槛设计（PR 级是否只跑 retrieval 指标）。
5. 多租户是否在半年路线图内？若否，P2-1 可降级为 payload 预留字段。
6. reader repair memory 的持久化目标存储选 Postgres 还是复用 Qdrant + payload？

---

*本报告全部结论来自 2026-07-02 仓库工作区状态（HEAD f9f7aaae），无外部假设。*
