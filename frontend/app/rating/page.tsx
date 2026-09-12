import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import { ApiFailureState, PageHeader, StatusPill } from "@/components/ui";
import { api } from "@/lib/api";
import { formatMetric, formatPercentage, PERIOD_LABELS, PLATFORM_LABELS } from "@/lib/format";
import { queryHref, type SearchParams } from "@/lib/params";
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
  const query = normalizeRatingQuery(await searchParams);
  const { platform, period } = query;

  if (platform === "max" || platform === "all") {
    return (
      <>
        <PageHeader
          title={`Рейтинг · ${PLATFORM_LABELS[platform]}`}
          description="Рейтинг будет построен только по выбранной площадке."
        />
        <section className="panel section platform-pending">
          <StatusPill tone="neutral">{PLATFORM_LABELS[platform]}</StatusPill>
          <div>
            <h2>Раздел не смешивает данные разных соцсетей</h2>
            <p className="muted">Платформенный контекст сохранён в адресе и навигации. Данные Telegram здесь намеренно не показываются вместо выбранной площадки.</p>
          </div>
          <Link className="secondary-button" href={queryHref("/", { platform })}>Вернуться к обзору</Link>
        </section>
      </>
    );
  }

  let page;
  try {
    page = await api.rating({ ...query, platform, entityLimit: 200 });
  } catch {
    return (
      <>
        <PageHeader title="Рейтинг каналов и публикаций" description="Сравнение активности по последнему замеру каждой публикации." />
        <ApiFailureState retryHref={queryHref("/rating", ratingHrefQuery(query))} />
      </>
    );
  }

  const title = platform === "telegram"
    ? "Рейтинг каналов и публикаций"
    : `Рейтинг · ${PLATFORM_LABELS[platform]}`;
  return (
    <>
      <PageHeader
        title={title}
        description={`Только публикации и замеры ${PLATFORM_LABELS[platform]}. Для каждой публикации берётся последний замер за выбранный период.`}
        meta={<StatusPill tone="blue">период {PERIOD_LABELS[period]}</StatusPill>}
      />
      <form className="panel filter-panel" action="/rating" method="get" aria-label="Настройка рейтинга">
        <div className="filter-grid rating-filter">
          <input type="hidden" name="platform" value={platform} />
          <label className="field"><span>Период</span><select name="period" defaultValue={period}>
            {Object.entries(PERIOD_LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
          </select></label>
          <input type="hidden" name="channel_sort" value={page.channelSort} />
          <input type="hidden" name="channel_direction" value={page.channelDirection} />
          <input type="hidden" name="post_sort" value={page.postSort} />
          <input type="hidden" name="post_direction" value={page.postDirection} />
          <button type="submit">Применить</button>
        </div>
      </form>

      {platform === "telegram"
        ? <TelegramEntityTable query={query} rows={page.entities} />
        : platform === "rutube"
          ? <RutubeEntityTable query={query} rows={page.entities} />
          : <VkEntityTable query={query} rows={page.entities} />}

      {platform === "telegram"
        ? <TelegramPublicationTable query={query} rows={page.publications} />
        : platform === "rutube"
          ? <RutubePublicationTable query={query} rows={page.publications} />
          : <VkPublicationTable query={query} rows={page.publications} />}

    </>
  );
}

function TelegramEntityTable({ query, rows }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingEntity[];
}) {
  return (
    <RatingSection eyebrow="Каналы" title="Рейтинг активности" empty={rows.length === 0}>
      <table>
        <caption className="sr-only">Каналы по активности за выбранный период</caption>
        <thead><tr><th>#</th><th>Канал</th>
          <th><EntitySortLink query={query} sort="average">Среднее реакций</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="total">Реакций всего</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="engagement">Реакции / подписчики</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="subscribers">Подписчики</EntitySortLink></th>
        </tr></thead>
        <tbody>{rows.map((row, index) => <tr key={row.entityId}>
          <td className="rank-cell">{index + 1}</td>
          <td className="entity-cell"><Link href={row.legacyRoute}>{row.title || `@${row.username}`}</Link><span>@{row.username} · {row.publicationCount} публикаций</span></td>
          <td><strong>{formatMetric(row.averageReactions, true)}</strong></td>
          <td>{formatMetric(row.totalReactions)}</td>
          <td><strong>{formatPercentage(row.engagementRate, 3)}</strong></td>
          <td>{formatMetric(row.subscriberCount)}</td>
        </tr>)}</tbody>
      </table>
    </RatingSection>
  );
}

function VkEntityTable({ query, rows }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingEntity[];
}) {
  return (
    <RatingSection eyebrow="Вузы" title="Рейтинг активности ВК" empty={rows.length === 0}>
      <table>
        <caption className="sr-only">Вузы по активности ВКонтакте</caption>
        <thead><tr><th>#</th><th>Вуз</th>
          <th><EntitySortLink query={query} sort="average">Среднее лайков</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="total">Лайков всего</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="views">Просмотры</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="engagement">Вовлечённость</EntitySortLink></th>
          <th><EntitySortLink query={query} sort="subscribers">Подписчики</EntitySortLink></th>
        </tr></thead>
        <tbody>{rows.map((row, index) => <tr key={row.entityId}>
          <td className="rank-cell">{index + 1}</td>
          <td className="entity-cell"><Link href={queryHref(row.legacyRoute, { platform: query.platform })}>{row.shortName || row.canonicalName}</Link><span>{row.publicationCount} публикаций · {formatMetric(row.totalComments)} комментариев · {formatMetric(row.totalShares)} репостов</span></td>
          <td><strong>{formatMetric(row.averageReactions, true)}</strong></td>
          <td>{formatMetric(row.totalReactions)}</td><td>{formatMetric(row.totalViews)}</td>
          <td><strong>{formatPercentage(row.engagementRate)}</strong></td>
          <td>{formatMetric(row.subscriberCount)}</td>
        </tr>)}</tbody>
      </table>
    </RatingSection>
  );
}

function RutubeEntityTable({ query, rows }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingEntity[];
}) {
  return (
    <RatingSection eyebrow="Вузы" title="Рейтинг просмотров Rutube" empty={rows.length === 0}>
      <table>
        <caption className="sr-only">Вузы по просмотрам Rutube</caption>
        <thead><tr><th>#</th><th>Вуз</th><th><RawEntitySortLink query={query} sort="average_views">Среднее просмотров</RawEntitySortLink></th>
          <th><EntitySortLink query={query} sort="views">Просмотры всего</EntitySortLink></th>
          <th><RawEntitySortLink query={query} sort="posts">Видео</RawEntitySortLink></th>
          <th><EntitySortLink query={query} sort="subscribers">Подписчики</EntitySortLink></th>
        </tr></thead>
        <tbody>{rows.map((row, index) => <tr key={row.entityId}>
          <td className="rank-cell">{index + 1}</td>
          <td className="entity-cell"><Link href={queryHref(row.legacyRoute, { platform: query.platform })}>{row.shortName || row.canonicalName}</Link></td>
          <td><strong>{formatMetric(row.averageViews, true)}</strong></td>
          <td>{formatMetric(row.totalViews)}</td><td>{row.publicationCount}</td>
          <td>{formatMetric(row.subscriberCount)}</td>
        </tr>)}</tbody>
      </table>
    </RatingSection>
  );
}

function TelegramPublicationTable({ query, rows }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingPublication[];
}) {
  return (
    <RatingSection eyebrow="Публикации" title="Рейтинг публикаций" empty={rows.length === 0}>
      <table>
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
            <td className="rank-cell">{index + 1}</td>
            <td className="entity-cell">{row.legacyRoute ? <Link href={row.legacyRoute}>{label}</Link> : <strong>{label}</strong>}
              {external ? <a href={external} target="_blank" rel="noopener noreferrer">{row.deletedAt ? "Открыть сохранённую публикацию в TGStat" : "Открыть пост в Telegram"} ↗</a> : null}
              {row.deletedAt ? <span>удалена из Telegram</span> : null}
            </td>
            <td><strong>{formatMetric(row.reactions)}</strong></td><td>{formatMetric(row.views)}</td>
            <td>{formatPercentage(row.subscriberShare, 3)}</td><td>{formatPercentage(row.viewShare)}</td>
          </tr>;
        })}</tbody>
      </table>
    </RatingSection>
  );
}

function VkPublicationTable({ query, rows }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingPublication[];
}) {
  return (
    <RatingSection eyebrow="Публикации" title="Публикации ВК" empty={rows.length === 0}>
      <table>
        <caption className="sr-only">Публикации ВКонтакте по активности</caption>
        <thead><tr><th>#</th><th>Публикация</th>
          <th><PostSortLink query={query} sort="reactions">Лайки</PostSortLink></th>
          <th><PostSortLink query={query} sort="views">Просмотры</PostSortLink></th>
          <th><PostSortLink query={query} sort="comments">Комментарии</PostSortLink></th>
          <th><PostSortLink query={query} sort="shares">Репосты</PostSortLink></th>
          <th><PostSortLink query={query} sort="view_share">Вовлечённость</PostSortLink></th>
        </tr></thead>
        <tbody>{rows.map((row, index) => <PlatformPublicationRow key={row.publicationId} row={row} index={index} showInteractions />)}</tbody>
      </table>
    </RatingSection>
  );
}

function RutubePublicationTable({ query, rows }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingPublication[];
}) {
  return (
    <RatingSection eyebrow="Публикации" title="Видео Rutube" empty={rows.length === 0}>
      <table>
        <caption className="sr-only">Видео Rutube по просмотрам</caption>
        <thead><tr><th>#</th><th>Видео</th><th><PostSortLink query={query} sort="views">Просмотры</PostSortLink></th></tr></thead>
        <tbody>{rows.map((row, index) => <PlatformPublicationRow key={row.publicationId} row={row} index={index} showInteractions={false} />)}</tbody>
      </table>
    </RatingSection>
  );
}

function PlatformPublicationRow({ row, index, showInteractions }: {
  row: ActivityRatingPublication;
  index: number;
  showInteractions: boolean;
}) {
  const label = `${row.institutionShortName || row.institutionCanonicalName} · ${row.externalId ?? "публикация"}`;
  return <tr>
    <td className="rank-cell">{index + 1}</td>
    <td className="entity-cell">{row.legacyRoute ? <Link href={row.legacyRoute}>{label}</Link> : <strong>{label}</strong>}
      {row.publicUrl ? <a href={row.publicUrl} target="_blank" rel="noopener noreferrer">Открыть публикацию ↗</a> : null}
      {row.deletedAt ? <span>удалена</span> : null}
      {row.joint ? <span>+{row.additionalAuthorCount} авт.</span> : null}
      {row.repost ? <span>репост</span> : null}
    </td>
    {showInteractions ? <>
      <td><strong>{formatMetric(row.reactions)}</strong></td><td>{formatMetric(row.views)}</td>
      <td>{formatMetric(row.comments)}</td><td>{formatMetric(row.shares)}</td>
      <td>{formatPercentage(row.viewShare)}</td>
    </> : <td><strong>{formatMetric(row.views)}</strong></td>}
  </tr>;
}

function RatingSection({ eyebrow, title, empty, children }: {
  eyebrow: string;
  title: string;
  empty: boolean;
  children: ReactNode;
}) {
  return <section className="panel section">
    <div className="section-head"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div></div>
    {empty
      ? <div className="embedded-empty"><p>За выбранный период пока нет подходящих замеров.</p></div>
      : <div className="table-wrap">{children}</div>}
  </section>;
}

function EntitySortLink({ query, sort, children }: {
  query: ParsedRatingQuery;
  sort: ActivityRatingChannelSort;
  children: ReactNode;
}) {
  const direction = query.channelSort === sort && query.channelDirection === "desc" ? "asc" : "desc";
  return <Link href={queryHref("/rating", {
    ...ratingHrefQuery(query), channel_sort: sort, channel_direction: direction,
  })}>{children}{query.channelSort === sort ? ` ${query.channelDirection === "desc" ? "↓" : "↑"}` : ""}</Link>;
}

function PostSortLink({ query, sort, children }: {
  query: ParsedRatingQuery;
  sort: ActivityRatingPostSort;
  children: ReactNode;
}) {
  const direction = query.postSort === sort && query.postDirection === "desc" ? "asc" : "desc";
  return <Link href={queryHref("/rating", {
    ...ratingHrefQuery(query), post_sort: sort, post_direction: direction,
  })}>{children}{query.postSort === sort ? ` ${query.postDirection === "desc" ? "↓" : "↑"}` : ""}</Link>;
}

function RawEntitySortLink({ query, sort, children }: {
  query: ParsedRatingQuery;
  sort: "average_views" | "posts";
  children: ReactNode;
}) {
  return <Link href={queryHref("/rating", {
    ...ratingHrefQuery(query), channel_sort: sort, channel_direction: "desc",
  })}>{children}</Link>;
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
