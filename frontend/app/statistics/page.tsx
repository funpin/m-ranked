import type { Metadata } from "next";
import Link from "@/components/native-link";
import { MethodNote } from "@/components/method-note";
import { NavigationBoundary } from "@/components/navigation-boundary";
import { NativeSegments } from "@/components/native-field";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatisticsFilterForm } from "@/components/statistics-filter-form";
import { StatisticsResults } from "@/components/statistics-results";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { first, queryHref, type SearchParams } from "@/lib/params";
import { normalizeStatisticsQuery, statisticsHrefQuery } from "@/lib/statistics";
import { ArrowRight, Search, X } from "lucide-react";
import { StatisticsSkeleton } from "@/components/skeletons";
import {
  FILTER_DIRECTION_CLASS,
  FILTER_PERIOD_CLASS,
  FILTER_PERIOD_OPTIONS,
  FILTER_PLATFORM_CLASS,
  FILTER_PLATFORM_OPTIONS,
  FILTER_SEARCH_CLASS,
  FILTER_SELECT_CLASS,
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
      <div className={FILTER_SEARCH_CLASS}>
        <InputGroup className="h-8">
          <InputGroupAddon><Search className="size-4" aria-hidden="true" /></InputGroupAddon>
          <InputGroupInput name="q" type="search" defaultValue={query.q} maxLength={200} placeholder="Вуз, аккаунт, ID или URL" aria-label="Поиск публикаций" className="text-sm md:text-sm" />
          <InputGroupAddon align="inline-end">
            {query.q ? <InputGroupButton size="icon-sm" className="size-6" nativeButton={false} aria-label="Очистить поиск" title="Очистить поиск"
              render={<Link role="link" href={queryHref("/statistics", { ...statisticsHrefQuery(query), q: undefined })} prefetch={false} />}><X className="size-3.5" aria-hidden="true" /></InputGroupButton> : null}
            <InputGroupButton type="submit" variant="secondary" size="icon-sm" className="size-6" aria-label="Найти" title="Найти"><ArrowRight className="size-3.5" aria-hidden="true" /></InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </div>
      <div className={FILTER_SORT_CLASS}>{query.view === "publications"
        ? <NativeSelect name="publication_sort" defaultValue={query.publicationSort} aria-label="Сортировка публикаций" className={FILTER_SELECT_CLASS}>{PUBLICATION_SORT_OPTIONS.map(([value, label]) => <NativeSelectOption key={value} value={value}>{label}</NativeSelectOption>)}</NativeSelect>
        : <NativeSelect name="entity_sort" defaultValue={query.entitySort} aria-label="Сортировка вузов" className={FILTER_SELECT_CLASS}>{ENTITY_SORT_OPTIONS.map(([value, label]) => <NativeSelectOption key={value} value={value}>{label}</NativeSelectOption>)}</NativeSelect>}</div>
      <div className={FILTER_DIRECTION_CLASS}>{query.view === "publications"
        ? <NativeSelect name="publication_direction" defaultValue={query.publicationDirection} aria-label="Направление сортировки публикаций" className={FILTER_SELECT_CLASS}><NativeSelectOption value="desc">По убыванию</NativeSelectOption><NativeSelectOption value="asc">По возрастанию</NativeSelectOption></NativeSelect>
        : <NativeSelect name="entity_direction" defaultValue={query.entityDirection} aria-label="Направление сортировки вузов" className={FILTER_SELECT_CLASS}><NativeSelectOption value="desc">По убыванию</NativeSelectOption><NativeSelectOption value="asc">По возрастанию</NativeSelectOption></NativeSelect>}</div>
      {query.view === "publications" ? <><input type="hidden" name="entity_sort" value={query.entitySort} /><input type="hidden" name="entity_direction" value={query.entityDirection} /></> : <><input type="hidden" name="publication_sort" value={query.publicationSort} /><input type="hidden" name="publication_direction" value={query.publicationDirection} /></>}
    </StatisticsFilterForm>

    {query.platform !== "all" ? <Tabs value={query.view} className="mb-5">
      <TabsList aria-label="Вид статистики" className="h-9">
        {(["publications", "entities"] as const).map((view) => <TabsTrigger key={view} value={view} nativeButton={false} className="px-4 text-sm"
          render={<Link href={queryHref("/statistics", { ...statisticsHrefQuery(query), view })} scroll={false} prefetch={false} />}>
          {view === "publications" ? "Публикации" : "Вузы"}
        </TabsTrigger>)}
      </TabsList>
    </Tabs> : null}

    <NavigationBoundary fallback={<StatisticsSkeleton chrome={false} view={query.view} />}>
      {failed || !page ? <ApiFailureState retryHref={queryHref("/statistics", statisticsHrefQuery(query))} /> : <StatisticsResults key={selectionKey} page={page} query={query} />}
    </NavigationBoundary>
  </>;
}
