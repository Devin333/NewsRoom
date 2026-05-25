import type { AdminLang, AdminStatus } from "@/features/admin/types"
import { cn } from "@/lib/utils"

const statusLabels: Record<AdminStatus, { zh: string; en: string }> = {
  ok: { zh: "正常", en: "OK" },
  warning: { zh: "警告", en: "Warning" },
  failed: { zh: "失败", en: "Failed" },
  review: { zh: "复核", en: "Review" },
  running: { zh: "运行中", en: "Running" },
  blocked: { zh: "已阻塞", en: "Blocked" }
}

const statusClasses: Record<AdminStatus, string> = {
  ok: "border-success/30 bg-success/10 text-success",
  warning: "border-warning/30 bg-warning/10 text-warning",
  failed: "border-danger/30 bg-danger/10 text-danger",
  review: "border-info/30 bg-info/10 text-info",
  running: "border-accent/30 bg-accent/10 text-accent",
  blocked: "border-danger/30 bg-danger/10 text-danger"
}

export function StatusPill({ status, lang, className }: { status: AdminStatus; lang: AdminLang; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex min-h-6 items-center rounded-md border px-2 py-0.5 text-xs font-medium",
        statusClasses[status],
        className
      )}
    >
      {statusLabels[status][lang]}
    </span>
  )
}
