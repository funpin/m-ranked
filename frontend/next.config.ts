import type { NextConfig } from "next";
import createMDX from "@next/mdx";
import path from "node:path";

const deploymentId = process.env.MRANKED_DEPLOYMENT_ID?.trim() || undefined;
// Локальный стенд без nginx: браузер запрашивает /api/v1 у того же адреса, что
// и страницу (месяц графика аккаунта, полная история, контекст анализа). В
// проде /api раздаёт nginx, и флаг не ставится; при сборке с
// MRANKED_API_REWRITE=1 Next сам переадресует /api на API_BASE_URL.
const apiRewrite = process.env.MRANKED_API_REWRITE === "1"
  ? process.env.API_BASE_URL?.trim().replace(/\/+$/, "") || undefined : undefined;

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
  async rewrites() {
    return apiRewrite ? [{ source: "/api/:path*", destination: `${apiRewrite}/api/:path*` }] : [];
  },
};

// Статьи методологии — MDX-файлы в content/methodology. Плагины передаются
// строками: функции в Turbopack не передать. GFM нужен ради таблиц.
const withMDX = createMDX({ options: { remarkPlugins: ["remark-gfm"] } });

export default withMDX(nextConfig);
