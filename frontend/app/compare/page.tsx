import { Suspense } from "react";
import type { Metadata } from "next";
import { CompareDashboard } from "@/components/compare/compare-dashboard";
import { CompareDashboardSkeleton } from "@/components/compare/compare-skeleton";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import {
  MAX_HIGHLIGHTS, normalizeDashboardPeriod, normalizeDashboardPlatform, type DashboardPeriod,
} from "@/lib/compare-dashboard";
import { first, many, queryHref, type SearchParams } from "@/lib/params";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Сравнение вузов",
  description: "Все вузы на одних графиках: охват, вовлечённость, активность, аномальная динамика по соцсетям.",
  openGraph: {
    title: "Сравнение вузов — M‑Ranked",
    description: "Все вузы на одних графиках: охват, вовлечённость, активность, аномальная динамика по соцсетям.",
  },
  twitter: {
    card: "summary",
    title: "Сравнение вузов — M‑Ranked",
    description: "Все вузы на одних графиках: охват, вовлечённость, активность, аномальная динамика по соцсетям.",
  },
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Панель приходит отдельным потоком: заголовок и каркас страницы видны сразу. */
async function Dashboard({ period, platform, highlight, legacyInstitutions }: {
  period: DashboardPeriod; platform: ReturnType<typeof normalizeDashboardPlatform>;
  highlight: string[]; legacyInstitutions: number[];
}) {
  let data;
  try {
    data = await api.comparisonDashboard(period);
  } catch {
    return <ApiFailureState retryHref={queryHref("/compare", { platform, period })} />;
  }
  // Старые ссылки сравнения несли legacy id вузов: они становятся выделением.
  const fromLegacy = data.institutions
    .filter((item) => item.legacyId !== null && legacyInstitutions.includes(item.legacyId))
    .map((item) => item.institutionId);
  const initialHighlights = [...new Set([...highlight, ...fromLegacy])].slice(0, MAX_HIGHLIGHTS);
  return <CompareDashboard data={data} period={period} initialPlatform={platform} initialHighlights={initialHighlights} />;
}

export default async function ComparePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  // Прежняя страница открывалась на Telegram; без площадки в адресе — все соцсети.
  const platform = normalizeDashboardPlatform(first(params.platform));
  // Прежний period был числом часов (24–336) — такие ссылки открывают 30 дней.
  const period = normalizeDashboardPeriod(first(params.period));
  const highlight = (first(params.highlight) ?? "").split(",").filter((id) => UUID.test(id)).map((id) => id.toLowerCase());
  const legacyInstitutions = many(params.institutions).map(Number).filter((id) => Number.isSafeInteger(id) && id > 0);
  return <>
    <PageHeader
      title="Сравнение вузов"
      description={<>Все вузы на одних графиках — без ограничения по числу. Охват поста за первые сутки, вовлечённость,
        активность, аудитория и <b>аномальная динамика</b> по каждой соцсети и по всем сразу.</>}
    />
    <Suspense key={period} fallback={<CompareDashboardSkeleton />}>
      <Dashboard period={period} platform={platform} highlight={highlight} legacyInstitutions={legacyInstitutions} />
    </Suspense>
  </>;
}
