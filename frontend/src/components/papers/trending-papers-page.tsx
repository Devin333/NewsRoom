"use client"

import { useState } from "react"
import { PapersDomainSidebar } from "@/components/papers/papers-domain-sidebar"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { PaperDetailDrawer } from "@/components/papers/shared/paper-detail-drawer"
import { PaperStream } from "@/components/papers/shared/paper-stream"
import { papersCopy, t } from "@/lib/papers/copy"
import { paperTasks, topDomains, trendingDomains } from "@/lib/papers/catalog"
import type { Locale, Paper } from "@/lib/papers/types"

export function TrendingPapersPage({ locale, papers }: { locale: Locale; papers: Paper[] }) {
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null)

  function previewPaper(paper: Paper) {
    setSelectedPaper(paper)
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
          { label: t(papersCopy.papers, locale), value: papers.length },
          { label: t(papersCopy.tasks, locale), value: paperTasks.length },
          { label: t(papersCopy.repositories, locale), value: papers.filter((paper) => paper.repoUrl).length }
        ]}
      />
      <div className="mt-8 grid gap-12 xl:grid-cols-[15rem_minmax(0,1fr)] 2xl:grid-cols-[16rem_minmax(0,1fr)] 2xl:gap-16">
        <PapersDomainSidebar topDomains={topDomains} trendingDomains={trendingDomains} papers={papers} locale={locale} />
        <PaperStream papers={papers} locale={locale} title="" onPreview={previewPaper} />
      </div>
      <PaperDetailDrawer
        paper={selectedPaper}
        locale={locale}
        open={Boolean(selectedPaper)}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedPaper(null)
          }
        }}
      />
    </div>
  )
}
