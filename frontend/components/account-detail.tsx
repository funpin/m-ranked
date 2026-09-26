import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { publicationHref } from "@/lib/entity-routes";
import Link from "@/components/native-link";
import { deletedPublicationArchiveUrl, duration, legacyDate, legacyNumber, moscowDay, PLATFORM_LABELS, PLATFORM_LONG_LABELS, postTypeLabel, publicationLabel, qualityHint } from "@/lib/format";
import { metricEvidence } from "@/lib/metric-evidence";
import type { AccountView, PublicationListItem } from "@/lib/types";
import { ChannelSwitch } from "@/components/channel-switch";
import { DeltaBadge, type DeltaTone } from "@/components/delta-badge";
import { WeeklyTrend } from "@/components/weekly-trend";
import { NavigationBoundary } from "@/components/navigation-boundary";
import { MethodNote } from "@/components/method-note";
import { AccountSkeleton } from "@/components/skeletons";
import { DaySpotlight } from "@/components/day-spotlight";
import { RowLink } from "@/components/row-link";
import { AnomalyLevelCell } from "@/components/anomaly-level-cell";
import type { AccountLevelsLoad } from "@/lib/anomaly";


/**
 * Плитка сводки: крупное число, подпись и изменение под ними.
 *
 * Место под плашкой держится всегда, даже когда её нет: иначе шесть плиток
 * разъезжались бы по высоте в зависимости от того, у кого есть с чем
 * сравнивать.
 */
function Tile({ value, label, note, delta, tone, deltaLabel }: {
  value: string; label: string; note?: string;
  delta?: number | null; tone?: DeltaTone; deltaLabel?: string;
}) {
  return (
    <div className="grid min-w-0 content-start gap-1 rounded-lg border p-4">
      <b data-slot="account-summary-value" className="font-heading tabular text-3xl leading-none font-extrabold tracking-tight sm:text-4xl">{value}</b>
      <small className="text-muted-foreground flex min-w-0 flex-wrap items-center gap-1">
        {label}
        {note ? <MethodNote title={label}>{note}</MethodNote> : null}
      </small>
      <span className="mt-1 block min-h-[22px]">
        <DeltaBadge value={delta} tone={tone} label={deltaLabel ?? label} />
      </span>
    </div>
  );
}

/** Разница, когда обе величины известны. Иначе сравнивать не с чем. */
function change(current: number | null | undefined,
                previous: number | null | undefined): number | null {
  if (current === null || current === undefined) return null;
  if (previous === null || previous === undefined) return null;
  return current - previous;
}

function MetricWithGrowth({ value, quality, growth, label }: { value: number | null; quality: string | null; growth?: number | null; label: string }) {
  return <TableCell title={qualityHint(quality)}><span className="flex items-center gap-2 whitespace-nowrap"><span>{legacyNumber(value)}</span><DeltaBadge value={growth} compact={false} label={`${label} за выбранные сутки`} /></span></TableCell>;
}

export function AccountDetail({ account, posts, truncated = false, siblings = [], selectedDay, selectedTrend, anomalyLevels = null }: { account: AccountView; posts: PublicationListItem[]; truncated?: boolean; siblings?: readonly AccountView[]; selectedDay?: string; selectedTrend?: "median" | "total"; anomalyLevels?: Promise<AccountLevelsLoad> | null }) {
  const name = account.title || account.institutionShortName || account.institutionName;
  const institutionName = account.institutionName.trim();
  const showInstitutionName = institutionName !== name.trim();
  const stats = account.stats;
  const telegram = account.platform === "telegram";
  const series = stats?.dailySeries ?? [];
  const previous = stats?.previous ?? {
    postCount: null, monitored: null, medianReactions: null, medianViews: null,
    medianComments: null, ratingRank: null, ratingPeriod: null,
  };
  const primary = account.platform === "vk" || account.platform === "rutube" ? "лайков" : "реакций";
  return <><span data-active-platform={account.platform} hidden />
    <header className="mb-4 min-w-0">
      <h1 className="font-heading text-2xl font-semibold tracking-tight wrap-break-word sm:text-3xl">{name}{account.username ? <> <span className="text-muted-foreground">@{account.username}</span></> : null}</h1>
      {showInstitutionName ? <p data-testid="institution-full-name" className="mt-1 max-w-4xl text-sm leading-relaxed text-muted-foreground sm:text-base">{institutionName}</p> : null}
    </header>
    <ChannelSwitch accounts={siblings} currentId={account.accountId} />
    {/* Заголовок и переключатель площадок остаются на месте, а блоки с
        данными подменяются заготовкой — так же, как при смене фильтра в
        обзоре и при переходе между постами. */}
    <NavigationBoundary fallback={<AccountSkeleton chrome={false} />}>
    <div className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm">
      {stats ? <><p className="mt-2 text-sm leading-relaxed text-muted-foreground">{telegram ? `Данные ниже — по всем публикациям, которые сейчас хранятся в базе: за последние ${stats.retentionDays} дней.` : `Данные ниже — по всем публикациям ${PLATFORM_LONG_LABELS[account.platform]}, которые сейчас хранятся в базе: за последние ${stats.retentionDays} дней. Недоступные площадке метрики показываются прочерком.`}</p>
      {/* Слева шесть чисел, справа один график за неделю. Линии внутри плиток
          соперничали с самими числами и ничего толком не показывали: на ста
          пикселях ширины форма недели не читается. */}
      <div className="mt-4 grid min-w-0 gap-4 lg:grid-cols-2">
        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
          <Tile value={String(stats.postCount)} label="публикаций в базе"
            delta={change(stats.postCount, previous.postCount)} deltaLabel="публикаций за сутки" />
          <Tile value={String(stats.monitored)} label={`с полной историей${telegram ? "" : " ⓘ"}`}
            delta={change(stats.monitored, previous.monitored)} deltaLabel="с полной историей за сутки" />
          <Tile value={stats.medianReactions.value === null ? "—" : String(Math.trunc(stats.medianReactions.value))}
            label={`медиана ${primary}`} note={metricEvidence(stats.medianReactions)}
            delta={change(stats.medianReactions.value, previous.medianReactions)} />
          <Tile value={stats.medianComments.value === null ? "—" : String(Math.trunc(stats.medianComments.value))}
            label="медиана комментариев" note={metricEvidence(stats.medianComments)}
            delta={change(stats.medianComments.value, previous.medianComments)} />
          <Tile value={stats.medianViews.value === null ? "—" : String(Math.trunc(stats.medianViews.value))}
            label="медиана просмотров" note={metricEvidence(stats.medianViews)}
            delta={change(stats.medianViews.value, previous.medianViews)} />
          {/* Место в рейтинге сравнивается с прошлым опубликованным месяцем, а
              не с прошлыми сутками: рейтинг выходит раз в месяц. И знак у него
              читается наоборот — подняться значит уменьшить номер. */}
          <Tile value={stats.ratingRank ? `№${stats.ratingRank}` : "—"}
            label={`М‑Рейтинг ${PLATFORM_LABELS[account.platform]}${stats.ratingPeriod ? ` · ${stats.ratingPeriod}` : ""}`}
            note={`Официальное место в М‑Рейтинге ${PLATFORM_LABELS[account.platform]}.`}
            delta={change(stats.ratingRank, previous.ratingRank)} tone="rank"
            deltaLabel={previous.ratingPeriod ? `место против периода «${previous.ratingPeriod}»` : "место в рейтинге"} />
        </div>
        <WeeklyTrend key={selectedTrend ?? "unselected"} points={series} primary={primary} selectedDay={selectedDay} selectedTrend={selectedTrend} />
      </div></> : <p className="mt-2 text-sm leading-relaxed text-muted-foreground">Сводка публикаций ещё не рассчитана.</p>}
    </div>
    <div className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm mt-5 min-w-0 overflow-x-auto">
      <DaySpotlight day={selectedDay} mode={selectedTrend} />{truncated ? <p className="mt-2 text-sm leading-relaxed text-muted-foreground">Показаны первые 100 публикаций. Более старые записи доступны через API с курсором.</p> : null}<Table className="reveal"><TableHeader><TableRow><TableHead>Публикация</TableHead><TableHead>Опубликовано, МСК</TableHead><TableHead>Возраст</TableHead><TableHead>История</TableHead><TableHead>{telegram ? "Реакции" : primary}</TableHead><TableHead>Просмотры</TableHead><TableHead>Комментарии</TableHead><TableHead>Тип</TableHead>{anomalyLevels ? <TableHead>Анализ динамики</TableHead> : null}</TableRow></TableHeader><TableBody>
      {posts.map((post) => {
        const observedAt = post.reactions.observedAt ?? post.views.observedAt;
        const complete = post.historyCompleteness === "complete";
        const archiveUrl = deletedPublicationArchiveUrl(account.platform, post.deletedAt, post.displayExternalId ?? post.externalId, account.username, account.archiveUrl);
        const externalUrl = archiveUrl ?? post.publicUrl;
        const archiveLabel = archiveUrl ? (telegram ? "TGStat" : "MAXSTAT") : null;
        const archiveHint = archiveLabel === "MAXSTAT" ? `На MAXSTAT выберите в фильтрах дату ${legacyDate(post.publishedAt).slice(0, 10)}` : undefined;
        const detail = post.publicationId ? publicationHref(post.publicationId) : null;
        const publishedDay = moscowDay(post.publishedAt) ?? undefined;
        const cells = <><TableCell>{post.publicationId ? <Link href={publicationHref(post.publicationId)} prefetch={false}>{publicationLabel(post.displayExternalId ?? post.externalId,account.platform)}</Link> : publicationLabel(post.displayExternalId ?? post.externalId,account.platform)}{externalUrl?.startsWith("https://") ? <> · <a className="text-muted-foreground text-xs underline underline-offset-4" href={externalUrl} target="_blank" rel="noopener noreferrer" title={archiveHint}>{archiveLabel ?? PLATFORM_LONG_LABELS[account.platform]}</a></> : null}{post.deletedAt ? <> <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-destructive/10 text-destructive">удалена</span></> : null}{post.repost ? <> · <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-muted text-muted-foreground">репост</span></> : null}{post.joint ? <> · <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-muted text-muted-foreground">+{post.additionalAuthorCount} авт.</span></> : null}</TableCell><TableCell>{legacyDate(post.publishedAt)}</TableCell><TableCell>{duration(observedAt ? (Date.parse(observedAt)-Date.parse(post.publishedAt))/1000 : null)}</TableCell><TableCell>{observedAt || telegram ? <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${complete ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>{complete ? "полная" : "неполная"}</span> : <span className="text-muted-foreground" title="В этом снимке данных замера ещё нет. Ответ отдаётся из кэша и может отставать на несколько минут.">ожидает замера</span>}</TableCell><MetricWithGrowth value={post.reactions.value} quality={post.reactions.quality} growth={post.dailyGrowth?.reactions} label={telegram ? "реакции" : primary} /><MetricWithGrowth value={post.views.value} quality={post.views.quality} growth={post.dailyGrowth?.views} label="просмотры" /><TableCell title={qualityHint(post.comments.quality)}>{legacyNumber(post.comments.value)}</TableCell><TableCell>{postTypeLabel(post.publicationType)}</TableCell>{anomalyLevels ? <AnomalyLevelCell levels={anomalyLevels} publicationId={post.publicationId} /> : null}</>;
        return detail
          ? <RowLink key={post.publicationId} href={detail} data-published-day={publishedDay} className="cursor-pointer">{cells}</RowLink>
          : <TableRow key={post.publicationId} data-published-day={publishedDay}>{cells}</TableRow>;
      })}
      {!posts.length ? <TableRow><TableCell colSpan={anomalyLevels ? 9 : 8} className="space-y-3 py-10 text-center text-muted-foreground">Публикации ещё не собраны.</TableCell></TableRow> : null}
    </TableBody></Table></div>
    </NavigationBoundary>
  </>;
}
