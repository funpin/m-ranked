import Link from "@/components/native-link";
import { TableCell, TableRow } from "@/components/ui/table";
import { DeltaBadge } from "@/components/delta-badge";
import { RowLink } from "@/components/row-link";
import { publicationHref } from "@/lib/entity-routes";
import { deletedPublicationArchiveUrl, duration, legacyDate, legacyNumber, moscowDay, PLATFORM_LONG_LABELS, postTypeLabel, publicationLabel, qualityHint } from "@/lib/format";
import type { AccountView, PublicationListItem } from "@/lib/types";
import type { ReactNode } from "react";

export type PublicationRowAccount = Pick<AccountView, "platform" | "username" | "archiveUrl">;

function MetricWithGrowth({ value, quality, growth, label }: { value: number | null; quality: string | null; growth?: number | null; label: string }) {
  return <TableCell title={qualityHint(quality)}><span className="flex items-center gap-2 whitespace-nowrap"><span>{legacyNumber(value)}</span><DeltaBadge value={growth} compact={false} label={`${label} за выбранные сутки`} /></span></TableCell>;
}

/** Строка таблицы публикаций аккаунта. Общая для первой страницы, которую
 *  рисует сервер, и страниц «Показать ещё», которые догружает браузер. */
export function PublicationRow({ post, account, primary, level }: {
  post: PublicationListItem; account: PublicationRowAccount; primary: string; level?: ReactNode;
}) {
  const telegram = account.platform === "telegram";
  const observedAt = post.reactions.observedAt ?? post.views.observedAt;
  const complete = post.historyCompleteness === "complete";
  const archiveUrl = deletedPublicationArchiveUrl(account.platform, post.deletedAt, post.displayExternalId ?? post.externalId, account.username, account.archiveUrl);
  const externalUrl = archiveUrl ?? post.publicUrl;
  const archiveLabel = archiveUrl ? (telegram ? "TGStat" : "MAXSTAT") : null;
  const archiveHint = archiveLabel === "MAXSTAT" ? `На MAXSTAT выберите в фильтрах дату ${legacyDate(post.publishedAt).slice(0, 10)}` : undefined;
  const detail = post.publicationId ? publicationHref(post.publicationId) : null;
  const publishedDay = moscowDay(post.publishedAt) ?? undefined;
  const cells = <><TableCell>{post.publicationId ? <Link href={publicationHref(post.publicationId)} prefetch={false}>{publicationLabel(post.displayExternalId ?? post.externalId,account.platform)}</Link> : publicationLabel(post.displayExternalId ?? post.externalId,account.platform)}{externalUrl?.startsWith("https://") ? <> · <a className="text-muted-foreground text-xs underline underline-offset-4" href={externalUrl} target="_blank" rel="noopener noreferrer" title={archiveHint}>{archiveLabel ?? PLATFORM_LONG_LABELS[account.platform]}</a></> : null}{post.deletedAt ? <> <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-destructive/10 text-destructive">удалена</span></> : null}{post.repost ? <> · <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-muted text-muted-foreground">репост</span></> : null}{post.joint ? <> · <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-muted text-muted-foreground">+{post.additionalAuthorCount} авт.</span></> : null}</TableCell><TableCell>{legacyDate(post.publishedAt)}</TableCell><TableCell>{duration(observedAt ? (Date.parse(observedAt)-Date.parse(post.publishedAt))/1000 : null)}</TableCell><TableCell>{observedAt || telegram ? <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${complete ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>{complete ? "полная" : "неполная"}</span> : <span className="text-muted-foreground" title="В этом снимке данных замера ещё нет. Ответ отдаётся из кэша и может отставать на несколько минут.">ожидает замера</span>}</TableCell><MetricWithGrowth value={post.reactions.value} quality={post.reactions.quality} growth={post.dailyGrowth?.reactions} label={telegram ? "реакции" : primary} /><MetricWithGrowth value={post.views.value} quality={post.views.quality} growth={post.dailyGrowth?.views} label="просмотры" /><TableCell title={qualityHint(post.comments.quality)}>{legacyNumber(post.comments.value)}</TableCell><TableCell>{postTypeLabel(post.publicationType)}</TableCell>{level}</>;
  return detail
    ? <RowLink href={detail} data-published-day={publishedDay} className="cursor-pointer">{cells}</RowLink>
    : <TableRow data-published-day={publishedDay}>{cells}</TableRow>;
}
