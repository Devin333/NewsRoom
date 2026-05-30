import Link from "next/link"
import { comicSansFont } from "@/lib/fonts"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatWholeNumber, taskName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { ProjectCategoryDomain } from "@/lib/papers/metrics"
import type { Locale, Paper, TaskRef } from "@/lib/papers/types"

export function PapersDomainSidebar({
  topDomains,
  projectDomains,
  papers,
  locale,
}: {
  topDomains: TaskRef[]
  projectDomains: ProjectCategoryDomain[]
  papers: Paper[]
  locale: Locale
}) {
  return (
    <aside className="space-y-9">
      {/* 01/ 论文研究方向 */}
      <section className="border-t border-[#d7dfd8] pt-5 dark:border-border">
        <p className="text-[0.7rem] font-semibold text-emerald-600">01/</p>
        <h2 className="mt-2 text-[0.72rem] font-black uppercase tracking-[0.18em] text-[#334155] dark:text-foreground">
          {t(papersCopy.topDomains, locale)}
        </h2>
        <div className="mt-5 grid gap-3.5">
          {topDomains.map((domain) => {
            const count = papers.filter(
              (p) => p.isPublished && (p.taskRefs ?? []).some((r) => r.slug === domain.slug)
            ).length
            return (
              <Link
                key={domain.id}
                href={papersRoutes.taskDetail(domain.slug)}
                className="flex items-baseline justify-between gap-3 text-base font-semibold text-[#334155]/80 transition-colors hover:text-emerald-700 dark:text-muted-foreground dark:hover:text-foreground"
                style={comicSansFont}
              >
                <span className="leading-5">{taskName(domain, locale)}</span>
                <span className="text-[0.7rem] font-semibold text-[#334155]/52">
                  {formatWholeNumber(count, locale)}
                </span>
              </Link>
            )
          })}
        </div>
      </section>

      {/* 02/ 项目技术方向 */}
      {projectDomains.length > 0 && (
        <section className="border-t border-[#d7dfd8] pt-5 dark:border-border">
          <p className="text-[0.7rem] font-semibold text-sky-600">02/</p>
          <h2 className="mt-2 text-[0.72rem] font-black uppercase tracking-[0.18em] text-[#334155] dark:text-foreground">
            {t(papersCopy.projectDomains, locale)}
          </h2>
          <div className="mt-5 grid gap-3.5">
            {projectDomains.map((domain) => (
              <Link
                key={domain.slug}
                href={`/projects/hot?category=${encodeURIComponent(domain.slug)}`}
                className="flex items-baseline justify-between gap-3 text-base font-semibold text-[#334155]/80 transition-colors hover:text-sky-700 dark:text-muted-foreground dark:hover:text-foreground"
                style={comicSansFont}
              >
                <span className="leading-5">{domain.name}</span>
                <span className="text-[0.7rem] font-semibold text-[#334155]/52">
                  {formatWholeNumber(domain.count, locale)}
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </aside>
  )
}

// keep for tests that import this
export function countPapersForTask(papers: Paper[], taskSlug: string) {
  return papers.filter(
    (p) => p.isPublished && (p.taskRefs ?? []).some((r) => r.slug === taskSlug)
  ).length
}
