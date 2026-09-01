# Design

## Context

现有 /projects/lab 路由委托给 ProjectsProductPage route="lab"，在同一组件中管理问题 textarea、active question、Generate Solution、LabGraph 和原始 JSON。/projects/lab/[sessionId] 单独读取 session，提供简单的保存按钮和四个信息面板。

该路由位于 Projects AppShell，已经有 ResearchHeader、shadcn/Radix primitives、React Query、ProjectLoadingState、ProjectErrorState、ProjectEmptyState、ProjectDegradedNotice、ProjectSourceLine、explain-node API、LabGraph 以及 light/dark tokens。设计应在现有系统内演进，不引入并行 dashboard 或新设计框架。

## Goals

- 用一个明确的下一动作让确定性 Lab flow 易于理解。
- 让用户 brief、真实数据上下文、问题、生成方案和 session 操作保持视觉区分，避免卡片套卡片。
- 真实表达 pending、错误、空数据和降级数据。
- 让 graph、status 和 solution 内容不依赖鼠标或 SVG 解读。
- 在移动端保持同一套研究任务，而不是制作一个功能缩水的第二产品。

## Non-goals

- 不用前端状态机替代业务 stage 逻辑。
- 不展示伪造的 streaming/typing feedback 或内部推理。
- 不重做所有 Projects route 或全局字体。
- 不用积极但含糊的语言隐藏不可用 source data。

## Architecture and ownership

### Data flow

~~~text
Projects API client
  -> React Query query/mutation
  -> ResearchLabWorkspace presentation state
  -> Lab workflow/status, clarification, context, solution, actions components
~~~

所有有权限含义的呈现状态都来自 API response：

~~~text
current_stage + next_action + can_generate_solution + unanswered_question_ids
  -> LabWorkflowStatus and action availability
~~~

ResearchLabWorkspace 只可保留未提交 UI draft、选中的 visual Tab、打开的 node explanation 和 focus targets。它不得重新计算问题完整性、生成授权、保存状态、quality evaluation、source selection 或 workflow routing。

### Component ownership

| Component | Owns | Does not own |
| --- | --- | --- |
| ResearchLabWorkspace | composition、React Query wiring、local drafts、focus transitions | domain state calculation |
| LabBriefComposer | problem draft and start submission view | case selection policy |
| LabWorkflowStatus | status rendering and accessible announcement | stage mutation |
| LabClarificationList | question card order、answer input、local error display | answer persistence |
| LabContextPanel | source/degraded UI、graph viewer、text summary、node explanation UI | graph derivation |
| LabSolutionPanel | Summary/Structured/Evidence view and copy action | content generation/editing |
| LabSessionActions | detail navigation、save interaction、terminology | approval/publication |

## Visual system

### Adapted reference language

参考页使用 light surfaces、紧凑但可读的纵向层级、chat-shaped exchange cards、dark code surface、concise chips/status 和清晰 Tabs。本设计沿用交互语法但改变产品意图：

- chat cards 变成研究 artifact，而不是 assistant persona；
- 使用 Agora Hub blue accent 替代 purple；
- source、data_state、case counts 和 non-goals 作为一等信息；
- 不使用 billboard hero、pricing、integrations、gradient imagery 或外部 brand treatment；
- 视觉语气是严肃的 research operation：边界克制、标签简洁、信息可扫描。

### Layout

~~~text
Header and real-data notice
Brief composer
-------------------------------------------------------
Workflow rail | Conversation and solution workspace | Context
              | clarification cards / solution tabs | graph/evidence
-------------------------------------------------------
~~~

在 >=1280px 时中央内容优先，context 保持可见但更窄；1024-1279px 使用 7/5 或 8/4 两栏；低于 1024px 时堆叠 workflow、conversation、solution、context，context 可收进 Sheet 或明确 disclosure，但必须可由键盘访问；低于 768px 时 action 全宽，source/graph context 移到 active question 或 solution summary 之后。

### Surface and feedback rules

- 页面背景复用 --background；workspace surfaces 复用 --card / --lab-surface。
- 不使用装饰性嵌套卡片。页面使用 bands 和 feature surfaces；重复的问题/history item 可以是 card。
- 默认使用 1px border 和 8px radius。elevation 只用于 popover、mobile sheet 和桌面密集布局中的主 workspace。
- Primary button 使用现有蓝色；outline 用于次要操作；icon-only controls 使用 lucide 和 tooltip。
- Status 同时包含 icon、label、count、color；禁止只用颜色表示完成、警告或失败。
- JSON 使用固定深色 --lab-code，提供语义明确的 copy feedback，不作为普通用户的默认视图。
- 动画控制在 150-200ms，在 prefers-reduced-motion 下关闭或降低。

## Interaction details

### Composer

compose field 使用可见 label、简短辅助文本和 Start session primary command，不做成大型 marketing prompt。提交时按钮进入 pending，composer 使用 aria-busy；成功前 draft 保持可见。成功后保留已提交 brief 作为用户 artifact，只有用户明确开始新的 session 时才清空新 session draft。

### Clarification

问题按 API 的确定性顺序渲染。已完成问题显示答案摘要和完成 icon。第一个未回答问题是 active task；成功后 focus 到下一个未回答问题，只有服务端允许生成时才 focus 到 Generate solution。错误内容贴近对应 control 并保留文本。

### Solution

使用 Radix Tabs：

- Summary：generated_solution、标题、MVP 和 non-goals（如果 API 返回）。
- Structured：格式化 solution_json、copy action，不做 executable rendering。
- Evidence：selected case IDs、source/data policy、review notes 和 source/degraded notices。

字段不存在时显示明确的 unavailable text，不从 label 或无关数据推导。

### Graph

LabGraph 成为 feature component 或保留 focused local extraction，必须提供：

- 可见 title、node/edge count；
- 可聚焦 node controls 或等价的 text list；
- 使用 explainProjectLabNode 的 Explain node action；
- text relationships list；
- graph explanation failure 与 session workflow 隔离。

### Save

只有 contract 允许时才渲染 save command。确认文案使用 Session saved，并与 adopted、archived、quality-approved、published 严格区分。

## States

### Route loading

使用与最终布局对齐的 LabWorkspaceSkeleton：header bar、composer、rail、两个 question rows 和 context rectangle。mutation 期间不要把成功 session 切换成 whole-page spinner。

### Mutation feedback

Pending 文案对应实际操作：

- Starting session
- Saving answer
- Generating solution
- Saving session
- Loading node explanation

不使用模拟消息流或计时器式渐进结果。进度只说明已知事实。

### Empty and degraded data

继续使用 ProjectEmptyState、ProjectDegradedNotice 和 ProjectSourceLine。它们位于相关 workspace 上方，不隐藏到 generic tooltip。空数据不创建 substitute case chips。

### Error and unknown state

Route failure 使用 ProjectErrorState。mutation failure 保持局部。409 readiness failure 引导用户回到 clarification。unknown stage 禁用 active commands，提供 refresh/detail navigation 和诊断标签；按 fail-closed 处理。

## Responsive and accessibility requirements

- 验证 320、375、414、768、1024、1280、1440px。
- body 不得横向溢出；structured/code 内容只能在自身 bounded container 内滚动。
- 移动端 editable controls 的基础文字至少 16px，避免 browser zoom 问题，controls 至少 44x44px。
- 使用 semantic heading order、form labels、error association、aria-live=polite、正确 Tabs semantics、keyboard focus restoration 和高对比度。
- 提供 graph text alternative 和 keyboard node actions。
- 遵守 prefers-reduced-motion。
- 所有字符串使用现有 i18n resource pattern；不新增应用内长篇说明或 shortcut tutorial。

## Test plan

### Unit/component

- composer validation、trim、pending、error retention；
- API contract-driven generate state 和 unknown stage fail-closed；
- questions state、focus movement、mutation failure retention；
- solution Tabs、JSON copy feedback、unavailable field rendering；
- graph text alternative 和 node explanation success/failure；
- save terminology 和 local error state。

### Integration/e2e

- start -> answer all -> generate -> save against contract fixtures；
- 409 early generate 将用户引回 unanswered question；
- ready、empty、degraded 和 route-error data modes；
- keyboard-only primary path；
- screen-reader landmarks/announcements 和 axe；
- viewport screenshots 和 document.body.scrollWidth <= window.innerWidth。

## Rollout and rollback

只有 workflow contract change 上线且 frontend types/tests 已理解新字段后才部署。视觉组件可独立回滚，前提是 API 行为仍正确。不得通过关闭 source notice、开放未授权生成或填充 mock records 来制造可用假象。
