import { headers } from "next/headers";
import { api } from "@/lib/api";
import type { Platform } from "@/lib/types";
import type { Metadata, Viewport } from "next";
import { Suspense, type ReactNode } from "react";
import favicon from "../assets/favicon.png";
import { SiteHeader } from "@/components/site-header";
import { publicOrigin } from "@/lib/deployment";
import "./globals.css";
import { Geologica, Montserrat } from "next/font/google";
import { cn } from "@/lib/utils";

// Self-hosted by next/font: no request to fonts.gstatic.com, and the fallback
// metrics it emits keep the layout from shifting while a face loads.
const heading = Geologica({ subsets: ["cyrillic", "latin"], display: "swap", variable: "--font-heading" });
const sans = Montserrat({ subsets: ["cyrillic", "latin"], display: "swap", variable: "--font-sans" });

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
  let stored = null;
  try { stored = localStorage.getItem("m-ranked-theme"); } catch (_) {}
  // "system" is opt-in; anyone who never chose keeps the dark default.
  document.documentElement.dataset.theme =
    stored === "light" || stored === "dark" ? stored
    : stored === "system" && matchMedia("(prefers-color-scheme: light)").matches ? "light"
    : "dark";
})();`;

export default async function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  const path = (await headers()).get("x-mranked-path") ?? "/";
  let activePlatform: Platform = path.startsWith("/institutions/") ? "all" : "telegram";
  const identity = /^\/(accounts|publications)\/([0-9a-f-]{36})$/i.exec(path);
  if (identity) {
    try {
      const value = identity[1] === "accounts" ? await api.account(identity[2]) : await api.publication(identity[2]);
      activePlatform = value.platform;
    } catch { /* The page owns unavailable/404 handling; header remains usable. */ }
  }
  return (
    <html lang="ru" data-theme="dark" data-scroll-behavior="smooth" suppressHydrationWarning className={cn(sans.variable, heading.variable)}>
      <head><script dangerouslySetInnerHTML={{ __html: themeScript }} /></head>
      <body>
        <a className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[300] focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-foreground focus:ring-2 focus:ring-ring" href="#main-content">Перейти к содержимому</a>
        <Suspense><SiteHeader initialPlatform={activePlatform} /></Suspense>
        <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-[1400px] min-w-0 px-4 py-6 sm:px-6 lg:px-10">{children}</main>
      </body>
    </html>
  );
}
