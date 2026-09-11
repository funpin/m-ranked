import type { Metadata } from "next";
import { LegacyFilterForm } from "@/components/legacy-filter-form";
import Link from "@/components/native-link";
import { OverviewCard } from "@/components/overview-card";
import { ApiFailureState, PageHeader } from "@/components/ui";
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
      <h1>{platform === "all" ? "Обзор вузов" : "Обзор каналов"}</h1>
      <p className="lead">{platform === "all" ? <><b>Общий контур вуза:</b> официальные аккаунты и общий М‑Рейтинг без сложения несопоставимых метрик разных площадок.</> : platform === "telegram" ? <><b>Активность всех постов в базе за выбранный период</b> — включая публикации, вышедшие раньше. Это прирост реакций и просмотров внутри временного окна, а не сумма текущих показателей только у новых постов.</> : <><b>Активность всех публикаций в базе за выбранный период</b> — включая публикации, вышедшие раньше. Это прирост доступных метрик {PLATFORM_LONG_LABELS[platform]} внутри временного окна, а не сумма текущих показателей только у новых публикаций. Данные других соцсетей в расчёт не попадают.</>}</p>

      <LegacyFilterForm key={`${platform}:${period}:${sort}:${direction}:${q}`} className="panel controls compact" action="/" method="get" aria-label="Фильтры обзора">
          <label className="overview-search">
            Поиск вуза<br />
            <input name="q" type="search" defaultValue={q} placeholder="Сокращение или полное название" />
          </label>
          <label>
            Период<br />
            <select name="period" defaultValue={period}>
              {Object.entries(PERIOD_LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
            </select>
          </label>
          <label>
            <span>Сортировать ⓘ</span><br />
            <select name="sort" defaultValue={sort}>
              <option value="name">Название вуза · алфавит</option>
              {platform === "all" ? (
                <>
                  <option value="m_rating">Общий М‑Рейтинг · место</option>
                  <option value="coverage">Подключённые площадки</option>
                  <option value="accounts">Количество аккаунтов</option>
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
            </select>
          </label>
          <label>
            Порядок<br />
            <select name="direction" defaultValue={direction}>
              <option value="desc">По убыванию</option>
              <option value="asc">По возрастанию</option>
            </select>
          </label>
          <button type="submit">Применить</button>
        <fieldset className="platform-selector">
          <legend className="sr-only">Площадка</legend><span aria-hidden="true">Площадка</span>
          <div className="platform-segments segments">
            {PLATFORM_VALUES.map((value) => (
              <label key={value}>
                <input type="radio" name="platform" value={value} defaultChecked={value === platform} />
                <span>{PLATFORM_LABELS[value]}</span>
              </label>
            ))}
          </div>
        </fieldset>
      </LegacyFilterForm>

      <section className="grid section overview-grid" aria-label="Вузы">{items.length ? (
        <>
          {items.map((item) => <OverviewCard item={item} integrationWarning={page.integrationWarning} key={item.entityId} />)}
        </>
      ) : (
        <div className="panel">{q ? `По запросу «${q}» вузы не найдены.` : platform === "telegram" ? "За выбранный период публикаций не найдено." : "Вузы ещё не добавлены."}</div>
      )}</section>

      {page.nextCursor ? (
        <nav className="pagination" aria-label="Пагинация">
          <Link className="button-link secondary-button" prefetch={false} href={queryHref("/", {
            platform, period, q, sort, direction, cursor: page.nextCursor,
          })}>Следующая страница</Link>
        </nav>
      ) : null}

      <p className="notice section">
        {platform === "all" ? <><b>Почему нет общей суммы:</b> лайк, реакция, просмотр видео и просмотр поста имеют разный смысл. Общий режим показывает покрытие и официальный общий М‑Рейтинг; единый межплатформенный индекс будет добавлен только после утверждения формулы.</> : platform === "telegram" ? <><b>Как считаются показатели:</b> в карточке показана активность всех отслеживаемых постов, для которых внутри выбранного периода есть сравнимые замеры, а не только новых публикаций. Реакции и просмотры — разница между первым и последним замером внутри окна; прирост до первого замера в период не включается. Для новых постов с полной историей отсчёт идёт от нуля в момент публикации. Медианы — типичный прирост одного поста за это окно и округляются до целого. Плашка у медианы сравнивает типичный прирост с предыдущим таким же периодом и скрывается, если сравнивать не с чем или изменения нет. Метки скачков временно отключены.</> : <><b>Как считаются показатели:</b> для каждой публикации берётся разница между первым и последним сравнимым снимком внутри окна. Метрики, которых нет в официальном источнике {PLATFORM_LONG_LABELS[platform]}, не заменяются нулями и не подменяются Telegram-данными.</>}
      </p>
    </>
  );
}
