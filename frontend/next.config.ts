import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

/**
 * Veyra's UI is exported as static files (out/) and served by NGINX, which
 * also proxies /api to the backend. There is no Node.js runtime in
 * production. During `next dev`, /api is proxied to a local backend instead.
 */
export default function config(phase: string): NextConfig {
  const base: NextConfig = {
    output: "export",
    trailingSlash: true,
    images: { unoptimized: true },
    reactStrictMode: true,
    poweredByHeader: false,
  };
  if (phase !== PHASE_DEVELOPMENT_SERVER) return base;
  const backend = process.env.VEYRA_DEV_API ?? "http://127.0.0.1:8000";
  return {
    ...base,
    output: undefined,
    // API paths have no trailing slash; don't let trailingSlash redirect them.
    skipTrailingSlashRedirect: true,
    async rewrites() {
      return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
    },
  };
}
