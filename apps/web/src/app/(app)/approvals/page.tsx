import { ApprovalTable } from "@/components/approvals/ApprovalTable"
import { EmptyState } from "@/components/common/EmptyState"
import { safeApiGet } from "@/lib/api-client"
import type { ApprovalListResponse } from "@/lib/types"

export default async function ApprovalsPage() {
  const res = await safeApiGet<ApprovalListResponse>("/api/v1/approvals?status=pending")
  const approvals = res.data?.approvals ?? res.data?.items ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-ink">Approvals</h1>
        <p className="mt-0.5 text-sm text-muted">Pending human-in-the-loop decisions</p>
      </div>
      {res.ok && approvals.length ? (
        <ApprovalTable approvals={approvals} />
      ) : (
        <div className="rounded-xl border border-line bg-white p-5 shadow-card">
          <EmptyState title="No pending approvals" message={res.errorMessage} />
        </div>
      )}
    </div>
  )
}
