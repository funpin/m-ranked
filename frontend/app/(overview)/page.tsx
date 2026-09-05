import type { Metadata } from "next";
import Link from "next/link";
import { OverviewCard } from "@/components/overview-card";
import { ApiFailureState, EmptyState, InfoNotice, PageHeader, StatusPill } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate, PERIOD_LABELS, PLATFORM_LABELS } from "@/lib/format";
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
  const q = (first(params.q) ?? "").trim().slice(0, 200);
  const cursor = first(params.cursor);

  let page;
  try {
    page = await api.overview({
      platform, period, q, sort, direction, limit: 50, cursor,
    });
  } catch {
    return (
      <>
        <PageHeader title="Обзор каналов" description="Активность официальных соцсетей вузов за выбранный период." />
        <ApiFailureState retryHref={queryHref("/", { platform, period, q })} />
      </>
    );
  }

  const items = page.items;
  return (
    <>
      <PageHeader
        title="Обзор каналов"
        description="Активность публикаций за выбранный период — с размером выборки, покрытием и качеством исходных данных."
        meta={<StatusPill tone="blue">ревизия #{page.datasetRevision}</StatusPill>}
      />

      <form className="panel filter-panel" action="/" method="get" aria-label="Фильтры обзора">
        <div className="filter-grid">
          <label className="field">
            <span>Поиск вуза</span>
            <input name="q" type="search" defaultValue={q} maxLength={200} placeholder="Сокращение или полное название" />
          </label>
          <label className="field">
            <span>Период</span>
            <select name="period" defaultValue={period}>
              {Object.entries(PERIOD_LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Сортировать</span>
            <select name="sort" defaultValue={sort}>
              <option value="name">Название</option>
              {platform === "all" ? (
                <>
                  <option value="m_rating">Общий М‑Рейтинг · место</option>
                  <option value="coverage">Подключённые площадки</option>
                  <option value="accounts">Количество аккаунтов</option>
                </>
              ) : (
                <>
                  <option value="median_reactions">Медиана прироста реакций</option>
                  <option value="m_rating">М‑Рейтинг · место</option>
                  <option value="reactions">Прирост реакций</option>
                  <option value="views">Прирост просмотров</option>
                  <option value="posts">Новые публикации</option>
                  <option value="subscribers">Подписчики</option>
                </>
              )}
            </select>
          </label>
          <label className="field">
            <span>Порядок</span>
            <select name="direction" defaultValue={direction}>
              <option value="desc">По убыванию</option>
              <option value="asc">По возрастанию</option>
            </select>
          </label>
          <button type="submit">Применить</button>
        </div>
        <fieldset className="platform-fieldset">
          <legend>Площадка</legend>
          <div className="segments">
            {PLATFORM_VALUES.map((value) => (
              <label key={value}>
                <input type="radio" name="platform" value={value} defaultChecked={value === platform} />
                <span>{PLATFORM_LABELS[value]}</span>
              </label>
            ))}
          </div>
        </fieldset>
      </form>

      {items.length ? (
        <section className="overview-grid" aria-label="Вузы">
          {items.map((item) => <OverviewCard item={item} key={item.entityId} />)}
        </section>
      ) : (
        <EmptyState
          title="Подходящих данных пока нет"
          description="Измените площадку, период или поисковый запрос. Пустой ответ API не заменяется нулевыми показателями."
          action={{ href: "/", label: "Сбросить фильтры" }}
        />
      )}

      <div className="dataset-line">
        <span>Согласованный срез: {formatDate(page.asOf)}</span>
        <span>Показано: {items.length} · период {PERIOD_LABELS[period]}</span>
      </div>

      {page.nextCursor ? (
        <nav className="pagination" aria-label="Пагинация">
          <Link className="button-link secondary-button" href={queryHref("/", {
            platform, period, q, sort, direction, cursor: page.nextCursor,
          })}>Следующая страница</Link>
        </nav>
      ) : null}

      <InfoNotice>
        {platform === "all" ? (
          <><strong>Почему нет общей суммы:</strong> лайк, реакция, просмотр видео и просмотр поста имеют разный смысл.
          Общий режим показывает покрытие и официальный общий М‑Рейтинг.</>
        ) : (
          <><strong>Как считаются показатели:</strong> для каждой публикации берётся разница между первым и последним
          сравнимым снимком внутри окна. Недоступные метрики не заменяются нулями.</>
        )}
      </InfoNotice>
    </>
  );
}
