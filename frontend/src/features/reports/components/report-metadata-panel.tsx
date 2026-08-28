import { Badge, QualityBadge } from "@/components/common/badges";
import { formatDate, titleCase } from "@/lib/format";
import type { Report } from "@/types/report";

export function ReportMetadataPanel({ report }: { report: Report }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-base font-semibold text-foreground">元数据</h2>
      <div className="mt-4 space-y-3 text-sm">
        <Row label="类型" value={<Badge tone="accent">{titleCase(report.reportType ?? report.type ?? "report")}</Badge>} />
        <Row label="状态" value={<Badge tone={report.status === "published" ? "good" : "info"}>{titleCase(report.status)}</Badge>} />
        <Row label="生成时间" value={formatDate(report.generatedAt)} />
        <Row label="覆盖范围" value={`${formatDate(report.coveredFrom)} - ${formatDate(report.coveredTo)}`} />
        <Row label="智能体" value={report.agentName ?? "Agora Hub 智能体"} />
        <Row label="主题" value={String(report.topicIds?.length ?? 0)} />
        <Row label="新闻" value={String(report.newsItemIds?.length ?? 0)} />
        <Row label="证据" value={String(report.evidenceIds?.length ?? 0)} />
        <QualityBadge score={report.qualityScore ?? 0} />
      </div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border pb-2 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium text-foreground">{value}</span>
    </div>
  );
}
