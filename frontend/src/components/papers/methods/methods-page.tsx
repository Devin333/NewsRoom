"use client"

import { useEffect, useState } from "react"
import { MethodCard } from "@/components/papers/methods/method-card"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { papersCopy, t } from "@/lib/papers/copy"
import { papers, paperMethods, paperTasks } from "@/lib/papers/catalog"
import { fetchPaperMethods, fetchPaperTasks, fetchPapers } from "@/lib/papers/api"
import type { Locale, Paper, PaperMethod, PaperTask } from "@/lib/papers/types"

export function MethodsPage({ locale }: { locale: Locale }) {
  const [methods, setMethods] = useState<PaperMethod[]>([])
  const [tasks, setTasks] = useState<PaperTask[]>([])
  const [paperItems, setPaperItems] = useState<Paper[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">("loading")
  const [fallbackNoticeVisible, setFallbackNoticeVisible] = useState(true)

  useEffect(() => {
    let active = true
    Promise.all([fetchPaperMethods(), fetchPaperTasks(), fetchPapers({ limit: 1000, period: "all" })])
      .then(([apiMethods, apiTasks, apiPapers]) => {
        if (!active) {
          return
        }
        setMethods(apiMethods)
        setTasks(apiTasks)
        setPaperItems(apiPapers.papers)
        setStatus("ready")
      })
      .catch(() => {
        if (!active) {
          return
        }
        setMethods(paperMethods)
        setTasks(paperTasks)
        setPaperItems(papers)
        setStatus("fallback")
      })
    return () => {
      active = false
    }
  }, [])

  const methodItems = status === "loading" ? [] : methods
  const taskItems = status === "loading" ? [] : tasks
  const paperItemsForStats = status === "loading" ? [] : paperItems

  return (
    <div className="space-y-6">
      <PapersMicrobar items={[{ label: "Methods" }]} meta={t(papersCopy.methodBranch, locale)} locale={locale} />
      <PapersHero
        eyebrow="Papers / Methods"
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
          message={fallbackNoticeVisible ? "Paper method API is unavailable; showing local catalog fallback." : null}
          locale={locale}
          onDismiss={() => setFallbackNoticeVisible(false)}
        />
      ) : null}
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {status === "loading" ? (
          <p className="text-sm text-[#334155]/60 dark:text-muted-foreground">Loading paper methods...</p>
        ) : null}
        {methodItems.map((method) => (
          <MethodCard key={method.id} method={method} locale={locale} />
        ))}
      </section>
    </div>
  )
}
