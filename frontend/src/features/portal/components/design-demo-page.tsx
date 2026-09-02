"use client"

import { useState, type FormEvent, type ReactNode } from "react"
import {
  ArrowUpRight,
  BookOpen,
  ChevronRight,
  FileText,
  Github,
  Languages,
  Menu,
  Moon,
  Quote,
  Search,
  Sparkles,
  Users,
} from "lucide-react"
import { cn } from "@/lib/utils"

type Intent = {
  module: string
  description: string
  href: string
  tone: "blue" | "green" | "amber" | "slate"
}

const intents: Array<Intent & { keywords: string[] }> = [
  { module: "论文研究", description: "检索论文、方法和可验证的证据", href: "/papers", tone: "blue", keywords: ["论文", "文献", "研究", "方法", "评测", "引用"] },
  { module: "项目雷达", description: "查看项目活跃度、仓库和工具链", href: "/projects", tone: "green", keywords: ["项目", "仓库", "github", "工具", "开源", "代码"] },
  { module: "社区信号", description: "追踪讨论、主题和行业动态", href: "/community", tone: "amber", keywords: ["社区", "讨论", "动态", "趋势", "新闻", "行业"] },
  { module: "研究报告", description: "整理研究结果并形成可读报告", href: "/reports", tone: "slate", keywords: ["报告", "总结", "整理", "结论", "对比"] },
]

const suggestions = [
  "找出支持长上下文 Agent 评测的论文",
  "看看最近活跃的研究基础设施项目",
  "总结本周社区讨论最多的主题",
]

const recentPapers = [
  { title: "Sibyl-AutoResearch: Autonomous Research Needs Self-Evolving Trial-and-Error Harnesses", meta: "Chengcheng Wang, Qinhua Xie, Wei He · 2026年5月21日 · arXiv", tone: "blue" },
  { title: "Gated DeltaNet-2: Decoupling Erase and Write in Linear Attention", meta: "Ali Hatamizadeh, Yejin Choi, Jan Kautz · 2026年5月22日 · arXiv", tone: "green" },
]

export function DesignDemoPage() {
  const [query, setQuery] = useState("")
  const [matchedIntent, setMatchedIntent] = useState<Intent | null>(null)

  function resolveIntent(value: string) {
    const normalized = value.trim().toLowerCase()
    const match = intents.find((intent) => intent.keywords.some((keyword) => normalized.includes(keyword.toLowerCase())))
    setMatchedIntent(match ?? intents[0])
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (query.trim()) resolveIntent(query)
  }

  function handleSuggestion(value: string) {
    setQuery(value)
    resolveIntent(value)
  }

  return (
    <div className="min-h-screen bg-[#f5f7f4] text-[#202a36]">
      <header className="h-[62px] border-b border-[#dfe4df] bg-white">
        <div className="mx-auto flex h-full max-w-[1280px] items-center gap-6 px-8">
          <div className="flex w-[245px] shrink-0 items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-[11px] bg-[#172033] text-sm font-bold text-white">A</span>
            <div className="leading-none">
              <p className="text-[15px] font-semibold tracking-[-0.01em] text-[#202a36]">Agora Hub <span className="text-[#00a36c]">Research</span></p>
              <p className="mt-1 text-[11px] text-[#71808b]">论文 · 项目 · 信号</p>
            </div>
          </div>

          <label className="mx-auto flex h-10 w-[min(420px,42vw)] items-center gap-2 rounded-full border border-[#d7ded8] bg-[#fbfcfb] px-3.5 text-sm text-[#7a8790] shadow-[0_1px_2px_rgba(29,43,35,0.03)]">
            <Search className="size-4 shrink-0" />
            <input aria-label="搜索论文、任务、方法" className="min-w-0 flex-1 bg-transparent text-[#27343f] outline-none placeholder:text-[#87939b]" placeholder="搜索论文、任务、方法..." />
          </label>

          <div className="flex shrink-0 items-center gap-2">
            <button type="button" title="切换深色模式" aria-label="切换深色模式" className="flex h-9 items-center gap-2 rounded-full border border-[#d7ded8] px-3 text-xs font-medium text-[#34414b] transition-colors hover:bg-[#f5f8f5]"><Moon className="size-3.5" />浅色</button>
            <button type="button" title="切换语言" aria-label="切换语言" className="flex h-9 items-center gap-2 rounded-full border border-[#d7ded8] px-2.5 text-xs font-medium text-[#34414b] transition-colors hover:bg-[#f5f8f5]"><Languages className="size-3.5" /><span className="rounded-full bg-[#26354b] px-1.5 py-0.5 text-[10px] text-white">中</span><span className="text-[#87939b]">EN</span></button>
            <button type="button" title="打开菜单" aria-label="打开菜单" className="flex size-9 items-center justify-center rounded-full text-[#64727c] transition-colors hover:bg-[#f1f5f1]"><Menu className="size-[18px]" /></button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1280px] px-8 pb-16 pt-7">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-[11px] font-medium tracking-[0.16em] text-[#83909a]"><span>RESEARCH</span><span className="text-[#b0b9bd]">›</span><span>HOME</span></div>
          <div className="inline-flex items-center gap-2 rounded-full border border-[#dce4dc] bg-white px-3 py-1.5 text-xs text-[#73817b] shadow-[0_1px_3px_rgba(27,44,34,0.06)]"><span className="size-2 rounded-full bg-[#00a976]" />前台用户视图 · 已发布研究内容</div>
        </div>

        <section className="mx-auto mt-16 max-w-[860px] text-center">
          <p className="text-[11px] font-semibold tracking-[0.2em] text-[#73847b]">AGORA RESEARCH</p>
          <h1 className="mt-4 text-[42px] font-semibold leading-tight tracking-[-0.035em] text-[#202a36]">从一个问题开始研究</h1>
          <p className="mx-auto mt-4 max-w-[610px] text-[15px] leading-7 text-[#65727b]">告诉我你想了解什么，我会把你带到最合适的研究模块。</p>

          <form onSubmit={handleSubmit} className="mx-auto mt-8 flex min-h-[72px] items-center gap-3 rounded-2xl border border-[#cfdad1] bg-white p-2 pl-5 text-left shadow-[0_10px_30px_rgba(27,49,36,0.08)] focus-within:border-[#8bb69b]">
            <Sparkles className="size-5 shrink-0 text-[#1f7a58]" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="向 Agora 提问" className="min-w-0 flex-1 bg-transparent text-[15px] text-[#263440] outline-none placeholder:text-[#9aa5a6]" placeholder="例如：找出支持长上下文 Agent 评测的论文" />
            <kbd className="hidden rounded-md border border-[#e2e7e3] px-2 py-1 text-[10px] text-[#9aa5a6] sm:inline">⌘ ↵</kbd>
            <button type="submit" className="inline-flex h-11 shrink-0 items-center gap-2 rounded-xl bg-[#172033] px-5 text-sm font-semibold text-white transition-colors hover:bg-[#26354b]">提问<ArrowUpRight className="size-4" /></button>
          </form>

          <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-xs text-[#8b9799]">
            <span className="mr-1">试试：</span>
            {suggestions.map((suggestion) => <button key={suggestion} type="button" onClick={() => handleSuggestion(suggestion)} className="rounded-full border border-[#dce4dc] bg-white px-3 py-1.5 text-[#63716f] transition-colors hover:border-[#aac7b1] hover:bg-[#f3f8f3]">{suggestion}</button>)}
          </div>
        </section>

        {matchedIntent ? <IntentResult intent={matchedIntent} query={query} /> : null}

        <section className="mt-16 border-t border-[#dce3dc] pt-7">
          <div className="flex items-end justify-between gap-4"><div><p className="text-[11px] font-semibold tracking-[0.18em] text-[#7b8a82]">RESEARCH MODULES</p><h2 className="mt-2 text-xl font-semibold text-[#263440]">进入研究空间</h2></div><span className="text-xs text-[#8c989c]">也可以直接选择一个模块</span></div>
          <div className="mt-5 grid grid-cols-4 gap-4">
            <ModuleCard icon={<BookOpen className="size-5" />} title="论文研究" description="论文、方法、引用" href="/papers" tone="blue" />
            <ModuleCard icon={<Github className="size-5" />} title="项目雷达" description="仓库、工具、活跃度" href="/projects" tone="green" />
            <ModuleCard icon={<Users className="size-5" />} title="社区信号" description="讨论、主题、动态" href="/community" tone="amber" />
            <ModuleCard icon={<FileText className="size-5" />} title="研究报告" description="整理、比较、输出" href="/reports" tone="slate" />
          </div>
        </section>

        <section className="mt-14 overflow-hidden rounded-xl border border-[#d9e0da] bg-white">
          <div className="flex items-center justify-between border-b border-[#dfe5df] px-5 py-3.5"><div className="flex items-center gap-2"><Quote className="size-4 text-[#64746e]" /><h2 className="text-sm font-semibold text-[#263440]">最近论文</h2></div><a href="/papers" className="inline-flex items-center gap-1 text-xs font-medium text-[#2b684d] hover:text-[#174d37]">查看全部<ChevronRight className="size-3.5" /></a></div>
          {recentPapers.map((paper, index) => <a key={paper.title} href="/papers" className={cn("flex items-center gap-4 px-5 py-4 transition-colors hover:bg-[#f8faf8]", index > 0 && "border-t border-[#e5eae5]")}><PaperMark tone={paper.tone} /><div className="min-w-0 flex-1"><h3 className="truncate text-sm font-semibold text-[#263440]">{paper.title}</h3><p className="mt-1.5 truncate text-xs text-[#89959d]">{paper.meta}</p></div><ChevronRight className="size-4 shrink-0 text-[#a2ada9]" /></a>)}
        </section>
      </main>
    </div>
  )
}

function IntentResult({ intent, query }: { intent: Intent; query: string }) {
  return <section className="mx-auto mt-8 flex max-w-[860px] items-center justify-between gap-5 rounded-xl border border-[#c9ddce] bg-[#f1f8f2] px-5 py-4 text-left"><div className="min-w-0"><p className="text-[11px] font-semibold tracking-[0.16em] text-[#5e7d69]">已识别研究意图</p><h2 className="mt-1.5 text-base font-semibold text-[#1d4e38]">{intent.module}</h2><p className="mt-1 truncate text-sm text-[#6c8275]">“{query}” · {intent.description}</p></div><a href={intent.href} className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-[#1f6b4d] px-3.5 text-xs font-semibold text-white transition-colors hover:bg-[#18563d]">进入模块<ChevronRight className="size-3.5" /></a></section>
}

function ModuleCard({ icon, title, description, href, tone }: { icon: ReactNode; title: string; description: string; href: string; tone: Intent["tone"] }) {
  const toneClass = tone === "blue" ? "bg-[#eaf1fa] text-[#5278a8]" : tone === "green" ? "bg-[#e6f2e8] text-[#3d7c59]" : tone === "amber" ? "bg-[#fbf1e4] text-[#a66f43]" : "bg-[#edf0f2] text-[#667580]"
  return <a href={href} className="group flex items-start gap-3 rounded-xl border border-[#dce3dd] bg-white p-4 transition-colors hover:border-[#b8cdbd] hover:bg-[#fbfdfb]"><span className={cn("flex size-9 shrink-0 items-center justify-center rounded-lg", toneClass)}>{icon}</span><span className="min-w-0"><span className="block text-sm font-semibold text-[#263440]">{title}</span><span className="mt-1 block text-xs text-[#849099]">{description}</span></span><ChevronRight className="ml-auto mt-1 size-4 shrink-0 text-[#a6b0ad] transition-transform group-hover:translate-x-0.5" /></a>
}

function PaperMark({ tone }: { tone: string }) {
  const toneClass = tone === "blue" ? "bg-[#dce8f8]" : tone === "green" ? "bg-[#e4f1e6]" : "bg-[#f7ecde]"
  return <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-lg", toneClass)}><FileText className="size-5 text-[#6d7f7c]" /></span>
}
