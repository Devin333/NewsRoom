"use client"

import { useState } from "react"
import { PapersDomainSidebar } from "@/components/papers/papers-domain-sidebar"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { PaperStream } from "@/components/papers/shared/paper-stream"
import { papersCopy, t } from "@/lib/papers/copy"
import { topDomains, trendingDomains } from "@/lib/papers/mock-data"
import type { Locale, Paper } from "@/lib/papers/types"

export function TrendingPapersPage({ locale, papers }: { locale: Locale; papers: Paper[] }) {
  const [notice, setNotice] = useState<string | null>(null)

  function previewPaper(paper: Paper) {
    setNotice(`${paper.title}: ${t(papersCopy.paperPreview, locale)}`)
  }

  return (
    <div className="space-y-0">
      <PapersMicrobar
        items={[{ label: "Trending" }]}
        meta={t(papersCopy.frontendView, locale)}
        locale={locale}
      />
      <PapersHero
        eyebrow="Papers / Trending"
        title={t(papersCopy.researchPapers, locale)}
        subtitle={t(papersCopy.researchSubtitle, locale)}
        variant="editorial"
        stats={[
          { label: t(papersCopy.papers, locale), value: "2.4k" },
          { label: t(papersCopy.repositories, locale), value: "1.1k" },
          { label: t(papersCopy.tasks, locale), value: "318" }
        ]}
      />
      <InlineNotice message={notice} locale={locale} onDismiss={() => setNotice(null)} />
      <div className="mt-6 grid gap-7 xl:grid-cols-[15rem_minmax(0,1fr)]">
        <PapersDomainSidebar topDomains={topDomains} trendingDomains={trendingDomains} locale={locale} />
        <PaperStream papers={papers} locale={locale} title="" onPreview={previewPaper} />
      </div>
    </div>
  )
}
