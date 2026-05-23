import { CredibilityBadge, ExternalTextLink, SourceBadge } from "@/components/common/badges";
import { ScoreMeter } from "@/components/common/score-meter";
import { formatDateTime } from "@/lib/format";
import type { Evidence } from "@/types/evidence";

export function EvidenceCard({ evidence }: { evidence: Evidence }) {
  return (
    <article className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{evidence.title}</h3>
          <p className="mt-1 text-xs text-muted-foreground">捕获于 {formatDateTime(evidence.capturedAt)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <SourceBadge sourceName={evidence.sourceName} sourceType={evidence.sourceType} />
          <CredibilityBadge credibility={evidence.credibility} />
        </div>
      </div>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">{evidence.quote ?? evidence.summary}</p>
      <p className="mt-3 rounded-md border border-border bg-background/70 p-3 text-xs text-muted-foreground">{evidence.relationReason}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
        <ScoreMeter label="置信度" value={evidence.confidenceScore ?? 0} />
        <ExternalTextLink href={evidence.originalUrl ?? evidence.sourceUrl ?? "#"}>原始来源</ExternalTextLink>
      </div>
    </article>
  );
}
