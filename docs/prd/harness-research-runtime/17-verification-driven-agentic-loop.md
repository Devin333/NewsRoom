# 阶段 17：验证驱动的 Agentic 循环 PRD

## 背景

阶段 3B 建立的 `BoundedRAGSessionController`（`framework/harness/rag/session.py`，511 行）忠实实现了 PLAN → EXECUTE → VERIFY 有界状态机：deterministic planner、11 个纯函数 gate、预算贯穿、transcript 全程记录。控制面骨架符合 README 总则的全部要求。

但 2026-07-02 的 Agentic 循环专项审查发现，**循环体内三个关键环节是占位符级实现，导致循环退化为"带预算的单策略重试"，而非验证驱动的检索智能体**：

**缺陷 1：evidence coverage 收敛条件是自我实现的恒真式。** 数据流如下：`DeterministicRAGPlanner.plan` 把本轮想要的 evidence type 写进 step metadata（`planner.py` L40 `metadata={"evidence_type": evidence_type}`）；`KernelRAGRetrieverHarnessAdapter.retrieve` 直接用 `request.metadata.get("evidence_type")` 给**所有**返回候选打标（`kernel_evidence_adapter.py` L61-64）；`_gap_report` 用 `present = {item.evidence_type for item in accepted}` 对 required types 做集合差（`session.py` L472-483）。于是第一轮找 "method"，返回的任何 chunk——哪怕是 related work 段落——都被标为 "method"，coverage 即告满足。**coverage gate 度量的是请求时的标签分配，不是证据的实际内容。** 只要检索非空，循环必然在 `len(required_evidence_types)` 轮内"成功"。

**缺陷 2：replan 不改变检索策略。** `DeterministicRAGPlanner` 的 gap 响应只是字符串拼接（`planner.py` L25-27：`query_text = f"{question} {' '.join(missing_evidence_types)}"`）。无查询改写、无子问题分解、无检索路径切换。第 N 轮与第 1 轮行为几乎相同，replan 预算花在重复同一动作上。已实现的 `WorkerRAGPlanner`（`planner.py` L62-105，含 forbidden_fields 防越权与 deterministic fallback）**没有任何生产调用点**——最该 agentic 的位置放着现成组件未接线。

**缺陷 3：VERIFY 链上没有"证据是否回答了问题"的判断。** `SourceVerifier.verify`（`source_verifier.py` L31-60）只检查 confidence 阈值与 lineage 完整性；conflict 判定依赖上游设置 `metadata["conflict"]`，而单论文路径上无任何组件设置它，conflicting 恒为空。检索回来五个高分但全是方法描述的 chunk，问"消融实验说明了什么"，循环会满意地组装 context pack 返回 SUCCEEDED。

**附带缺口：** generation 与 citation verification 在循环之外（企业审查 R2/R4）：`PaperRAGSession` 止步于 context pack；`rag_ask`（`interfaces/services/paper_rag_service.py`）绕过全部 gate 直达 `AnswerGenerator`；`CitationVerifier`（`business/research/services/citation_verifier.py`）无生产调用点。生成阶段的失败无法反馈为补查信号——而这正是 Agentic RAG 相对单轮 RAG 的核心价值。

本 PRD 交付四件事，把循环从"标签驱动"改为"验证驱动"：

```text
现状每轮：  plan(字符串拼接) → search → 按请求打标 → 集合差 → 假收敛
目标每轮：  plan(gap+拒绝原因驱动) → search → 按内容打标 → 相关性验证 → 真实 gap → 有策略的 replan
循环末端：  generation → citation verify → 失败 claim 回注 gap → 受控补查 → abstain 或返回
```

本 PRD 遵守层边界：`framework/harness/rag` 不 import business/infrastructure；business 通过 Port 提供实现；interfaces 层 factory 负责装配。所有新 gate 是纯函数，LLM 只产出候选，符合 README「VERIFY 不允许用 LLM 自评替代 gate」的红线。

---

## 设计原则

**先暴露真相，再提升能力**：缺陷 1 修复后，部分现在 SUCCEEDED 的 session 会变为 INSUFFICIENT_EVIDENCE——这是暴露真实覆盖率，不是回退。评测报告必须区分"打标修复导致的状态变化"与"能力回退"。

**LLM planner 是候选提供者，不是决策者**：`WorkerRAGPlanner` 产出的计划仍要过全套 plan gate（schema/allowlist/dedup/scope/budget）；LLM 不可用或产出不合法时 deterministic fallback 保证行为不劣于现状。

**相关性验证是 deterministic 判分**：相关性分数由 CrossEncoder 模型产出（模型推理是确定性计算，非 LLM 自评），阈值判定是纯函数。这与现有 reranker 在检索层的用法一致，不违反 gate 纯函数原则。

**生成失败是检索信号**：citation verify 发现无证据支撑的 claim 时，该 claim 成为新的 retrieval gap 回注循环，消耗 replan 预算受控补查；预算耗尽则 abstain。abstention 是显式决策与状态，不是空字符串。

**每个新相位入 transcript**：generation、citation verify、abstention 决策全部产生事件，格式对齐现有 `rag_*` 事件族，服务阶段 4 的 replay 目标。

---

## 一、E1：内容驱动的 evidence_type 打标

### 问题定位

`framework/harness/rag/kernel_evidence_adapter.py` L58-64：

```python
evidence_type = str(request.metadata.get("evidence_type") or self._default_evidence_type)
candidates = tuple(
    evidence_candidate_from_rag_evidence(item, evidence_type=evidence_type)  # 所有候选同一标签
    for item in evidence
)
```

### 方案

chunk 在阶段 11 chunking 时已携带内容结构信号：`PaperChunk.section_role: list[SectionRole]`（`business/research/document/models.py` L12，取值 `background | related_work | method | experiment | analysis | conclusion`）与 `chunk_type: ChunkType`（`abstract | paragraph | proposition | formula | figure | table`）。这些信号经 `paper_chunk_adapter` 进入 `RAGEvidence.metadata`。打标改为从内容信号映射，请求标签只作最后兜底。

### 代码定义

**新增 `framework/harness/rag/evidence_typing.py`**（framework 层，不依赖 business）：

```python
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class EvidenceTypeResolver(Protocol):
    """Maps retrieved-chunk metadata to a content-derived evidence type.

    Returns None when the metadata carries no usable signal, in which case
    the caller falls back to the requested/default type and records the
    fallback in candidate metadata.
    """

    def resolve(self, metadata: Mapping[str, Any]) -> str | None: ...


class MetadataKeyEvidenceTypeResolver:
    """Deterministic resolver driven by a declarative mapping table.

    mapping example (business supplies it, framework stays domain-neutral):
        {
          "section_role": {"method": "method", "experiment": "experiment",
                            "analysis": "experiment", "conclusion": "limitation"},
          "chunk_type":   {"table": "experiment", "figure": "experiment",
                            "formula": "method"},
        }
    Keys are checked in declaration order; first hit wins. Values in metadata
    may be scalars or lists (section_role is a list) — lists match on first
    mappable element.
    """

    def __init__(self, mapping: Mapping[str, Mapping[str, str]]) -> None:
        self._mapping = {str(k): dict(v) for k, v in mapping.items()}

    def resolve(self, metadata: Mapping[str, Any]) -> str | None:
        for meta_key, table in self._mapping.items():
            raw = metadata.get(meta_key)
            values = raw if isinstance(raw, (list, tuple)) else (raw,)
            for value in values:
                mapped = table.get(str(value))
                if mapped:
                    return mapped
        return None


__all__ = ["EvidenceTypeResolver", "MetadataKeyEvidenceTypeResolver"]
```

**修改 `framework/harness/rag/kernel_evidence_adapter.py`**：

```python
class KernelRAGRetrieverHarnessAdapter:
    def __init__(
        self,
        retriever: RAGRetrieverPort,
        *,
        default_intent: str = "general",
        default_evidence_type: str = "rag_evidence",
        evidence_type_resolver: EvidenceTypeResolver | None = None,   # 新增
    ) -> None: ...

    def retrieve(self, request: RetrievalRequest) -> EvidencePackCollection:
        ...
        requested_type = str(request.metadata.get("evidence_type") or self._default_evidence_type)
        candidates = []
        for item in evidence:
            resolved = (
                self._evidence_type_resolver.resolve(item.metadata)
                if self._evidence_type_resolver is not None else None
            )
            candidate = evidence_candidate_from_rag_evidence(
                item,
                evidence_type=resolved or requested_type,
            )
            if resolved is None and self._evidence_type_resolver is not None:
                candidate.metadata["evidence_type_source"] = "requested_fallback"
            else:
                candidate.metadata["evidence_type_source"] = "content_resolved" if resolved else "requested_default"
            candidates.append(candidate)
        ...
```

**新增 `business/research/rag/evidence_typing.py`**（business 提供领域映射表）：

```python
from framework.harness.rag.evidence_typing import MetadataKeyEvidenceTypeResolver

RESEARCH_EVIDENCE_TYPE_MAPPING: dict[str, dict[str, str]] = {
    "section_role": {
        "method": "method",
        "experiment": "experiment",
        "analysis": "experiment",
        "conclusion": "limitation",
        "background": "claim_support",
        "related_work": "claim_support",
    },
    "chunk_type": {
        "table": "experiment",
        "figure": "experiment",
        "formula": "method",
        "abstract": "claim_support",
    },
}

def build_research_evidence_type_resolver() -> MetadataKeyEvidenceTypeResolver:
    return MetadataKeyEvidenceTypeResolver(RESEARCH_EVIDENCE_TYPE_MAPPING)
```

**接线点**：`business/research/rag/retrieval_port.py` 的 `PaperChunkRetrievalPort.__init__` 构造 `KernelRAGRetrieverHarnessAdapter` 时传入 `evidence_type_resolver=build_research_evidence_type_resolver()`。

**前置校验**：`paper_chunk_adapter.py` 必须把 `section_role` 与 `chunk_type` 原样带入 `RAGEvidence.metadata`（当前已带 chunk metadata，需加测试锁定这两个键不丢失）。

### 测试

- `tests/framework/harness/rag/test_evidence_typing.py`：mapping 命中/列表值/未命中返回 None/声明序优先。
- `tests/framework/harness/rag/test_kernel_evidence_adapter.py` 扩展：resolver 命中时标签来自内容、`evidence_type_source` 三态正确。
- `tests/business/research/rag/test_research_evidence_typing.py`：领域映射表对六种 section_role 与四种 chunk_type 的映射断言。
- 回归：golden set 跑 `PaperRAGSession`，统计修复前后 SUCCEEDED → INSUFFICIENT_EVIDENCE 的迁移率并入报告（预期非零，属暴露真相）。

---

## 二、E2：SourceVerifier 相关性验证

### 问题定位

`SourceVerifier`（`framework/harness/rag/source_verifier.py`）只组合 `RAGSourceQualityGate` + `RAGLineageGate`，无相关性判断。

### 方案

framework 定义领域中立的 `RelevanceScorerPort`；新增 `RAGRelevanceGate`（纯函数阈值判定）；`SourceVerifier` 可选注入 scorer，reject 时记录 `low_relevance` 原因——该原因随 gap report 流入 planner，成为 E3 中 LLM replan 的输入。business 侧复用已有 CrossEncoder（`infrastructure/external/reranker.py`，进程单例已由 `paper_rag_factory.get_reranker` 管理）。

**关键细节**：相关性打分对象是 **spec.goal.question（原始问题）**，不是本轮拼接/改写后的查询——否则改写偏航会污染验证基准。

### 代码定义

**新增 `framework/harness/rag/relevance.py`**：

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.harness.rag.gates import RAGGateResult
from framework.harness.rag.models import EvidenceCandidate


@runtime_checkable
class RelevanceScorerPort(Protocol):
    """Scores evidence passages against the original goal question.

    Implementations must be deterministic for identical inputs (model
    inference qualifies; LLM free-form judgment does not).
    Returns one float in [0, 1] per passage, aligned with input order.
    """

    def score(self, question: str, passages: list[str]) -> list[float]: ...


class RAGRelevanceGate:
    gate_name = "rag_relevance"

    def __init__(self, *, default_threshold: float = 0.30) -> None:
        self._default_threshold = default_threshold

    def evaluate(
        self,
        question: str,
        evidence: tuple[EvidenceCandidate, ...],
        scores: tuple[float, ...],
        *,
        threshold: float | None = None,
    ) -> RAGGateResult:
        limit = self._default_threshold if threshold is None else float(threshold)
        low = [
            {"evidence_id": item.evidence_id, "score": round(score, 4)}
            for item, score in zip(evidence, scores)
            if score < limit
        ]
        passed = not low
        return RAGGateResult(
            self.gate_name,
            passed,
            None if passed else "one or more evidence candidates fall below the relevance threshold",
            {"threshold": limit, "low_relevance": low, "scored": len(evidence)},
        )


__all__ = ["RAGRelevanceGate", "RelevanceScorerPort"]
```

**修改 `framework/harness/rag/source_verifier.py`**：

```python
class SourceVerifier:
    def __init__(
        self,
        *,
        relevance_scorer: RelevanceScorerPort | None = None,   # 新增，None 时行为与现状完全一致
        relevance_gate: RAGRelevanceGate | None = None,
    ) -> None:
        self.source_quality = RAGSourceQualityGate()
        self.lineage = RAGLineageGate()
        self.relevance_scorer = relevance_scorer
        self.relevance_gate = relevance_gate or RAGRelevanceGate()

    def verify(
        self,
        evidence: tuple[EvidenceCandidate, ...],
        *,
        policy: RAGExecutionPolicy,
        question: str | None = None,   # 新增：原始 goal question
    ) -> SourceVerificationResult:
        relevance_scores: dict[str, float] = {}
        if self.relevance_scorer is not None and question and evidence:
            raw = self.relevance_scorer.score(question, [item.summary for item in evidence])
            relevance_scores = {item.evidence_id: float(s) for item, s in zip(evidence, raw)}
        threshold = float(policy.source_policy.get("min_relevance", 0.30))
        for candidate in evidence:
            ...  # 现有 quality/lineage 判定不变
            score = relevance_scores.get(candidate.evidence_id)
            if score is not None and score < threshold:
                rejected.append(_with_rejection_reason(candidate, "low_relevance", score))
                continue
            ...
```

reject 原因写入候选 metadata（`rejection_reason: "low_relevance"`、`relevance_score`），`SourceVerificationResult.gate_results` 追加 relevance gate 结果。

**修改 `framework/harness/rag/session.py`** L140：`self.source_verifier.verify(..., question=spec.goal.question)`。

**修改 `_gap_report`（session.py）** 使 gap 携带拒绝原因分布，供 planner 消费：

```python
def _gap_report(spec, accepted, results, rejected=()):
    ...
    return {
        "missing_evidence_types": missing,
        "accepted_evidence_ids": [...],
        "gate_results": _results(results),
        "rejection_summary": _rejection_summary(rejected),   # 新增
        # 形如 {"low_relevance": {"count": 3, "evidence_types": {"method": 3}},
        #       "low_confidence": {"count": 1, ...}}
    }
```

**business 侧适配器，新增 `business/research/rag/adapters/relevance_scorer.py`**：

```python
from business.research.ports.reranker import RerankerPort


class RerankerRelevanceScorer:
    """RelevanceScorerPort implementation backed by the existing CrossEncoder RerankerPort.

    CrossEncoder raw scores are unbounded logits for some models; normalize via
    sigmoid so the gate threshold lives in [0, 1] regardless of backbone.
    """

    def __init__(self, reranker: RerankerPort) -> None:
        self._reranker = reranker

    def score(self, question: str, passages: list[str]) -> list[float]:
        raw = self._reranker.score(question, passages)
        return [_sigmoid(v) for v in raw]
```

**装配点**：`interfaces/services/paper_rag_factory.py` 的 `build_paper_rag_session` 把 `RerankerRelevanceScorer(get_reranker())` 传入 `PaperRAGSession`，后者透传给 `BoundedRAGSessionController(source_verifier=SourceVerifier(relevance_scorer=...))`。`min_relevance` 阈值经 `ResearchRAGPolicyBuilder.build_session_spec` 写入 `source_policy`（默认 0.30，与检索层 `rerank_score_threshold` 对齐，后续用 golden set 校准）。

**性能预算**：相关性打分复用 reranker 单例，每轮增加一次 batch 推理（≤ max_context_items 条 passage）。`RAGBudget.max_worker_calls` 已有额度约束；打分耗时入 transcript 事件。

### 测试

- `tests/framework/harness/rag/test_rag_relevance_gate.py`：阈值边界、低分明细、空 evidence。
- `tests/framework/harness/rag/test_source_verifier_relevance.py`：scorer 注入后 reject 带 `low_relevance` 原因；scorer 为 None 时与现状逐位一致（回归保护）。
- `tests/framework/harness/rag/test_rag_session_controller.py` 扩展：低相关证据被拒后 gap_report.rejection_summary 非空且触发 replan。
- `tests/business/research/rag/test_reranker_relevance_scorer.py`：sigmoid 归一、与 RerankerPort 对接。

---

## 三、E3：WorkerRAGPlanner 生产接线

### 问题定位

`WorkerRAGPlanner` 已实现（含 forbidden_fields、fallback、`RetrievalPlanCandidate.from_dict` 校验），但 `PaperRAGSession` 构造 controller 时未传 planner（`business/research/application/paper_rag_session.py` L74：`BoundedRAGSessionController(retrieval=retrieval_port)`）。

### 方案

business 侧提供一个把 `ResearchCandidateWorkerPort`（`business/research/ports/llm_worker.py`，`generate_candidate(*, task, payload) -> dict`）适配为 WorkerRAGPlanner 所需 worker 形状（`generate(request) -> HarnessWorkerResult`）的适配器；从第 2 轮起才启用 LLM planner（第 1 轮 deterministic 计划已足够且零成本）；LLM 输入包含 E2 产出的拒绝原因摘要。

### 代码定义

**修改 `framework/harness/rag/planner.py` 的 `WorkerRAGPlanner`**，支持轮次门槛（保持向后兼容）：

```python
class WorkerRAGPlanner:
    def __init__(
        self,
        worker: Any,
        fallback: RAGPlanner | None = None,
        *,
        min_round_index: int = 0,   # 新增：低于该轮次直接走 fallback，省 worker 调用
    ) -> None: ...

    def plan(self, spec, *, round_index, gap_report):
        if round_index < self._min_round_index:
            return self.fallback.plan(spec, round_index=round_index, gap_report=gap_report)
        ...  # 现有逻辑不变；request 已含 gap_report（E2 后自然携带 rejection_summary）
```

同时在 request 中补充已执行查询，防 LLM 重复提案（dedup gate 仍是最终防线）：

```python
request = {
    "task_type": "rag_plan_candidate",
    ...
    "executed_queries": sorted(executed_queries),   # plan() 签名增加可选参数透传
}
```

`RAGPlanner` Protocol 的 `plan` 签名增加 `executed_queries: tuple[str, ...] = ()` 关键字参数（Protocol 与两个实现同步改，`session.py` 调用点传 `tuple(state.executed_queries)`）。

**新增 `business/research/rag/adapters/plan_worker.py`**：

```python
from framework.harness.rag.models import RetrievalPlanCandidate
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus
from business.research.ports.llm_worker import ResearchCandidateWorkerPort


class ResearchRAGPlanWorker:
    """Adapts ResearchCandidateWorkerPort to the worker shape WorkerRAGPlanner calls.

    The LLM receives: goal question, gap report (missing types + rejection
    summary), executed queries, budget snapshot, allowed corpora/namespaces,
    and the RetrievalPlanCandidate JSON schema. It must return
    {"candidate": {...}} parseable by RetrievalPlanCandidate.from_dict.
    Any parse/validation error is surfaced as FAILED so WorkerRAGPlanner
    falls back deterministically.
    """

    def __init__(self, candidate_worker: ResearchCandidateWorkerPort) -> None:
        self._worker = candidate_worker

    def generate(self, request: dict) -> HarnessWorkerResult:
        try:
            payload = self._worker.generate_candidate(
                task="rag_replan_candidate",
                payload=request,
            )
            candidate = RetrievalPlanCandidate.from_dict(payload["candidate"])
        except Exception as exc:
            return HarnessWorkerResult(status=HarnessWorkerStatus.FAILED,
                                       output={}, errors=(str(exc),))
        return HarnessWorkerResult(status=HarnessWorkerStatus.SUCCEEDED,
                                   output={"candidate": candidate})
```

Prompt 模板放 `business/research/rag/adapters/plan_worker_prompt.py`，要求 LLM 产出的每个 query step 附 `metadata["replan_strategy"]`（`rephrase | decompose | scope_narrow | scope_widen` 之一），入 transcript 供离线分析哪种策略有效。

**修改 `business/research/application/paper_rag_session.py`**：

```python
class PaperRAGSession:
    def __init__(
        self,
        chunk_store: ChunkStorePort,
        *,
        ...
        plan_worker: ResearchCandidateWorkerPort | None = None,   # 新增
        relevance_scorer: RelevanceScorerPort | None = None,       # E2 新增
    ) -> None: ...

    def run(self, goal, *, run_id, workflow_id, step_id, session_id, current_section_index=0):
        ...
        planner = (
            WorkerRAGPlanner(
                ResearchRAGPlanWorker(self._plan_worker),
                fallback=DeterministicRAGPlanner(),
                min_round_index=1,          # 第 1 轮 deterministic，第 2 轮起 LLM 改写
            )
            if self._plan_worker is not None
            else None
        )
        controller = BoundedRAGSessionController(
            retrieval=retrieval_port,
            planner=planner,
            source_verifier=SourceVerifier(relevance_scorer=self._relevance_scorer),
        )
        ...
```

**装配点**：`interfaces/services/paper_rag_factory.py` 的 `build_paper_rag_session` 增加 `with_llm_planner: bool = True` 参数，为 True 时用 `build_unity_llm_call`（`business/research/application/llm_client.py` 已有）构造 candidate worker 注入。环境开关 `NEWS_RAG_LLM_PLANNER=0` 可关闭（降级为纯 deterministic，行为等于现状）。

### 测试

- `tests/framework/harness/rag/test_worker_rag_planner.py` 扩展：min_round_index 门槛、executed_queries 透传、worker FAILED 时 fallback。
- `tests/business/research/rag/test_research_rag_plan_worker.py`：合法 candidate 解析、非法 payload → FAILED、forbidden_fields 出现在 request 中。
- `tests/business/research/integration/test_rag_replan_with_worker_planner.py`（fake candidate worker）：第 1 轮 deterministic、第 2 轮 LLM 计划生效、LLM 计划被 plan gate 拒绝时受控 replan/halt、`replan_strategy` 入 transcript。

---

## 四、E4：generation + citation verify 收进循环（GENERATE 相位）

### 问题定位

循环止步于 `RETURN_CONTEXT_PACK`；`AnswerGenerator`（`business/research/rag/retrieval/paper_answer_generator.py`，`GeneratedAnswer` 含 `context_chunk_ids`）与 `CitationVerifier` 在循环外各自孤立；`rag_ask` 无 gate。生成失败无法驱动补查。

### 方案

framework 定义 `AnswerWorkerPort` 与 `RAGAnswerGate`（纯函数）；controller 增加可选的 GENERATE → VERIFY_ANSWER 相位：context pack 通过后调用 answer worker，产出过 answer gate；**unsupported claims 回注 gap report 触发受控补查**；预算耗尽或补查仍失败则显式 ABSTAINED。整个相位默认关闭（`generation_policy` 未配置时行为与现状逐位一致），保证 3B 既有语义不被破坏。

### 代码定义

**扩展 `framework/harness/rag/models.py`**：

```python
class RAGSessionStatus(Enum):
    SUCCEEDED = "succeeded"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    HALTED = "halted"
    ANSWERED = "answered"        # 新增：生成相位启用且答案过 gate
    ABSTAINED = "abstained"      # 新增：显式弃答


@dataclass(frozen=True)
class GroundedAnswerCandidate:
    """LLM worker output for the GENERATE phase. A candidate, not a decision."""
    answer_id: str
    question: str
    answer_text: str
    cited_evidence_ids: tuple[str, ...]          # 每条必须指向 context pack 内的 evidence_id
    claims: tuple[AnswerClaim, ...]              # 结构化 claim 列表，逐条绑 evidence
    abstained: bool = False                      # worker 可以提议弃答，但由 gate/controller 决定
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnswerClaim:
    claim_id: str
    text: str
    evidence_ids: tuple[str, ...]
```

`RAGSessionResult` 增加 `answer: GroundedAnswerCandidate | None = None` 字段（`to_dict` 同步）。

**新增 `framework/harness/rag/answer_gate.py`**：

```python
class RAGAnswerGate:
    """Pure-function verification of a GroundedAnswerCandidate against its context pack.

    Checks (all deterministic):
      1. citation_integrity  — every cited_evidence_id / claim evidence_id exists in the pack
      2. claim_coverage      — every claim carries >= 1 evidence_id
      3. answer_nonempty     — answer_text non-blank unless abstained
      4. abstention_honesty  — abstained=True requires empty answer_text
    """
    gate_name = "rag_answer"

    def evaluate(
        self,
        candidate: GroundedAnswerCandidate,
        pack: RAGContextPack,
    ) -> tuple[RAGGateResult, ...]:
        available = {item.evidence_id for item in pack.context_items}
        ...
        # 返回 (citation_integrity_result, claim_coverage_result, shape_result)
        # 每个 fail 的 metadata 携带 unsupported_claims: [{"claim_id", "text", "missing_evidence_ids"}]
```

**新增 `framework/harness/rag/answer_worker.py`**：

```python
@runtime_checkable
class AnswerWorkerPort(Protocol):
    """LLM worker that drafts a grounded answer from a verified context pack.

    Workers produce candidates only. They must not decide loop continuation,
    memory writes, or publication — those remain controller/gate decisions.
    """

    def generate_answer(
        self,
        *,
        question: str,
        pack: RAGContextPack,
    ) -> GroundedAnswerCandidate: ...
```

**修改 `framework/harness/rag/session.py`** —— 在 `RETURN_CONTEXT_PACK` 决策点之后插入生成相位（伪代码级完整逻辑）：

```python
class BoundedRAGSessionController:
    def __init__(self, *, ..., answer_worker: AnswerWorkerPort | None = None,
                 answer_gate: RAGAnswerGate | None = None) -> None:
        ...
        self.answer_worker = answer_worker
        self.answer_gate = answer_gate or RAGAnswerGate()

    def run(self, spec):
        ...
        # 现有循环结束、pack 验证通过后：
        if pack is not None and self.answer_worker is not None and policy.generation_enabled:
            answer, status, decision = self._run_generation_phase(spec, state, policy, pack)
        ...

    def _run_generation_phase(self, spec, state, policy, pack):
        for attempt in range(policy.max_generation_attempts):        # 默认 2
            state.budget_snapshot = state.budget_snapshot.with_usage(worker_calls=1)
            budget_gate = self.gates.budget.evaluate(state.budget_snapshot, policy)
            if not budget_gate.passed:
                return None, RAGSessionStatus.ABSTAINED, self._abstain(state, "generation budget exhausted")
            candidate = self.answer_worker.generate_answer(question=spec.goal.question, pack=pack)
            self._event(state, "rag_answer_candidate_created",
                        {"attempt": attempt, "answer_id": candidate.answer_id,
                         "claims": len(candidate.claims), "abstained": candidate.abstained})
            results = self.answer_gate.evaluate(candidate, pack)
            self._event(state, "rag_answer_verified",
                        {"attempt": attempt, "gate_results": _results(results)})
            if all(r.passed for r in results):
                if candidate.abstained:
                    return candidate, RAGSessionStatus.ABSTAINED, self._abstain(state, "worker proposed abstention and gates concur")
                return candidate, RAGSessionStatus.ANSWERED, RAGDecision(
                    RAGDecisionType.RETURN_ANSWER, "answer verified",
                    gate_results=_results(results), budget_snapshot=state.budget_snapshot)
            unsupported = _unsupported_claims(results)
            if unsupported and self._can_replan(state, spec):
                # 失败 claim 回注 gap，走一轮受控补查后重组 pack、重试生成
                state.budget_snapshot = state.budget_snapshot.with_usage(replans=1)
                state.gap_report["unsupported_claims"] = unsupported
                self._event(state, "rag_answer_replan", {"unsupported_claims": unsupported})
                pack = self._supplemental_round(spec, state, policy) or pack
                continue
        return None, RAGSessionStatus.ABSTAINED, self._abstain(state, "answer verification failed and no replan remains")
```

`_supplemental_round` 复用主循环的单轮逻辑（plan → plan gate → execute → source verify → 重新 assemble + pack gate），unsupported claim 文本作为 planner 输入（进入 gap_report，E3 的 LLM planner 自然消费）。`RAGDecisionType` 增加 `RETURN_ANSWER` 与 `ABSTAIN` 两个枚举值（`policy.py`）。

**generation policy 进 `RAGExecutionPolicy`**（`policy.py`）：

```python
# RAGSessionSpec.context_policy 或新增 generation_policy dict 承载：
# {"enabled": true, "max_generation_attempts": 2}
@property
def generation_enabled(self) -> bool:
    return bool(self.generation_policy.get("enabled", False))
```

`RAGSessionSpec` 增加 `generation_policy: dict[str, Any] = field(default_factory=dict)`（`models.py`，`to_dict/from_dict` 同步）。默认空 dict → 相位关闭 → 现状行为，全部既有测试无需改动即通过。

**business 侧 answer worker 适配器，新增 `business/research/rag/adapters/answer_worker.py`**：

```python
class PaperAnswerWorker:
    """AnswerWorkerPort implementation wrapping the existing AnswerGenerator.

    Responsibilities:
      - project RAGContextPack items back to PaperChunks (via chunk_store.get_chunk
        on metadata["rag_chunk_id"]) so AnswerGenerator's context-role bucketing keeps working
      - run AnswerGenerator (async) synchronously via anyio/asyncio.run boundary here,
        keeping the framework port synchronous
      - parse the structured answer into GroundedAnswerCandidate: claims come from
        a structured-output prompt revision of AnswerGenerator (each claim cites chunk ids);
        cited chunk ids map back to evidence_ids via the pack's rag_chunk_id -> evidence_id index
      - propose abstention (abstained=True, empty text) when AnswerGenerator's
        insufficient-context marker fires
    """

    def __init__(self, generator: AnswerGenerator, chunk_store: ChunkStorePort) -> None: ...

    def generate_answer(self, *, question: str, pack: RAGContextPack) -> GroundedAnswerCandidate: ...
```

`AnswerGenerator` 的 prompt 需扩展结构化输出段（claims JSON，逐条带 `cited_chunk_ids`），解析失败时降级为"整答案单 claim + 全部 context ids"，并在 metadata 记 `claims_degraded: true`（gate 仍能做 citation integrity，只是粒度粗）。此扩展在 `paper_answer_generator.py` 内完成，不新建平行生成器。

**`CitationVerifier` 的归宿**：`RAGAnswerGate` 的 citation_integrity 检查在 framework 层重新实现了同等 deterministic 逻辑（evidence_id 集合验证），`business/research/services/citation_verifier.py` 保留用于 `single_paper_runtime` 的 claim 验证场景；span 级升级（PRD 16 讨论的 P0-2）作为后续阶段在 `RAGAnswerGate` 上扩展 `span_containment` 检查，本 PRD 不含。

### `rag_ask` 切换（interfaces 层）

`interfaces/services/paper_rag_service.py`：

```python
class PaperRagApplicationService:
    def rag_ask(self, paper_id, question, *, section_index=0, limit=5,
                generate=False, gated: bool = True) -> dict[str, Any]:
        if generate and gated:
            return self._gated_ask(paper_id, question, section_index=section_index)
        ...  # 旧路径保留为 gated=False 的显式降级（标注 deprecated，阶段 18 删除）

    def _gated_ask(self, paper_id, question, *, section_index):
        session = build_paper_rag_session(with_llm_planner=True, with_answer_worker=True)
        goal = build_ask_goal(paper_id, question)      # AskPaperUseCase 充实为真实构建器
        result = session.run(goal, run_id=..., ...)
        return {
            "status": result.status.value,             # answered | abstained | insufficient_evidence | halted
            "answer": result.answer.answer_text if result.answer else None,
            "claims": [c.to_dict() for c in (result.answer.claims if result.answer else ())],
            "citations": _citations_with_locators(result),   # evidence_id → source_locator 投影
            "gate_results": _final_gate_results(result.transcript),
            "transcript_id": result.transcript.transcript_id,
        }
```

`AskPaperUseCase`（`business/research/application/ask_paper.py`，现为 pass-through）充实为 `build_ask_goal`：按问题构建 `ResearchRetrievalGoal`——`required_evidence_types` 由检索层 intent 分类映射（table/numerical → `["experiment"]`，concept_method → `["method"]`，默认 `["claim_support"]`），复用 `business/research/rag/retrieval/paper_policy.py` 的 `build_retrieval_route`，不新写分类器。

CLI `paper ask --generate`（`interfaces/cli/commands/paper.py`）输出增加 `status` 与 citations 段；abstained 时打印 gap report 摘要而非空答案。

### 测试

- `tests/framework/harness/rag/test_rag_answer_gate.py`：citation integrity（含 pack 外引用）、claim coverage、abstention honesty、unsupported_claims metadata 形状。
- `tests/framework/harness/rag/test_rag_generation_phase.py`（fake answer worker）：一次通过 → ANSWERED；unsupported claim → 补查轮 → 重试通过；replan 耗尽 → ABSTAINED；`generation_policy` 缺省 → 相位不运行、现状逐位一致（回归锁）。
- `tests/framework/harness/rag/test_rag_transcript.py` 扩展：`rag_answer_candidate_created / rag_answer_verified / rag_answer_replan / rag_abstained` 事件序列。
- `tests/business/research/rag/test_paper_answer_worker.py`：pack→chunk 投影、claims 解析、降级路径（claims_degraded）、abstention 提议。
- `tests/business/research/integration/test_gated_ask_loop.py`（fake LLM + 真实 gate 链）：可回答问题 → ANSWERED 带 citations；证据不足问题 → ABSTAINED；引用 pack 外 id 的 fake 答案 → 补查或 ABSTAINED，绝不 ANSWERED。
- golden set 回归：`expected_behavior == "abstain"` 的样本经 gated 路径 100% 不返回 ANSWERED。

---

## 五、Harness 层影响汇总

| 文件 | 变更 | 兼容性 |
| --- | --- | --- |
| `framework/harness/rag/evidence_typing.py` | 新增 resolver Protocol + 映射实现 | 纯新增 |
| `framework/harness/rag/kernel_evidence_adapter.py` | 可选 resolver 参数 + `evidence_type_source` 标记 | resolver=None 时行为不变 |
| `framework/harness/rag/relevance.py` | 新增 RelevanceScorerPort + RAGRelevanceGate | 纯新增 |
| `framework/harness/rag/source_verifier.py` | 可选 scorer + question 参数 + 拒绝原因 | scorer=None 时行为不变 |
| `framework/harness/rag/planner.py` | WorkerRAGPlanner 加 min_round_index；plan() 签名加 executed_queries | 默认值保持现状 |
| `framework/harness/rag/session.py` | verify 传 question；gap_report 加 rejection_summary；生成相位 `_run_generation_phase` + `_supplemental_round` | generation_policy 空时相位关闭 |
| `framework/harness/rag/models.py` | RAGSessionStatus 加 ANSWERED/ABSTAINED；新增 GroundedAnswerCandidate/AnswerClaim；RAGSessionSpec 加 generation_policy；RAGSessionResult 加 answer | 新枚举/字段默认不激活 |
| `framework/harness/rag/policy.py` | RAGDecisionType 加 RETURN_ANSWER/ABSTAIN；RAGExecutionPolicy 加 generation_enabled | 同上 |
| `framework/harness/rag/answer_gate.py` / `answer_worker.py` | 新增 | 纯新增 |
| `framework/harness/rag/gates.py` | RAGGateSuite 注册 relevance 与 answer gate 引用（构造保持无参） | 不变 |
| `framework/harness/rag/__init__.py` | 导出全部新符号 | — |

红线自查：framework 新增代码零 business/infrastructure import；所有 gate 为纯函数；LLM（planner worker / answer worker）只产候选；ABSTAIN/RETURN_ANSWER 由 controller 依 gate 结果决定。transcript 事件族扩展与阶段 4 replay 契约兼容（事件仍是 append-only dict 序列）。

fake 运行时同步：`framework/harness/rag/fake.py` 增加 `FakeAnswerWorker`（可编程返回合法/非法/弃答候选），供 framework 级测试；`FakeResearchRAGRuntime`（business 测试用）增加对 ANSWERED/ABSTAINED 状态的模拟。

---

## 六、交付分解与顺序

| 步骤 | 内容 | 依赖 | 回归要求 |
| --- | --- | --- | --- |
| T0 | golden set 基线快照（若 PRD 16 S0 已做则复用） | — | 基线报告存档 |
| T1 | E1 内容打标：resolver + adapter 改造 + 领域映射 + 接线 | — | SUCCEEDED→INSUFFICIENT 迁移率入报告；`evidence_type_source` 分布可见 |
| T2 | E2 相关性验证：gate + verifier + gap rejection_summary + factory 装配 | T1 | scorer=None 回归逐位一致；注入后 golden set evidence_coverage 变化入报告 |
| T3 | E3 planner 接线：min_round_index + plan worker 适配器 + prompt + 环境开关 | T2（消费 rejection_summary） | `NEWS_RAG_LLM_PLANNER=0` 下逐位一致；开启后 replan 轮的新查询去重率 100% |
| T4 | E4 生成相位：framework 相位 + answer gate + business answer worker + spec/policy 扩展 | T1-T3 | generation_policy 空时全量既有测试绿；fake worker 相位测试全绿 |
| T5 | `rag_ask` 切换 gated 路径 + AskPaperUseCase 充实 + CLI 输出 | T4 | golden set abstain 样本 0 误答；gated 路径延迟 P95 入报告 |

T1/T2 可并行开发但按序合入；T3 依赖 T2 的 gap 结构；T4 是最大单体，内部再按 framework → business → interfaces 三个 commit 推进。

---

## 七、验收标准

1. **恒真收敛消除**：构造"required=experiment 但语料只有 method 章节"的测试论文，session 必须以 INSUFFICIENT_EVIDENCE 结束而非 SUCCEEDED（这是 E1 的判决性测试）。
2. **相关性拒绝可见**：低相关证据被拒时 transcript 含 relevance gate 结果与 rejection_summary；`min_relevance` 可经 source_policy 配置。
3. **replan 有策略**：开启 LLM planner 后，第 2 轮起的查询与第 1 轮不同且通过 dedup gate；`replan_strategy` 在 transcript 中可统计。
4. **生成受控**：gated `rag_ask` 返回体含 status/claims/citations/gate_results/transcript_id；引用 pack 外 evidence_id 的答案永不以 ANSWERED 返回。
5. **abstention 显式**：golden set `expected_behavior=abstain` 样本经 gated 路径 abstention accuracy ≥ 0.9，误答率 0。
6. **零静默回归**：resolver/scorer/planner/generation 四个注入点全部为 None/关闭时，全量既有测试与 golden set 指标逐位一致。
7. **层边界**：`tests/framework/rag/test_import_boundaries.py` 扩展覆盖新文件，framework 新代码无向上依赖。
8. **transcript 完整**：新事件族（answer candidate/verified/replan/abstained）入 transcript，`test_rag_transcript.py` 锁定事件序列形状。

---

## 八、风险与对策

| 风险 | 对策 |
| --- | --- |
| E1 修复后 INSUFFICIENT_EVIDENCE 比例骤升，下游（single_paper_runtime 的 `ResearchRAGEvidenceNeedGate`）连锁 fail | T1 单独合入并先跑影子评测；映射表阈值（如 conclusion→limitation）依据迁移率报告调整；必要时 `required_evidence_types` 按论文实际结构裁剪（goal 构建时用 document.sections 的 role 分布过滤） |
| 相关性阈值误杀正确证据（尤其 formula/table 类 summary 文本短） | 阈值按 evidence_type 分层配置（source_policy 支持 `min_relevance_by_type`）；formula/table 初始阈值放宽至 0.20；golden set 校准后固化 |
| LLM planner 提案质量差、浪费预算 | min_round_index=1 保证首轮零成本；plan gate 全套拦截非法提案；`replan_strategy` 统计离线评估提案有效率，无效则回退纯 deterministic（环境开关一键关） |
| 生成相位拉长交互延迟 | max_generation_attempts=2 硬上限；补查轮消耗 replan 预算（默认 safe_default 的 max_replans）；P95 延迟入验收报告，超标则默认关闭 gated 路径待优化 |
| GroundedAnswerCandidate 的 claims 结构化输出解析失败率高 | 降级路径（单 claim + claims_degraded 标记）保证 gate 仍可运行；解析失败率入 transcript 统计，超 20% 时优化 prompt 而非放宽 gate |
| framework 相位扩展破坏 3B 既有测试 | generation_policy 默认空 = 相位不存在；T4 合入前全量 `tests/framework/harness/rag/` 必须零修改通过（新增测试除外） |
| 与 PRD 16 检索层重构的合并冲突 | 本 PRD 不触碰 `paper_retriever.py` 内部；接触面仅 `retrieval_port.py`（E1 接线一行）与 factory；若 PRD 16 S4-S8 先行，E1 接线点随 pipeline 装配同步移动 |

---

## 九、OpenSpec change 拆分建议

1. `rag-content-derived-evidence-typing`（T1）：resolver + adapter + 领域映射 + 判决性测试。
2. `rag-relevance-verification`（T2）：RelevanceScorerPort + gate + verifier 扩展 + gap rejection_summary + factory 装配。
3. `rag-worker-planner-wiring`（T3）：min_round_index + plan worker 适配器 + prompt + 集成测试。
4. `rag-generation-phase-and-answer-gate`（T4，最大）：framework 相位 + answer gate + models/policy 扩展 + business answer worker + fake。
5. `gated-rag-ask-endpoint`（T5）：rag_ask 切换 + AskPaperUseCase 充实 + CLI + abstention 回归。

每个 change 独立可回滚；change 1-3 合入后即使 change 4 未动工，循环也已从"假收敛"变为"真验证"，价值独立成立。
