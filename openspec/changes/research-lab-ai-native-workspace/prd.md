# PRD: Agora Hub Research Lab Workspace

| 项目 | 内容 |
| --- | --- |
| 产品 | Agora Hub / NewsRoom Research Intelligence |
| 功能名称 | Research Lab Workspace |
| 主目标路由 | /projects/lab |
| 配套路由 | /projects/lab/[sessionId] |
| 变更类型 | Projects Lab 的工作区体验、可访问性和响应式改造 |
| 前置 OpenSpec | projects-lab-workflow-contract |
| 参考方式 | 参考 AI chatbot platform 的低噪声对话工作区和反馈语言；不复制其品牌、文案、资产或信息架构 |
| 版本 | v1.0 planning |

## 1. 产品摘要

Research Lab Workspace 是 Agora Hub 中将真实 Project Radar 案例转化为可审查模块方案的研究工作区。用户输入一个真实的产品或模块问题，系统基于已有的真实项目与案例生成确定性澄清问题、结构图谱和方案草稿；用户在一个稳定、可回溯、可阅读的工作区中完成澄清、生成、审阅和保存。

本次改造的核心不是把 Lab 包装成“会实时思考的通用聊天机器人”。它要让用户清楚区分三件事：

1. 自己提供了什么问题和约束。
2. 系统基于哪些真实 Project Radar 案例和确定性状态推进。
3. 当前可以进行什么动作，以及该动作尚未代表质量通过、采纳或发布。

## 2. 背景与问题

现有 /projects/lab 已能启动会话、回答问题、生成方案，并打开详情页，但交互以两个通用面板和原始 JSON 为主。用户无法在第一眼获得清晰的步骤、证据上下文、行动资格和结果层次；移动端与辅助技术也缺少可预测的工作流反馈。

审计还发现当前 current_stage 的实际后端字符串、前端类型和测试夹具不一致，且生成资格没有成为显式 API 契约。这个问题不能由视觉层掩盖。因此 workspace 实施依赖 projects-lab-workflow-contract，以服务端返回的 current_stage、next_action、can_generate_solution、unanswered_question_ids 为唯一 workflow 真相。

## 3. 目标、非目标与成功标准

### 3.1 目标

- 将 /projects/lab 建成可在连续研究任务中反复使用的 AI-native 工作区，而不是营销 landing page。
- 让用户在每一步知道当前阶段、下一步、数据来源、未完成事项与可恢复错误。
- 让方案输出从单一 JSON 改为“阅读摘要、结构化方案、证据与图谱”三个可切换的视图。
- 用真实、可验证的 pending 反馈替代虚构 token streaming、思考过程或伪进度。
- 复用现有 shadcn/Radix、Projects 状态组件、React Query、LabGraph 和 explain-node 能力。
- 在 320px 至 1440px 以上视口中保持内容可读、无页面级横向滚动，且核心任务可由键盘与屏幕阅读器完成。

### 3.2 非目标

- 不复制 NexusAI 或参考页的品牌名、紫色品牌色、文案、插画、定价区、集成墙或营销 hero。
- 不引入实时模型流式输出、隐藏的 chain-of-thought、AI 自主追问、自动路由、自动质量判定、自动 memory write、工具授权或代码发布。
- 不改变真实数据政策：没有真实 Project Radar artifact 时只展示空态或降级提示，绝不填充 mock 项目、案例、引用或指标。
- 不改写 Projects Lab 的领域逻辑、Project Radar bridge、state repository 或 /studio、paper reader、全站主题。
- 不把“保存会话”描述成方案已经通过 quality gate、被采纳或已发布。

### 3.3 成功标准

首版上线后以以下可观测结果验收：

| 指标 | 目标 | 采集方式 |
| --- | --- | --- |
| 可完成性 | 在真实数据可用条件下，用户可从启动到保存完成主路径，不需要离开 /projects/lab | 既有 recordProjectInteraction 事件序列 |
| 流程清晰度 | 每个 session 都有当前阶段、下一动作和数据来源可见文本 | 自动化 DOM 和可访问性断言 |
| 误触控制 | can_generate_solution=false 时前端不触发 generate 请求 | 前端与 API 集成测试 |
| 容错 | mutation 失败不丢失问题输入、回答输入或已成功 session | 组件测试 |
| 移动可用性 | 320、375、414px 下无页面级横向滚动，主动作触控区域不小于 44px | Playwright viewport 检查 |
| 可访问性 | 核心路径不出现 axe 的 critical/serious 违规；状态变化可由读屏获知 | axe 和 keyboard 测试 |

事件只记录用户已经执行的界面操作和现有匿名或会话标识，不采集隐藏推理内容，也不将交互事件直接升级为 memory 或 skill 变更。

## 4. 用户与任务

### 4.1 核心用户

| 用户 | 需要完成的工作 | 当前阻力 | 新工作区如何帮助 |
| --- | --- | --- | --- |
| 研究负责人 | 将案例研究沉淀为一个可讨论的模块方案 | 无法快速知道案例、问题和方案之间的关系 | 用 Brief、Evidence、Graph、Solution 分层展示 |
| 产品负责人 | 明确问题、约束、MVP 与非目标 | JSON 和阶段字符串难以扫描 | 用可读摘要、步骤、结构化 Tab 和 action bar 展示 |
| 工程负责人 | 审查方案中的组件、依赖与数据政策 | 难以判断输出是否真实、是否只是草案 | 固定展示真实数据来源、数据状态、非目标和保存语义 |
| 移动端或辅助技术用户 | 提交问题、回答澄清、读取方案、保存 | 多栏、图谱、状态变化可能不可用 | 单栏重排、文本图谱摘要、焦点管理和 live region |

### 4.2 Jobs to be done

- 当我准备评估一个研究模块时，我希望把问题和约束写成一次可保存的 Lab session，这样我能回到同一上下文继续审查。
- 当系统需要我澄清需求时，我希望明确看到未完成问题和下一步，这样不会在错误时机生成方案。
- 当方案生成后，我希望先读结论和真实案例依据，再按需查看结构化 JSON 和图谱，这样能更快判断是否值得采用。
- 当数据不完整或请求失败时，我希望知道限制、保留已输入内容并能重试，这样不会误把失败当成没有结果。

## 5. 信息架构与主路径

### 5.1 页面层级

/projects/lab 是持续工作的主面，不采用营销页的大型 hero。页面从上至下为：

1. LabPageHeader：面包屑/标题、简短真实数据说明、当前 session 的状态标签。
2. LabBriefComposer：问题输入、系统已选案例摘要、开始会话动作。
3. LabWorkspace：
   - 左侧或上方 LabProgressRail：阶段、待回答数量、下一动作、数据来源。
   - 中央 LabConversationPanel：用户 brief、澄清卡、提交反馈。
   - 右侧 LabContextPanel：案例与图谱；窄屏改为抽屉或下方区块。
4. LabSolutionPanel：生成后显示，含 Summary、Structured、Evidence 三个 Tab。
5. LabSessionActions：打开详情、保存、状态说明；只在 API 明确允许时展示可用动作。

/projects/lab/[sessionId] 是持久化审阅面：保留 header、状态、证据、图谱、问题和方案；首版不在详情页重复创建/回答交互，避免两个路由同时拥有同一 session 的 mutation 状态。

### 5.2 正常流程

1. 用户进入 /projects/lab，看到与最终布局相同尺寸的 skeleton 或现有真实数据/降级说明。
2. 用户输入问题。开始按钮只有在 trim 后文本非空且 mutation 未进行时可用。
3. session 成功创建后，界面以 API 返回的 clarifying_requirements、next_action 和问题列表呈现第一项待办；焦点移到阶段公告或首个问题。
4. 用户回答每个问题。提交成功后，只刷新 session 相关区域，保留问题输入失败时的内容并聚焦下一个未回答问题。
5. API 返回 can_generate_solution=true 后，生成按钮可用。点击时显示真实的 Generating solution pending 状态，不模拟逐字生成。
6. 方案成功后，默认打开 Summary；用户可切换到 Structured 或 Evidence，查看图谱和节点解释。
7. 用户打开详情或保存 session。保存后明确显示“已保存会话”，不显示“已发布”或“已验证通过”。

### 5.3 异常和回退流程

- 首次读取错误：使用现有 ProjectErrorState 与 Retry，避免无上下文的空白页。
- 创建、回答、生成、保存失败：错误紧邻触发控件，保留本地文本，且只禁用正在提交的控制区。
- API 返回 409：把服务端提供的 unanswered_question_ids 显示为待完成项，不重试生成。
- data_state 不为 ready 或 notices 非空：保留 ProjectDegradedNotice 与 ProjectSourceLine，不隐藏限制。
- 无真实数据：用 ProjectEmptyState 明确说明数据不可用；composer 可按现有后端能力展示，但不可假造候选案例。
- 未知 stage：显示保守的“状态需要刷新”提示，提供刷新/打开详情；不启用生成、保存或采纳动作。

## 6. 功能需求

### FR-01：稳定的 session brief

系统必须将用户问题、selected case count、数据状态和来源信息呈现在启动区域；它们来自 API 或真实 Projects 数据，不创建虚构案例。

验收：

- 输入框有可见 label，placeholder 只是补充提示。
- 未输入有效问题时无法提交。
- mutation pending 时只禁用 composer，不遮盖已经存在的 workspace。
- 失败时问题文本保持不变。
- 展示的案例数与最终传入 selected_case_ids 一致；若无选择案例，显示真实的空或降级原因。

### FR-02：服务端驱动的 workflow feedback

系统必须以 current_stage、next_action、can_generate_solution、unanswered_question_ids 驱动 UI。不得用 question 数量、文案或本地布尔变量决定生成资格。

验收：

- 当前阶段同时有颜色、图标和文本标签。
- can_generate_solution=false 时 Generate Solution 不可用，并解释缺少的输入或当前阶段。
- status 更新使用礼貌 aria-live，且不会在每次渲染重复朗读。
- API 返回未知状态时不赋予额外权限。

### FR-03：澄清对话与提交反馈

系统必须将每项澄清问题展示为有状态的对话或任务卡，而不是一串无上下文 inputs。

验收：

- 已回答项显示简短答案摘要和完成状态；未回答项在视觉和语义上可区分。
- 当前待回答项有稳定的输入区域，提交成功后将焦点移到下一项或生成动作。
- 答案 trim 后发送；失败时保留原文本。
- 不伪造 assistant typing、流式 token 或思考日志。

### FR-04：方案阅读、结构化数据与证据

生成成功后，系统必须把 API 返回的 generated_solution 和 solution_json 以可审阅结构呈现。

验收：

- Summary 默认展示用户可读的 markdown 或文本方案。
- Structured 展示语法可辨识、可局部横向滚动的 JSON，提供带 tooltip 的复制图标按钮与成功反馈。
- Evidence 显示 selected case ids、可用的 source line、data policy、MVP、non-goals 和 review notes；这些字段缺失时显示明确的不可用状态，不补数据。
- Tab 使用现有 Radix Tabs，支持键盘方向键、焦点环和已选择状态。
- 所有可读内容在移动端自然换行；仅 code 或 JSON 面板可以容器内横向滚动。

### FR-05：图谱和节点解释

系统必须保留 LabGraph 的图谱价值，并提供不依赖 SVG 的文本等价物。

验收：

- 图谱容器有标题和节点/关系数量摘要。
- 节点可通过键盘操作；触发解释后使用现有 explainProjectLabNode，显示节点标题、解释和关联节点。
- 图谱下方或可访问抽屉提供结构化文本清单。
- 图谱请求失败时不影响回答、生成、查看方案或保存。

### FR-06：会话详情与保存语义

详情页必须使用同一套 visual/state primitives，且保存语义不扩张为审批或发布。

验收：

- Save Session 仅在服务端指示可以保存时启用。
- 保存 pending/error 贴近按钮呈现，成功后读屏可获知状态变化。
- 详情页保留 requirement profile、图谱、问题和方案的可访问阅读顺序。
- 显示 saved/adopted/archived 时使用准确文本，绝不推断 quality pass 或 publication。

### FR-07：可恢复的 loading、empty、error

系统必须为初始加载、局部 mutation、空真实数据、降级数据和错误分别提供稳定状态。

验收：

- 初始 skeleton 与最终 composer/workspace/solution 版式对齐，防止 layout shift。
- 局部 mutation 使用按钮文本、spinner 和 aria-busy，不使用整页覆盖 spinner。
- 空态保持真实数据政策的说明，可返回 Projects 其他真实内容。
- 错误包含恢复动作；未提交文本和上一次成功 session 不丢失。

### FR-08：本地化和内容规则

本次触及的 Lab 文案必须通过现有 i18n 模式管理，至少覆盖当前支持语言；不能将翻译工程扩大到全站。

验收：

- 新增 UI 文案不直接散落为硬编码字符串。
- 中文和英文长文本在 320px 与桌面宽度均不溢出控制区。
- 错误文本优先使用可执行、无责备的语言，例如“仍需回答 2 个澄清问题”。

## 7. 视觉语言与 Design Tokens

### 7.1 参考页分析及适配原则

参考页的有效语言是“轻量、白底、明确层级的 AI 工作台”：浅灰背景承托白色表面；大标题与简短支持文本形成分层；输入、聊天气泡、代码面板、Tabs 和状态点让用户快速分辨交互对象和结果。卡片使用细边框、中等圆角、克制阴影；强调色只用于主动作、激活 Tab 和用户输入。代码块用深色表面承载高密度内容。

NewsRoom 的适配原则如下：

- 采用“研究工作区”而不是 reference 的 marketing hero：首屏直接进入问题和 session。
- 继承 Agora Hub 已有蓝色、石墨文字、暖白背景、8px 基础圆角与 dark mode；不导入紫色品牌。
- 将 reference 的 chat bubble 变成 User brief、Lab clarification、System status 卡片，不把确定性服务写成拟人化 AI。
- 将 reference 的 code tab 变成结构化方案 JSON；只在生成结束后呈现，且提供复制和辅助文本。
- 渐变只允许极弱的 header surface 或 focus/hover 分层，不用于主背景、文字或视觉噪声；不得使用独立光球、bokeh 或装饰性 hero SVG。

### 7.2 设计 token

实现时优先复用 frontend/src/styles/globals.css 的现有 tokens。确有语义差异时，仅在 Lab scope 增加以下 token，并为 dark mode 提供映射：

| Token | Light 建议值 | Dark 建议值 | 用途 |
| --- | --- | --- | --- |
| --lab-surface | #ffffff | #172033 | workspace 主表面，优先等价 --card |
| --lab-surface-muted | #eef0f2 | #202b42 | stage/assistant/次级表面 |
| --lab-border-subtle | #d8dee7 | #2b3750 | 卡片与分隔线 |
| --lab-accent | #1f5fbf | #60a5fa | 主动作、active tab、focus 语义 |
| --lab-success | #16803c | #22c55e | 已完成状态，始终同时附文本和图标 |
| --lab-warning | #b7791f | #f59e0b | 数据降级/待完成状态，始终同时附文本和图标 |
| --lab-code | #111827 | #0b1220 | JSON/code surface |
| --lab-shadow | 0 8px 24px rgba(32,33,36,.08) | 0 8px 24px rgba(0,0,0,.22) | 仅用于浮层和主工作区 |

| 类别 | 规则 |
| --- | --- |
| 字体 | 沿用 font-papers-research；页面标题 28-32px，区块标题 18-20px，正文 14-16px，辅助说明 12-14px。禁止基于 viewport 缩放字体，letter-spacing 为 0。 |
| 间距 | 基础 4px；内部 padding 16/20/24px；页面 gutter mobile 16px、tablet 24px、desktop 32px。 |
| 圆角 | 保持全局 8px；输入/按钮可用 8px；不引入 16px 以上的软糖式容器圆角。 |
| 边框与阴影 | 默认 1px --lab-border-subtle；常规卡片无或极弱 shadow；只有悬浮提示、抽屉、关键 workspace 有 --lab-shadow。 |
| 按钮 | 主按钮蓝色填充；次要操作 outline；工具性操作使用 lucide icon + tooltip；按钮/输入最小高度 44px。 |
| 动画 | hover/focus 仅 150-200ms opacity/border/transform；prefers-reduced-motion 时关闭非必要过渡。 |

### 7.3 表面、卡片、标签与反馈

- LabBriefComposer 与 LabWorkspace 是相邻工作区块，不嵌套装饰性 card。
- 对话卡按角色采用克制背景：用户 brief 使用淡蓝边线/表面，系统澄清使用 muted surface，错误用 destructive text + icon + 可恢复动作。
- 状态标签展示 stage 文案、图标和数量；不要只用圆点颜色。
- Tabs 保持扁平 segmented control，不额外套 card；active 使用 --lab-accent 与文字/底线双重信号。
- JSON 面板深色、等宽字体、最大高度固定、局部滚动；复制用 Copy/Check lucide icon 并有 tooltip。

## 8. 页面结构和组件清单

### 8.1 优先复用

| 现有组件/能力 | 用法 |
| --- | --- |
| Button、Input、Tabs、Tooltip、Sheet、Skeleton | 交互原语；不重造基础 UI |
| ProjectLoadingState、ProjectErrorState、ProjectEmptyState | 路由级状态和 Retry |
| ProjectDegradedNotice、ProjectSourceLine | 真实数据政策、来源和降级说明 |
| LabGraph | 图谱可视化；抽取后保留行为并补文本替代 |
| explainProjectLabNode | 节点解释请求，不创建假解释 |
| React Query mutations | start、answer、generate、save 的 pending/error/retry 生命周期 |
| ResearchHeader、AppShell | /projects 路由既有布局、移动导航与字体环境 |

### 8.2 计划新增或重组的 feature components

| 组件 | 职责 | 复用边界 |
| --- | --- | --- |
| ResearchLabWorkspace | 组装 session 状态、mutations、布局和焦点恢复 | 不承载领域 stage 推断 |
| LabBriefComposer | 创建 session 的问题输入、case/source 摘要 | 只调用 start mutation |
| LabWorkflowStatus | stage、next action、待回答数量、live announcement | 只消费 API contract |
| LabClarificationList | 问题顺序、回答输入、局部 pending/error | 不保存业务状态副本 |
| LabContextPanel | source line、selected cases、graph、文本摘要与节点解释 | graph failure 隔离 |
| LabSolutionPanel | Summary/Structured/Evidence Tabs、复制反馈 | 不生成或改写方案 |
| LabSessionActions | 打开详情、保存及准确状态文案 | 服务端未授权时禁用 |
| LabWorkspaceSkeleton | 与最终布局匹配的初始 loading | 仅展示期使用 |

建议先将 LabGraph 从 projects-product-page.tsx 抽至 Projects feature 的明确文件，保留 unit test 和 API 引用；没有可复用价值的页面级状态不要抽成全局组件。

## 9. 响应式行为

| 视口 | 布局 | 行为 |
| --- | --- | --- |
| >=1280px | 12 列工作区：progress/context 3-4 列，主对话 5-6 列，solution/context rail 3-4 列 | 图谱和证据可保持右侧；长 JSON 仅面板内滚动 |
| 1024-1279px | 两栏：主对话 7-8 列，context 4-5 列 | solution 置于对话下方；不压缩输入/按钮文字 |
| 768-1023px | 单主栏 + 可折叠 context section | 用 Sheet 或可展开区承载图谱/证据；保留键盘访问 |
| <768px | 单栏、16px gutter | Composer、回答和主动作全宽；Tabs 可横向滚动但各 Tab 保持最小可点击宽度；JSON 只局部滚动 |
| 320-374px | 单栏紧凑布局 | 不隐藏关键文本；标题可换行；图标按钮有 aria-label/tooltip；不产生 body 横向滚动 |

响应式验收需覆盖 320、375、414、768、1024、1280、1440px。表格/结构化内容应在窄屏转为 definition list 或卡片，不创建全页横向滚动。

## 10. 状态设计

| 状态 | 呈现 | 用户可做什么 | 不能做什么 |
| --- | --- | --- | --- |
| 初始 loading | 对齐 composer/workspace 的 skeleton，aria-busy=true | 等待或使用既有路由导航 | 不显示虚构 session |
| 无 active session | 可填写 brief，右侧说明真实来源和预期流程 | Start session | 生成、保存 |
| clarifying requirements | 进度标签、未答问题和局部输入 | 回答、查看 context | 生成方案 |
| ready to generate | 完成标签、生成主按钮 | Generate solution、查看 context | 把生成称为质量通过 |
| generating | 真实 button pending、区域 busy、保留已有信息 | 等待；可按实现支持取消前仅不重复提交 | 再次触发 generate |
| solution generated | 默认 Summary、Tabs、详情入口 | 阅读、复制、查看证据、保存 | 推断已采用/发布 |
| saved/adopted/archived | 状态标签、时间/结果提示 | 打开详情、返回 Lab | 伪造其他业务状态 |
| degraded/empty | ProjectDegradedNotice 或 ProjectEmptyState | Retry/返回项目页 | 填充假项目、案例或引用 |
| mutation error | 控件附近 error + Retry，保留文本 | 修正/重试 | 丢失已经输入内容 |
| unknown state | 保守状态说明、Refresh/详情入口 | 刷新、诊断 | 生成、保存、采纳 |

## 11. 无障碍与可用性

- 每个 textarea、input、Tabs、状态区域和图谱控制器都有可见 label 或可访问名称。
- 表单错误使用 aria-invalid 和 aria-describedby 关联；错误文案可被读屏读取。
- 状态变化、生成完成、保存成功使用单一的 aria-live=polite 公告区域，避免重复朗读所有历史消息。
- 完整支持 Tab、Shift+Tab、Enter、Space、方向键 Tabs 操作和清晰 focus ring；任何鼠标 hover 信息都有键盘/触控等价入口。
- 颜色、图标和文本三者组合表达完成、警告、错误与当前状态；对比度满足 WCAG AA。
- 所有核心按钮和 icon button 最小触控区域 44x44px；工具 icon 使用 lucide 且带 tooltip/aria-label。
- 图谱提供节点列表、关系列表、焦点节点和解释的文本等价物；屏幕阅读器用户可以跳过 SVG 并完成相同任务。
- 处理 prefers-reduced-motion，不把动画作为理解状态的唯一方式。
- 在 i18n 文案中为中文和英文设置可自然换行的 max-width/min-width，避免截断阶段、错误和长 case 名称。

## 12. 数据、隐私与业务边界

- UI 只显示 Projects API 已返回的真实 case/project/source 数据；没有时显示空/降级，而不是 mock。
- recordProjectInteraction 继续记录用户实际 lab_started、question_answered、solution_generated 等行为，作为将来受控分析的输入；它不直接写入 memory、skill package 或生产策略。
- 此功能不改变 Harness 的 PLAN -> EXECUTE -> VERIFY 责任边界。Lab 是 Projects 的确定性会话体验，不能成为自动决策、质量通过、工具授权或发布通道。
- 接口层继续经 ProjectApplicationService 调用领域服务，前端不访问 executor、store 或本地 artifact 文件。
- solution_json 可能含长文本或引用；渲染时必须作为数据处理，禁止注入原始 HTML。

## 13. 风险、依赖与不应修改的边界

### 13.1 风险和缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| workflow contract 尚未统一 | UI 错误启用生成或展示不一致阶段 | 以 projects-lab-workflow-contract 为实施硬依赖；未知值保守降级 |
| 真实 Project Radar 数据缺失 | 用户认为系统无结果或被假数据误导 | 复用 degraded/empty 状态，保留 source line，不用 mock |
| 图谱成为纯装饰 | 辅助技术用户和移动端无法使用 | 文本摘要、节点解释和 API 错误隔离 |
| mutation 造成输入丢失 | 研究问题需要重写 | 保持 controlled local draft，仅在成功后清空已提交字段 |
| UI 把确定性逻辑拟人化 | 形成对 AI 能力和审核责任的错误预期 | 真实进度文案，禁止 typing/chain-of-thought 伪造 |
| 全局 token 扩散 | 影响 reader/studio 视觉回归 | Lab scope class 或少量语义 token，完整 light/dark 映射 |

### 13.2 绝不修改的业务边界

- 不在前端决定 workflow routing、can_generate_solution、quality pass/fail、memory write、tool authorization 或 publication。
- 不替换 source collection -> evidence -> agent analysis -> report -> quality gate -> artifacts/storage 主路径。
- 不改变 Project Radar 的真实数据来源，不绕过 source policy，不摄入付费/不可访问内容。
- 不改变 /studio、paper reader、PDF/KaTeX、ReactFlow 或全站主题，除非有独立 OpenSpec。
- 不把新界面等同于通用 AI chatbot，也不引入与目标无关的 landing page、定价或品牌资产。

## 14. 发布、验收与回滚

### 14.1 发布顺序

1. 完成并严格验证 projects-lab-workflow-contract。
2. 实现 desktop workspace，再实现 tablet/mobile reflow。
3. 接入详情页与保存状态，完成 i18n、a11y、loading/error 覆盖。
4. 运行 targeted tests、frontend lint/typecheck/test、Playwright viewports、python -m scripts.dev compile 和 python -m scripts.dev smoke。
5. 在真实有数据、空数据、降级数据和 API 409 四种环境验收后发布。

### 14.2 回滚

- 视觉回归可仅回滚 Lab feature components，不更改已稳定的 workflow contract。
- 后端 contract 不能单独回滚到允许 premature generation 的行为；若发生兼容性问题，前后端同步回退。
- 任何回滚都不得以 fake data、隐藏错误或禁用质量边界来维持“看起来可用”。

## 15. 需求到任务追溯

| PRD 需求 | OpenSpec 任务 |
| --- | --- |
| FR-01、FR-02 | 1.1-1.4、2.1-2.4 |
| FR-03 | 3.1-3.4 |
| FR-04、FR-05 | 4.1-4.5 |
| FR-06 | 5.1-5.3 |
| FR-07、FR-08 | 6.1-6.4 |
| 响应式与无障碍 | 7.1-7.5 |
| 测试、发布、回滚 | 8.1-8.6 |

## 16. 参考与实施证据

- 视觉参考：[AI Chatbot Platform](https://uupm.cc/demo/ai-chatbot-platform)，仅抽取轻量工作区、对话层级、Tabs、代码面板、状态和移动重排原则。
- 现有主入口：frontend/src/app/projects/lab/page.tsx 与 frontend/src/features/projects/components/projects-product-page.tsx。
- 现有详情页：frontend/src/app/projects/lab/[sessionId]/page.tsx 与 frontend/src/features/projects/components/projects-detail-pages.tsx。
- 现有 API client：frontend/src/lib/projects/api.ts。
- 现有真实数据与非目标约束：backend/projects/lab.py。
- 现有基础 tokens：frontend/src/styles/globals.css。
