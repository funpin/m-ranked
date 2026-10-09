import { cache, Suspense } from "react";
import "./landing.css";
import type { Metadata } from "next";
import { Skeleton } from "@/components/ui/skeleton";
import { LandingReach, LandingRhythm } from "@/components/landing/landing-charts";
import { LazyCorridor } from "@/components/landing/lazy-corridor";
import { PhoneDashboard, PhoneShowcase } from "@/components/landing/phone-showcase";
import { RevealObserver } from "@/components/landing/reveal-observer";
import {
  Analysis, ChartUnavailable, Closing, Hero, LANDING_SECTIONS, LandingFooter, Pipeline, Platforms, Rhythm, Stats, Verify, type LandingPlatform,
} from "@/components/landing/sections";
import { ScrollChrome } from "@/components/landing/scroll-chrome";
import { Unbounded } from "next/font/google";
import { api } from "@/lib/api";
import { publicOrigin } from "@/lib/deployment";
import { KNOWN_PLATFORMS, corridorModel, landingDashboard, phoneSummary, platformsFromSummary, type SiteSummary } from "@/lib/landing";

export const dynamic = "force-dynamic";

// Широкий дисплейный шрифт заголовков главной — только на этой странице.
const display = Unbounded({ subsets: ["cyrillic", "latin"], weight: ["500", "600"], display: "swap", variable: "--font-display" });

const DESCRIPTION = "m-ranked замеряет каждую публикацию официальных соцсетей российских вузов с первых минут и сравнивает их на одной шкале — с открытым кодом и методологией.";
export const metadata: Metadata = {
  title: { absolute: "m-ranked — соцсети вузов как есть" },
  description: DESCRIPTION,
  alternates: { canonical: "/" },
  openGraph: { title: "m-ranked — соцсети вузов как есть", description: DESCRIPTION },
  twitter: { card: "summary", title: "m-ranked — соцсети вузов как есть", description: DESCRIPTION },
};

// Панель сравнения нужна двум блокам: запрос к API один на отрисовку.
const dashboard = cache(async () => {
  try {
    return landingDashboard(await api.comparisonDashboard("30d"));
  } catch {
    return null;
  }
});

async function summary(): Promise<SiteSummary | null> {
  try {
    const value = await api.siteSummary();
    return value.available ? value : null;
  } catch {
    return null;
  }
}

async function Reach() {
  const data = await dashboard();
  return data ? <LandingReach data={data} /> : <ChartUnavailable />;
}

/** Экран телефона — сравнение площадок; пока данных нет, остаётся заставка. */
async function PhoneScreen() {
  const data = await dashboard();
  return data ? <PhoneDashboard {...phoneSummary(data)} /> : null;
}

async function RhythmCharts() {
  const data = await dashboard();
  return data ? <LandingRhythm data={data} /> : <ChartUnavailable />;
}

const chartFallback = (height: number) => <Skeleton className="w-full rounded-lg" style={{ height }} aria-label="График загружается" role="status" />;

/** Главная: что делает проект, как устроен сбор и где всё проверить. */
export default async function HomePage() {
  const site = await summary();
  // Без сводки площадки всё равно перечислены — просто без числа аккаунтов.
  const platforms: LandingPlatform[] = site
    ? platformsFromSummary(site)
    : Object.keys(KNOWN_PLATFORMS).map((platform) => ({ platform, accounts: null }));
  return (
    <div className={`landing ${display.variable}`} data-testid="landing">
      <ScrollChrome sections={LANDING_SECTIONS} />
      <Hero platforms={platforms} />
      {site && <Stats summary={site} />}
      <Platforms platforms={platforms} phone={<PhoneShowcase><Suspense fallback={null}><PhoneScreen /></Suspense></PhoneShowcase>} />
      <Pipeline chart={<Suspense fallback={chartFallback(340)}><Reach /></Suspense>} />
      <Rhythm chart={<Suspense fallback={chartFallback(380)}><RhythmCharts /></Suspense>} />
      <Analysis corridor={<LazyCorridor model={corridorModel()} />} />
      <Verify summary={site} origin={publicOrigin().origin} />
      <Closing />
      <LandingFooter />
      <RevealObserver />
    </div>
  );
}
