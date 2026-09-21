import type { NextConfig } from "next";
import path from "node:path";

const deploymentId = process.env.MRANKED_DEPLOYMENT_ID?.trim() || undefined;

const nextConfig: NextConfig = {
  output: "standalone",
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Production builds set a unique ID per release. Next appends it to client
  // asset URLs, so a browser cannot reuse a transient 403 cached by an older
  // deployment under the same content-hashed chunk path.
  deploymentId,
  supportsImmutableAssets: false,
  devIndicators: false,
  poweredByHeader: false,
  reactStrictMode: true,
  turbopack: {
    root: path.resolve(process.cwd(), ".."),
  },
};

export default nextConfig;
