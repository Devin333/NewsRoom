import { ApprovalTable } from "@/components/approvals/ApprovalTable"
import { ErrorState } from "@/components/common/ErrorState"
import { safeApiGet } from "@/lib/api-client"
import type { ApprovalListResponse } from "@/lib/types"

export default async function ApprovalsPage() {
  const approvals = await safeApiGet<ApprovalListResponse>("/api/v1/approvals?status=pending")
  const rows = approvals.data?.approvals ?? approvals.data?.items ?? []

  return (
    <main className="space-y-6">
      <header className="border-b border-line pb-4">
        <h1 className="text-2xl font-semibold text-ink">Approvals</h1>
        <p className="text-sm text-muted">Pending human approvals with explicit approve and reject actions.</p>
      </header>

      {approvals.ok ? (
        <ApprovalTable approvals={rows} />
      ) : (
        <ErrorState message={approvals.errorMessage} requestId={approvals.requestId} />
      )}
    </main>
  )
}
