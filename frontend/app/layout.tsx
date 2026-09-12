import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import favicon from "../../app/web/static/favicon.png";
import { SiteHeader } from "@/components/site-header";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://m-ranked.ru"),
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

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ru" data-theme="dark" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeScript }} /></head>
      <body>
        <a className="skip-link" href="#main-content">Перейти к содержимому</a>
        <SiteHeader />
        <main id="main-content" className="page-shell">{children}</main>
      </body>
    </html>
  );
}
