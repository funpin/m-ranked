import type { Metadata } from "next";
import { Card, CardContent } from "@/components/ui/card";
import { Pagination, PaginationContent, PaginationEllipsis, PaginationItem,
  PaginationLink, PaginationNext, PaginationPrevious } from "@/components/ui/pagination";
import { NativeButton, NativeInput, NativeSegments, NativeSelect } from "@/components/native-field";
import { LegacyFilterForm } from "@/components/legacy-filter-form";
import { OverviewCard } from "@/components/overview-card";
import { CoverageSummary } from "@/components/coverage-summary";
import { NavigationBoundary } from "@/components/navigation-boundary";
import { CardGridSkeleton } from "@/components/skeletons";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { MethodNote } from "@/components/method-note";
import { Search } from "lucide-react";
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
import { api } from "@/lib/api";
import { overviewPagination } from "@/lib/overview-pagination";
import { PLATFORM_LABELS, PLATFORM_LONG_LABELS } from "@/lib/format";
import {
  first,
  normalizeDirection,
  normalizePeriod,
  normalizePlatform,
  normalizeSort,
  queryHref,
  type SearchParams,
} from "@/lib/params";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Обзор соцсетей вузов",
  description: "Сводные показатели активности официальных соцсетей вузов с размером выборки, покрытием и качеством данных.",
  alternates: { canonical: "/review" },
  openGraph: {
    title: "Обзор соцсетей вузов — M‑Ranked",
    description: "Сводные показатели активности официальных соцсетей вузов с прозрачной оценкой качества данных.",
  },
  twitter: {
    card: "summary",
    title: "Обзор соцсетей вузов — M‑Ranked",
    description: "Сводные показатели активности официальных соцсетей вузов с прозрачной оценкой качества данных.",
  },
};

export default async function OverviewPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const period = normalizePeriod(params.period, "1d");
  const platform = normalizePlatform(params.platform, "telegram");
  const sort = normalizeSort(params.sort, platform);
  const direction = normalizeDirection(params.direction, sort);
  const q = (first(params.q) ?? "").trim();
  const cursor = first(params.cursor);
  const pagination = overviewPagination(cursor, params.from);

  let page;
  try {
    page = await api.overview({
      platform, period, q, sort, direction, limit: 20, cursor,
    });
  } catch {
    return (
      <>
        <PageHeader title={platform === "all" ? "Обзор вузов" : "Обзор каналов"} description="Активность официальных соцсетей вузов за выбранный период." />
        <ApiFailureState retryHref={queryHref("/review", { platform, period, q })} />
      </>
    );
  }

  const items = page.items;
  return (
    <>
      <PageHeader
        title={platform === "all" ? "Обзор вузов" : "Обзор каналов"}
        titleNote={
          <MethodNote title="Как считаются показатели">
            {platform === "all"
              ? <><b>Почему нет общей суммы:</b> лайк, реакция, просмотр видео и просмотр поста имеют разный смысл. Общий режим показывает покрытие и официальный общий М‑Рейтинг; единый межплатформенный индекс будет добавлен только после утверждения формулы.</>
              : platform === "telegram"
                ? <>В карточке показана активность всех отслеживаемых постов, для которых внутри выбранного периода есть сравнимые замеры, а не только новых публикаций. Реакции и просмотры — разница между первым и последним замером внутри окна; прирост до первого замера в период не включается. Для новых постов с полной историей отсчёт идёт от нуля в момент публикации. Медианы — типичный прирост одного поста за это окно и округляются до целого. Плашка у медианы сравнивает типичный прирост с предыдущим таким же периодом и скрывается, если сравнивать не с чем или изменения нет.</>
                : <>Для каждой публикации берётся разница между первым и последним сравнимым снимком внутри окна. Метрики, которых нет в официальном источнике {PLATFORM_LONG_LABELS[platform]}, не заменяются нулями и не подменяются Telegram-данными.</>}
          </MethodNote>
        }
        description={platform === "all"
          ? "Официальные аккаунты и общий М‑Рейтинг без сложения несопоставимых метрик."
          : "Прирост показателей всех постов в базе за выбранный период, а не только новых."}
      />

      <LegacyFilterForm key={`${platform}:${period}:${sort}:${direction}:${q}`} action="/review" method="get"
        aria-label="Фильтры обзора" data-testid="filter-toolbar" className={FILTER_TOOLBAR_CLASS}>
              <div className={FILTER_PLATFORM_CLASS}><NativeSegments
                  name="platform"
                  legend="Площадка"
                  value={platform}
                  options={FILTER_PLATFORM_OPTIONS}
                  labelled={false}
                /></div>
              <div className={FILTER_PERIOD_CLASS}><NativeSegments name="period" legend="Период" value={period}
                options={FILTER_PERIOD_OPTIONS} labelled={false} /></div>
              <div className={FILTER_SEARCH_CLASS}>
                <NativeInput name="q" type="search" defaultValue={q} aria-label="Поиск вуза" placeholder="Поиск вуза" className="h-8" />
                <NativeButton type="submit" variant="outline" aria-label="Применить фильтры" title="Применить фильтры" className="size-8 min-h-8 shrink-0 px-0">
                  <Search className="size-4" aria-hidden="true" />
                </NativeButton>
              </div>
              <div className={FILTER_SORT_CLASS}>
                <NativeSelect name="sort" defaultValue={sort} aria-label="Сортировка" title="Порядок карточек в списке" className="h-8">
                  <option value="name">Название вуза · алфавит</option>
                  {platform === "all" ? (
                    <>
                      <option value="m_rating">Общий М‑Рейтинг · место</option>
                    </>
                  ) : (
                    <>
                      <option value="median_reactions">Медиана прироста реакций</option>
                      <option value="m_rating">М‑Рейтинг {PLATFORM_LABELS[platform]} · место</option>
                      <option value="reactions">Прирост реакций</option>
                      <option value="views">Прирост просмотров</option>
                      <option value="posts">Новые публикации</option>
                      <option value="subscribers">Подписчики</option>
                    </>
                  )}
                </NativeSelect>
              </div>
              <div className={FILTER_DIRECTION_CLASS}>
                <NativeSelect name="direction" defaultValue={direction} aria-label="Порядок" title="Порядок" className="h-8">
                  <option value="desc">По убыванию</option>
                  <option value="asc">По возрастанию</option>
                </NativeSelect>
              </div>
      </LegacyFilterForm>

      {/* Заготовка стоит только вокруг списка: заголовок и фильтры остаются
          видимыми и рабочими, пока едет новая выборка. */}
      <NavigationBoundary fallback={<CardGridSkeleton chrome={false} />}>
        {platform === "all" ? <CoverageSummary items={items} /> : null}

        <section className="reveal grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-4" aria-label="Вузы">{items.length ? (
          items.map((item) => <OverviewCard item={item} integrationWarning={page.integrationWarning} key={item.entityId} />)
        ) : (
          <Card><CardContent className="text-muted-foreground py-6">{q ? `По запросу «${q}» вузы не найдены.` : platform === "telegram" ? "За выбранный период публикаций не найдено." : "Вузы ещё не добавлены."}</CardContent></Card>
        )}</section>
      </NavigationBoundary>
      {(cursor || page.nextCursor) && (() => {
        const common = { platform, period, q, sort, direction };
        const firstHref = queryHref("/review", common);
        const previousHref = cursor ? queryHref("/review", { ...common,
          cursor: pagination.previousCursor, from: pagination.previousTrail }) : null;
        const nextHref = page.nextCursor ? queryHref("/review", { ...common,
          cursor: page.nextCursor, from: pagination.nextTrail }) : null;
        const currentHref = queryHref("/review", { ...common, cursor, from: pagination.trail });
        return <div className="border-border bg-card mt-6 rounded-xl border px-3 py-3 shadow-sm" data-testid="overview-pagination">
          <Pagination><PaginationContent>
            {previousHref ? <PaginationItem><PaginationPrevious href={previousHref} rel="prev" /></PaginationItem> : null}
            {pagination.page > 1 ? <PaginationItem><PaginationLink href={firstHref}>1</PaginationLink></PaginationItem> : null}
            {pagination.page > 3 ? <PaginationItem><PaginationEllipsis /></PaginationItem> : null}
            {previousHref && pagination.page > 2 ? <PaginationItem><PaginationLink href={previousHref}>{pagination.page - 1}</PaginationLink></PaginationItem> : null}
            <PaginationItem><PaginationLink href={currentHref} isActive aria-label={`Страница ${pagination.page}`}>{pagination.page}</PaginationLink></PaginationItem>
            {nextHref ? <PaginationItem><PaginationLink href={nextHref}>{pagination.page + 1}</PaginationLink></PaginationItem> : null}
            {nextHref ? <PaginationItem><PaginationNext href={nextHref} rel="next" /></PaginationItem> : null}
          </PaginationContent></Pagination>
        </div>;
      })()}
    </>
  );
}
