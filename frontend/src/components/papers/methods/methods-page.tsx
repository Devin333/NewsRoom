"use client"

import { useEffect, useState } from "react"
import { MethodCard } from "@/components/papers/methods/method-card"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { Button } from "@/components/ui/button"
import { localizedResearchNotice, papersCopy, t } from "@/lib/papers/copy"
import { fetchPaperMethodsResult, fetchPaperTasksResult, fetchPapers } from "@/lib/papers/api"
import { methodAreaSlug } from "@/lib/papers/metrics"
import type { Locale, Paper, PaperMethod, PaperTask } from "@/lib/papers/types"

type TaxonomySort = "paper_count" | "recent" | "benchmark"

export function MethodsPage({ locale }: { locale: Locale }) {
  const [methods, setMethods] = useState<PaperMethod[]>([])
  const [tasks, setTasks] = useState<PaperTask[]>([])
  const [paperItems, setPaperItems] = useState<Paper[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">("loading")
  const [notice, setNotice] = useState<string | null>(null)
  const [fallbackNoticeVisible, setFallbackNoticeVisible] = useState(true)
  const [sort, setSort] = useState<TaxonomySort>("paper_count")

  useEffect(() => {
    let active = true
    Promise.allSettled([fetchPaperMethodsResult(), fetchPaperTasksResult(), fetchPapers({ limit: 5000, period: "all" })])
      .then(([methodsResult, tasksResult, papersResult]) => {
        if (!active) {
          return
        }

        const publicPaperItems = papersResult.status === "fulfilled" ? publicPapers(papersResult.value.papers) : []

        if (methodsResult.status === "rejected") {
          setMethods([])
          setTasks(tasksResult.status === "fulfilled" ? tasksResult.value.tasks.filter((task) => task.paperCount > 0) : [])
          setPaperItems(publicPaperItems)
          setNotice(t(papersCopy.methodApiFallback, locale))
          setStatus("fallback")
          return
        }

        setMethods(methodsResult.value.methods.filter((method) => method.paperCount > 0))
        setTasks(tasksResult.status === "fulfilled" ? tasksResult.value.tasks.filter((task) => task.paperCount > 0) : [])
        setPaperItems(publicPaperItems)
        setNotice(combineNotices([
          localizedResearchNotice(methodsResult.value.notices?.[0] ?? null, locale),
          tasksResult.status === "fulfilled"
            ? localizedResearchNotice(tasksResult.value.notices?.[0] ?? null, locale)
            : taskListUnavailableNotice(locale),
          papersResult.status === "rejected" ? paperListUnavailableNotice(locale) : null
        ]))
        setStatus(
          (methodsResult.value.dataState === "ready" || !methodsResult.value.dataState) &&
            tasksResult.status === "fulfilled" &&
            papersResult.status === "fulfilled"
            ? "ready"
            : "fallback"
        )
      })
    return () => {
      active = false
    }
  }, [locale])

  const methodItems = status === "loading" ? [] : sortMethods(methods.filter((method) => method.paperCount > 0), paperItems, sort)
  const taskItems = status === "loading" ? [] : tasks.filter((task) => task.paperCount > 0)
  const paperItemsForStats = status === "loading" ? [] : paperItems.filter((paper) => (paper.methodRefs ?? []).length > 0)
  const methodPaperCount = paperItemsForStats.length || paperCountFromMethods(methodItems)
  const methodTaskCount = taskItems.length || taskCountFromMethods(methodItems)
  const methodGroups = groupMethodsByArea(methodItems)

  return (
    <div className="space-y-6">
      <PapersMicrobar items={[{ label: "Methods" }]} meta={t(papersCopy.methodBranch, locale)} locale={locale} />
      <PapersHero
        eyebrow=""
        title={t(papersCopy.methods, locale)}
        subtitle={t(papersCopy.methodsSubtitle, locale)}
        stats={[
          { label: t(papersCopy.methods, locale), value: methodItems.length },
          { label: t(papersCopy.papers, locale), value: methodPaperCount },
          { label: t(papersCopy.tasks, locale), value: methodTaskCount }
        ]}
      />
      {status === "fallback" ? (
        <InlineNotice
          message={fallbackNoticeVisible ? notice ?? t(papersCopy.methodApiFallback, locale) : null}
          locale={locale}
          onDismiss={() => setFallbackNoticeVisible(false)}
        />
      ) : null}
      <section className="space-y-6">
        {status !== "loading" && methodItems.length > 0 ? (
          <TaxonomySortControls value={sort} locale={locale} onChange={setSort} />
        ) : null}
        {status === "loading" ? (
          <p className="text-sm text-[#334155]/60 dark:text-muted-foreground">{t(papersCopy.loadingMethods, locale)}</p>
        ) : null}
        {status !== "loading" && methodItems.length === 0 ? (
          <p className="rounded-md border border-dashed border-border p-6 text-sm text-muted-foreground">
            {t(papersCopy.noPapers, locale)}
          </p>
        ) : null}
        {methodGroups.map((group) => (
          <div key={group.area} id={methodAreaSlug(group.area)} className="space-y-3">
            <div className="flex items-center justify-between gap-3 border-b border-border pb-2">
              <h2 className="text-base font-semibold text-[#334155] dark:text-foreground">{group.area}</h2>
              <span className="text-xs text-muted-foreground">{group.methods.length} {t(papersCopy.methods, locale)}</span>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {group.methods.map((method) => (
                <MethodCard key={method.id} method={method} locale={locale} />
              ))}
            </div>
          </div>
        ))}
      </section>
    </div>
  )
}

function publicPapers(papers: Paper[]) {
  return papers.filter((paper) => paper.isPublished !== false)
}

function paperCountFromMethods(methods: PaperMethod[]) {
  const ids = new Set(methods.flatMap((method) => method.representativePaperIds ?? []))
  return ids.size || methods.reduce((total, method) => total + method.paperCount, 0)
}

function taskCountFromMethods(methods: PaperMethod[]) {
  const slugs = new Set(methods.flatMap((method) => (method.relatedTasks ?? []).map((task) => task.slug)))
  return slugs.size || methods.reduce((total, method) => total + method.taskCount, 0)
}

function groupMethodsByArea(methods: PaperMethod[]) {
  const records = new Map<string, PaperMethod[]>()
  methods.forEach((method) => {
    const area = method.area || "Unclassified"
    records.set(area, [...(records.get(area) ?? []), method])
  })
  return Array.from(records.entries())
    .map(([area, items]) => ({
      area,
      methods: items
    }))
    .sort((left, right) => {
      const paperDelta =
        right.methods.reduce((total, method) => total + method.paperCount, 0) -
        left.methods.reduce((total, method) => total + method.paperCount, 0)
      return paperDelta || left.area.localeCompare(right.area)
    })
}

function taskListUnavailableNotice(locale: Locale) {
  return locale === "zh"
    ? "任务目录正在刷新；方法目录仍使用已验证分类。"
    : "Task taxonomy is refreshing; method taxonomy remains available from verified data."
}

function paperListUnavailableNotice(locale: Locale) {
  return locale === "zh"
    ? "论文列表正在刷新；方法目录仍使用已验证分类。"
    : "Paper list is refreshing; method taxonomy remains available from verified data."
}

function combineNotices(notices: Array<string | null | undefined>) {
  const uniqueNotices = [...new Set(notices.filter((notice): notice is string => Boolean(notice)))]
  return uniqueNotices.length ? uniqueNotices.join(" ") : null
}

function TaxonomySortControls({
  value,
  locale,
  onChange
}: {
  value: TaxonomySort
  locale: Locale
  onChange: (value: TaxonomySort) => void
}) {
  const items: TaxonomySort[] = ["paper_count", "recent", "benchmark"]
  return (
    <div className="flex gap-2 overflow-x-auto" aria-label={locale === "zh" ? "方法排序" : "Method sorting"}>
      {items.map((item) => (
        <Button
          key={item}
          type="button"
          variant={item === value ? "default" : "outline"}
          size="sm"
          className="h-8 shrink-0 rounded-full px-3 text-xs shadow-none"
          onClick={() => onChange(item)}
        >
          {sortLabel(item, locale)}
        </Button>
      ))}
    </div>
  )
}

function sortMethods(methods: PaperMethod[], papers: Paper[], sort: TaxonomySort) {
  const latestByMethod = latestPaperTimeByMethodSlug(papers)
  return [...methods].sort((left, right) => {
    if (sort === "recent") {
      return (latestByMethod.get(right.slug) ?? 0) - (latestByMethod.get(left.slug) ?? 0) || right.paperCount - left.paperCount
    }
    if (sort === "benchmark") {
      return (right.commonBenchmarks?.length ?? 0) - (left.commonBenchmarks?.length ?? 0) || right.paperCount - left.paperCount
    }
    return right.paperCount - left.paperCount || left.name.localeCompare(right.name)
  })
}

function latestPaperTimeByMethodSlug(papers: Paper[]) {
  const records = new Map<string, number>()
  for (const paper of publicPapers(papers)) {
    const time = new Date(paper.publishedAt).getTime()
    if (!Number.isFinite(time)) {
      continue
    }
    for (const method of paper.methodRefs ?? []) {
      records.set(method.slug, Math.max(records.get(method.slug) ?? 0, time))
    }
  }
  return records
}

function sortLabel(value: TaxonomySort, locale: Locale) {
  if (value === "recent") return locale === "zh" ? "最近更新" : "Recent"
  if (value === "benchmark") return locale === "zh" ? "有评测" : "Benchmarks"
  return locale === "zh" ? "按论文数" : "Paper count"
}
