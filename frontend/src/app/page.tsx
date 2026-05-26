import { DashboardHomePage } from "@/features/dashboard/components/dashboard-home-page"
import { StudioShell } from "@/features/studio/shared/components/studio-shell"
import { getFrontendSurface } from "@/lib/frontend-surface"

export const dynamic = "force-dynamic"

export default function HomePage() {
  if (getFrontendSurface() === "admin") {
    return (
      <StudioShell>
        <DashboardHomePage />
      </StudioShell>
    )
  }

  return <DashboardHomePage />
}
