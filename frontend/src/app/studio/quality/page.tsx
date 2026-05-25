import { QualityGatePage } from "@/features/studio/quality/components/quality-gate-page"
import { getQualityDashboard } from "@/features/studio/quality/api/quality-gate-api"

export default async function StudioQualityPage() {
  const dashboard = await getQualityDashboard()
  return <QualityGatePage dashboard={dashboard} />
}
