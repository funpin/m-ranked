import { headers } from "next/headers";
import { api } from "@/lib/api";
import type { Platform } from "@/lib/types";
import type { Metadata, Viewport } from "next";
import { Suspense, type ReactNode } from "react";
import logoMarkDark from "../assets/logo-mark-dark.svg";
import logoMarkLight from "../assets/logo-mark-light.svg";
import { SiteHeader } from "@/components/site-header";
import { publicOrigin } from "@/lib/deployment";
import "./globals.css";
import { Geologica, Montserrat } from "next/font/google";
import { RouteBoundary } from "@/components/navigation-boundary";
import { SiteHeaderFallback } from "@/components/site-header-fallback";
import { IconSprite } from "@/components/icon-sprite";
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
  applicationName: "m-ranked",
  appleWebApp: {
    capable: true,
    title: "m-ranked",
    statusBarStyle: "black-translucent",
  },
  // Next 16 emits the standard mobile-web-app-capable tag. Keep the Apple
  // spelling too for iOS versions that still key off the legacy name.
  other: { "apple-mobile-web-app-capable": "yes" },
  icons: {
    icon: [
      { url: logoMarkDark.src, type: "image/svg+xml" },
      { url: "/icons/favicon-32.png?v=20260921", type: "image/png", sizes: "32x32" },
    ],
    shortcut: [{ url: "/icons/favicon-32.png?v=20260921", type: "image/png" }],
    // Keep the Apple icon at the conventional root URL. iOS can request that
    // path directly (without consulting the manifest) and may ignore query
    // parameters while reusing an older home-screen icon.
    apple: [{ url: "/apple-touch-icon.png", type: "image/png", sizes: "180x180" }],
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
  viewportFit: "cover",
  colorScheme: "dark light",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#080c12" },
    { media: "(prefers-color-scheme: light)", color: "#f4f7fb" },
  ],
};

const themeScript = `(() => {
  let stored = null;
  try { stored = localStorage.getItem("m-ranked-theme"); } catch (_) {}
  // Выбор пользователя сильнее системы; без выбора решает система.
  const theme =
    stored === "light" || stored === "dark" ? stored
    : matchMedia("(prefers-color-scheme: light)").matches ? "light"
    : "dark";
  document.documentElement.dataset.theme = theme;
  if (navigator.standalone === true || matchMedia("(display-mode: standalone)").matches) {
    document.documentElement.dataset.displayMode = "standalone";
  }
})();`;

// iOS does not build a branded launch screen from the web app manifest.
// It selects an exact apple-touch-startup-image for the device instead.
// Keep both orientations: this PWA deliberately allows any orientation.
const appleStartupImages = [
  ["640x1136", 320, 568, 2],
  ["750x1334", 375, 667, 2],
  ["1242x2208", 414, 736, 3],
  ["1125x2436", 375, 812, 3],
  ["828x1792", 414, 896, 2],
  ["1242x2688", 414, 896, 3],
  ["1170x2532", 390, 844, 3],
  ["1284x2778", 428, 926, 3],
  ["1179x2556", 393, 852, 3],
  ["1290x2796", 430, 932, 3],
  ["1206x2622", 402, 874, 3],
  ["1320x2868", 440, 956, 3],
] as const;

export default async function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  const incoming = await headers();
  const path = incoming.get("x-mranked-path") ?? "/";
  // nonce выдаёт прокси на каждый ответ; свой инлайн-скрипт обязан его нести.
  const nonce = incoming.get("x-nonce") ?? undefined;
  let activePlatform: Platform = path.startsWith("/institutions/") ? "all" : "telegram";
  const identity = /^\/(accounts|publications)\/([0-9a-f-]{36})$/i.exec(path);
  if (identity) {
    try {
      const value = identity[1] === "accounts" ? await api.account(identity[2]) : await api.publication(identity[2]);
      activePlatform = value.platform;
    } catch { /* The page owns unavailable/404 handling; header remains usable. */ }
  }
  return (
    <html
      lang="ru"
      data-theme="dark"
      data-favicon-dark={logoMarkDark.src}
      data-favicon-light={logoMarkLight.src}
      data-scroll-behavior="smooth"
      suppressHydrationWarning
      className={cn(sans.variable, heading.variable)}
    >
      <head>
        <link rel="apple-touch-icon-precomposed" href="/apple-touch-icon-precomposed.png" sizes="180x180" />
        {appleStartupImages.flatMap(([portraitSize, width, height, pixelRatio]) => {
          const [portraitWidth, portraitHeight] = portraitSize.split("x");
          const media = `(device-width: ${width}px) and (device-height: ${height}px) and (-webkit-device-pixel-ratio: ${pixelRatio})`;
          return [
            <link key={`${portraitSize}-portrait`} rel="apple-touch-startup-image"
              href={`/splash/apple-splash-${portraitSize}.png`} media={`${media} and (orientation: portrait)`} />,
            <link key={`${portraitSize}-landscape`} rel="apple-touch-startup-image"
              href={`/splash/apple-splash-${portraitHeight}x${portraitWidth}.png`} media={`${media} and (orientation: landscape)`} />,
          ];
        })}
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        {/* The physical notch or Dynamic Island obscures its own centre strip.
            This tiny brand sits immediately below it, at the visible bottom
            edge of the top safe area; controls remain below the full inset. */}
        <div className="notch-screenshot-brand" data-testid="notch-screenshot-brand" aria-hidden="true">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={logoMarkDark.src} alt="" />
          <strong>m-ranked</strong>
        </div>
        {/* Набор контуров объявляется раз на страницу: значки ссылаются на
            него вместо того, чтобы возить свои контуры сотнями копий. */}
        <IconSprite />
        <a className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[300] focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-foreground focus:ring-2 focus:ring-ring" href="#main-content">Перейти к содержимому</a>
        <Suspense fallback={<SiteHeaderFallback platform={activePlatform} />}><SiteHeader initialPlatform={activePlatform} /></Suspense>
        <main id="main-content" tabIndex={-1} className="safe-page-inset mx-auto w-full max-w-[1400px] min-w-0 py-6"><RouteBoundary>{children}</RouteBoundary></main>
      </body>
    </html>
  );
}
