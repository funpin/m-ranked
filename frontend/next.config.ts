import type { NextConfig } from "next";
import createMDX from "@next/mdx";
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
  // Оглавление статьи строится на сервере из её исходника: файлы статей должны
  // попасть в автономную сборку вместе со страницей.
  outputFileTracingIncludes: { "/methodology/*": ["./content/methodology/**/*"] },
  turbopack: {
    root: path.resolve(process.cwd(), ".."),
  },
};

// Статьи методологии — MDX-файлы в content/methodology. Плагины передаются
// строками: функции в Turbopack не передать. GFM нужен ради таблиц.
const withMDX = createMDX({ options: { remarkPlugins: ["remark-gfm"] } });

export default withMDX(nextConfig);
