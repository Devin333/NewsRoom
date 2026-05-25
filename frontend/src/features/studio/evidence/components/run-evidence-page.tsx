import Link from "next/link"
import { ArrowLeft, CheckCircle2, CircleHelp, FileWarning, Gauge, Route, XCircle } from "lucide-react"
import { Badge } from "@/components/common/badge"
import { Button } from "@/components/ui/button"
import { ClaimSupportTable } from "@/features/studio/evidence/components/claim-support-table"
import { NoticeList } from "@/features/studio/evidence/components/evidence-center-page"
import { LlmTracePanel } from "@/features/studio/evidence/components/llm-trace-panel"
import { QualityLineageGraph } from "@/features/studio/evidence/components/quality-lineage-graph"
import { UnsupportedClaimsPanel } from "@/features/studio/evidence/components/unsupported-claims-panel"
import {
  StudioMetricCard,
  StudioMetricGrid,
  StudioPageHeader
} from "@/features/studio/shared/components/studio-dashboard"
import type { StudioRunEvidenceDetail } from "@/types/evidence"

export function RunEvidencePage({ detail }: { detail: StudioRunEvidenceDetail }) {
  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Evidence Center"
        title={detail.workflowName ?? detail.runId}
        description="Source, evidence, claim, report section, and quality decision lineage for this run."
        actions={
          <Button asChild variant="outline">
            <Link href="/studio/evidence">
              <ArrowLeft className="size-4" />
              Evidence
            </Link>
          </Button>
        }
        meta={
          <>
            <Badge tone={detail.dataState === "ready" ? "success" : detail.dataState === "fallback" ? "info" : "warning"}>{detail.dataState}</Badge>
            {detail.qualityDecision ? <Badge tone={detail.qualityDecision === "blocked" ? "danger" : "neutral"}>{detail.qualityDecision}</Badge> : null}
          </>
        }
      />
      <NoticeList notices={detail.notices} tone={detail.dataState === "ready" ? "success" : "warning"} />

      <StudioMetricGrid className="xl:grid-cols-5 2xl:grid-cols-5">
        <StudioMetricCard label="Run" value={<span className="text-sm">{detail.runId}</span>} detail={detail.reportId ? `Report ${detail.reportId}` : "No report linked"} icon={Route} />
        <StudioMetricCard label="Decision" value={detail.qualityDecision ?? "unknown"} detail={detail.qualityRoute ?? "No quality route"} icon={Gauge} tone={detail.qualityDecision === "blocked" ? "danger" : "accent"} />
        <StudioMetricCard label="Accepted" value={detail.counts.accepted} detail="Supported" icon={CheckCircle2} tone="success" />
        <StudioMetricCard label="Rejected" value={detail.counts.rejected} detail="Rejected" icon={XCircle} tone="danger" />
        <StudioMetricCard label="Unsupported" value={detail.counts.unsupported} detail={`${detail.counts.uncertain} uncertain`} icon={FileWarning} tone={detail.counts.unsupported ? "warning" : "info"} />
      </StudioMetricGrid>

      <StudioMetricGrid className="xl:grid-cols-4 2xl:grid-cols-4">
        <StudioMetricCard label="Quality score" value={detail.qualityScore === undefined ? "none" : `${detail.qualityScore}%`} detail="Report quality" icon={Gauge} tone="accent" />
        <StudioMetricCard label="Uncertain" value={detail.counts.uncertain} detail="Needs review" icon={CircleHelp} tone="warning" />
        <StudioMetricCard label="Rejected" value={detail.counts.rejected} detail="Not usable" icon={XCircle} tone="danger" />
        <StudioMetricCard label="Claims" value={detail.claims.length} detail="Rendered in support table" icon={Route} />
      </StudioMetricGrid>

      <QualityLineageGraph claims={detail.claims} />
      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ClaimSupportTable claims={detail.claims} />
        <div className="space-y-4">
          <UnsupportedClaimsPanel claims={detail.claims} />
          <LlmTracePanel trace={detail.llmTrace} />
        </div>
      </section>
    </main>
  )
}
