"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { PapersDomainSidebar } from "@/components/papers/papers-domain-sidebar"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { PaperDetailDrawer } from "@/components/papers/shared/paper-detail-drawer"
import { PaperPeriodTabs } from "@/components/papers/shared/paper-period-tabs"
import { PaperStream } from "@/components/papers/shared/paper-stream"
import { Button } from "@/components/ui/button"
import { comicSansFont } from "@/lib/fonts"
import { fetchPapers } from "@/lib/papers/api"
import { papersCopy, t } from "@/lib/papers/copy"
import { buildPaperPortalMetrics, deriveTopPaperDomains, deriveTrendingPaperDomains } from "@/lib/papers/metrics"
import type { Locale, Paper, PaperPeriod, PaperSort } from "@/lib/papers/types"

const PAPER_DASHBOARD_LIMIT = 5000
const PAPER_PAGE_SIZE = 15

export function TrendingPapersPage({ locale, papers }: { locale: Locale; papers: Paper[] }) {
  const router = useRouter()
  const routerReplace = router.replace
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const searchText = searchParams.toString()
  const period = parsePeriod(searchParams.get("period"))
  const sort = parseSort(searchParams.get("sort"))
  const page = parsePage(searchParams.get("page"))
  const query = searchParams.get("q") ?? ""
  const deepLinkedPaperId = searchParams.get("paper")
  const [dashboardPapers, setDashboardPapers] = useState(papers)
  const [visiblePapers, setVisiblePapers] = useState(papers.slice(0, PAPER_PAGE_SIZE))
  const [paperTotalCount, setPaperTotalCount] = useState(papers.filter((paper) => paper.isPublished !== false).length)
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(deepLinkedPaperId)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pageOffset = (page - 1) * PAPER_PAGE_SIZE
  const portalMetrics = useMemo(
    () => buildPaperPortalMetrics(dashboardPapers, paperTotalCount),
    [dashboardPapers, paperTotalCount]
  )
  const topDomains = useMemo(() => deriveTopPaperDomains(dashboardPapers), [dashboardPapers])
  const trendingDomains = useMemo(() => deriveTrendingPaperDomains(dashboardPapers), [dashboardPapers])
  const selectedPaper = useMemo(
    () =>
      visiblePapers.find((paper) => paper.id === selectedPaperId || paper.slug === selectedPaperId) ??
      dashboardPapers.find((paper) => paper.id === selectedPaperId || paper.slug === selectedPaperId) ??
      null,
    [dashboardPapers, selectedPaperId, visiblePapers]
  )
  const updateQuery = useCallback((updates: Record<string, string | null>) => {
    const nextParams = new URLSearchParams(searchText)
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === "") {
        nextParams.delete(key)
      } else {
        nextParams.set(key, value)
      }
    }
    const nextQuery = nextParams.toString()
    routerReplace(nextQuery ? `${pathname}?${nextQuery}` : pathname, { scroll: false })
  }, [pathname, routerReplace, searchText])
  const updatePage = useCallback((nextPage: number) => {
    updateQuery({ page: nextPage <= 1 ? null : String(nextPage), paper: null })
  }, [updateQuery])

  useEffect(() => {
    setSelectedPaperId(deepLinkedPaperId)
  }, [deepLinkedPaperId])

  useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    setError(null)
    Promise.all([
      fetchPapers({ q: query, period, sort, limit: PAPER_PAGE_SIZE, offset: pageOffset }),
      fetchPapers({ q: query, period, sort, limit: PAPER_DASHBOARD_LIMIT })
    ])
      .then(([pageResult, dashboardResult]) => {
        if (!cancelled) {
          setVisiblePapers(pageResult.papers)
          setDashboardPapers(dashboardResult.papers)
          setPaperTotalCount(pageResult.total_count)
          const nextTotalPages = Math.max(1, Math.ceil(pageResult.total_count / PAPER_PAGE_SIZE))
          if (pageResult.total_count > 0 && page > nextTotalPages) {
            updatePage(nextTotalPages)
          }
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setVisiblePapers(papers.slice(pageOffset, pageOffset + PAPER_PAGE_SIZE))
          setDashboardPapers(papers)
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
  }, [page, pageOffset, papers, period, query, sort, updatePage])

  function previewPaper(paper: Paper) {
    updateQuery({ paper: paper.id })
  }

  function updatePeriod(nextPeriod: PaperPeriod) {
    updateQuery({ period: nextPeriod === "all" ? null : nextPeriod, page: null, paper: null })
  }

  function periodHref(nextPeriod: PaperPeriod) {
    const nextParams = new URLSearchParams(searchText)
    nextParams.delete("paper")
    nextParams.delete("page")
    if (nextPeriod === "all") {
      nextParams.delete("period")
    } else {
      nextParams.set("period", nextPeriod)
    }
    const nextQuery = nextParams.toString()
    return nextQuery ? `${pathname}?${nextQuery}` : pathname
  }

  function updateSort(nextSort: PaperSort) {
    updateQuery({ sort: nextSort === "trending" ? null : nextSort, page: null, paper: null })
  }

  function closeDrawer() {
    updateQuery({ paper: null })
  }

  function closeDrawerHref() {
    const nextParams = new URLSearchParams(searchText)
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
          <PaperPagination
            currentPage={page}
            totalCount={paperTotalCount}
            pageSize={PAPER_PAGE_SIZE}
            visibleCount={visiblePapers.length}
            locale={locale}
            onPageChange={updatePage}
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

function parsePage(value: string | null): number {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1
}

function PaperPagination({
  currentPage,
  totalCount,
  pageSize,
  visibleCount,
  locale,
  onPageChange
}: {
  currentPage: number
  totalCount: number
  pageSize: number
  visibleCount: number
  locale: Locale
  onPageChange: (page: number) => void
}) {
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  if (totalPages <= 1) {
    return null
  }

  const safePage = Math.min(Math.max(currentPage, 1), totalPages)
  const start = totalCount === 0 || visibleCount === 0 ? 0 : Math.min((safePage - 1) * pageSize + 1, totalCount)
  const end = visibleCount === 0 ? 0 : Math.min(start + visibleCount - 1, totalCount)
  const pages = paginationRange(safePage, totalPages)
  const previousLabel = locale === "zh" ? "上一页" : "Previous page"
  const nextLabel = locale === "zh" ? "下一页" : "Next page"
  const rangeLabel =
    locale === "zh"
      ? `第 ${start}-${end} 篇，共 ${totalCount} 篇`
      : `${start}-${end} of ${totalCount} papers`

  return (
    <nav
      aria-label={locale === "zh" ? "论文分页" : "Paper pagination"}
      className="flex flex-col gap-3 border-t border-[#d8dfd8] py-6 sm:flex-row sm:items-center sm:justify-between dark:border-border"
      style={comicSansFont}
    >
      <p className="text-xs font-medium text-[#334155]/62 dark:text-muted-foreground">{rangeLabel}</p>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="size-8 bg-white dark:bg-card"
          aria-label={previousLabel}
          disabled={safePage <= 1}
          onClick={() => onPageChange(safePage - 1)}
        >
          <ChevronLeft className="size-4" aria-hidden="true" />
        </Button>
        {pages.map((item) =>
          typeof item === "number" ? (
            <Button
              key={item}
              type="button"
              variant={item === safePage ? "default" : "outline"}
              size="sm"
              className="h-8 min-w-8 px-2"
              aria-label={locale === "zh" ? `第 ${item} 页` : `Page ${item}`}
              aria-current={item === safePage ? "page" : undefined}
              onClick={() => onPageChange(item)}
            >
              {item}
            </Button>
          ) : (
            <span key={item} className="flex h-8 min-w-8 items-center justify-center text-xs text-[#334155]/45">
              ...
            </span>
          )
        )}
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="size-8 bg-white dark:bg-card"
          aria-label={nextLabel}
          disabled={safePage >= totalPages}
          onClick={() => onPageChange(safePage + 1)}
        >
          <ChevronRight className="size-4" aria-hidden="true" />
        </Button>
      </div>
    </nav>
  )
}

function paginationRange(currentPage: number, totalPages: number): Array<number | string> {
  const pages = new Set<number>([1, totalPages])
  for (let page = currentPage - 1; page <= currentPage + 1; page += 1) {
    if (page >= 1 && page <= totalPages) {
      pages.add(page)
    }
  }
  const sorted = Array.from(pages).sort((left, right) => left - right)
  const range: Array<number | string> = []
  for (const page of sorted) {
    const previous = range[range.length - 1]
    if (typeof previous === "number" && page - previous > 1) {
      range.push(`ellipsis-${previous}-${page}`)
    }
    range.push(page)
  }
  return range
}
