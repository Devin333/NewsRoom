"use client"

import { useEffect, useState } from "react"
import { MethodCard } from "@/components/papers/methods/method-card"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { papersCopy, t } from "@/lib/papers/copy"
import { paperMethods, paperTasks } from "@/lib/papers/catalog"
import { fetchPaperMethodsResult, fetchPaperTasksResult, fetchPapers } from "@/lib/papers/api"
import type { Locale, Paper, PaperMethod, PaperTask } from "@/lib/papers/types"

export function MethodsPage({ locale }: { locale: Locale }) {
  const [methods, setMethods] = useState<PaperMethod[]>([])
  const [tasks, setTasks] = useState<PaperTask[]>([])
  const [paperItems, setPaperItems] = useState<Paper[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">("loading")
  const [notice, setNotice] = useState<string | null>(null)
  const [fallbackNoticeVisible, setFallbackNoticeVisible] = useState(true)

  useEffect(() => {
    let active = true
    Promise.all([fetchPaperMethodsResult(), fetchPaperTasksResult(), fetchPapers({ limit: 1000, period: "all" })])
      .then(([apiMethods, apiTasks, apiPapers]) => {
        if (!active) {
          return
        }
        setMethods(apiMethods.methods)
        setTasks(apiTasks.tasks)
        setPaperItems(apiPapers.papers)
        setNotice(apiMethods.notices?.[0] ?? apiTasks.notices?.[0] ?? null)
        setStatus(apiMethods.dataState === "ready" || !apiMethods.dataState ? "ready" : "fallback")
      })
      .catch(() => {
        if (!active) {
          return
        }
        setMethods(emptyMethodCounts(paperMethods))
        setTasks(emptyTaskCounts(paperTasks))
        setPaperItems([])
        setNotice(t(papersCopy.methodApiFallback, locale))
        setStatus("fallback")
      })
    return () => {
      active = false
    }
  }, [locale])

  const methodItems = status === "loading" ? [] : methods
  const taskItems = status === "loading" ? [] : tasks
  const paperItemsForStats = status === "loading" ? [] : paperItems
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
          { label: t(papersCopy.papers, locale), value: paperItemsForStats.length },
          { label: t(papersCopy.tasks, locale), value: taskItems.length }
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
        {status === "loading" ? (
          <p className="text-sm text-[#334155]/60 dark:text-muted-foreground">{t(papersCopy.loadingMethods, locale)}</p>
        ) : null}
        {status !== "loading" && methodItems.length === 0 ? (
          <p className="rounded-md border border-dashed border-border p-6 text-sm text-muted-foreground">
            {t(papersCopy.noPapers, locale)}
          </p>
        ) : null}
        {methodGroups.map((group) => (
          <div key={group.area} className="space-y-3">
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

function emptyTaskCounts(tasks: PaperTask[]): PaperTask[] {
  return tasks.map((task) => ({
    ...task,
    paperCount: 0,
    benchmarkCount: 0,
    methodCount: 0,
    latestPaperIds: [],
    implementationCount: 0
  }))
}

function emptyMethodCounts(methods: PaperMethod[]): PaperMethod[] {
  return methods.map((method) => ({
    ...method,
    paperCount: 0,
    taskCount: 0,
    implementationCount: 0,
    representativePaperIds: [],
    relatedProjectIds: []
  }))
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
      methods: items.sort((left, right) => right.paperCount - left.paperCount || left.name.localeCompare(right.name))
    }))
    .sort((left, right) => {
      const paperDelta =
        right.methods.reduce((total, method) => total + method.paperCount, 0) -
        left.methods.reduce((total, method) => total + method.paperCount, 0)
      return paperDelta || left.area.localeCompare(right.area)
    })
}
