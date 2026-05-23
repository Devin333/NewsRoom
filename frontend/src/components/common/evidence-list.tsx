import { EmptyState } from "@/components/common/empty-state";
import { EvidenceCard } from "@/components/common/evidence-card";
import type { Evidence } from "@/types/evidence";

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (!evidence.length) {
    return <EmptyState title="暂无证据" description="这个模块尚未收到支撑证据。" />;
  }

  return (
    <div className="space-y-3">
      {evidence.map((item) => (
        <EvidenceCard key={item.id} evidence={item} />
      ))}
    </div>
  );
}
