import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { ClaimSupportTable } from "@/features/studio/evidence/components/claim-support-table"
import type { StudioClaimEvidence } from "@/types/evidence"

const claims: StudioClaimEvidence[] = [
  {
    claimId: "claim-accepted",
    claimText: "Accepted claim",
    status: "accepted",
    sourceRefs: [{ url: "https://example.com/a" }],
    evidenceRefs: [{ evidenceId: "ev-a" }],
    reportSection: "Summary"
  },
  {
    claimId: "claim-rejected",
    claimText: "Rejected claim",
    status: "rejected",
    sourceRefs: [],
    evidenceRefs: [],
    failureReason: "Contradicted"
  },
  {
    claimId: "claim-uncertain",
    claimText: "Uncertain claim",
    status: "uncertain",
    sourceRefs: [],
    evidenceRefs: []
  },
  {
    claimId: "claim-unsupported",
    claimText: "Unsupported claim",
    status: "unsupported",
    sourceRefs: [],
    evidenceRefs: [],
    reportSection: "Market"
  }
]

describe("ClaimSupportTable", () => {
  it("renders all claim statuses", () => {
    render(<ClaimSupportTable claims={claims} />)

    expect(screen.getAllByText("已接受").length).toBeGreaterThan(0)
    expect(screen.getAllByText("已拒绝").length).toBeGreaterThan(0)
    expect(screen.getAllByText("不确定").length).toBeGreaterThan(0)
    expect(screen.getAllByText("未支撑").length).toBeGreaterThan(0)
  })

  it("filters unsupported claims", () => {
    render(<ClaimSupportTable claims={claims} />)

    fireEvent.click(screen.getByRole("button", { name: "未支撑" }))

    expect(screen.getByText("Unsupported claim")).toBeInTheDocument()
    expect(screen.queryByText("Accepted claim")).not.toBeInTheDocument()
    expect(screen.queryByText("Rejected claim")).not.toBeInTheDocument()
  })

  it("renders missing source, evidence, and section states", () => {
    render(<ClaimSupportTable claims={[claims[1]]} />)

    expect(screen.getByText("暂无来源")).toBeInTheDocument()
    expect(screen.getByText("暂无证据")).toBeInTheDocument()
    expect(screen.getByText("暂无章节")).toBeInTheDocument()
  })
})
