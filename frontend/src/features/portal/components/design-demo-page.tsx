"use client"

import { useMemo, useState, type ReactNode } from "react"
import {
  Bell,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  FileText,
  GitBranch,
  LayoutGrid,
  Menu,
  Network,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Users,
} from "lucide-react"
import { cn } from "@/lib/utils"

type SignalType = "全部" | "论文" | "项目" | "新闻"

const navItems = [
  { label: "今日情报", icon: LayoutGrid, active: true },
  { label: "论文研究", icon: BookOpen },
  { label: "项目雷达", icon: GitBranch },
  { label: "社区信号", icon: Users },
  { label: "主题追踪", icon: TrendingUp },
  { label: "研究报告", icon: FileText },
]

const signals = [
  {
    type: "论文" as const,
    label: "研究方法",
    title: "Agent 系统开始把试错过程当成一等研究对象",
    summary: "新的研究把重点从“生成一篇论文”转向记录实验、失败和后续行为之间的证据链。",
    meta: "3 小时前 · arXiv · 4 个引用",
    tone: "blue",
  },
  {
    type: "项目" as const,
    label: "项目雷达",
    title: "可审计的工作流编排工具正在加速更新",
    summary: "多个开源项目同时补齐运行记录、回放和人工复核能力，采用门槛明显下降。",
    meta: "5 小时前 · GitHub · 活跃度上升",
    tone: "green",
  },
  {
    type: "新闻" as const,
    label: "产品更新",
    title: "模型供应商把长上下文能力放进默认工作流",
    summary: "上下文窗口变大只是表面变化，真正值得关注的是检索、缓存与成本控制的组合方式。",
    meta: "昨天 · 官方博客 · 2 个关联主题",
    tone: "amber",
  },
]

const evidence = [
  { label: "一手来源", value: "12 条", note: "官方文档与论文原文" },
  { label: "可交叉验证", value: "8 条", note: "至少两个独立来源" },
  { label: "待复核", value: "3 条", note: "缺少直接证据" },
]

export function DesignDemoPage() {
  const [activeType, setActiveType] = useState<SignalType>("全部")
  const [selectedSignal, setSelectedSignal] = useState(0)
  const filteredSignals = useMemo(
    () => activeType === "全部" ? signals : signals.filter((signal) => signal.type === activeType),
    [activeType]
  )
  const currentSignal = filteredSignals[selectedSignal] ?? filteredSignals[0] ?? signals[0]

  return (
    <div className="min-h-screen bg-[#f5f6f3] text-[#18231f]">
      <header className="flex h-[72px] items-center border-b border-[#dce3dc] bg-[#fbfcfa] px-8">
        <div className="flex w-[252px] shrink-0 items-center gap-3 border-r border-[#e2e8e2] pr-8">
          <span className="flex size-10 items-center justify-center rounded-xl bg-[#17261f] text-sm font-bold text-white">A</span>
          <div>
            <p className="text-[15px] font-semibold tracking-[0.01em]">Agora Hub</p>
            <p className="mt-0.5 text-[11px] font-medium uppercase tracking-[0.16em] text-[#6b7a71]">Research Desk</p>
          </div>
        </div>
        <div className="flex min-w-0 flex-1 items-center gap-6 pl-8">
          <div className="flex items-center gap-2 text-sm font-medium text-[#22352b]"><span className="size-2 rounded-full bg-[#1f7a58]" />今日工作区</div>
          <div className="h-5 w-px bg-[#dce3dc]" />
          <label className="flex h-10 w-[min(30rem,42vw)] items-center gap-2 rounded-full border border-[#d7e0d8] bg-white px-3.5 text-sm text-[#7a887f] shadow-sm">
            <Search className="size-4 shrink-0" />
            <input aria-label="搜索论文、项目、主题或来源" className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-[#95a097]" placeholder="搜索论文、项目、主题或来源" />
            <span className="rounded-md border border-[#e1e7e1] px-1.5 py-0.5 text-[10px] text-[#87938b]">⌘ K</span>
          </label>
        </div>
        <div className="flex items-center gap-4 pl-6">
          <button type="button" className="relative flex size-9 items-center justify-center rounded-full text-[#607068] transition-colors hover:bg-[#edf2ed]" aria-label="通知">
            <Bell className="size-[18px]" />
            <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-[#db7a44]" />
          </button>
          <div className="flex items-center gap-2 border-l border-[#e2e8e2] pl-4">
            <span className="flex size-8 items-center justify-center rounded-full bg-[#dbe9df] text-xs font-semibold text-[#205a42]">林</span>
            <span className="text-sm font-medium text-[#33453b]">研究员</span>
          </div>
        </div>
      </header>

      <div className="flex min-h-[calc(100vh-72px)]">
        <aside className="flex w-[252px] shrink-0 flex-col border-r border-[#dce3dc] bg-[#f8faf7] px-5 py-7">
          <div className="flex items-center justify-between px-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#819087]">Workspace</p>
            <button type="button" className="flex size-7 items-center justify-center rounded-md text-[#7d8c82] hover:bg-[#eaf0ea]" aria-label="工作区设置"><Settings2 className="size-4" /></button>
          </div>
          <nav className="mt-4 space-y-1" aria-label="主导航">
            {navItems.map((item) => {
              const Icon = item.icon
              return <button key={item.label} type="button" className={cn("flex h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-sm transition-colors", item.active ? "bg-[#e3efe6] font-semibold text-[#1c694b]" : "text-[#637269] hover:bg-[#edf2ed] hover:text-[#263a30]")}><Icon className="size-[17px]" />{item.label}{item.active ? <span className="ml-auto size-1.5 rounded-full bg-[#1f7a58]" /> : null}</button>
            })}
          </nav>
          <div className="mt-9 border-t border-[#dfe7df] pt-6">
            <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#819087]">Saved views</p>
            <div className="mt-3 space-y-1">
              <button type="button" className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-[#637269] hover:bg-[#edf2ed]"><span className="size-2 rounded-full bg-[#5c8cc5]" />Agent infra</button>
              <button type="button" className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-[#637269] hover:bg-[#edf2ed]"><span className="size-2 rounded-full bg-[#bd7e4d]" />Evaluation</button>
            </div>
          </div>
          <div className="mt-auto rounded-xl border border-[#dfe7df] bg-white p-4">
            <div className="flex items-center gap-2 text-xs font-semibold text-[#3f5549]"><ShieldCheck className="size-4 text-[#1f7a58]" />数据状态</div>
            <p className="mt-2 text-xs leading-5 text-[#7b8981]">来源同步正常，最近更新于 8 分钟前。</p>
            <div className="mt-3 flex items-center gap-2 text-[11px] font-medium text-[#1f7a58]"><span className="size-1.5 rounded-full bg-[#1f7a58]" />全部来源可用</div>
          </div>
        </aside>

        <main className="min-w-0 flex-1 px-10 py-9">
          <div className="mx-auto max-w-[1260px]">
            <div className="flex items-end justify-between gap-6 border-b border-[#dce3dc] pb-7">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6f8176]">Wednesday · 09 September 2026</p>
                <h1 className="mt-3 text-[38px] font-semibold leading-tight tracking-[-0.02em] text-[#182a21]">今天值得看什么</h1>
                <p className="mt-3 max-w-[600px] text-[15px] leading-7 text-[#69796f]">把重要的研究进展、项目变化和社区信号，整理成一份可以快速判断的工作简报。</p>
              </div>
              <div className="grid grid-cols-3 gap-7 pb-1 text-right">
                <div><p className="text-[11px] uppercase tracking-[0.14em] text-[#849189]">今日信号</p><p className="mt-2 text-2xl font-semibold text-[#20352a]">24</p></div>
                <div><p className="text-[11px] uppercase tracking-[0.14em] text-[#849189]">新增来源</p><p className="mt-2 text-2xl font-semibold text-[#20352a]">08</p></div>
                <div><p className="text-[11px] uppercase tracking-[0.14em] text-[#849189]">待复核</p><p className="mt-2 text-2xl font-semibold text-[#b96b3d]">03</p></div>
              </div>
            </div>

            <section className="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1fr)_20rem]">
              <div>
                <div className="flex items-center justify-between gap-4">
                  <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#718177]">Signal stream</p><h2 className="mt-2 text-xl font-semibold text-[#20352a]">今日主线</h2></div>
                  <div className="flex items-center gap-1 rounded-full border border-[#dce3dc] bg-white p-1">
                    {(["全部", "论文", "项目", "新闻"] as SignalType[]).map((type) => <button key={type} type="button" onClick={() => { setActiveType(type); setSelectedSignal(0) }} className={cn("rounded-full px-3 py-1.5 text-xs font-medium transition-colors", activeType === type ? "bg-[#203b2e] text-white" : "text-[#6e7e74] hover:bg-[#edf2ed]")}>{type}</button>)}
                  </div>
                </div>
                <div className="mt-5 divide-y divide-[#e1e7e1] border-y border-[#dce3dc] bg-white">
                  {filteredSignals.map((signal, index) => <button key={signal.title} type="button" onClick={() => setSelectedSignal(index)} className={cn("grid w-full grid-cols-[5.5rem_minmax(0,1fr)_auto] gap-5 px-5 py-5 text-left transition-colors hover:bg-[#f8faf7]", currentSignal.title === signal.title && "bg-[#f5f9f5]")}>
                    <div><span className={cn("inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold", signal.tone === "blue" ? "bg-[#eaf1fa] text-[#4674a7]" : signal.tone === "green" ? "bg-[#e5f2e8] text-[#29704f]" : "bg-[#fbefe5] text-[#a6673d]")}>{signal.type}</span><p className="mt-3 text-xs text-[#8a978f]">{signal.label}</p></div>
                    <div className="min-w-0"><h3 className="text-[15px] font-semibold leading-6 text-[#20352a]">{signal.title}</h3><p className="mt-1.5 line-clamp-2 text-sm leading-6 text-[#718078]">{signal.summary}</p><p className="mt-3 text-xs text-[#95a097]">{signal.meta}</p></div>
                    <ChevronRight className={cn("mt-1 size-4 text-[#a1ada5] transition-transform", currentSignal.title === signal.title && "translate-x-0.5 text-[#2a7957]")} />
                  </button>)}
                </div>
              </div>
              <aside className="border-l border-[#dce3dc] pl-7">
                <div className="flex items-center justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#718177]">Selected signal</p><h2 className="mt-2 text-xl font-semibold text-[#20352a]">证据摘要</h2></div><CircleHelp className="size-4 text-[#91a098]" /></div>
                <div className="mt-5 border-y border-[#dce3dc] py-5"><span className="inline-flex rounded-full bg-[#eaf1fa] px-2.5 py-1 text-[11px] font-semibold text-[#4674a7]">{currentSignal.type}</span><h3 className="mt-4 text-base font-semibold leading-6 text-[#20352a]">{currentSignal.title}</h3><p className="mt-3 text-sm leading-6 text-[#718078]">{currentSignal.summary}</p></div>
                <div className="mt-5 space-y-4">{evidence.map((item) => <div key={item.label} className="flex items-start justify-between gap-4"><div><p className="text-xs font-medium text-[#7b8981]">{item.label}</p><p className="mt-1 text-xs text-[#a0aaa3]">{item.note}</p></div><p className="text-sm font-semibold text-[#2e5f49]">{item.value}</p></div>)}</div>
                <button type="button" className="mt-6 flex h-10 w-full items-center justify-center gap-2 rounded-full border border-[#bfd2c4] text-sm font-medium text-[#2b684d] transition-colors hover:bg-[#edf5ef]">查看完整证据链 <ChevronRight className="size-4" /></button>
              </aside>
            </section>

            <section className="mt-10 border-t border-[#dce3dc] pt-7">
              <div className="flex items-end justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#718177]">Your workspace</p><h2 className="mt-2 text-xl font-semibold text-[#20352a]">继续工作</h2></div><button type="button" className="inline-flex items-center gap-2 text-sm font-medium text-[#2b684d] hover:text-[#174d37]">查看全部 <ChevronRight className="size-4" /></button></div>
              <div className="mt-5 grid grid-cols-3 gap-4">
                <WorkspaceCard icon={<Sparkles className="size-4" />} label="研究简报" title="Agent 评测的证据边界" meta="上次编辑 · 18 分钟前" />
                <WorkspaceCard icon={<Network className="size-4" />} label="证据图谱" title="长上下文工作流" meta="12 个节点 · 3 个待复核" />
                <WorkspaceCard icon={<Check className="size-4" />} label="待处理" title="复核 3 个来源冲突" meta="质量队列 · 今天" />
              </div>
            </section>
          </div>
        </main>
      </div>
      <button type="button" className="fixed bottom-7 right-8 flex size-12 items-center justify-center rounded-full bg-[#203b2e] text-white shadow-[0_12px_26px_rgba(22,51,37,0.2)] transition-transform hover:-translate-y-0.5" aria-label="打开快捷操作"><Menu className="size-5" /></button>
    </div>
  )
}

function WorkspaceCard({ icon, label, title, meta }: { icon: ReactNode; label: string; title: string; meta: string }) {
  return <button type="button" className="group border border-[#dce3dc] bg-white p-5 text-left transition-colors hover:border-[#b9cdbd] hover:bg-[#fbfdfb]"><div className="flex items-center gap-2 text-[#2b7655]"><span className="flex size-7 items-center justify-center rounded-lg bg-[#e8f2ea]">{icon}</span><span className="text-xs font-semibold uppercase tracking-[0.12em]">{label}</span></div><h3 className="mt-5 text-sm font-semibold text-[#20352a]">{title}</h3><div className="mt-4 flex items-center justify-between gap-2"><span className="text-xs text-[#8a978f]">{meta}</span><ChevronRight className="size-4 text-[#a1ada5] transition-transform group-hover:translate-x-0.5" /></div></button>
}
