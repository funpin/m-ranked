import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { publicationHref } from "@/lib/entity-routes";
import Link from "@/components/native-link";
import { duration, legacyDate, legacyNumber, PLATFORM_LABELS, PLATFORM_LONG_LABELS, postTypeLabel, publicationLabel } from "@/lib/format";
import { metricEvidence } from "@/lib/metric-evidence";
import type { AccountView, PublicationListItem } from "@/lib/types";

export function AccountDetail({ account, posts, truncated = false }: { account: AccountView; posts: PublicationListItem[]; truncated?: boolean }) {
  const name = account.title || account.institutionShortName || account.institutionName;
  const stats = account.stats;
  const telegram = account.platform === "telegram";
  const primary = account.platform === "vk" || account.platform === "rutube" ? "лайков" : "реакций";
  return <><span data-active-platform={account.platform} hidden />
    <h1 className="mb-5 font-heading text-2xl font-semibold tracking-tight sm:text-3xl">{name}{account.username ? <> <span className="text-muted-foreground">@{account.username}</span></> : null}</h1>
    <div className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm">
      {stats ? <><p className="mt-2 text-sm leading-relaxed text-muted-foreground">{telegram ? `Данные ниже — по всем публикациям, которые сейчас хранятся в базе: за последние ${stats.retentionDays} дней. Метки скачков временно отключены; реакции и просмотры продолжают накапливаться для настройки алгоритма.` : `Данные ниже — по всем публикациям ${PLATFORM_LONG_LABELS[account.platform]}, которые сейчас хранятся в базе: за последние ${stats.retentionDays} дней. Недоступные площадке метрики показываются прочерком.`}</p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 [&>span]:grid [&>span]:gap-1 [&>span]:rounded-lg [&>span]:border [&>span]:p-4 [&_small]:text-muted-foreground mt-4">
        <span><b className="text-2xl font-heading tabular">{stats.postCount}</b><small>публикаций в базе</small></span>
        <span><b className="text-2xl font-heading tabular">{stats.monitored}</b><small>с полной историей{telegram ? "" : " ⓘ"}</small></span>
        {([{ metric:stats.medianReactions, label:`медиана ${primary}` },{ metric:stats.medianViews,label:"медиана просмотров" },{ metric:stats.medianComments,label:"медиана комментариев" }]).map(({metric,label}) => <span key={label} tabIndex={0} title={metricEvidence(metric)}><b className="text-2xl font-heading tabular">{metric.value === null ? "—" : Math.trunc(metric.value)}</b><small>{label} ⓘ</small><span className="sr-only">{metricEvidence(metric)}</span></span>)}
        <span tabIndex={0} title={`Официальное место в М‑Рейтинге ${PLATFORM_LABELS[account.platform]}.`}><b className="text-2xl font-heading tabular">{stats.ratingRank ? `№${stats.ratingRank}` : "—"}</b><small>М‑Рейтинг {PLATFORM_LABELS[account.platform]} ⓘ{stats.ratingPeriod ? ` · ${stats.ratingPeriod}` : ""}</small></span>
      </div></> : <p className="mt-2 text-sm leading-relaxed text-muted-foreground">Сводка публикаций ещё не рассчитана.</p>}
    </div>
    <div className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm mt-5 min-w-0 overflow-x-auto">{truncated ? <p className="mt-2 text-sm leading-relaxed text-muted-foreground">Показаны первые 100 публикаций. Более старые записи доступны через API с курсором.</p> : null}<Table><TableHeader><TableRow><TableHead>Публикация</TableHead><TableHead>Опубликовано, МСК</TableHead><TableHead>Возраст</TableHead><TableHead>История</TableHead><TableHead>{telegram ? "Реакции" : primary}</TableHead><TableHead>Просмотры</TableHead><TableHead>Комментарии</TableHead><TableHead>Тип</TableHead></TableRow></TableHeader><TableBody>
      {posts.map((post) => {
        const observedAt = post.reactions.observedAt ?? post.views.observedAt;
        const complete = post.historyCompleteness === "complete";
        const externalUrl = telegram && post.deletedAt && account.username ? `https://tgstat.ru/channel/@${account.username}/${post.displayExternalId ?? post.externalId}` : post.publicUrl;
        return <TableRow key={post.publicationId}><TableCell>{post.publicationId ? <Link href={publicationHref(post.publicationId)} prefetch={false}>{publicationLabel(post.displayExternalId ?? post.externalId,account.platform)}</Link> : publicationLabel(post.displayExternalId ?? post.externalId,account.platform)}{externalUrl?.startsWith("https://") ? <> · <a className="text-muted-foreground text-xs underline underline-offset-4" href={externalUrl} target="_blank" rel="noopener noreferrer">{telegram && post.deletedAt ? "TGStat" : PLATFORM_LONG_LABELS[account.platform]}</a></> : null}{post.deletedAt ? <> <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-destructive/10 text-destructive">удалена</span></> : null}{post.repost ? <> · <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-muted text-muted-foreground">репост</span></> : null}{post.joint ? <> · <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-muted text-muted-foreground">+{post.additionalAuthorCount} авт.</span></> : null}</TableCell><TableCell>{legacyDate(post.publishedAt)}</TableCell><TableCell>{duration(observedAt ? (Date.parse(observedAt)-Date.parse(post.publishedAt))/1000 : null)}</TableCell><TableCell>{observedAt || telegram ? <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${complete ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>{complete ? "полная" : "неполная"}</span> : <span className="text-muted-foreground">нет замеров</span>}</TableCell><TableCell title={post.reactions.quality ?? undefined}>{legacyNumber(post.reactions.value)}</TableCell><TableCell title={post.views.quality ?? undefined}>{legacyNumber(post.views.value)}</TableCell><TableCell title={post.comments.quality ?? undefined}>{legacyNumber(post.comments.value)}</TableCell><TableCell>{postTypeLabel(post.publicationType)}</TableCell></TableRow>;
      })}
      {!posts.length ? <TableRow><TableCell colSpan={8} className="space-y-3 py-10 text-center text-muted-foreground">Публикации ещё не собраны.</TableCell></TableRow> : null}
    </TableBody></Table></div>
  </>;
}
