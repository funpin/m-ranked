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
    <h1>{name}{account.username ? <> <span className="muted">@{account.username}</span></> : null}</h1>
    <div className="panel">
      {stats ? <><p className="panel-note">{telegram ? `Данные ниже — по всем публикациям, которые сейчас хранятся в базе: за последние ${stats.retentionDays} дней. Метки скачков временно отключены; реакции и просмотры продолжают накапливаться для настройки алгоритма.` : `Данные ниже — по всем публикациям ${PLATFORM_LONG_LABELS[account.platform]}, которые сейчас хранятся в базе: за последние ${stats.retentionDays} дней. Недоступные площадке метрики показываются прочерком.`}</p>
      <div className="metrics channel-metrics">
        <span><b className="metric">{stats.postCount}</b><small>публикаций в базе</small></span>
        <span><b className="metric">{stats.monitored}</b><small>с полной историей{telegram ? "" : " ⓘ"}</small></span>
        {([{ metric:stats.medianReactions, label:`медиана ${primary}` },{ metric:stats.medianViews,label:"медиана просмотров" },{ metric:stats.medianComments,label:"медиана комментариев" }]).map(({metric,label}) => <span key={label} className="has-tooltip" tabIndex={0} data-tooltip={metricEvidence(metric)}><b className="metric">{metric.value === null ? "—" : Math.trunc(metric.value)}</b><small>{label} ⓘ</small><span className="sr-only">{metricEvidence(metric)}</span></span>)}
        <span className="has-tooltip" tabIndex={0} data-tooltip={`Официальное место в М‑Рейтинге ${PLATFORM_LABELS[account.platform]}.`}><b className="metric">{stats.ratingRank ? `№${stats.ratingRank}` : "—"}</b><small>М‑Рейтинг {PLATFORM_LABELS[account.platform]} ⓘ{stats.ratingPeriod ? ` · ${stats.ratingPeriod}` : ""}</small></span>
      </div></> : <p className="panel-note">Сводка публикаций ещё не рассчитана.</p>}
    </div>
    <div className="panel mt table-wrap">{truncated ? <p className="panel-note">Показаны первые 100 публикаций. Более старые записи доступны через API с курсором.</p> : null}<table><thead><tr><th>Публикация</th><th>Опубликовано, МСК</th><th>Возраст</th><th>История</th><th>{telegram ? "Реакции" : primary}</th><th>Просмотры</th><th>Комментарии</th><th>Тип</th></tr></thead><tbody>
      {posts.map((post) => {
        const observedAt = post.reactions.observedAt ?? post.views.observedAt;
        const complete = post.historyCompleteness === "complete";
        const externalUrl = telegram && post.deletedAt && account.username ? `https://tgstat.ru/channel/@${account.username}/${post.displayExternalId ?? post.externalId}` : post.publicUrl;
        return <tr key={post.publicationId}><td>{post.publicationId ? <Link href={publicationHref(post.publicationId)} prefetch={false}>{publicationLabel(post.displayExternalId ?? post.externalId,account.platform)}</Link> : publicationLabel(post.displayExternalId ?? post.externalId,account.platform)}{externalUrl?.startsWith("https://") ? <> · <a className="muted external" href={externalUrl} target="_blank" rel="noopener noreferrer">{telegram && post.deletedAt ? "TGStat" : PLATFORM_LONG_LABELS[account.platform]}</a></> : null}{post.deletedAt ? <> <span className="pill deleted">удалена</span></> : null}{post.repost ? <> · <span className="pill repost">репост</span></> : null}{post.joint ? <> · <span className="pill coauthor">+{post.additionalAuthorCount} авт.</span></> : null}</td><td>{legacyDate(post.publishedAt)}</td><td>{duration(observedAt ? (Date.parse(observedAt)-Date.parse(post.publishedAt))/1000 : null)}</td><td>{observedAt || telegram ? <span className={`pill ${complete ? "ok" : "warn"}`}>{complete ? "полная" : "неполная"}</span> : <span className="muted">нет замеров</span>}</td><td title={post.reactions.quality ?? undefined}>{legacyNumber(post.reactions.value)}</td><td title={post.views.quality ?? undefined}>{legacyNumber(post.views.value)}</td><td title={post.comments.quality ?? undefined}>{legacyNumber(post.comments.value)}</td><td>{postTypeLabel(post.publicationType)}</td></tr>;
      })}
      {!posts.length ? <tr><td colSpan={8} className="empty-state">Публикации ещё не собраны.</td></tr> : null}
    </tbody></table></div>
  </>;
}
