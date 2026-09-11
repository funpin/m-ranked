import { accountHref, publicationHref } from "@/lib/entity-routes";
import Link from "@/components/native-link";
import { legacyDate, PLATFORM_LONG_LABELS, postTypeLabel, publicationLabel } from "@/lib/format";
import type { DetailHistory } from "@/lib/detail-data";
import { queryHref } from "@/lib/params";
import { FULL_PUBLICATION_HISTORY_LIMIT } from "@/lib/types";
import { PublicationMeasurements } from "./publication-measurements";
export function PublicationDetail({history,historyLimit=100}:{history:DetailHistory;historyLimit?:number}) {
  const p=history.publication, telegram=p.platform === "telegram";
  const url=telegram && p.deletedAt && p.accountUsername ? `https://tgstat.ru/channel/@${p.accountUsername}/${p.displayExternalId ?? p.externalId}` : p.publicUrl;
  const label=`${publicationLabel(p.displayExternalId ?? p.externalId,p.platform)}${telegram && p.deletedAt ? " в TGStat" : ""}`;
  return <><span data-active-platform={p.platform} hidden /><div className="post-heading"><div><h1>{history.accountId ? <Link href={accountHref(history.accountId)} prefetch={false}>{history.accountDisplayName || p.accountName || p.accountUsername}</Link> : p.accountName}{" / "}{url?.startsWith("https://") ? <a className="external" href={url} target="_blank" rel="noopener noreferrer">{label}</a> : label}</h1><p className="muted">Опубликовано: <b>{legacyDate(p.publishedAt,true)}</b> · история {p.historyCompleteness === "complete" ? "полная" : "неполная"} · тип: {postTypeLabel(p.publicationType)}{telegram ? "" : ` · ${PLATFORM_LONG_LABELS[p.platform]}`}{p.deletedAt ? <> · <span className="pill deleted">удалена из {PLATFORM_LONG_LABELS[p.platform]}</span></> : null}{p.repost ? <> · <span className="pill repost">репост</span></> : null}{p.ambiguousAlbumReactions ? <> · <span className="warn">реакции элементов альбома различаются</span></> : null}{p.joint ? <> · <span className="pill coauthor">+{p.additionalAuthorCount} авт.</span></> : null}</p></div>
    <nav className="post-navigation" aria-label="Навигация по публикациям">{history.previousPublicationId ? <Link className="post-nav-link" href={publicationHref(history.previousPublicationId)} rel="prev" prefetch={false}><span>← Назад</span><small>{history.previousDisplayId ? publicationLabel(history.previousDisplayId,p.platform) : "Предыдущая публикация"}</small></Link> : <span className="post-nav-link disabled"><span>← Назад</span><small>Нет более раннего</small></span>}{history.nextPublicationId ? <Link className="post-nav-link next" href={publicationHref(history.nextPublicationId)} rel="next" prefetch={false}><span>Вперёд →</span><small>{history.nextDisplayId ? publicationLabel(history.nextDisplayId,p.platform) : "Следующая публикация"}</small></Link> : <span className="post-nav-link next disabled"><span>Вперёд →</span><small>Нет более нового</small></span>}</nav></div>
    {p.deletedAt && history.archivedText ? <section className="panel archived-publication"><h2>Сохранённый текст публикации</h2><p className="panel-note">Последняя копия, полученная до удаления из {PLATFORM_LONG_LABELS[p.platform]}.</p><div className="archived-publication-text">{history.archivedText}</div></section> : null}
    <PublicationMeasurements key={p.publicationId} rows={history.items} platform={p.platform} historyLimit={historyLimit}
      fullHistoryHref={history.nextCursor ? queryHref(publicationHref(p.publicationId),{history_limit:FULL_PUBLICATION_HISTORY_LIMIT}) : undefined} />
  </>;
}
