import { cache, Suspense } from "react";
import "./landing.css";
import type { Metadata } from "next";
import { Skeleton } from "@/components/ui/skeleton";
import { LandingReach, LandingRhythm } from "@/components/landing/landing-charts";
import { LazyCorridor } from "@/components/landing/lazy-corridor";
import {
  Analysis, ChartUnavailable, Hero, LandingFooter, Pipeline, Platforms, Rhythm, Stats, Verify, type LandingPlatform,
} from "@/components/landing/sections";
import { api } from "@/lib/api";
import { publicOrigin } from "@/lib/deployment";
import { KNOWN_PLATFORMS, landingDashboard, platformsFromSummary, type SiteSummary } from "@/lib/landing";

export const dynamic = "force-dynamic";

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
    <div className="landing" data-testid="landing">
      <Hero platforms={platforms} />
      {site && <Stats summary={site} />}
      <Platforms platforms={platforms} />
      <Pipeline chart={<Suspense fallback={chartFallback(340)}><Reach /></Suspense>} />
      <Rhythm chart={<Suspense fallback={chartFallback(380)}><RhythmCharts /></Suspense>} />
      <Analysis corridor={<LazyCorridor />} />
      <Verify summary={site} origin={publicOrigin().origin} />
      <LandingFooter />
    </div>
  );
}
