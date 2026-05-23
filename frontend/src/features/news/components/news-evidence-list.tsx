import { ExternalLink } from "lucide-react"
import { CredibilityBadge } from "@/components/common/credibility-badge"
import { SourceBadge } from "@/components/common/source-badge"
import { formatDateTime } from "@/lib/format"
import type { EvidenceItem } from "@/types/evidence"

export function NewsEvidenceList({ evidence }: { evidence: EvidenceItem[] }) {
  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <h2 className="text-lg font-semibold text-foreground">证据</h2>
      {evidence.length ? (
        <div className="mt-4 space-y-3">
          {evidence.map((item) => (
            <article key={item.id} className="rounded-md border border-border bg-background/40 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-foreground">{item.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.summary}</p>
                </div>
                {item.originalUrl || item.sourceUrl ? (
                  <a
                    href={item.originalUrl ?? item.sourceUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-secondary hover:text-foreground"
                    aria-label="打开原始证据来源"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </a>
                ) : null}
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <SourceBadge name={item.sourceName} type={item.sourceType} />
                <CredibilityBadge value={item.credibility} />
                <span className="text-xs text-muted-foreground">捕获于 {formatDateTime(item.capturedAt)}</span>
              </div>
              <p className="mt-3 text-xs leading-5 text-muted-foreground">关联原因：{item.relationReason}</p>
            </article>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">这条新闻尚未关联证据。</p>
      )}
    </section>
  )
}
