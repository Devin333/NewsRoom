import { PortalHomePage } from "@/features/portal/portal-home-page"
import { getPortalHomeData } from "@/features/portal/portal-home-data"

export const dynamic = "force-dynamic"

export default async function HomePage() {
  const data = await getPortalHomeData()
  return <PortalHomePage data={data} />
}
