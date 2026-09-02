"use client"

import { useRef, useState, type FormEvent, type ReactNode } from "react"
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  ClipboardCheck,
  FileText,
  Github,
  Play,
  Quote,
  Sparkles,
  WandSparkles,
} from "lucide-react"
import { cn } from "@/lib/utils"

type Intent = {
  command: string
  module: string
  description: string
  href: string
  icon: ReactNode
  keywords: string[]
}

const intents: Intent[] = [
  { command: "找论文", module: "论文研究", description: "检索论文、方法和可验证的证据", href: "/papers", icon: <BookOpen className="size-4" />, keywords: ["论文", "文献", "研究", "方法", "评测", "引用"] },
  { command: "找项目", module: "项目雷达", description: "查看项目活跃度、仓库和工具链", href: "/projects", icon: <Github className="size-4" />, keywords: ["项目", "仓库", "github", "工具", "开源", "代码"] },
  { command: "看社区", module: "社区信号", description: "追踪讨论、主题和行业动态", href: "/community", icon: <Quote className="size-4" />, keywords: ["社区", "讨论", "动态", "趋势", "新闻", "行业"] },
  { command: "写报告", module: "研究报告", description: "整理研究结果并形成可读报告", href: "/reports", icon: <FileText className="size-4" />, keywords: ["报告", "总结", "整理", "结论", "对比"] },
]

const quickPrompts = [
  "找出支持长上下文 Agent 评测的论文",
  "看看最近活跃的研究基础设施项目",
  "总结本周社区讨论最多的主题",
]

export function DesignDemoPage() {
  const [query, setQuery] = useState("")
  const [intent, setIntent] = useState<Intent>(intents[0])
  const [modeMenuOpen, setModeMenuOpen] = useState(false)
  const selectedModeRef = useRef<Intent | null>(null)
  const [hasSubmitted, setHasSubmitted] = useState(false)

  function resolveIntent(value: string) {
    const normalized = value.trim().toLowerCase()
    return intents.find((item) => item.keywords.some((keyword) => normalized.includes(keyword))) ?? intents[0]
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (query.trim()) {
      setIntent(selectedModeRef.current ?? resolveIntent(query))
      setHasSubmitted(true)
    }
  }

  function setPrompt(value: string) {
    setQuery(value)
    setIntent(resolveIntent(value))
    selectedModeRef.current = null
    setHasSubmitted(false)
    setModeMenuOpen(false)
  }

  return (
    <div className="min-h-screen bg-[#fbf8ff] text-[#211a3c]">
      <header className="border-b border-[#eee8f5] bg-white">
        <nav className="mx-auto flex h-[64px] max-w-[1200px] items-center justify-between px-8" aria-label="主导航">
          <a href="/design-demo" className="flex items-center gap-2.5">
            <span className="flex size-9 items-center justify-center rounded-[10px] bg-[#7c3aed] text-white shadow-[0_5px_12px_rgba(124,58,237,0.22)]"><WandSparkles className="size-[18px]" /></span>
            <span className="text-[17px] font-bold tracking-[-0.02em] text-[#2b2148]">Agora<span className="text-[#7c3aed]">AI</span></span>
          </a>
          <div className="flex items-center gap-7 text-sm text-[#6d6286]">
            <a href="#how-it-works" className="transition-colors hover:text-[#6735d3]">如何工作</a>
            <a href="#modules" className="transition-colors hover:text-[#6735d3]">研究模块</a>
            <a href="/papers" className="transition-colors hover:text-[#6735d3]">论文研究</a>
          </div>
          <div className="flex items-center gap-3">
            <button type="button" className="text-sm font-medium text-[#594f71] transition-colors hover:text-[#6735d3]">登录</button>
            <a href="#workspace" className="inline-flex h-10 items-center rounded-xl bg-[#7c3aed] px-4 text-sm font-semibold text-white shadow-[0_5px_14px_rgba(124,58,237,0.25)] transition-colors hover:bg-[#6d28d9]">开始研究</a>
          </div>
        </nav>
      </header>

      <main>
        <section className="px-8 pb-14 pt-16 text-center">
          <span className="inline-flex items-center gap-2 rounded-full bg-[#f0e9ff] px-3 py-1.5 text-xs font-medium text-[#7042cc]"><Sparkles className="size-3.5" />由 Agora Research 驱动</span>
          <h1 className="mx-auto mt-6 max-w-[820px] text-[54px] font-bold leading-[1.05] tracking-[-0.045em] text-[#251d42]">研究得更清楚，<span className="text-[#7c3aed]">更快</span>找到答案</h1>
          <p className="mx-auto mt-5 max-w-[650px] text-[17px] leading-7 text-[#756b84]">从一个自然语言问题开始。Agora AI 会理解你的研究意图，并将你带到最合适的论文、项目、社区或报告模块。</p>
          <div className="mt-8 flex justify-center gap-3">
            <a href="#workspace" className="inline-flex h-12 items-center gap-2 rounded-xl bg-[#7c3aed] px-5 text-sm font-semibold text-white shadow-[0_7px_18px_rgba(124,58,237,0.26)] transition-colors hover:bg-[#6d28d9]">开始提问<ArrowRight className="size-4" /></a>
            <a href="#how-it-works" className="inline-flex h-12 items-center gap-2 rounded-xl border border-[#ddd2f1] bg-white px-5 text-sm font-semibold text-[#594f71] transition-colors hover:bg-[#faf7ff]"><Play className="size-4 fill-current" />查看示例</a>
          </div>
        </section>

        <section id="workspace" className="mx-auto max-w-[900px] px-8 pb-12">
          <div className="overflow-visible rounded-2xl border border-[#e7dff1] bg-white p-5 shadow-[0_18px_45px_rgba(86,58,127,0.13)]">
            <div className="flex items-center justify-between px-1 text-xs text-[#8b7fa0]">
              <span className="inline-flex items-center gap-2 font-semibold uppercase tracking-[0.12em]"><Sparkles className="size-4 text-[#7c3aed]" />Agora AI</span>
              <span className="inline-flex items-center gap-2 text-[#7c3aed]"><span className="size-2 rounded-full bg-[#8b5cf6]" />准备回答</span>
            </div>

            <form onSubmit={handleSubmit} className="relative mt-4 flex h-14 items-center gap-2 rounded-xl border border-[#ded4ec] bg-[#fefeff] p-2 pl-2.5 shadow-[0_3px_12px_rgba(86,58,127,0.06)] focus-within:border-[#a783ec] focus-within:ring-2 focus-within:ring-[#f0e9ff]">
              <button type="button" aria-label="选择研究模式" aria-haspopup="menu" aria-expanded={modeMenuOpen} onClick={() => setModeMenuOpen((open) => !open)} className="inline-flex h-9 shrink-0 items-center gap-2 rounded-lg px-2.5 text-xs font-semibold text-[#5b4c76] transition-colors hover:bg-[#f3edff]">
                <span className="flex size-7 items-center justify-center rounded-md bg-[#f0e9ff] text-[#7c3aed]">{intent.icon}</span>{intent.command}<ChevronRight className={cn("size-3.5 text-[#998caf] transition-transform", modeMenuOpen && "rotate-90")} />
              </button>
              <input value={query} onChange={(event) => { setQuery(event.target.value); setHasSubmitted(false) }} aria-label="向 Agora AI 提问" className="min-w-0 flex-1 bg-transparent px-1 text-sm text-[#3a304f] outline-none placeholder:text-[#aaa0b7]" placeholder="输入你想研究的问题..." />
              <button type="submit" aria-label="发送问题" className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[#7c3aed] text-white transition-colors hover:bg-[#6d28d9]"><ArrowRight className="size-4" /></button>

              {modeMenuOpen ? <ModeMenu activeIntent={intent} onSelect={(nextIntent) => { selectedModeRef.current = nextIntent; setIntent(nextIntent); setModeMenuOpen(false); setHasSubmitted(false) }} /> : null}
            </form>

            <div className="mt-3 flex flex-wrap items-center gap-2 px-1">
              <span className="mr-1 text-xs text-[#9389a2]">试试：</span>
              {quickPrompts.map((prompt) => <button key={prompt} type="button" onClick={() => setPrompt(prompt)} className="rounded-lg border border-[#e7dff1] bg-white px-2.5 py-1.5 text-left text-[11px] leading-4 text-[#6b607e] transition-colors hover:border-[#b99beb] hover:bg-[#faf7ff]">{prompt}</button>)}
            </div>

            {hasSubmitted ? <div className="mt-4 flex items-center justify-between gap-4 rounded-lg border border-[#e0d3f4] bg-[#faf7ff] px-3.5 py-2.5 text-xs"><span className="inline-flex min-w-0 items-center gap-2 text-[#695d7d]"><span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-[#f0e9ff] text-[#7c3aed]">{intent.icon}</span><span className="truncate">将带着你的问题进入 <strong className="font-semibold text-[#382758]">{intent.module}</strong></span></span><a href={intent.href} className="inline-flex shrink-0 items-center gap-1 font-semibold text-[#7042cc] hover:text-[#5425b5]">进入模块<ChevronRight className="size-3.5" /></a></div> : null}
          </div>
        </section>

        <section id="how-it-works" className="border-y border-[#eee8f5] bg-white px-8 py-12">
          <div className="mx-auto max-w-[1040px]">
            <p className="text-center text-xs font-semibold uppercase tracking-[0.16em] text-[#8a7ca3]">HOW IT WORKS</p>
            <h2 className="mt-3 text-center text-[30px] font-bold tracking-[-0.03em] text-[#2b2148]">一个入口，四类研究工作</h2>
            <div id="modules" className="mt-8 grid grid-cols-4 gap-4">
              <ModuleCard icon={<BookOpen className="size-5" />} title="论文研究" description="论文、方法、证据" href="/papers" />
              <ModuleCard icon={<Github className="size-5" />} title="项目雷达" description="仓库、工具、活跃度" href="/projects" />
              <ModuleCard icon={<Quote className="size-5" />} title="社区信号" description="讨论、主题、动态" href="/community" />
              <ModuleCard icon={<ClipboardCheck className="size-5" />} title="研究报告" description="整理、比较、输出" href="/reports" />
            </div>
          </div>
        </section>
      </main>

      <footer className="bg-[#fbf8ff] px-8 py-7"><div className="mx-auto flex max-w-[1200px] items-center justify-between text-xs text-[#9389a2]"><span>Agora Hub Research</span><span>用 AI 开始你的下一次研究</span></div></footer>
    </div>
  )
}

function ModeMenu({ activeIntent, onSelect }: { activeIntent: Intent; onSelect: (intent: Intent) => void }) {
  return <div role="menu" className="absolute left-2 top-[calc(100%+10px)] z-20 w-64 rounded-xl border border-[#e4d9ef] bg-white p-2 text-left shadow-[0_14px_36px_rgba(60,41,93,0.16)]"><p className="px-2.5 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#9a8eaa]">研究模式</p>{intents.map((item) => <button key={item.module} type="button" role="menuitem" onClick={() => onSelect(item)} className="flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left transition-colors hover:bg-[#f8f4ff]"><span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-[#f0e9ff] text-[#7c3aed]">{item.icon}</span><span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-[#3f3158]">{item.command}</span><span className="mt-0.5 block text-xs text-[#8e839b]">{item.description}</span></span>{activeIntent.module === item.module ? <Check className="size-4 shrink-0 text-[#7c3aed]" /> : null}</button>)}</div>
}

function ModuleCard({ icon, title, description, href }: { icon: ReactNode; title: string; description: string; href: string }) {
  return <a href={href} className="group rounded-xl border border-[#e9e2f0] bg-[#fefeff] p-4 transition-colors hover:border-[#c7acef] hover:bg-[#fcfaff]"><span className="flex size-9 items-center justify-center rounded-lg bg-[#f0e9ff] text-[#7c3aed]">{icon}</span><h3 className="mt-5 text-sm font-semibold text-[#372b51]">{title}</h3><p className="mt-1 text-xs text-[#8e839b]">{description}</p><span className="mt-4 flex items-center gap-1 text-xs font-medium text-[#7650c6]">进入模块<ChevronRight className="size-3.5 transition-transform group-hover:translate-x-0.5" /></span></a>
}
