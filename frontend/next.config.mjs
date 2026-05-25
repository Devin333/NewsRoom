import { fileURLToPath } from "node:url"
import path from "node:path"
import { loadRootEnv } from "./root-env.mjs"

const configDir = path.dirname(fileURLToPath(import.meta.url))

loadRootEnv(configDir)

const apiBaseUrl =
  process.env.NEWSROOM_API_BASE_URL ??
  process.env.NEXT_PUBLIC_NEWSROOM_API_BASE_URL ??
  "http://127.0.0.1:8000"

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiBaseUrl.replace(/\/$/, "")}/api/v1/:path*`
      }
    ]
  }
}

export default nextConfig
