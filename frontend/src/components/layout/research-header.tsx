"use client"

import { useState } from "react"
import Link from "next/link"
import { ChevronDown, Menu, Search } from "lucide-react"
import { AccountMenu } from "@/components/auth/account-menu"
import { PapersLanguageToggle } from "@/components/papers/shared/language-toggle"
import { PapersThemeToggle } from "@/components/papers/shared/theme-toggle"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { papersCopy, t } from "@/lib/papers/copy"
import type { Locale } from "@/lib/papers/types"
import { cn } from "@/lib/utils"
import type { ThemeMode } from "@/stores/ui-store"

export function ResearchHeader({
  locale,
  theme,
  onLocaleChange,
  onThemeChange
}: {
  locale: Locale
  theme: ThemeMode
  onLocaleChange: (locale: Locale) => void
  onThemeChange: (theme: ThemeMode) => void
}) {
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null)
  const [mobileOpen, setMobileOpen] = useState(false)

  function handleGroupBlur(event: React.FocusEvent<HTMLDivElement>) {
    const nextFocus = event.relatedTarget
    if (nextFocus instanceof Node && event.currentTarget.contains(nextFocus)) {
      return
    }
    setActiveGroupId(null)
  }

  return (
    <header className="sticky top-0 z-40 border-b border-[#dfe5df] bg-white/90 backdrop-blur dark:border-border dark:bg-card/95">
      <div className="mx-auto flex min-h-[64px] max-w-[1920px] items-center gap-5 px-4 py-2 sm:px-6 2xl:px-0">
        <Link href="/papers" className="flex shrink-0 items-center gap-3" aria-label="NewsRoom Research">
          <span className="flex size-9 items-center justify-center rounded-full bg-[#0f172a] text-sm font-black text-white">
            N
          </span>
          <span>
            <span className="block text-base font-semibold leading-5">
              NewsRoom <span className="text-emerald-600">Research</span>
            </span>
            <span className="block text-xs text-[#334155]/55 dark:text-muted-foreground">{t(papersCopy.brandSubline, locale)}</span>
          </span>
        </Link>

        <div
          className="relative hidden flex-1 items-center justify-start lg:flex"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setActiveGroupId(null)
            }
          }}
        >
          <nav className="flex items-center gap-2" aria-label="Portal modules">
            {researchHeaderGroups.map((group) => {
              const active = activeGroupId === group.id
              const dropdownId = `research-header-${group.id}-menu`

              return (
                <div
                  key={group.id}
                  className="relative"
                  onBlur={handleGroupBlur}
                  onMouseEnter={() => setActiveGroupId(group.id)}
                  onMouseLeave={() => setActiveGroupId(null)}
                >
                  <button
                    type="button"
                    className={cn(
                      "inline-flex h-9 items-center gap-1 rounded-full px-4 text-sm font-medium text-[#334155] transition-colors hover:bg-[#eef3ef] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:text-foreground dark:hover:bg-secondary",
                      active && "bg-[#eef3ef] dark:bg-secondary"
                    )}
                    aria-expanded={active}
                    aria-controls={dropdownId}
                    onClick={() => setActiveGroupId(active ? null : group.id)}
                    onFocus={() => setActiveGroupId(group.id)}
                  >
                    {t(group.label, locale)}
                    <ChevronDown className={cn("size-4 transition-transform", active && "rotate-180")} />
                  </button>
                  {active ? <ResearchHeaderDropdown id={dropdownId} group={group} locale={locale} /> : null}
                </div>
              )
            })}
          </nav>
        </div>

        <div className="relative ml-auto hidden w-[min(26rem,32vw)] md:block">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-10 rounded-full border-[#d7dfd8] bg-white pl-9 shadow-sm dark:border-border dark:bg-card" placeholder={t(papersCopy.searchPlaceholder, locale)} />
        </div>
        <div className="hidden items-center gap-2 sm:flex">
          <PapersThemeToggle theme={theme} locale={locale} onThemeChange={onThemeChange} />
          <PapersLanguageToggle locale={locale} onLocaleChange={onLocaleChange} />
        </div>
        <AccountMenu />

        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <Button type="button" variant="ghost" size="icon" className="lg:hidden" aria-label={t(papersCopy.openNavigation, locale)}>
              <Menu className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent className="w-[min(22rem,88vw)] overflow-y-auto">
            <SheetTitle className="sr-only">{t(papersCopy.brand, locale)}</SheetTitle>
            <SheetDescription className="sr-only">{t(papersCopy.brandSubline, locale)}</SheetDescription>
            <div className="mb-6 pr-8">
              <p className="text-sm font-semibold">{t(papersCopy.brand, locale)}</p>
              <p className="text-xs text-muted-foreground">{t(papersCopy.brandSubline, locale)}</p>
            </div>
            <div className="relative mb-4">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input className="h-9 pl-9" placeholder={t(papersCopy.searchPlaceholder, locale)} />
            </div>
            <div className="mb-4 flex flex-wrap items-center gap-2 sm:hidden">
              <PapersThemeToggle theme={theme} locale={locale} onThemeChange={onThemeChange} />
              <PapersLanguageToggle locale={locale} onLocaleChange={onLocaleChange} />
            </div>
            <nav className="space-y-4" aria-label="Research mobile navigation">
              {researchHeaderGroups.map((group) => (
                <div key={group.id}>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    {t(group.label, locale)}
                  </p>
                  <div className="space-y-2">
                    {group.items.map((item) => (
                      <SheetClose asChild key={item.href}>
                        <Link
                          href={item.href}
                          className="block rounded-md border border-border bg-background/60 px-3 py-2 text-sm transition-colors hover:bg-secondary"
                        >
                          <span className="font-medium">{t(item.label, locale)}</span>
                          <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                            {t(item.description, locale)}
                          </span>
                        </Link>
                      </SheetClose>
                    ))}
                  </div>
                </div>
              ))}
            </nav>
          </SheetContent>
        </Sheet>
      </div>
    </header>
  )
}

type HeaderCopy = Record<Locale, string>

type HeaderNavItem = {
  href: string
  label: HeaderCopy
  description: HeaderCopy
}

type HeaderNavGroup = {
  id: string
  label: HeaderCopy
  items: HeaderNavItem[]
}

function ResearchHeaderDropdown({ id, group, locale }: { id: string; group: HeaderNavGroup; locale: Locale }) {
  return (
    <div id={id} className="absolute left-0 top-full z-50 w-[min(30rem,calc(100vw-2rem))] pt-2">
      <div className="rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-soft">
        <div className="grid gap-1">
          {group.items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="group rounded-md px-3 py-2 transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="flex items-center justify-between gap-3 text-sm font-semibold text-foreground">
                {t(item.label, locale)}
              </span>
              <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                {t(item.description, locale)}
              </span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}

const researchHeaderGroups: HeaderNavGroup[] = [
  {
    id: "research",
    label: papersCopy.papersNav,
    items: [
      {
        href: "/papers",
        label: papersCopy.trendingPapers,
        description: papersCopy.dropdownTrendingDescription
      },
      {
        href: "/papers/tasks",
        label: papersCopy.tasks,
        description: papersCopy.dropdownTasksDescription
      },
      {
        href: "/papers/methods",
        label: papersCopy.methods,
        description: papersCopy.dropdownMethodsDescription
      }
    ]
  },
  {
    id: "today",
    label: { zh: "今日", en: "Today" },
    items: [
      {
        href: "/news",
        label: { zh: "头条", en: "Top Stories" },
        description: { zh: "每日 AI 新闻主线和重点来源。", en: "Daily AI news front page and key sources." }
      },
      {
        href: "/news?source=official",
        label: { zh: "官方更新", en: "Official Updates" },
        description: { zh: "来自官方博客、公告和一手来源的更新。", en: "Updates from official blogs, announcements, and primary sources." }
      },
      {
        href: "/news?topic=product-updates",
        label: { zh: "产品更新", en: "Product Updates" },
        description: { zh: "产品发布、能力变化和采用信号。", en: "Product launches, capability changes, and adoption signals." }
      },
      {
        href: "/tech/repos",
        label: { zh: "开源", en: "Open Source" },
        description: { zh: "GitHub 仓库、项目动量和工程落地线索。", en: "GitHub repositories, project momentum, and engineering adoption clues." }
      },
      {
        href: "/community",
        label: { zh: "社区脉搏", en: "Community Pulse" },
        description: { zh: "开发者讨论、争议、反馈和传播路径。", en: "Developer discussion, controversy, feedback, and propagation paths." }
      }
    ]
  },
  {
    id: "trends",
    label: { zh: "趋势", en: "Trends" },
    items: [
      {
        href: "/news?sort=hot",
        label: { zh: "热门", en: "Hot" },
        description: { zh: "当前热度最高的新闻和社区信号。", en: "The hottest current news and community signals." }
      },
      {
        href: "/news?sort=rising",
        label: { zh: "上升", en: "Rising" },
        description: { zh: "正在加速升温的新主题和项目。", en: "New topics and projects gaining momentum." }
      },
      {
        href: "/topics?view=timeline",
        label: { zh: "时间线", en: "Timeline" },
        description: { zh: "按时间追踪主题演化和关键事件。", en: "Track topic evolution and key events over time." }
      },
      {
        href: "/news?sort=controversial",
        label: { zh: "争议", en: "Controversial" },
        description: { zh: "争议、分歧和观点碰撞较强的信号。", en: "Signals with strong disagreement, debate, and controversy." }
      },
      {
        href: "/topics?view=evidence-graph",
        label: { zh: "证据图谱", en: "Evidence Graph" },
        description: { zh: "跨新闻、论文、项目和社区的证据关系。", en: "Evidence relationships across news, papers, projects, and community." }
      },
      {
        href: "/topics?topic=agents",
        label: { zh: "智能体", en: "Agents" },
        description: { zh: "Agent 运行时、工作流和评测方向。", en: "Agent runtimes, workflows, and evaluation directions." }
      },
      {
        href: "/topics?topic=llms",
        label: { zh: "大模型", en: "LLMs" },
        description: { zh: "大模型能力、发布和生态变化。", en: "Model capabilities, releases, and ecosystem changes." }
      },
      {
        href: "/topics?topic=models",
        label: { zh: "模型", en: "Models" },
        description: { zh: "模型架构、基准和应用表现。", en: "Model architectures, benchmarks, and application performance." }
      },
      {
        href: "/topics?view=compare",
        label: { zh: "对比", en: "Compare" },
        description: { zh: "对比主题、来源和趋势信号强度。", en: "Compare topics, sources, and trend signal strength." }
      }
    ]
  },
  {
    id: "reports",
    label: { zh: "报告", en: "Reports" },
    items: [
      {
        href: "/reports?type=daily",
        label: { zh: "日报", en: "Daily" },
        description: { zh: "每日 AI 情报摘要和关键变化。", en: "Daily AI intelligence briefings and key changes." }
      },
      {
        href: "/reports?type=weekly",
        label: { zh: "周报", en: "Weekly" },
        description: { zh: "每周趋势、来源健康和主题复盘。", en: "Weekly trends, source health, and topic reviews." }
      },
      {
        href: "/reports?type=deep-dives",
        label: { zh: "深度分析", en: "Deep Dives" },
        description: { zh: "围绕重点主题生成的长分析报告。", en: "Long-form reports around important topics." }
      },
      {
        href: "/reports?type=briefings",
        label: { zh: "简报", en: "Briefings" },
        description: { zh: "适合快速阅读和分发的简短情报。", en: "Short intelligence briefs for fast reading and sharing." }
      },
      {
        href: "/reports?type=watchlists",
        label: { zh: "关注列表", en: "Watchlists" },
        description: { zh: "持续跟踪的主题、项目和来源集合。", en: "Tracked topics, projects, and source collections." }
      },
      {
        href: "/reports?type=archive",
        label: { zh: "归档", en: "Archive" },
        description: { zh: "历史报告和可追溯情报记录。", en: "Historical reports and traceable intelligence records." }
      }
    ]
  }
]
