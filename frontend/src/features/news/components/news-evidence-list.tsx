import { ExternalLink } from "lucide-react"
import { CredibilityBadge } from "@/components/common/credibility-badge"
import { SourceBadge } from "@/components/common/source-badge"
import { formatDateTime } from "@/lib/format"
import type { EvidenceItem } from "@/types/evidence"

export function NewsEvidenceList({ evidence }: { evidence: EvidenceItem[] }) {
  return (
    <section className="rounded-md border border-[#dbe3dc] bg-white/85 p-5 dark:border-border dark:bg-card">
      <h2 className="text-lg font-semibold text-[#334155] dark:text-foreground">Evidence</h2>
      {evidence.length ? (
        <div className="mt-4 space-y-3">
          {evidence.map((item) => (
            <article key={item.id} className="rounded-md border border-[#edf1ed] bg-[#f7f9f6] p-4 dark:border-border dark:bg-background/60">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-[#334155] dark:text-foreground">{item.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-[#334155]/68 dark:text-muted-foreground">{item.summary}</p>
                </div>
                {item.originalUrl || item.sourceUrl ? (
                  <a
                    href={item.originalUrl ?? item.sourceUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-[#dbe3dc] text-[#334155]/60 hover:bg-white hover:text-[#334155] dark:border-border dark:text-muted-foreground"
                    aria-label="Open original evidence source"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </a>
                ) : null}
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <SourceBadge name={item.sourceName} type={item.sourceType} />
                <CredibilityBadge value={item.credibility} />
                <span className="text-xs text-[#334155]/55 dark:text-muted-foreground">Captured {formatDateTime(item.capturedAt)}</span>
              </div>
              <p className="mt-3 text-xs leading-5 text-[#334155]/60 dark:text-muted-foreground">Relation: {item.relationReason}</p>
            </article>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-sm text-[#334155]/60 dark:text-muted-foreground">No evidence is linked to this news item yet.</p>
      )}
    </section>
  )
}
