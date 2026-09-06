import { headers } from "next/headers";
import { api } from "@/lib/api";
import type { Platform } from "@/lib/types";
import type { Metadata, Viewport } from "next";
import { Suspense, type ReactNode } from "react";
import favicon from "../assets/favicon.png";
import { SiteHeader } from "@/components/site-header";
import { publicOrigin } from "@/lib/deployment";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: publicOrigin(),
  title: {
    default: "m-ranked — аналитика соцсетей вузов",
    template: "%s · m-ranked",
  },
  description: "Сравнение активности, охвата и качества данных официальных соцсетей российских вузов.",
  icons: {
    icon: [{ url: favicon.src, type: "image/png" }],
  },
  openGraph: {
    type: "website",
    locale: "ru_RU",
    siteName: "m-ranked",
    title: "m-ranked — аналитика соцсетей вузов",
    description: "Сравнение активности, охвата и качества данных официальных соцсетей российских вузов.",
  },
  twitter: {
    card: "summary",
    title: "m-ranked — аналитика соцсетей вузов",
    description: "Сравнение активности, охвата и качества данных официальных соцсетей российских вузов.",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "dark light",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#080c12" },
    { media: "(prefers-color-scheme: light)", color: "#f4f7fb" },
  ],
};

const themeScript = `(() => {
  let theme = "dark";
  try {
    const saved = localStorage.getItem("m-ranked-theme");
    if (saved === "light" || saved === "dark") theme = saved;
  } catch (_) {}
  document.documentElement.dataset.theme = theme;
})();`;

export default async function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  const path = (await headers()).get("x-mranked-path") ?? "/";
  let activePlatform: Platform = path.startsWith("/institutions/") ? "all" : "telegram";
  const identity = /^\/(platform-accounts|platform-posts)\/(\d+)$/.exec(path);
  if (identity) {
    try {
      const value = identity[1] === "platform-accounts" ? await api.account(Number(identity[2]),"platform_accounts") : await api.publication(Number(identity[2]),"platform_posts");
      activePlatform = value.platform;
    } catch { /* The page owns unavailable/404 handling; header remains usable. */ }
  }
  return (
    <html lang="ru" data-theme="dark" data-scroll-behavior="smooth" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeScript }} /></head>
      <body>
        <a className="skip-link" href="#main-content">Перейти к содержимому</a>
        <Suspense><SiteHeader initialPlatform={activePlatform} /></Suspense>
        <main id="main-content" className="page-shell">{children}</main>
      </body>
    </html>
  );
}
