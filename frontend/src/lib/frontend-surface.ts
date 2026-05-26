export const FRONTEND_SURFACES = ["portal", "admin"] as const

export type FrontendSurface = (typeof FRONTEND_SURFACES)[number]

export function resolveFrontendSurface(value = process.env.NEWSROOM_FRONTEND_SURFACE): FrontendSurface {
  return value === "admin" ? "admin" : "portal"
}

export function getFrontendSurface(): FrontendSurface {
  return resolveFrontendSurface()
}

export function defaultPostLoginPath(surface: FrontendSurface = getFrontendSurface()) {
  return surface === "admin" ? "/" : "/"
}
