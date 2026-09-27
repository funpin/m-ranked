import type { Metadata } from "next";
import Link from "@/components/native-link";
import { MethodNote } from "@/components/method-note";
import { NavigationBoundary } from "@/components/navigation-boundary";
import { NativeButton, NativeInput, NativeSegments, NativeSelect } from "@/components/native-field";
import { StatisticsFilterForm } from "@/components/statistics-filter-form";
import { StatisticsResults } from "@/components/statistics-results";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { first, queryHref, type SearchParams } from "@/lib/params";
import { normalizeStatisticsQuery, statisticsHrefQuery } from "@/lib/statistics";
import { Search, X } from "lucide-react";
import { StatisticsSkeleton } from "@/components/skeletons";
import {
  FILTER_DIRECTION_CLASS,
  FILTER_PERIOD_CLASS,
  FILTER_PERIOD_OPTIONS,
  FILTER_PLATFORM_CLASS,
  FILTER_PLATFORM_OPTIONS,
  FILTER_SEARCH_CLASS,
  FILTER_SORT_CLASS,
  FILTER_TOOLBAR_CLASS,
} from "@/components/filter-toolbar";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Статистика публикаций",
  description: "Накопленные результаты публикаций вузов по площадкам и периоду публикации.",
};

const PUBLICATION_SORT_OPTIONS = [
  ["erv", "ERV"], ["views", "Просмотры"], ["interactions", "Взаимодействия"],
  ["published_at", "Дата публикации"],
] as const;
const ENTITY_SORT_OPTIONS = [
  ["erv", "ERV"], ["median_interactions", "Медиана взаимодействий"],
  ["interactions", "Взаимодействия"], ["views", "Просмотры"], ["publications", "Публикации"],
] as const;

export default async function StatisticsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const raw = await searchParams;
  const query = normalizeStatisticsQuery(raw);
  const cursor = first(raw.cursor);
  let page = null;
  let failed = false;
  try {
    page = await api.statistics({ ...query, limit: 50, cursor });
  } catch {
    failed = true;
  }
  const selectionKey = [query.view, query.platform, query.period, query.q, query.publicationSort,
    query.publicationDirection, query.entitySort, query.entityDirection].join(":");
  const updated = page ? new Date(page.asOf).toLocaleTimeString("ru-RU", {
    timeZone: "Europe/Moscow", hour: "2-digit", minute: "2-digit",
  }) : null;

  return <>
    <PageHeader
      title="Статистика публикаций"
      titleNote={<MethodNote title="Как считается статистика"><p>Период — по дате публикации. Взаимодействия = лайки или реакции + комментарии + репосты (нет данных — 0). ERV = взаимодействия ÷ просмотры × 100%.</p></MethodNote>}
      description="Накопленные результаты публикаций, вышедших в выбранный период."
      meta={page ? <span className="text-muted-foreground text-xs" title={`${formatDate(page.asOf)} · datasetRevision ${page.datasetRevision}`}>Обновлено {updated}</span> : null}
    />

    <StatisticsFilterForm key={selectionKey} action="/statistics" method="get" aria-label="Фильтры статистики"
      data-testid="filter-toolbar" className={FILTER_TOOLBAR_CLASS}>
      {query.platform !== "all" ? <input type="hidden" name="view" value={query.view} /> : null}
      <div className={FILTER_PLATFORM_CLASS}><NativeSegments name="platform" legend="Площадка" value={query.platform} labelled={false}
        options={FILTER_PLATFORM_OPTIONS} /></div>
      <div className={FILTER_PERIOD_CLASS}><NativeSegments name="period" legend="Период" value={query.period}
        options={FILTER_PERIOD_OPTIONS} labelled={false} /></div>
      <div className={FILTER_SEARCH_CLASS}><NativeInput name="q" type="search" defaultValue={query.q} maxLength={200} placeholder="Вуз, аккаунт, ID или URL" aria-label="Поиск публикаций" className="h-8" />{query.q ? <Link className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border" href={queryHref("/statistics", { ...statisticsHrefQuery(query), q: undefined })} aria-label="Очистить поиск" prefetch={false}><X className="size-4" aria-hidden="true" /></Link> : null}<NativeButton type="submit" variant="outline" className="size-8 min-h-8 shrink-0 px-0" aria-label="Найти" title="Найти"><Search className="size-4" aria-hidden="true" /></NativeButton></div>
      <div className={FILTER_SORT_CLASS}>{query.view === "publications"
        ? <NativeSelect name="publication_sort" defaultValue={query.publicationSort} aria-label="Сортировка публикаций" className="h-8">{PUBLICATION_SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</NativeSelect>
        : <NativeSelect name="entity_sort" defaultValue={query.entitySort} aria-label="Сортировка вузов" className="h-8">{ENTITY_SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</NativeSelect>}</div>
      <div className={FILTER_DIRECTION_CLASS}>{query.view === "publications"
        ? <NativeSelect name="publication_direction" defaultValue={query.publicationDirection} aria-label="Направление сортировки публикаций" className="h-8"><option value="desc">По убыванию</option><option value="asc">По возрастанию</option></NativeSelect>
        : <NativeSelect name="entity_direction" defaultValue={query.entityDirection} aria-label="Направление сортировки вузов" className="h-8"><option value="desc">По убыванию</option><option value="asc">По возрастанию</option></NativeSelect>}</div>
      {query.view === "publications" ? <><input type="hidden" name="entity_sort" value={query.entitySort} /><input type="hidden" name="entity_direction" value={query.entityDirection} /></> : <><input type="hidden" name="publication_sort" value={query.publicationSort} /><input type="hidden" name="publication_direction" value={query.publicationDirection} /></>}
    </StatisticsFilterForm>

    {query.platform !== "all" ? <nav className="mb-5 flex w-fit rounded-md bg-muted p-0.5" aria-label="Вид статистики" role="tablist">
      {(["publications", "entities"] as const).map((view) => <Link key={view} role="tab" aria-selected={query.view === view} className={`rounded px-4 py-2 text-sm font-medium ${query.view === view ? "bg-background text-foreground shadow-sm" : "text-muted-foreground"}`} href={queryHref("/statistics", { ...statisticsHrefQuery(query), view })} scroll={false} prefetch={false}>{view === "publications" ? "Публикации" : "Вузы"}</Link>)}
    </nav> : null}

    <NavigationBoundary fallback={<StatisticsSkeleton chrome={false} view={query.view} />}>
      {failed || !page ? <ApiFailureState retryHref={queryHref("/statistics", statisticsHrefQuery(query))} /> : <StatisticsResults key={selectionKey} page={page} query={query} />}
    </NavigationBoundary>
  </>;
}
