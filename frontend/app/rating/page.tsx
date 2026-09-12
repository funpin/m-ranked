import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { NativeButton } from "@/components/native-field";
import { NativeSelect } from "@/components/native-field";
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
    if (entityCursor && error instanceof ApiError && error.status === 400) return <section className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm space-y-3 py-10 text-center text-muted-foreground"><h1 className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl">Рейтинг обновился</h1><p>Откройте первую страницу, чтобы продолжить в актуальном срезе данных.</p><Link href={queryHref("/rating", ratingHrefQuery(query))} prefetch={false}>Начать с первой страницы</Link></section>;
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
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3"><div><h1 className="font-heading text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1><p className="mt-2 mb-5 text-sm text-muted-foreground">{platform === "telegram" ? "Для каждой публикации берётся её последний замер за выбранный период." : `Только публикации и замеры ${PLATFORM_LONG_LABELS[platform]}. Данные других площадок в расчёт не входят.`}</p></div></div>
      <RatingFilterForm key={`${period}:${page.channelSort}:${page.channelDirection}:${page.postSort}:${page.postDirection}`} className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm mb-5 flex flex-wrap items-end gap-3" action="/rating" method="get" aria-label="Настройка рейтинга">
        <input type="hidden" name="platform" value={platform} />
        <label><span>Период ⓘ</span><br /><NativeSelect name="period" defaultValue={period}>{Object.entries(PERIOD_LABELS).map(([value,label]) => <option value={value} key={value}>{label}</option>)}</NativeSelect></label>
        <input type="hidden" name="channel_sort" value={page.channelSort} /><input type="hidden" name="channel_direction" value={page.channelDirection} /><input type="hidden" name="post_sort" value={page.postSort} /><input type="hidden" name="post_direction" value={page.postDirection} /><NativeButton type="submit">Применить</NativeButton>
      </RatingFilterForm>

      {platform === "telegram"
        ? <TelegramEntityTable query={query} rows={page.entities} offset={page.entityOffset} />
        : <VkEntityTable query={query} rows={page.entities} offset={page.entityOffset} />}

      {page.nextEntityCursor ? <nav className="my-5 flex flex-wrap justify-end gap-2" aria-label="Страницы рейтинга">
        <Link className="inline-flex min-h-9 items-center justify-center rounded-md border px-3 py-2 text-sm font-medium hover:bg-accent" href={queryHref("/rating", { ...ratingHrefQuery(query), entityCursor: page.nextEntityCursor })} prefetch={false}>Следующая страница рейтинга</Link>
      </nav> : page.entitiesTruncated ? <section className="my-4 rounded-lg border p-4 text-sm border-warning/30 bg-warning/10 text-warning" role="alert">API ограничил список без ссылки продолжения. Полный рейтинг доступен на действующем сайте; этот маршрут ещё не готов к переключению.</section> : null}

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
      <Table data-testid="rating-table" className="tabular">
        <caption className="sr-only">Каналы по активности за выбранный период</caption>
        <TableHeader><TableRow><TableHead>#</TableHead><TableHead>Канал</TableHead>
          <TableHead><EntitySortLink query={query} sort="average">Среднее реакций</EntitySortLink></TableHead>
          <TableHead><EntitySortLink query={query} sort="total">Реакций всего</EntitySortLink></TableHead>
          <TableHead><EntitySortLink query={query} sort="engagement">Реакции / подписчики</EntitySortLink></TableHead>
          <TableHead><EntitySortLink query={query} sort="subscribers">Подписчики</EntitySortLink></TableHead>
        </TableRow></TableHeader>
        <TableBody>{rows.map((row, index) => <TableRow key={row.entityId}>
          <TableCell className="text-muted-foreground w-10">{offset + index + 1}</TableCell>
          <TableCell className="min-w-52 whitespace-normal"><Link data-testid="rating-entity-link" className="font-semibold underline-offset-4 hover:underline" href={accountHref(row.entityId)} prefetch={false}>{row.title || `@${row.username}`}</Link><div className="text-muted-foreground">@{row.username} · {row.publicationCount} публикаций</div></TableCell>
          <TableCell><strong>{formatMetric(row.averageReactions, true)}</strong></TableCell>
          <TableCell>{formatMetric(row.totalReactions)}</TableCell>
          <TableCell><strong>{formatPercentage(row.engagementRate, 3)}</strong></TableCell>
          <TableCell>{formatMetric(row.subscriberCount)}</TableCell>
        </TableRow>)}{!rows.length ? <EmptyRatingRow query={query} publications={false} columns={6} /> : null}</TableBody>
      </Table>
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
      <Table data-testid="rating-table" className="tabular">
        <caption className="sr-only">Вузы по активности ВКонтакте</caption>
        <TableHeader><TableRow><TableHead>#</TableHead><TableHead>Вуз</TableHead>
          <TableHead><EntitySortLink query={query} sort="average">Среднее лайков</EntitySortLink></TableHead>
          <TableHead><EntitySortLink query={query} sort="total">Лайков всего</EntitySortLink></TableHead>
          <TableHead><EntitySortLink query={query} sort="views">Просмотры</EntitySortLink></TableHead>
          <TableHead><EntitySortLink query={query} sort="engagement">Вовлечённость</EntitySortLink></TableHead>
          <TableHead><EntitySortLink query={query} sort="subscribers">Подписчики</EntitySortLink></TableHead>
        </TableRow></TableHeader>
        <TableBody>{rows.map((row, index) => <TableRow key={row.entityId}>
          <TableCell className="text-muted-foreground w-10">{offset + index + 1}</TableCell>
          <TableCell className="min-w-52 whitespace-normal"><Link data-testid="rating-entity-link" className="font-semibold underline-offset-4 hover:underline" href={queryHref(row.legacyRoute, { platform: query.platform })} prefetch={false}>{row.shortName || row.canonicalName}</Link><div className="text-muted-foreground">{row.publicationCount} публикаций · {formatMetric(row.totalComments)} комментариев{query.platform === "vk" ? ` · ${formatMetric(row.totalShares)} репостов` : ""}</div></TableCell>
          <TableCell><strong>{formatMetric(row.averageReactions, true)}</strong></TableCell>
          <TableCell>{formatMetric(row.totalReactions)}</TableCell><TableCell>{formatMetric(row.totalViews)}</TableCell>
          <TableCell><strong>{formatPercentage(row.engagementRate)}</strong></TableCell>
          <TableCell>{formatMetric(row.subscriberCount)}</TableCell>
        </TableRow>)}{!rows.length ? <EmptyRatingRow query={query} publications={false} columns={7} /> : null}</TableBody>
      </Table>
    </RatingSection>
  );
}

function TelegramPublicationTable({ query, rows }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingPublication[];
}) {
  return (
    <RatingSection query={query} eyebrow="Публикации" title="Рейтинг публикаций" empty={rows.length === 0}>
      <Table data-testid="rating-table" className="tabular">
        <caption className="sr-only">Публикации Telegram по активности</caption>
        <TableHeader><TableRow><TableHead>#</TableHead><TableHead>Публикация</TableHead>
          <TableHead><PostSortLink query={query} sort="reactions">Реакции</PostSortLink></TableHead>
          <TableHead><PostSortLink query={query} sort="views">Просмотры</PostSortLink></TableHead>
          <TableHead><PostSortLink query={query} sort="subscriber_share">Реакции / подписчики</PostSortLink></TableHead>
          <TableHead><PostSortLink query={query} sort="view_share">Реакции / просмотры</PostSortLink></TableHead>
        </TableRow></TableHeader>
        <TableBody>{rows.map((row, index) => {
          const external = telegramExternalLink(row);
          const label = `${row.accountTitle || `@${row.accountUsername}`} · №${row.externalId ?? "—"}`;
          return <TableRow key={row.publicationId}>
            <TableCell className="text-muted-foreground w-10">{index + 1}</TableCell>
            <TableCell className="min-w-52 whitespace-normal">{row.publicationId ? <Link data-testid="rating-entity-link" className="font-semibold underline-offset-4 hover:underline" href={publicationHref(row.publicationId)} prefetch={false}>{label}</Link> : <strong>{label}</strong>}
              {external ? <a href={external} target="_blank" rel="noopener noreferrer">{row.deletedAt ? "Открыть сохранённую публикацию в TGStat" : "Открыть пост в Telegram"} ↗</a> : null}
              {row.deletedAt ? <span>удалена из Telegram</span> : null}
            </TableCell>
            <TableCell><strong>{formatMetric(row.reactions)}</strong></TableCell><TableCell>{formatMetric(row.views)}</TableCell>
            <TableCell>{formatPercentage(row.subscriberShare, 3)}</TableCell><TableCell>{formatPercentage(row.viewShare)}</TableCell>
          </TableRow>;
        })}{!rows.length ? <EmptyRatingRow query={query} publications columns={6} /> : null}</TableBody>
      </Table>
    </RatingSection>
  );
}

function VkPublicationTable({ query, rows }: {
  query: ParsedRatingQuery;
  rows: ActivityRatingPublication[];
}) {
  return (
    <RatingSection query={query} eyebrow="Публикации" title="Публикации ВК" empty={rows.length === 0}>
      <Table data-testid="rating-table" className="tabular">
        <caption className="sr-only">Публикации ВКонтакте по активности</caption>
        <TableHeader><TableRow><TableHead>#</TableHead><TableHead>Публикация</TableHead>
          <TableHead><PostSortLink query={query} sort="reactions">Лайки</PostSortLink></TableHead>
          <TableHead><PostSortLink query={query} sort="views">Просмотры</PostSortLink></TableHead>
          <TableHead><PostSortLink query={query} sort="comments">Комментарии</PostSortLink></TableHead>
          {query.platform === "vk" ? <TableHead><PostSortLink query={query} sort="shares">Репосты</PostSortLink></TableHead> : null}
          <TableHead><PostSortLink query={query} sort="view_share">Вовлечённость</PostSortLink></TableHead>
        </TableRow></TableHeader>
        <TableBody>{rows.map((row, index) => <PlatformPublicationRow key={row.publicationId} row={row} index={index} showInteractions showShares={query.platform === "vk"} />)}{!rows.length ? <EmptyRatingRow query={query} publications columns={query.platform === "vk" ? 7 : 6} /> : null}</TableBody>
      </Table>
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
  return <TableRow>
    <TableCell className="text-muted-foreground w-10">{index + 1}</TableCell>
    <TableCell className="min-w-52 whitespace-normal">{row.publicationId ? <Link data-testid="rating-entity-link" className="font-semibold underline-offset-4 hover:underline" href={publicationHref(row.publicationId)} prefetch={false}>{label}</Link> : <strong>{label}</strong>}
      {row.deletedAt ? <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-destructive/10 text-destructive">удалена</span> : null}
      {row.joint ? <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-muted text-muted-foreground">+{row.additionalAuthorCount} авт.</span> : null}
      {row.repost ? <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-muted text-muted-foreground">репост</span> : null}
      {row.publicUrl ? <a className="underline underline-offset-4 text-xs underline underline-offset-4" href={row.publicUrl} target="_blank" rel="noopener noreferrer">Открыть публикацию {showShares ? "VK" : "Rutube"}</a> : null}
    </TableCell>
    {showInteractions ? <>
      <TableCell><strong>{formatMetric(row.reactions)}</strong></TableCell><TableCell>{formatMetric(row.views)}</TableCell>
      <TableCell>{formatMetric(row.comments)}</TableCell>{showShares ? <TableCell>{formatMetric(row.shares)}</TableCell> : null}
      <TableCell>{formatPercentage(row.viewShare)}</TableCell>
    </> : <TableCell><strong>{formatMetric(row.views)}</strong></TableCell>}
  </TableRow>;
}

function RatingSection({ query, eyebrow, title, children }: {
  query: ParsedRatingQuery; eyebrow: string; title: string; empty: boolean; children: ReactNode;
}) {
  const telegram=query.platform === "telegram", publications=eyebrow === "Публикации";
  const name=publications ? telegram ? "Публикации" : `Публикации ${PLATFORM_LONG_LABELS[query.platform]}` : telegram ? "Каналы" : "Вузы";
  const badge={"3h":"3 часа","1d":"24 часа","7d":"7 дней","30d":"30 дней"}[query.period];
  const description=publications ? telegram ? "Сравнение отдельных постов по реакциям, просмотрам и их соотношению." : "Последний известный замер каждой публикации, вышедшей за период." : telegram ? "Типичная и общая активность каналов в сравнении с размером аудитории." : `Если у вуза несколько аккаунтов ${PLATFORM_LONG_LABELS[query.platform]}, их публикации объединяются.`;
  return <section className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm mt-5" aria-label={title}>
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-heading text-lg font-semibold">{name}</h2><p className="mt-2 text-sm leading-relaxed text-muted-foreground">{description}</p></div><span className="inline-flex shrink-0 rounded-full bg-muted px-3 py-1 text-xs font-medium">Период: {badge}</span></div>
    {!publications ? <div className="mb-4 rounded-md bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">{telegram ? <><b>По умолчанию:</b> выше показаны каналы с большей долей среднего числа реакций от текущего числа подписчиков.</> : <><b>Вовлечённость:</b> (лайки + комментарии{query.platform === "vk" ? " + репосты" : ""}) / просмотры. Это отношение событий, а не уникальных пользователей.</>}</div> : telegram ? <div className="mb-4 rounded-md bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">Название вуза открывает <b>внутреннюю статистику</b>. Ссылка «Открыть пост в Telegram ↗» ведёт на оригинал в новой вкладке.</div> : null}
    <div className="min-w-0 overflow-x-auto">{children}</div>
  </section>;
}

function EmptyRatingRow({query,publications,columns}:{query:ParsedRatingQuery;publications:boolean;columns:number}) {
  const telegram=query.platform === "telegram";
  return <TableRow><TableCell colSpan={columns} className="space-y-3 py-10 text-center text-muted-foreground">{publications ? telegram ? "Пока нет замеров." : `Пока нет публикаций ${PLATFORM_LONG_LABELS[query.platform]} за выбранный период.` : `Данные появятся после первого замера${telegram ? "" : ` ${PLATFORM_LONG_LABELS[query.platform]}`}.`}</TableCell></TableRow>;
}

function EntitySortLink({ query, sort, children }: {
  query: ParsedRatingQuery;
  sort: ActivityRatingChannelSort;
  children: ReactNode;
}) {
  const direction = query.channelSort === sort && query.channelDirection === "desc" ? "asc" : "desc";
  return <Link className="inline-flex items-center gap-1 whitespace-normal underline-offset-4 hover:underline" scroll={false} prefetch={false} href={queryHref("/rating", {
    ...ratingHrefQuery(query), channel_sort: sort, channel_direction: direction,
  })}>{children} <span className="text-muted-foreground" aria-hidden="true">ⓘ</span>{query.channelSort === sort ? <span className="font-bold">{query.channelDirection === "desc" ? "↓" : "↑"}</span> : null}</Link>;
}

function PostSortLink({ query, sort, children }: {
  query: ParsedRatingQuery;
  sort: ActivityRatingPostSort;
  children: ReactNode;
}) {
  const direction = query.postSort === sort && query.postDirection === "desc" ? "asc" : "desc";
  return <Link className="inline-flex items-center gap-1 whitespace-normal underline-offset-4 hover:underline" scroll={false} prefetch={false} href={queryHref("/rating", {
    ...ratingHrefQuery(query), post_sort: sort, post_direction: direction,
  })}>{children} <span className="text-muted-foreground" aria-hidden="true">ⓘ</span>{query.postSort === sort ? <span className="font-bold">{query.postDirection === "desc" ? "↓" : "↑"}</span> : null}</Link>;
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
