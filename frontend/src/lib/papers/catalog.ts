import type { Benchmark, BenchmarkRef, MethodRef, Paper, PaperMethod, PaperTask, TaskRef } from "@/lib/papers/types"

const taskRefs = {
  // agents
  agents: { id: "task-agents", slug: "agents", name: "Agents", nameZh: "智能体" },
  codingAgents: { id: "task-coding-agents", slug: "coding-agents", name: "Coding Agents", nameZh: "代码智能体" },
  computerUseAgents: { id: "task-computer-use-agents", slug: "computer-use-agents", name: "Computer Use Agents", nameZh: "计算机操作智能体" },
  multiAgentSystems: { id: "task-multi-agent-systems", slug: "multi-agent-systems", name: "Multi-Agent Systems", nameZh: "多智能体系统" },
  // language-models
  languageModeling: { id: "task-language-modeling", slug: "language-modeling", name: "Language Modeling", nameZh: "语言建模" },
  instructionFollowing: { id: "task-instruction-following", slug: "instruction-following", name: "Instruction Following", nameZh: "指令跟随" },
  longContext: { id: "task-long-context", slug: "long-context", name: "Long Context", nameZh: "长上下文" },
  textGeneration: { id: "task-text-generation", slug: "text-generation", name: "Text Generation", nameZh: "文本生成" },
  // reasoning
  reasoning: { id: "task-reasoning", slug: "reasoning", name: "Reasoning", nameZh: "推理" },
  mathematicalReasoning: { id: "task-mathematical-reasoning", slug: "mathematical-reasoning", name: "Mathematical Reasoning", nameZh: "数学推理" },
  codeReasoning: { id: "task-code-reasoning", slug: "code-reasoning", name: "Code Reasoning", nameZh: "代码推理" },
  // multimodal
  visualQuestionAnswering: { id: "task-visual-question-answering", slug: "visual-question-answering", name: "Visual QA", nameZh: "视觉问答" },
  documentUnderstanding: { id: "task-document-understanding", slug: "document-understanding", name: "Document Understanding", nameZh: "文档理解" },
  imageGeneration: { id: "task-image-generation", slug: "image-generation", name: "Image Generation", nameZh: "图像生成" },
  videoUnderstanding: { id: "task-video-understanding", slug: "video-understanding", name: "Video Understanding", nameZh: "视频理解" },
  // computer-vision
  objectDetection: { id: "task-object-detection", slug: "object-detection", name: "Object Detection", nameZh: "目标检测" },
  imageSegmentation: { id: "task-image-segmentation", slug: "image-segmentation", name: "Image Segmentation", nameZh: "图像分割" },
  // code-ai
  codeGeneration: { id: "task-code-generation", slug: "code-generation", name: "Code Generation", nameZh: "代码生成" },
  codeReview: { id: "task-code-review", slug: "code-review", name: "Code Review", nameZh: "代码审查" },
  // retrieval-knowledge
  rag: { id: "task-rag", slug: "retrieval-augmented-generation", name: "Retrieval-Augmented Generation", nameZh: "检索增强生成" },
  knowledgeGraphs: { id: "task-knowledge-graphs", slug: "knowledge-graphs", name: "Knowledge Graphs", nameZh: "知识图谱" },
  // systems-infra
  inferenceServing: { id: "task-inference-serving", slug: "inference-serving", name: "Inference Serving", nameZh: "推理服务" },
  modelQuantization: { id: "task-model-quantization", slug: "model-quantization", name: "Model Quantization", nameZh: "模型量化" },
  distributedTraining: { id: "task-distributed-training", slug: "distributed-training", name: "Distributed Training", nameZh: "分布式训练" },
  // data-evaluation
  benchmarking: { id: "task-benchmarking", slug: "benchmarking", name: "Benchmarking", nameZh: "基准评测" },
  datasetCreation: { id: "task-dataset-creation", slug: "dataset-creation", name: "Dataset Creation", nameZh: "数据集构建" },
  // security-safety
  safetyAlignment: { id: "task-safety-alignment", slug: "safety-alignment", name: "Safety & Alignment", nameZh: "安全与对齐" },
  adversarialRobustness: { id: "task-adversarial-robustness", slug: "adversarial-robustness", name: "Adversarial Robustness", nameZh: "对抗鲁棒性" },
  // speech-audio
  speechRecognition: { id: "task-speech-recognition", slug: "speech-recognition", name: "Speech Recognition", nameZh: "语音识别" },
  audioGeneration: { id: "task-audio-generation", slug: "audio-generation", name: "Audio Generation", nameZh: "音频生成" },
  // ai-for-science
  proteinStructure: { id: "task-protein-structure", slug: "protein-structure", name: "Protein Structure", nameZh: "蛋白质结构" },
  molecularGeneration: { id: "task-molecular-generation", slug: "molecular-generation", name: "Molecular Generation", nameZh: "分子生成" },
  // human-ai-interaction
  humanFeedback: { id: "task-human-feedback", slug: "human-feedback", name: "Human Feedback & RLHF", nameZh: "人类反馈与RLHF" },
  // robotics-embodied
  embodiedAI: { id: "task-embodied-ai", slug: "embodied-ai", name: "Embodied AI", nameZh: "具身智能" },
} satisfies Record<string, TaskRef>

const methodRefs = {
  llm: { id: "method-llm", slug: "large-language-model", name: "Large Language Model (LLM)", nameZh: "大语言模型" },
  react: { id: "method-react", slug: "react", name: "ReAct" },
  agent: { id: "method-agent", slug: "agent", name: "Agent", nameZh: "智能体" },
  toolUse: { id: "method-tool-use", slug: "tool-use", name: "Tool Use", nameZh: "工具使用" },
  chainOfThought: { id: "method-chain-of-thought", slug: "chain-of-thought", name: "Chain-of-Thought", nameZh: "思维链" },
  planning: { id: "method-planning", slug: "planning", name: "Planning", nameZh: "规划" },
  agentMemory: { id: "method-agent-memory", slug: "agent-memory", name: "Agent Memory", nameZh: "智能体记忆" },
  postTraining: { id: "method-post-training", slug: "post-training", name: "Post-training", nameZh: "后训练" }
} satisfies Record<string, MethodRef>

const benchmarkRefs = {
  sweBench: { id: "benchmark-swe-bench", slug: "swe-bench", name: "SWE-bench" },
  hotpotQa: { id: "benchmark-hotpotqa", slug: "hotpotqa", name: "HotpotQA" },
  gameOf24: { id: "benchmark-game-of-24", slug: "game-of-24", name: "Game of 24" },
  sam1b: { id: "benchmark-sa-1b", slug: "sa-1b", name: "SA-1B" },
  llavaBench: { id: "benchmark-llava-bench", slug: "llava-bench", name: "LLaVA-Bench" },
  longContext: { id: "benchmark-long-context", slug: "long-context", name: "Long-context throughput" }
} satisfies Record<string, BenchmarkRef>

export const paperTasks: PaperTask[] = [
  // ── Agents ──────────────────────────────────────────────────────────────────
  {
    ...taskRefs.agents,
    group: "agents",
    description: "Agent systems that reason, call tools, use memory, and complete multi-step tasks.",
    descriptionZh: "能够推理、调用工具、使用记忆并完成多步任务的智能体系统。",
    paperCount: 4,
    benchmarkCount: 3,
    methodCount: 6,
    trendSignal: "+1.4x",
    sisterTasks: [taskRefs.codingAgents, taskRefs.computerUseAgents, taskRefs.reasoning, taskRefs.languageModeling],
    commonMethods: [methodRefs.llm, methodRefs.react, methodRefs.agent, methodRefs.toolUse, methodRefs.planning, methodRefs.agentMemory]
  },
  {
    ...taskRefs.codingAgents,
    group: "code-ai",
    description: "Agents that plan, edit, and test changes inside software repositories.",
    descriptionZh: "能够在代码仓库中规划、编辑和测试变更的智能体。",
    paperCount: 1,
    benchmarkCount: 1,
    methodCount: 4,
    trendSignal: "+1.3x",
    sisterTasks: [taskRefs.agents, taskRefs.computerUseAgents, taskRefs.reasoning],
    commonMethods: [methodRefs.agent, methodRefs.toolUse, methodRefs.planning, methodRefs.react]
  },
  {
    ...taskRefs.reasoning,
    group: "reasoning",
    description: "Reasoning tasks for multi-step inference, search, planning, and self-correction.",
    descriptionZh: "面向多步推理、搜索、规划和自我修正的研究任务。",
    paperCount: 3,
    benchmarkCount: 2,
    methodCount: 4,
    trendSignal: "+1.2x",
    sisterTasks: [taskRefs.agents, taskRefs.languageModeling, taskRefs.codingAgents],
    commonMethods: [methodRefs.chainOfThought, methodRefs.planning, methodRefs.react, methodRefs.agentMemory]
  },
  {
    ...taskRefs.visualQuestionAnswering,
    group: "multimodal",
    description: "Answering and grounding questions in images, diagrams, documents, and visual scenes.",
    descriptionZh: "围绕图像、图表、文档和视觉场景进行问答与定位。",
    paperCount: 2,
    benchmarkCount: 2,
    methodCount: 3,
    trendSignal: "+18%",
    sisterTasks: [taskRefs.documentUnderstanding, taskRefs.languageModeling, taskRefs.agents],
    commonMethods: [methodRefs.llm, methodRefs.postTraining, methodRefs.toolUse]
  },
  {
    ...taskRefs.documentUnderstanding,
    group: "multimodal",
    description: "Understanding layouts, masks, visual regions, and long visual text.",
    descriptionZh: "理解版式、掩码、视觉区域和长视觉文本。",
    paperCount: 2,
    benchmarkCount: 1,
    methodCount: 3,
    trendSignal: "+15%",
    sisterTasks: [taskRefs.visualQuestionAnswering, taskRefs.agents],
    commonMethods: [methodRefs.llm, methodRefs.toolUse, methodRefs.postTraining]
  },
  {
    ...taskRefs.languageModeling,
    group: "language-models",
    description: "Modeling language distributions, instruction following, and generation behavior.",
    descriptionZh: "建模语言分布、指令跟随和生成行为。",
    paperCount: 4,
    benchmarkCount: 3,
    methodCount: 5,
    trendSignal: "+9%",
    sisterTasks: [taskRefs.reasoning, taskRefs.agents, taskRefs.visualQuestionAnswering],
    commonMethods: [methodRefs.llm, methodRefs.postTraining, methodRefs.chainOfThought]
  },
  {
    ...taskRefs.inferenceServing,
    group: "systems-infra",
    description: "Serving systems, kernels, routing, and optimization for deployed AI workloads.",
    descriptionZh: "面向已部署 AI 工作负载的服务系统、内核、路由与优化。",
    paperCount: 1,
    benchmarkCount: 1,
    methodCount: 1,
    trendSignal: "+12%",
    sisterTasks: [taskRefs.languageModeling],
    commonMethods: [methodRefs.llm]
  },
  {
    ...taskRefs.computerUseAgents,
    group: "agents",
    description: "Agents that operate browsers, desktops, terminals, and software interfaces.",
    descriptionZh: "能够操作浏览器、桌面、终端和软件界面的智能体。",
    paperCount: 1,
    benchmarkCount: 1,
    methodCount: 3,
    trendSignal: "+1.1x",
    sisterTasks: [taskRefs.agents, taskRefs.codingAgents, taskRefs.documentUnderstanding],
    commonMethods: [methodRefs.react, methodRefs.toolUse, methodRefs.planning]
  }
  {
    ...taskRefs.multiAgentSystems,
    group: "agents",
    description: "Coordination, communication, and collaboration between multiple autonomous agents.",
    descriptionZh: "多个自主智能体之间的协调、通信与协作。",
    paperCount: 0, benchmarkCount: 0, methodCount: 3, trendSignal: "+2.1x",
    sisterTasks: [taskRefs.agents, taskRefs.codingAgents],
    commonMethods: [methodRefs.agent, methodRefs.planning, methodRefs.toolUse]
  },
  // ── Language Models ──────────────────────────────────────────────────────────
  {
    ...taskRefs.instructionFollowing,
    group: "language-models",
    description: "Training and evaluating models to follow natural language instructions accurately.",
    descriptionZh: "训练和评估模型准确遵循自然语言指令的能力。",
    paperCount: 0, benchmarkCount: 0, methodCount: 3, trendSignal: "+11%",
    sisterTasks: [taskRefs.languageModeling, taskRefs.reasoning],
    commonMethods: [methodRefs.postTraining, methodRefs.llm, methodRefs.chainOfThought]
  },
  {
    ...taskRefs.longContext,
    group: "language-models",
    description: "Extending context windows and improving retrieval over long documents.",
    descriptionZh: "扩展上下文窗口并改善对长文档的检索能力。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+18%",
    sisterTasks: [taskRefs.languageModeling, taskRefs.rag],
    commonMethods: [methodRefs.llm, methodRefs.postTraining]
  },
  {
    ...taskRefs.textGeneration,
    group: "language-models",
    description: "Open-ended and constrained text generation, summarization, and translation.",
    descriptionZh: "开放式和受限文本生成、摘要与翻译。",
    paperCount: 0, benchmarkCount: 0, methodCount: 3, trendSignal: "+8%",
    sisterTasks: [taskRefs.languageModeling, taskRefs.instructionFollowing],
    commonMethods: [methodRefs.llm, methodRefs.postTraining, methodRefs.chainOfThought]
  },
  // ── Reasoning ────────────────────────────────────────────────────────────────
  {
    ...taskRefs.mathematicalReasoning,
    group: "reasoning",
    description: "Solving mathematical problems requiring symbolic manipulation and multi-step proof.",
    descriptionZh: "解决需要符号操作和多步证明的数学问题。",
    paperCount: 0, benchmarkCount: 0, methodCount: 3, trendSignal: "+1.5x",
    sisterTasks: [taskRefs.reasoning, taskRefs.codeReasoning],
    commonMethods: [methodRefs.chainOfThought, methodRefs.planning, methodRefs.llm]
  },
  {
    ...taskRefs.codeReasoning,
    group: "reasoning",
    description: "Understanding, tracing, and reasoning about program behavior and semantics.",
    descriptionZh: "理解、追踪和推理程序行为与语义。",
    paperCount: 0, benchmarkCount: 0, methodCount: 3, trendSignal: "+1.3x",
    sisterTasks: [taskRefs.reasoning, taskRefs.codingAgents],
    commonMethods: [methodRefs.chainOfThought, methodRefs.agent, methodRefs.toolUse]
  },
  // ── Multimodal ───────────────────────────────────────────────────────────────
  {
    ...taskRefs.imageGeneration,
    group: "multimodal",
    description: "Generating high-fidelity images from text prompts or reference images.",
    descriptionZh: "从文本提示或参考图像生成高保真图像。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+14%",
    sisterTasks: [taskRefs.visualQuestionAnswering, taskRefs.videoUnderstanding],
    commonMethods: [methodRefs.llm, methodRefs.postTraining]
  },
  {
    ...taskRefs.videoUnderstanding,
    group: "multimodal",
    description: "Temporal reasoning, action recognition, and captioning over video streams.",
    descriptionZh: "对视频流进行时序推理、动作识别和字幕生成。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+16%",
    sisterTasks: [taskRefs.visualQuestionAnswering, taskRefs.imageGeneration],
    commonMethods: [methodRefs.llm, methodRefs.postTraining]
  },
  // ── Computer Vision ──────────────────────────────────────────────────────────
  {
    ...taskRefs.objectDetection,
    group: "computer-vision",
    description: "Localizing and classifying objects in images and video frames.",
    descriptionZh: "在图像和视频帧中定位和分类目标。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+7%",
    sisterTasks: [taskRefs.imageSegmentation, taskRefs.visualQuestionAnswering],
    commonMethods: [methodRefs.llm, methodRefs.toolUse]
  },
  {
    ...taskRefs.imageSegmentation,
    group: "computer-vision",
    description: "Pixel-level understanding including semantic, instance, and panoptic segmentation.",
    descriptionZh: "像素级理解，包括语义分割、实例分割和全景分割。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+9%",
    sisterTasks: [taskRefs.objectDetection, taskRefs.documentUnderstanding],
    commonMethods: [methodRefs.toolUse, methodRefs.llm]
  },
  // ── Code AI ──────────────────────────────────────────────────────────────────
  {
    ...taskRefs.codeGeneration,
    group: "code-ai",
    description: "Generating correct, efficient code from natural language specifications.",
    descriptionZh: "从自然语言规范生成正确、高效的代码。",
    paperCount: 0, benchmarkCount: 0, methodCount: 3, trendSignal: "+1.4x",
    sisterTasks: [taskRefs.codingAgents, taskRefs.codeReasoning],
    commonMethods: [methodRefs.llm, methodRefs.postTraining, methodRefs.agent]
  },
  {
    ...taskRefs.codeReview,
    group: "code-ai",
    description: "Automated review, bug detection, and patch suggestion for code changes.",
    descriptionZh: "对代码变更进行自动审查、缺陷检测和补丁建议。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+12%",
    sisterTasks: [taskRefs.codingAgents, taskRefs.codeGeneration],
    commonMethods: [methodRefs.llm, methodRefs.agent]
  },
  // ── Retrieval & Knowledge ────────────────────────────────────────────────────
  {
    ...taskRefs.rag,
    group: "retrieval-knowledge",
    description: "Augmenting generation with retrieved documents, passages, or structured knowledge.",
    descriptionZh: "通过检索文档、段落或结构化知识来增强生成能力。",
    paperCount: 0, benchmarkCount: 0, methodCount: 3, trendSignal: "+1.6x",
    sisterTasks: [taskRefs.languageModeling, taskRefs.longContext, taskRefs.knowledgeGraphs],
    commonMethods: [methodRefs.llm, methodRefs.toolUse, methodRefs.agent]
  },
  {
    ...taskRefs.knowledgeGraphs,
    group: "retrieval-knowledge",
    description: "Building, querying, and reasoning over structured knowledge representations.",
    descriptionZh: "构建、查询和推理结构化知识表示。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+10%",
    sisterTasks: [taskRefs.rag, taskRefs.reasoning],
    commonMethods: [methodRefs.llm, methodRefs.toolUse]
  },
  // ── Systems & Infra ──────────────────────────────────────────────────────────
  {
    ...taskRefs.modelQuantization,
    group: "systems-infra",
    description: "Reducing model precision and size while preserving accuracy for efficient deployment.",
    descriptionZh: "在保持精度的同时降低模型精度和大小以实现高效部署。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+13%",
    sisterTasks: [taskRefs.inferenceServing, taskRefs.distributedTraining],
    commonMethods: [methodRefs.llm, methodRefs.postTraining]
  },
  {
    ...taskRefs.distributedTraining,
    group: "systems-infra",
    description: "Parallelism strategies, communication optimization, and fault tolerance for large-scale training.",
    descriptionZh: "大规模训练的并行策略、通信优化和容错机制。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+11%",
    sisterTasks: [taskRefs.inferenceServing, taskRefs.modelQuantization],
    commonMethods: [methodRefs.llm, methodRefs.postTraining]
  },
  // ── Data & Evaluation ────────────────────────────────────────────────────────
  {
    ...taskRefs.benchmarking,
    group: "data-evaluation",
    description: "Designing and running evaluations to measure model capabilities and limitations.",
    descriptionZh: "设计和运行评估以衡量模型能力和局限性。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+15%",
    sisterTasks: [taskRefs.safetyAlignment, taskRefs.datasetCreation],
    commonMethods: [methodRefs.llm, methodRefs.chainOfThought]
  },
  {
    ...taskRefs.datasetCreation,
    group: "data-evaluation",
    description: "Collecting, annotating, and curating datasets for training and evaluation.",
    descriptionZh: "收集、标注和整理用于训练和评估的数据集。",
    paperCount: 0, benchmarkCount: 0, methodCount: 1, trendSignal: "+8%",
    sisterTasks: [taskRefs.benchmarking],
    commonMethods: [methodRefs.llm]
  },
  // ── Security & Safety ────────────────────────────────────────────────────────
  {
    ...taskRefs.safetyAlignment,
    group: "security-safety",
    description: "Aligning model behavior with human values, reducing harmful outputs and jailbreaks.",
    descriptionZh: "使模型行为与人类价值观对齐，减少有害输出和越狱行为。",
    paperCount: 0, benchmarkCount: 0, methodCount: 3, trendSignal: "+1.8x",
    sisterTasks: [taskRefs.humanFeedback, taskRefs.benchmarking],
    commonMethods: [methodRefs.postTraining, methodRefs.llm, methodRefs.agent]
  },
  {
    ...taskRefs.adversarialRobustness,
    group: "security-safety",
    description: "Defending models against adversarial inputs, prompt injection, and distribution shift.",
    descriptionZh: "防御模型对抗对抗性输入、提示注入和分布偏移。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+9%",
    sisterTasks: [taskRefs.safetyAlignment, taskRefs.benchmarking],
    commonMethods: [methodRefs.llm, methodRefs.postTraining]
  },
  // ── Speech & Audio ───────────────────────────────────────────────────────────
  {
    ...taskRefs.speechRecognition,
    group: "speech-audio",
    description: "Transcribing and understanding spoken language across languages and domains.",
    descriptionZh: "跨语言和领域转录和理解口语。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+7%",
    sisterTasks: [taskRefs.audioGeneration, taskRefs.languageModeling],
    commonMethods: [methodRefs.llm, methodRefs.postTraining]
  },
  {
    ...taskRefs.audioGeneration,
    group: "speech-audio",
    description: "Generating speech, music, and environmental audio from text or reference signals.",
    descriptionZh: "从文本或参考信号生成语音、音乐和环境音频。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+12%",
    sisterTasks: [taskRefs.speechRecognition, taskRefs.imageGeneration],
    commonMethods: [methodRefs.llm, methodRefs.postTraining]
  },
  // ── AI for Science ───────────────────────────────────────────────────────────
  {
    ...taskRefs.proteinStructure,
    group: "ai-for-science",
    description: "Predicting and designing protein 3D structures and functions.",
    descriptionZh: "预测和设计蛋白质三维结构与功能。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+14%",
    sisterTasks: [taskRefs.molecularGeneration],
    commonMethods: [methodRefs.llm, methodRefs.postTraining]
  },
  {
    ...taskRefs.molecularGeneration,
    group: "ai-for-science",
    description: "Generating novel molecules and materials with desired properties.",
    descriptionZh: "生成具有所需属性的新型分子和材料。",
    paperCount: 0, benchmarkCount: 0, methodCount: 2, trendSignal: "+11%",
    sisterTasks: [taskRefs.proteinStructure],
    commonMethods: [methodRefs.llm, methodRefs.postTraining]
  },
  // ── Human-AI Interaction ─────────────────────────────────────────────────────
  {
    ...taskRefs.humanFeedback,
    group: "human-ai-interaction",
    description: "Learning from human preferences, RLHF, and interactive feedback loops.",
    descriptionZh: "从人类偏好、RLHF和交互式反馈循环中学习。",
    paperCount: 0, benchmarkCount: 0, methodCount: 3, trendSignal: "+1.2x",
    sisterTasks: [taskRefs.safetyAlignment, taskRefs.instructionFollowing],
    commonMethods: [methodRefs.postTraining, methodRefs.llm, methodRefs.agent]
  },
  // ── Robotics & Embodied ──────────────────────────────────────────────────────
  {
    ...taskRefs.embodiedAI,
    group: "robotics-embodied",
    description: "Agents that perceive, plan, and act in physical or simulated 3D environments.",
    descriptionZh: "在物理或模拟三维环境中感知、规划和行动的智能体。",
    paperCount: 0, benchmarkCount: 0, methodCount: 3, trendSignal: "+1.7x",
    sisterTasks: [taskRefs.agents, taskRefs.computerUseAgents],
    commonMethods: [methodRefs.agent, methodRefs.planning, methodRefs.llm]
  },
]

export const paperMethods: PaperMethod[] = [
  {
    ...methodRefs.react,
    description: "Reasoning plus acting loops for agents that inspect state, choose actions, and learn from feedback.",
    descriptionZh: "面向智能体的推理加行动循环，用于观察状态、选择动作并从反馈中学习。",
    paperCount: 1,
    taskCount: 3,
    implementationCount: 1,
    area: "Prompt Engineering",
    relatedTasks: [taskRefs.agents, taskRefs.codingAgents, taskRefs.computerUseAgents, taskRefs.reasoning, taskRefs.languageModeling],
    relatedMethods: [methodRefs.toolUse, methodRefs.chainOfThought, methodRefs.planning, methodRefs.agentMemory, methodRefs.agent],
    commonBenchmarks: [benchmarkRefs.hotpotQa, benchmarkRefs.gameOf24, benchmarkRefs.sweBench]
  },
  {
    ...methodRefs.toolUse,
    description: "Calling external tools, APIs, kernels, or environments while keeping evidence visible.",
    descriptionZh: "在保留证据链的前提下调用外部工具、API、内核或环境。",
    paperCount: 3,
    taskCount: 5,
    implementationCount: 3,
    area: "Prompt Engineering",
    relatedTasks: [taskRefs.agents, taskRefs.codingAgents, taskRefs.visualQuestionAnswering],
    relatedMethods: [methodRefs.react, methodRefs.planning, methodRefs.agentMemory, methodRefs.llm],
    commonBenchmarks: [benchmarkRefs.sweBench, benchmarkRefs.hotpotQa]
  },
  {
    ...methodRefs.chainOfThought,
    description: "Intermediate reasoning traces used for deliberate search and multi-step problem solving.",
    descriptionZh: "用于深思熟虑搜索与多步问题求解的中间推理轨迹。",
    paperCount: 1,
    taskCount: 3,
    implementationCount: 1,
    area: "Prompt Engineering",
    relatedTasks: [taskRefs.reasoning, taskRefs.languageModeling, taskRefs.agents],
    relatedMethods: [methodRefs.planning, methodRefs.react, methodRefs.llm],
    commonBenchmarks: [benchmarkRefs.gameOf24, benchmarkRefs.hotpotQa]
  },
  {
    ...methodRefs.planning,
    description: "Task decomposition and action sequencing for long-horizon systems.",
    descriptionZh: "面向长程系统的任务分解与行动序列规划。",
    paperCount: 3,
    taskCount: 4,
    implementationCount: 3,
    area: "Prompt Engineering",
    relatedTasks: [taskRefs.agents, taskRefs.codingAgents, taskRefs.reasoning],
    relatedMethods: [methodRefs.react, methodRefs.toolUse, methodRefs.chainOfThought, methodRefs.agentMemory],
    commonBenchmarks: [benchmarkRefs.gameOf24, benchmarkRefs.sweBench]
  },
  {
    ...methodRefs.agentMemory,
    description: "Memory structures and feedback traces that help agents improve across attempts.",
    descriptionZh: "帮助智能体在多次尝试中改进的记忆结构与反馈轨迹。",
    paperCount: 1,
    taskCount: 2,
    implementationCount: 1,
    area: "Prompt Engineering",
    relatedTasks: [taskRefs.agents, taskRefs.reasoning],
    relatedMethods: [methodRefs.react, methodRefs.planning, methodRefs.toolUse],
    commonBenchmarks: [benchmarkRefs.hotpotQa]
  },
  {
    ...methodRefs.postTraining,
    description: "Instruction tuning and alignment recipes for stronger multimodal and language behavior.",
    descriptionZh: "用于增强多模态与语言行为的指令微调和对齐方法。",
    paperCount: 1,
    taskCount: 3,
    implementationCount: 1,
    area: "Language Models",
    relatedTasks: [taskRefs.visualQuestionAnswering, taskRefs.languageModeling, taskRefs.documentUnderstanding],
    relatedMethods: [methodRefs.llm, methodRefs.toolUse],
    commonBenchmarks: [benchmarkRefs.llavaBench]
  },
  {
    ...methodRefs.llm,
    description: "Large language model backbones and serving optimizations used across research workflows.",
    descriptionZh: "贯穿研究工作流的大语言模型底座与服务优化。",
    paperCount: 3,
    taskCount: 5,
    implementationCount: 3,
    area: "Language Models",
    relatedTasks: [taskRefs.languageModeling, taskRefs.reasoning, taskRefs.inferenceServing],
    relatedMethods: [methodRefs.postTraining, methodRefs.chainOfThought, methodRefs.planning],
    commonBenchmarks: [benchmarkRefs.longContext, benchmarkRefs.llavaBench]
  }
]

export const benchmarks: Benchmark[] = [
  { ...benchmarkRefs.sweBench, category: "software-engineering", taskSlug: "coding-agents", methodSlug: "tool-use", entryCount: 417, metric: "resolved", bestValue: "verified" },
  { ...benchmarkRefs.hotpotQa, category: "question-answering", taskSlug: "agents", methodSlug: "react", entryCount: 84, metric: "EM/F1", bestValue: "reported" },
  { ...benchmarkRefs.gameOf24, category: "reasoning-logic", taskSlug: "reasoning", methodSlug: "chain-of-thought", entryCount: 32, metric: "success", bestValue: "reported" },
  { ...benchmarkRefs.sam1b, category: "segmentation", taskSlug: "document-understanding", methodSlug: "tool-use", entryCount: 12, metric: "mIoU", bestValue: "reported" },
  { ...benchmarkRefs.llavaBench, category: "visual-question-answering", taskSlug: "visual-question-answering", methodSlug: "post-training", entryCount: 28, metric: "score", bestValue: "reported" },
  { ...benchmarkRefs.longContext, category: "long-context", taskSlug: "inference-serving", methodSlug: "large-language-model", entryCount: 16, metric: "throughput", bestValue: "reported" }
]

export const papers: Paper[] = [
  {
    id: "paper-swe-agent",
    slug: "swe-agent-agent-computer-interfaces",
    title: "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering",
    titleZh: "SWE-agent：智能体-计算机界面使自动化软件工程成为可能",
    abstractSnippet:
      "Language model (LM) agents are increasingly being used to automate complicated tasks in digital environments. Just as humans benefit from powerful software applications, such as integrated development environments, for complex tasks like software engineering, we posit that LM agents represent a new category of end users with their own needs and abilities, and would benefit from specially-built interfaces to the software they use. We investigate how interface design affects the performance of language model agents. As a result of this exploration, we introduce SWE-agent: a system that facilitates LM agents to autonomously use computers to solve software engineering tasks. SWE-agent's custom agent-computer interface (ACI) significantly enhances an agent's ability to create and edit code files, navigate entire repositories, and execute tests and other programs. We evaluate SWE-agent on SWE-bench and HumanEvalFix, achieving state-of-the-art performance on both with a pass@1 rate of 12.5% and 87.7%, respectively, far exceeding the previous state-of-the-art achieved with non-interactive LMs. Finally, we provide insight on how the design of the ACI can impact agents' behavior and performance.",
    authors: ["John Yang", "Carlos E. Jimenez", "Alexander Wettig", "Kilian Lieret", "Shunyu Yao", "Karthik Narasimhan"],
    publishedAt: "2024-05-06",
    venue: "arXiv",
    citationDoi: "10.48550/arxiv.2405.15793",
    tags: ["software engineering", "agents", "SWE-bench"],
    taskRefs: [taskRefs.codingAgents, taskRefs.agents, taskRefs.computerUseAgents],
    methodRefs: [methodRefs.agent, methodRefs.toolUse, methodRefs.planning],
    arxivUrl: "https://arxiv.org/abs/2405.15793",
    pdfUrl: "https://arxiv.org/pdf/2405.15793.pdf",
    repoUrl: "https://github.com/SWE-agent/SWE-agent",
    isPublished: true
  },
  {
    id: "paper-segment-anything",
    slug: "segment-anything",
    title: "Segment Anything",
    titleZh: "Segment Anything",
    abstractSnippet:
      "We introduce the Segment Anything (SA) project: a new task, model, and dataset for image segmentation. Using our efficient model in a data collection loop, we built the largest segmentation dataset to date (by far), with over 1 billion masks on 11M licensed and privacy respecting images. The model is designed and trained to be promptable, so it can transfer zero-shot to new image distributions and tasks. We evaluate its capabilities on numerous tasks and find that its zero-shot performance is impressive -- often competitive with or even superior to prior fully supervised results. We are releasing the Segment Anything Model (SAM) and corresponding dataset (SA-1B) of 1B masks and 11M images at https://segment-anything.com to foster research into foundation models for computer vision.",
    authors: ["Alexander Kirillov", "Eric Mintun", "Nikhila Ravi", "Hanzi Mao", "Chloe Rolland", "Laura Gustafson"],
    publishedAt: "2023-10-01",
    venue: "ICCV",
    citationDoi: "10.1109/iccv51070.2023.00371",
    tags: ["segmentation", "foundation model", "prompting"],
    taskRefs: [taskRefs.visualQuestionAnswering, taskRefs.documentUnderstanding],
    methodRefs: [methodRefs.toolUse, methodRefs.llm],
    paperUrl: "https://openaccess.thecvf.com/content/ICCV2023/html/Kirillov_Segment_Anything_ICCV_2023_paper.html",
    arxivUrl: "https://arxiv.org/abs/2304.02643",
    pdfUrl: "https://arxiv.org/pdf/2304.02643.pdf",
    repoUrl: "https://github.com/facebookresearch/segment-anything",
    isPublished: true
  },
  {
    id: "paper-llava-baselines",
    slug: "improved-baselines-with-visual-instruction-tuning",
    title: "Improved Baselines with Visual Instruction Tuning",
    titleZh: "通过视觉指令微调改进基线",
    abstractSnippet:
      "Large multimodal models (LMM) have recently shown encouraging progress with visual instruction tuning. In this note, we show that the fully-connected vision-language cross-modal connector in LLaVA is surprisingly powerful and data-efficient. With simple modifications to LLaVA, namely, using CLIP-ViT-L-336px with an MLP projection and adding academic-task-oriented VQA data with simple response formatting prompts, we establish stronger baselines that achieve state-of-the-art across 11 benchmarks. Our final 13B checkpoint uses merely 1.2M publicly available data, and finishes full training in ~1 day on a single 8-A100 node. We hope this can make state-of-the-art LMM research more accessible. Code and model will be publicly available.",
    authors: ["Haotian Liu", "Chunyuan Li", "Yuheng Li", "Yong Jae Lee"],
    publishedAt: "2023-10-05",
    venue: "CVPR",
    citationDoi: "10.1109/cvpr52733.2024.02484",
    tags: ["multimodal", "visual instruction tuning", "LLaVA"],
    taskRefs: [taskRefs.visualQuestionAnswering, taskRefs.languageModeling, taskRefs.documentUnderstanding],
    methodRefs: [methodRefs.llm, methodRefs.postTraining, methodRefs.toolUse],
    paperUrl: "https://openaccess.thecvf.com/content/CVPR2024/html/Liu_Improved_Baselines_with_Visual_Instruction_Tuning_CVPR_2024_paper.html",
    arxivUrl: "https://arxiv.org/abs/2310.03744",
    pdfUrl: "https://arxiv.org/pdf/2310.03744.pdf",
    repoUrl: "https://github.com/haotian-liu/LLaVA",
    isPublished: true
  },
  {
    id: "paper-tree-of-thoughts",
    slug: "tree-of-thoughts",
    title: "Tree of Thoughts: Deliberate Problem Solving with Large Language Models",
    titleZh: "Tree of Thoughts：使用大语言模型进行审慎问题求解",
    abstractSnippet:
      "Language models are increasingly being deployed for general problem solving across a wide range of tasks, but are still confined to token-level, left-to-right decision-making processes during inference. This means they can fall short in tasks that require exploration, strategic lookahead, or where initial decisions play a pivotal role. To surmount these challenges, we introduce a new framework for language model inference, Tree of Thoughts (ToT), which generalizes over the popular Chain of Thought approach to prompting language models, and enables exploration over coherent units of text (thoughts) that serve as intermediate steps toward problem solving. ToT allows LMs to perform deliberate decision making by considering multiple different reasoning paths and self-evaluating choices to decide the next course of action, as well as looking ahead or backtracking when necessary to make global choices. Our experiments show that ToT significantly enhances language models' problem-solving abilities on three novel tasks requiring non-trivial planning or search: Game of 24, Creative Writing, and Mini Crosswords. For instance, in Game of 24, while GPT-4 with chain-of-thought prompting only solved 4% of tasks, our method achieved a success rate of 74%. Code repo with all prompts: https://github.com/princeton-nlp/tree-of-thought-llm.",
    authors: ["Shunyu Yao", "Dian Yu", "Jeffrey Zhao", "Izhak Shafran", "Thomas L. Griffiths", "Yuan Cao"],
    publishedAt: "2023-05-17",
    venue: "arXiv",
    citationDoi: "10.48550/arxiv.2305.10601",
    tags: ["reasoning", "planning", "search"],
    taskRefs: [taskRefs.reasoning, taskRefs.agents, taskRefs.languageModeling],
    methodRefs: [methodRefs.chainOfThought, methodRefs.planning, methodRefs.llm],
    arxivUrl: "https://arxiv.org/abs/2305.10601",
    pdfUrl: "https://arxiv.org/pdf/2305.10601.pdf",
    repoUrl: "https://github.com/princeton-nlp/tree-of-thought-llm",
    isPublished: true
  },
  {
    id: "paper-reflexion",
    slug: "reflexion-language-agents",
    title: "Reflexion: Language Agents with Verbal Reinforcement Learning",
    titleZh: "Reflexion：具备语言强化学习的语言智能体",
    abstractSnippet:
      "Large language models (LLMs) have been increasingly used to interact with external environments (e.g., games, compilers, APIs) as goal-driven agents. However, it remains challenging for these language agents to quickly and efficiently learn from trial-and-error as traditional reinforcement learning methods require extensive training samples and expensive model fine-tuning. We propose Reflexion, a novel framework to reinforce language agents not by updating weights, but instead through linguistic feedback. Concretely, Reflexion agents verbally reflect on task feedback signals, then maintain their own reflective text in an episodic memory buffer to induce better decision-making in subsequent trials. Reflexion is flexible enough to incorporate various types (scalar values or free-form language) and sources (external or internally simulated) of feedback signals, and obtains significant improvements over a baseline agent across diverse tasks (sequential decision-making, coding, language reasoning). For example, Reflexion achieves a 91% pass@1 accuracy on the HumanEval coding benchmark, surpassing the previous state-of-the-art GPT-4 that achieves 80%. We also conduct ablation and analysis studies using different feedback signals, feedback incorporation methods, and agent types, and provide insights into how they affect performance.",
    authors: ["Noah Shinn", "Federico Cassano", "Edward Berman", "Ashwin Gopinath", "Karthik Narasimhan", "Shunyu Yao"],
    publishedAt: "2023-03-20",
    venue: "arXiv",
    citationDoi: "10.48550/arxiv.2303.11366",
    tags: ["agents", "verbal reinforcement", "memory"],
    taskRefs: [taskRefs.agents, taskRefs.reasoning, taskRefs.languageModeling],
    methodRefs: [methodRefs.react, methodRefs.agentMemory, methodRefs.agent],
    arxivUrl: "https://arxiv.org/abs/2303.11366",
    pdfUrl: "https://arxiv.org/pdf/2303.11366.pdf",
    repoUrl: "https://github.com/noahshinn/reflexion",
    isPublished: true
  },
  {
    id: "paper-flashattention-2",
    slug: "flashattention-2",
    title: "FlashAttention-2: Faster Attention with Better Parallelism and Work Partitioning",
    titleZh: "FlashAttention-2：通过更好的并行性与工作划分实现更快注意力",
    abstractSnippet:
      "Scaling Transformers to longer sequence lengths has been a major problem in the last several years, promising to improve performance in language modeling and high-resolution image understanding, as well as to unlock new applications in code, audio, and video generation. The attention layer is the main bottleneck in scaling to longer sequences, as its runtime and memory increase quadratically in the sequence length. FlashAttention exploits the asymmetric GPU memory hierarchy to bring significant memory saving (linear instead of quadratic) and runtime speedup (2-4x compared to optimized baselines), with no approximation. However, FlashAttention is still not nearly as fast as optimized matrix-multiply (GEMM) operations, reaching only 25-40% of the theoretical maximum FLOPs/s. We observe that the inefficiency is due to suboptimal work partitioning between different thread blocks and warps on the GPU, causing either low-occupancy or unnecessary shared memory reads/writes. We propose FlashAttention-2, with better work partitioning to address these issues. In particular, we (1) tweak the algorithm to reduce the number of non-matmul FLOPs (2) parallelize the attention computation, even for a single head, across different thread blocks to increase occupancy, and (3) within each thread block, distribute the work between warps to reduce communication through shared memory. These yield around 2x speedup compared to FlashAttention, reaching 50-73% of the theoretical maximum FLOPs/s on A100 and getting close to the efficiency of GEMM operations. We empirically validate that when used end-to-end to train GPT-style models, FlashAttention-2 reaches training speed of up to 225 TFLOPs/s per A100 GPU (72% model FLOPs utilization).",
    authors: ["Tri Dao"],
    publishedAt: "2023-07-17",
    venue: "arXiv",
    citationDoi: "10.48550/arxiv.2307.08691",
    tags: ["attention", "AI infrastructure", "long context"],
    taskRefs: [taskRefs.inferenceServing, taskRefs.languageModeling],
    methodRefs: [methodRefs.llm],
    arxivUrl: "https://arxiv.org/abs/2307.08691",
    pdfUrl: "https://arxiv.org/pdf/2307.08691.pdf",
    repoUrl: "https://github.com/Dao-AILab/flash-attention",
    isPublished: true
  }
]

export const topDomains = [taskRefs.agents, taskRefs.languageModeling, taskRefs.visualQuestionAnswering, taskRefs.reasoning]
export const trendingDomains = [taskRefs.codingAgents, taskRefs.computerUseAgents, taskRefs.documentUnderstanding, taskRefs.inferenceServing]

export function getTaskBySlug(slug: string) {
  return paperTasks.find((task) => task.slug === slug)
}

export function getMethodBySlug(slug: string) {
  return paperMethods.find((method) => method.slug === slug)
}

export function getPapersForTask(slug: string) {
  return papers.filter((paper) => paper.taskRefs.some((task) => task.slug === slug))
}

export function getPapersForMethod(slug: string) {
  return papers.filter((paper) => paper.methodRefs.some((method) => method.slug === slug))
}

export function getBenchmarksForTask(slug: string) {
  return benchmarks.filter((benchmark) => benchmark.taskSlug === slug)
}

export function getBenchmarksForMethod(slug: string) {
  return benchmarks.filter((benchmark) => benchmark.methodSlug === slug)
}

export function getTaskRef(slug: string) {
  return Object.values(taskRefs).find((task) => task.slug === slug)
}

export function getMethodRef(slug: string) {
  return Object.values(methodRefs).find((method) => method.slug === slug)
}
