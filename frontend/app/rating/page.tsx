import { accountHref, publicationHref } from "@/lib/entity-routes";
import { PlatformPending } from "@/components/platform-pending";
import { RatingFilterForm } from "@/components/rating-filter-form";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "@/components/native-link";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { PERIOD_LABELS, PLATFORM_LONG_LABELS, publicationLabel } from "@/lib/format";
import { first, queryHref, type SearchParams } from "@/lib/params";
import { normalizeRatingQuery, type ParsedRatingQuery } from "@/lib/rating";
import type {
  ActivityRatingEntity,
  ActivityRatingPublication,
  ActivityRatingPostSort,
  ActivityRatingChannelSort,
} from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Рейтинг активности",
  description: "Сравнение активности официальных соцсетей вузов по последним замерам публикаций.",
  openGraph: {
    title: "Рейтинг активности вузов — M‑Ranked",
    description: "Сравнение активности официальных соцсетей вузов по последним замерам публикаций.",
  },
  twitter: {
    card: "summary",
    title: "Рейтинг активности вузов — M‑Ranked",
    description: "Сравнение активности официальных соцсетей вузов по последним замерам публикаций.",
  },
};

export default async function RatingPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const rawParams = await searchParams;
  const query = normalizeRatingQuery(rawParams);
  const entityCursor = first(rawParams.entityCursor);
  const { platform, period } = query;

  if (platform === "max" || platform === "all") return <PlatformPending platform={platform} kind="rating" />;

  let page;
  try {
    page = await api.rating({ ...query, platform, entityLimit: 200, entityCursor });
  } catch (error) {
    if (entityCursor && error instanceof ApiError && error.status === 400) return <section className="panel empty-state"><h1>Рейтинг обновился</h1><p>Откройте первую страницу, чтобы продолжить в актуальном срезе данных.</p><Link href={queryHref("/rating", ratingHrefQuery(query))} prefetch={false}>Начать с первой страницы</Link></section>;
    return (
      <>
        <PageHeader title="Рейтинг каналов и публикаций" description="Сравнение активности по последнему замеру каждой публикации." />
        <ApiFailureState retryHref={queryHref("/rating", ratingHrefQuery(query))} />
      </>
    );
  }

  const title = platform === "telegram"
    ? "Рейтинг каналов и публикаций"
    : `Рейтинг · ${PLATFORM_LONG_LABELS[platform]}`;
  return (
    <>
      <div className="section-head"><div><h1>{title}</h1><p className="lead">{platform === "telegram" ? "Для каждой публикации берётся её последний замер за выбранный период." : `Только публикации и замеры ${PLATFORM_LONG_LABELS[platform]}. Данные других площадок в расчёт не входят.`}</p></div></div>
      <RatingFilterForm key={`${period}:${page.channelSort}:${page.channelDirection}:${page.postSort}:${page.postDirection}`} className="controls panel compact rating-controls" action="/rating" method="get" aria-label="Настройка рейтинга">
        <input type="hidden" name="platform" value={platform} />
        <label><span>Период ⓘ</span><br /><select name="period" defaultValue={period}>{Object.entries(PERIOD_LABELS).map(([value,label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <input type="hidden" name="channel_sort" value={page.channelSort} /><input type="hidden" name="channel_direction" value={page.channelDirection} /><input type="hidden" name="post_sort" value={page.postSort} /><input type="hidden" name="post_direction" value={page.postDirection} /><button type="submit">Применить</button>
      </RatingFilterForm>

      {platform === "telegram"
        ? <TelegramEntityTable query={query} rows={page.entities} offset={page.entityOffset} />
        : <VkEntityTable query={query} rows={page.entities} offset={page.entityOffset} />}

      {page.nextEntityCursor ? <nav className="pagination" aria-label="Страницы рейтинга">
        <Link className="button-link secondary-button" href={queryHref("/rating", { ...ratingHrefQuery(query), entityCursor: page.nextEntityCursor })} prefetch={false}>Следующая страница рейтинга</Link>
      </nav> : page.entitiesTruncated ? <section className="notice notice-amber" role="alert">API ограничил список без ссылки продолжения. Полный рейтинг доступен на действующем сайте; этот маршрут ещё не готов к переключению.</section> : null}

      {platform === "telegram"
        ? <TelegramPublicationTable query={query} rows={page.publications} />
        : <VkPublicationTable query={query} rows={page.publications} />}

    </>
  );
}

function TelegramEntityTable({ query, rows, offset }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingEntity[];
  offset: number;
}) {
  return (
    <RatingSection query={query} eyebrow="Каналы" title="Рейтинг активности" empty={rows.length === 0}>
      <table className="rating-table">
        <caption className="sr-only">Каналы по активности за выбранный период</caption>
        <thead><tr><th>#</th><th>Канал</th>
          <th><EntitySortLink query={query} sort="average">Среднее реакций</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="total">Реакций всего</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="engagement">Реакции / подписчики</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="subscribers">Подписчики</EntitySortLink></th>
        </tr></thead>
        <tbody>{rows.map((row, index) => <tr key={row.entityId}>
          <td className="rank rank-cell">{offset + index + 1}</td>
          <td className="entity-cell"><Link className="entity-link" href={accountHref(row.entityId)} prefetch={false}>{row.title || `@${row.username}`}</Link><div className="muted">@{row.username} · {row.publicationCount} публикаций</div></td>
          <td><strong>{formatMetric(row.averageReactions, true)}</strong></td>
          <td>{formatMetric(row.totalReactions)}</td>
          <td><strong>{formatPercentage(row.engagementRate, 3)}</strong></td>
          <td>{formatMetric(row.subscriberCount)}</td>
        </tr>)}{!rows.length ? <EmptyRatingRow query={query} publications={false} columns={6} /> : null}</tbody>
      </table>
    </RatingSection>
  );
}

function VkEntityTable({ query, rows, offset }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingEntity[];
  offset: number;
}) {
  return (
    <RatingSection query={query} eyebrow="Вузы" title="Рейтинг активности ВК" empty={rows.length === 0}>
      <table className="rating-table">
        <caption className="sr-only">Вузы по активности ВКонтакте</caption>
        <thead><tr><th>#</th><th>Вуз</th>
          <th><EntitySortLink query={query} sort="average">Среднее лайков</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="total">Лайков всего</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="views">Просмотры</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="engagement">Вовлечённость</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="subscribers">Подписчики</EntitySortLink></th>
        </tr></thead>
        <tbody>{rows.map((row, index) => <tr key={row.entityId}>
          <td className="rank rank-cell">{offset + index + 1}</td>
          <td className="entity-cell"><Link className="entity-link" href={queryHref(row.legacyRoute, { platform: query.platform })} prefetch={false}>{row.shortName || row.canonicalName}</Link><div className="muted">{row.publicationCount} публикаций · {formatMetric(row.totalComments)} комментариев{query.platform === "vk" ? ` · ${formatMetric(row.totalShares)} репостов` : ""}</div></td>
          <td><strong>{formatMetric(row.averageReactions, true)}</strong></td>
          <td>{formatMetric(row.totalReactions)}</td><td>{formatMetric(row.totalViews)}</td>
          <td><strong>{formatPercentage(row.engagementRate)}</strong></td>
          <td>{formatMetric(row.subscriberCount)}</td>
        </tr>)}{!rows.length ? <EmptyRatingRow query={query} publications={false} columns={7} /> : null}</tbody>
      </table>
    </RatingSection>
  );
}

function TelegramPublicationTable({ query, rows }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingPublication[];
}) {
  return (
    <RatingSection query={query} eyebrow="Публикации" title="Рейтинг публикаций" empty={rows.length === 0}>
      <table className="rating-table">
        <caption className="sr-only">Публикации Telegram по активности</caption>
        <thead><tr><th>#</th><th>Публикация</th>
          <th><PostSortLink query={query} sort="reactions">Реакции</PostSortLink></th>
          <th><PostSortLink query={query} sort="views">Просмотры</PostSortLink></th>
          <th><PostSortLink query={query} sort="subscriber_share">Реакции / подписчики</PostSortLink></th>
          <th><PostSortLink query={query} sort="view_share">Реакции / просмотры</PostSortLink></th>
        </tr></thead>
        <tbody>{rows.map((row, index) => {
          const external = telegramExternalLink(row);
          const label = `${row.accountTitle || `@${row.accountUsername}`} · №${row.externalId ?? "—"}`;
          return <tr key={row.publicationId}>
            <td className="rank rank-cell">{index + 1}</td>
            <td className="entity-cell">{row.publicationId ? <Link className="entity-link" href={publicationHref(row.publicationId)} prefetch={false}>{label}</Link> : <strong>{label}</strong>}
              {external ? <a href={external} target="_blank" rel="noopener noreferrer">{row.deletedAt ? "Открыть сохранённую публикацию в TGStat" : "Открыть пост в Telegram"} ↗</a> : null}
              {row.deletedAt ? <span>удалена из Telegram</span> : null}
            </td>
            <td><strong>{formatMetric(row.reactions)}</strong></td><td>{formatMetric(row.views)}</td>
            <td>{formatPercentage(row.subscriberShare, 3)}</td><td>{formatPercentage(row.viewShare)}</td>
          </tr>;
        })}{!rows.length ? <EmptyRatingRow query={query} publications columns={6} /> : null}</tbody>
      </table>
    </RatingSection>
  );
}

function VkPublicationTable({ query, rows }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingPublication[];
}) {
  return (
    <RatingSection query={query} eyebrow="Публикации" title="Публикации ВК" empty={rows.length === 0}>
      <table className="rating-table">
        <caption className="sr-only">Публикации ВКонтакте по активности</caption>
        <thead><tr><th>#</th><th>Публикация</th>
          <th><PostSortLink query={query} sort="reactions">Лайки</PostSortLink></th>
          <th><PostSortLink query={query} sort="views">Просмотры</PostSortLink></th>
          <th><PostSortLink query={query} sort="comments">Комментарии</PostSortLink></th>
          {query.platform === "vk" ? <th><PostSortLink query={query} sort="shares">Репосты</PostSortLink></th> : null}
          <th><PostSortLink query={query} sort="view_share">Вовлечённость</PostSortLink></th>
        </tr></thead>
        <tbody>{rows.map((row, index) => <PlatformPublicationRow key={row.publicationId} row={row} index={index} showInteractions showShares={query.platform === "vk"} />)}{!rows.length ? <EmptyRatingRow query={query} publications columns={query.platform === "vk" ? 7 : 6} /> : null}</tbody>
      </table>
    </RatingSection>
  );
}

function PlatformPublicationRow({ row, index, showInteractions, showShares=false }: {
  row: ActivityRatingPublication;
  index: number;
  showInteractions: boolean;
  showShares?: boolean;
}) {
  const label = `${row.institutionShortName || row.institutionCanonicalName} · ${publicationLabel(row.externalId ?? "",showShares ? "vk" : "rutube")}`;
  return <tr>
    <td className="rank rank-cell">{index + 1}</td>
    <td className="entity-cell">{row.publicationId ? <Link className="entity-link" href={publicationHref(row.publicationId)} prefetch={false}>{label}</Link> : <strong>{label}</strong>}
      {row.deletedAt ? <span className="pill deleted">удалена</span> : null}
      {row.joint ? <span className="pill coauthor">+{row.additionalAuthorCount} авт.</span> : null}
      {row.repost ? <span className="pill repost">репост</span> : null}
      {row.publicUrl ? <a className="telegram-link external" href={row.publicUrl} target="_blank" rel="noopener noreferrer">Открыть публикацию {showShares ? "VK" : "Rutube"}</a> : null}
    </td>
    {showInteractions ? <>
      <td><strong>{formatMetric(row.reactions)}</strong></td><td>{formatMetric(row.views)}</td>
      <td>{formatMetric(row.comments)}</td>{showShares ? <td>{formatMetric(row.shares)}</td> : null}
      <td>{formatPercentage(row.viewShare)}</td>
    </> : <td><strong>{formatMetric(row.views)}</strong></td>}
  </tr>;
}

function RatingSection({ query, eyebrow, title, children }: {
  query: ParsedRatingQuery; eyebrow: string; title: string; empty: boolean; children: ReactNode;
}) {
  const telegram=query.platform === "telegram", publications=eyebrow === "Публикации";
  const name=publications ? telegram ? "Публикации" : `Публикации ${PLATFORM_LONG_LABELS[query.platform]}` : telegram ? "Каналы" : "Вузы";
  const badge={"3h":"3 часа","1d":"24 часа","7d":"7 дней","30d":"30 дней"}[query.period];
  const description=publications ? telegram ? "Сравнение отдельных постов по реакциям, просмотрам и их соотношению." : "Последний известный замер каждой публикации, вышедшей за период." : telegram ? "Типичная и общая активность каналов в сравнении с размером аудитории." : `Если у вуза несколько аккаунтов ${PLATFORM_LONG_LABELS[query.platform]}, их публикации объединяются.`;
  return <section className="panel section rating-panel" aria-label={title}>
    <div className="rating-panel-head"><div><h2>{name}</h2><p className="panel-note">{description}</p></div><span className="period-badge">Период: {badge}</span></div>
    {!publications ? <div className="rating-explanation">{telegram ? <><b>По умолчанию:</b> выше показаны каналы с большей долей среднего числа реакций от текущего числа подписчиков.</> : <><b>Вовлечённость:</b> (лайки + комментарии{query.platform === "vk" ? " + репосты" : ""}) / просмотры. Это отношение событий, а не уникальных пользователей.</>}</div> : telegram ? <div className="rating-explanation">Название вуза открывает <b>внутреннюю статистику</b>. Ссылка «Открыть пост в Telegram ↗» ведёт на оригинал в новой вкладке.</div> : null}
    <div className="table-wrap rating-table-wrap">{children}</div>
  </section>;
}

function EmptyRatingRow({query,publications,columns}:{query:ParsedRatingQuery;publications:boolean;columns:number}) {
  const telegram=query.platform === "telegram";
  return <tr><td colSpan={columns} className="empty-state">{publications ? telegram ? "Пока нет замеров." : `Пока нет публикаций ${PLATFORM_LONG_LABELS[query.platform]} за выбранный период.` : `Данные появятся после первого замера${telegram ? "" : ` ${PLATFORM_LONG_LABELS[query.platform]}`}.`}</td></tr>;
}

function EntitySortLink({ query, sort, children }: {
  query: ParsedRatingQuery;
  sort: ActivityRatingChannelSort;
  children: ReactNode;
}) {
  const direction = query.channelSort === sort && query.channelDirection === "desc" ? "asc" : "desc";
  return <Link className="sort-link has-tooltip" scroll={false} prefetch={false} href={queryHref("/rating", {
    ...ratingHrefQuery(query), channel_sort: sort, channel_direction: direction,
  })}>{children} <span className="info-mark" aria-hidden="true">ⓘ</span>{query.channelSort === sort ? <span className="sort-direction">{query.channelDirection === "desc" ? "↓" : "↑"}</span> : null}</Link>;
}

function PostSortLink({ query, sort, children }: {
  query: ParsedRatingQuery;
  sort: ActivityRatingPostSort;
  children: ReactNode;
}) {
  const direction = query.postSort === sort && query.postDirection === "desc" ? "asc" : "desc";
  return <Link className="sort-link has-tooltip" scroll={false} prefetch={false} href={queryHref("/rating", {
    ...ratingHrefQuery(query), post_sort: sort, post_direction: direction,
  })}>{children} <span className="info-mark" aria-hidden="true">ⓘ</span>{query.postSort === sort ? <span className="sort-direction">{query.postDirection === "desc" ? "↓" : "↑"}</span> : null}</Link>;
}

function ratingHrefQuery(query: ParsedRatingQuery) {
  return {
    platform: query.platform,
    period: query.period,
    channel_sort: query.channelSort,
    channel_direction: query.channelDirection,
    post_sort: query.postSort,
    post_direction: query.postDirection,
  };
}

function telegramExternalLink(row: ActivityRatingPublication): string | null {
  if (!row.accountUsername || !row.externalId) return row.publicUrl;
  const username = encodeURIComponent(row.accountUsername.replace(/^@/, ""));
  const message = encodeURIComponent(row.externalId);
  return row.deletedAt
    ? `https://tgstat.ru/channel/@${username}/${message}`
    : `https://t.me/${username}/${message}`;
}

function formatMetric(value: number | null, fraction=false) { return value === null ? "—" : fraction ? value.toFixed(1) : String(value); }
function formatPercentage(value: number | null, digits=2) { return value === null ? "—" : `${value.toFixed(digits)}%`; }
