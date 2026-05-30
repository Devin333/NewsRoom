import Link from "next/link"
import { comicSansFont } from "@/lib/fonts"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatWholeNumber, taskName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { Locale, Paper, TaskRef } from "@/lib/papers/types"

export type ProjectDomain = {
  id: string
  slug: string
  name: string
  count: number
}

export function PapersDomainSidebar({
  topDomains,
  projectDomains,
  papers,
  locale
}: {
  topDomains: TaskRef[]
  projectDomains: ProjectDomain[]
  papers: Paper[]
  locale: Locale
}) {
  return (
    <aside className="space-y-9">
      {/* 01/ 论文聚类 — 跳转到 /papers/tasks/{slug} */}
      <PaperDomainPanel
        index="01/"
        title={t(papersCopy.topDomains, locale)}
        domains={topDomains}
        papers={papers}
        locale={locale}
      />
      {/* 02/ 项目聚类 — 跳转到 /projects/collections?tag={slug} */}
      <ProjectDomainPanel
        index="02/"
        title={t(papersCopy.projectDomains, locale)}
        domains={projectDomains}
        locale={locale}
      />
    </aside>
  )
}

function PaperDomainPanel({
  index,
  title,
  domains,
  papers,
  locale
}: {
  index: string
  title: string
  domains: TaskRef[]
  papers: Paper[]
  locale: Locale
}) {
  return (
    <section className="border-t border-[#d7dfd8] pt-5 dark:border-border">
      <p className="text-[0.7rem] font-semibold text-emerald-600">{index}</p>
      <h2 className="mt-2 text-[0.72rem] font-black uppercase tracking-[0.18em] text-[#334155] dark:text-foreground">{title}</h2>
      <div className="mt-5 grid gap-3.5">
        {domains.map((domain) => {
          const paperCount = countPapersForTask(papers, domain.slug)
          const name = taskName(domain, locale)
          return (
            <Link
              key={domain.id}
              href={papersRoutes.taskDetail(domain.slug)}
              className="group flex items-baseline justify-between gap-3 text-base font-semibold text-[#334155]/80 transition-colors hover:text-emerald-700 dark:text-muted-foreground dark:hover:text-foreground"
              style={comicSansFont}
            >
              <span className="leading-5">{name}</span>
              <span className="text-[0.7rem] font-semibold text-[#334155]/52">
                {formatWholeNumber(paperCount, locale)}
              </span>
            </Link>
          )
        })}
      </div>
    </section>
  )
}

function ProjectDomainPanel({
  index,
  title,
  domains,
  locale
}: {
  index: string
  title: string
  domains: ProjectDomain[]
  locale: Locale
}) {
  if (!domains.length) return null
  return (
    <section className="border-t border-[#d7dfd8] pt-5 dark:border-border">
      <p className="text-[0.7rem] font-semibold text-blue-600">{index}</p>
      <h2 className="mt-2 text-[0.72rem] font-black uppercase tracking-[0.18em] text-[#334155] dark:text-foreground">{title}</h2>
      <div className="mt-5 grid gap-3.5">
        {domains.map((domain) => (
          <Link
            key={domain.id}
            href={`/projects/collections?tag=${encodeURIComponent(domain.slug)}`}
            className="group flex items-baseline justify-between gap-3 text-base font-semibold text-[#334155]/80 transition-colors hover:text-blue-700 dark:text-muted-foreground dark:hover:text-foreground"
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
  )
}

export function countPapersForTask(papers: Paper[], taskSlug: string) {
  return papers.filter(
    (paper) => paper.isPublished && (paper.taskRefs ?? []).some((task) => task.slug === taskSlug)
  ).length
}
