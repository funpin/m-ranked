import type { Metadata } from "next";
import { Card, CardContent } from "@/components/ui/card";
import { NativeButton, NativeInput, NativeSegments, NativeSelect } from "@/components/native-field";
import { LegacyFilterForm } from "@/components/legacy-filter-form";
import { OverviewCard } from "@/components/overview-card";
import { CoverageSummary } from "@/components/coverage-summary";
import { NavigationBoundary } from "@/components/navigation-boundary";
import { CardGridSkeleton } from "@/components/skeletons";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { MethodNote } from "@/components/method-note";
import { Search } from "lucide-react";
import { api } from "@/lib/api";
import { PERIOD_LABELS, PLATFORM_LABELS, PLATFORM_LONG_LABELS } from "@/lib/format";
import {
  first,
  normalizeDirection,
  normalizePeriod,
  normalizePlatform,
  normalizeSort,
  queryHref,
  type SearchParams,
} from "@/lib/params";
import { PLATFORM_VALUES } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Обзор соцсетей вузов",
  description: "Сводные показатели активности официальных соцсетей вузов с размером выборки, покрытием и качеством данных.",
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

  let page;
  try {
    page = await api.overview({
      platform, period, q, sort, direction, limit: 50, cursor,
    });
  } catch {
    return (
      <>
        <PageHeader title={platform === "all" ? "Обзор вузов" : "Обзор каналов"} description="Активность официальных соцсетей вузов за выбранный период." />
        <ApiFailureState retryHref={queryHref("/", { platform, period, q })} />
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

      {/* Панель фильтров без карточки и без подписей над полями: подписи
          дублировали сами значения, а рамка панели спорила с рамками карточек
          вузов. Имена для скринридера остались на самих полях. */}
      <div className="mb-5">
          <LegacyFilterForm key={`${platform}:${period}:${sort}:${direction}:${q}`} action="/" method="get" aria-label="Фильтры обзора">
            <div className="flex flex-wrap items-center gap-2">
              <div className="min-w-[15rem] flex-1">
                <NativeInput name="q" type="search" defaultValue={q} aria-label="Поиск вуза" placeholder="Поиск вуза" />
              </div>
              {/* Кнопка стоит рядом с полем, как в рейтинге: внутри поля она
                  читалась как украшение, а не как способ применить фильтры. */}
              <NativeButton type="submit" aria-label="Применить фильтры" title="Применить фильтры" className="size-9 min-h-9 shrink-0 px-0">
                <Search className="size-4" aria-hidden="true" />
              </NativeButton>
              <div className="w-[9rem]">
                <NativeSelect name="period" defaultValue={period} aria-label="Период" title="Период">
                  {Object.entries(PERIOD_LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
                </NativeSelect>
              </div>
              <div className="w-[14rem]">
                <NativeSelect name="sort" defaultValue={sort} aria-label="Сортировка" title="Порядок карточек в списке">
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
              <div className="w-[10.5rem]">
                <NativeSelect name="direction" defaultValue={direction} aria-label="Порядок" title="Порядок">
                  <option value="desc">По убыванию</option>
                  <option value="asc">По возрастанию</option>
                </NativeSelect>
              </div>
              <NativeSegments
                name="platform"
                legend="Площадка"
                value={platform}
                options={PLATFORM_VALUES.map((value) => ({ value, label: PLATFORM_LABELS[value] }))}
                labelled={false}
              />
            </div>
          </LegacyFilterForm>
      </div>

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
    </>
  );
}
