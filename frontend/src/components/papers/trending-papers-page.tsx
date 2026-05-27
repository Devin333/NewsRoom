"use client"

import { useEffect, useMemo, useState } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { PapersDomainSidebar } from "@/components/papers/papers-domain-sidebar"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { PaperDetailDrawer } from "@/components/papers/shared/paper-detail-drawer"
import { PaperPeriodTabs } from "@/components/papers/shared/paper-period-tabs"
import { PaperStream } from "@/components/papers/shared/paper-stream"
import { fetchPapers } from "@/lib/papers/api"
import { papersCopy, t } from "@/lib/papers/copy"
import { buildPaperPortalMetrics, deriveTopPaperDomains, deriveTrendingPaperDomains } from "@/lib/papers/metrics"
import type { Locale, Paper, PaperPeriod, PaperSort } from "@/lib/papers/types"

const PAPER_DASHBOARD_LIMIT = 5000

export function TrendingPapersPage({ locale, papers }: { locale: Locale; papers: Paper[] }) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const period = parsePeriod(searchParams.get("period"))
  const sort = parseSort(searchParams.get("sort"))
  const query = searchParams.get("q") ?? ""
  const deepLinkedPaperId = searchParams.get("paper")
  const [visiblePapers, setVisiblePapers] = useState(papers)
  const [paperTotalCount, setPaperTotalCount] = useState(papers.filter((paper) => paper.isPublished !== false).length)
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(deepLinkedPaperId)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const portalMetrics = useMemo(
    () => buildPaperPortalMetrics(visiblePapers, paperTotalCount),
    [paperTotalCount, visiblePapers]
  )
  const topDomains = useMemo(() => deriveTopPaperDomains(visiblePapers), [visiblePapers])
  const trendingDomains = useMemo(() => deriveTrendingPaperDomains(visiblePapers), [visiblePapers])
  const selectedPaper = useMemo(
    () => visiblePapers.find((paper) => paper.id === selectedPaperId || paper.slug === selectedPaperId) ?? null,
    [selectedPaperId, visiblePapers]
  )

  useEffect(() => {
    setSelectedPaperId(deepLinkedPaperId)
  }, [deepLinkedPaperId])

  useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    setError(null)
    fetchPapers({ q: query, period, sort, limit: PAPER_DASHBOARD_LIMIT })
      .then((result) => {
        if (!cancelled) {
          setVisiblePapers(result.papers)
          setPaperTotalCount(result.total_count)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setVisiblePapers(papers)
          setPaperTotalCount(papers.filter((paper) => paper.isPublished !== false).length)
          setError(requestError instanceof Error ? requestError.message : "Papers request failed")
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [papers, period, query, sort])

  function previewPaper(paper: Paper) {
    updateQuery({ paper: paper.id })
  }

  function updatePeriod(nextPeriod: PaperPeriod) {
    updateQuery({ period: nextPeriod === "all" ? null : nextPeriod, paper: null })
  }

  function periodHref(nextPeriod: PaperPeriod) {
    const nextParams = new URLSearchParams(searchParams.toString())
    nextParams.delete("paper")
    if (nextPeriod === "all") {
      nextParams.delete("period")
    } else {
      nextParams.set("period", nextPeriod)
    }
    const nextQuery = nextParams.toString()
    return nextQuery ? `${pathname}?${nextQuery}` : pathname
  }

  function updateSort(nextSort: PaperSort) {
    updateQuery({ sort: nextSort === "trending" ? null : nextSort, paper: null })
  }

  function updateQuery(updates: Record<string, string | null>) {
    const nextParams = new URLSearchParams(searchParams.toString())
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === "") {
        nextParams.delete(key)
      } else {
        nextParams.set(key, value)
      }
    }
    const nextQuery = nextParams.toString()
    router.replace(nextQuery ? `${pathname}?${nextQuery}` : pathname, { scroll: false })
  }

  function closeDrawer() {
    updateQuery({ paper: null })
  }

  function closeDrawerHref() {
    const nextParams = new URLSearchParams(searchParams.toString())
    nextParams.delete("paper")
    const nextQuery = nextParams.toString()
    return nextQuery ? `${pathname}?${nextQuery}` : pathname
  }

  return (
    <div className="space-y-0">
      <PapersMicrobar
        items={[{ label: "Trending" }]}
        meta={t(papersCopy.frontendView, locale)}
        locale={locale}
      />
      <PapersHero
        title={t(papersCopy.researchPapers, locale)}
        subtitle={t(papersCopy.researchSubtitle, locale)}
        variant="editorial"
        stats={[
          { label: t(papersCopy.papers, locale), value: portalMetrics.paperCount },
          { label: t(papersCopy.tasks, locale), value: portalMetrics.taskCount },
          { label: t(papersCopy.repositories, locale), value: portalMetrics.repositoryCount }
        ]}
        aside={<PaperPeriodTabs value={period} locale={locale} hrefForPeriod={periodHref} onChange={updatePeriod} fullWidth />}
      />
      <div className="mt-6 border-t border-[#d7dfd8] dark:border-border" />
      {error ? (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {t(papersCopy.apiUnavailableCache, locale)}
          {error}
        </div>
      ) : null}
      <div className="mt-8 grid gap-12 xl:grid-cols-[15rem_minmax(0,1fr)] 2xl:grid-cols-[16rem_minmax(0,1fr)] 2xl:gap-16">
        <PapersDomainSidebar topDomains={topDomains} trendingDomains={trendingDomains} papers={visiblePapers} locale={locale} />
        <div className="space-y-3">
          {isLoading ? (
            <p className="text-sm text-[#334155]/55 dark:text-muted-foreground">
              {t(papersCopy.updatingPapers, locale)}
            </p>
          ) : null}
          <PaperStream
            papers={visiblePapers}
            locale={locale}
            title=""
            sort={sort}
            onSortChange={updateSort}
            onPreview={previewPaper}
          />
        </div>
      </div>
      <PaperDetailDrawer
        paper={selectedPaper}
        paperId={selectedPaperId}
        locale={locale}
        open={Boolean(selectedPaperId)}
        closeHref={closeDrawerHref()}
        onOpenChange={(open) => {
          if (!open) {
            closeDrawer()
          }
        }}
      />
    </div>
  )
}

function parsePeriod(value: string | null): PaperPeriod {
  return value === "daily" || value === "weekly" || value === "monthly" || value === "all" ? value : "all"
}

function parseSort(value: string | null): PaperSort {
  return value === "newest" || value === "most_cited" || value === "trending" ? value : "trending"
}
