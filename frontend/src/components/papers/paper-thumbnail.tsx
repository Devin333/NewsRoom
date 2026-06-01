import { FileSearch } from "lucide-react"
import { PdfPageThumbnail } from "@/components/papers/pdf-page-thumbnail"
import { translate } from "@/lib/i18n"
import { paperPdfUrl } from "@/lib/papers/format"
import type { Locale, Paper } from "@/lib/papers/types"

export function PaperThumbnail({ paper, locale }: { paper: Paper; locale: Locale }) {
  const pdfUrl = paperPdfUrl(paper)

  if (paper.thumbnailUrl) {
    return (
      <div
        aria-hidden="true"
        className="h-44 w-32 rounded-sm border border-[#d6d2c8] bg-contain bg-center bg-no-repeat shadow-[0_8px_20px_rgba(15,23,42,0.10)]"
        style={{ backgroundImage: `url(${paper.thumbnailUrl})` }}
      />
    )
  }

  if (pdfUrl) {
    return (
      <PdfPageThumbnail
        pdfUrl={pdfUrl}
        title={paper.title}
        locale={locale}
        className="h-44 w-32 shrink-0 overflow-hidden rounded-sm border border-[#d6d2c8] bg-white shadow-[0_8px_20px_rgba(15,23,42,0.10)] transition-transform group-hover:-translate-y-0.5 dark:border-border dark:bg-white"
      />
    )
  }

  return (
    <div className="relative h-44 w-32 shrink-0 overflow-hidden rounded-sm border border-[#d6d2c8] bg-[#fbfaf6] shadow-[0_8px_20px_rgba(15,23,42,0.08)] dark:border-border dark:bg-card">
      <div className="absolute inset-x-0 top-0 h-8 bg-[#eef6f1]" />
      <div className="flex h-full flex-col px-4 pb-4 pt-12">
        <FileSearch className="size-7 text-slate-400" />
        <div className="mt-5 space-y-2">
          <span className="block h-1.5 w-20 rounded-full bg-slate-200 dark:bg-slate-700" />
          <span className="block h-1.5 w-24 rounded-full bg-slate-200 dark:bg-slate-700" />
          <span className="block h-1.5 w-16 rounded-full bg-slate-200 dark:bg-slate-700" />
        </div>
        <p className="mt-auto text-[0.62rem] font-semibold uppercase tracking-[0.14em] text-slate-400">
          {translate(locale, "papers.reader.noVerifiedPdf")}
        </p>
      </div>
    </div>
  )
}
