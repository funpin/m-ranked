import { accountHref, publicationHref } from "@/lib/entity-routes";
import Link from "@/components/native-link";
import { ArrowLeft, ArrowRight, ExternalLink } from "lucide-react";
import { deletedPublicationArchiveUrl, legacyDate, PLATFORM_LONG_LABELS, postTypeLabel, publicationLabel } from "@/lib/format";
import type { DetailHistory } from "@/lib/detail-data";
import { queryHref } from "@/lib/params";
import { FULL_PUBLICATION_HISTORY_LIMIT } from "@/lib/types";
import type { AnalysisLoad } from "@/lib/anomaly";
import { PublicationMeasurements } from "./publication-measurements";
import { StatusPill } from "@/components/ui";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { NavigationBoundary } from "@/components/navigation-boundary";
import { PlatformChip } from "@/components/platform-chip";
import { PublicationSkeleton } from "@/components/skeletons";

/** Previous and next keep their rel hints and stay readable when unavailable,
 *  so the absence of a neighbour is conveyed by words rather than by colour. */
function Neighbour({ href, id, platform, direction }: {
  href?: string; id?: string | null; platform: DetailHistory["publication"]["platform"];
  direction: "prev" | "next";
}) {
  const back = direction === "prev";
  const Icon = back ? ArrowLeft : ArrowRight;
  const title = back ? "Назад" : "Вперёд";
  const body = (
    <>
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      <span className="grid text-left">
        <span className="text-sm leading-tight font-semibold">{title}</span>
        <span className="text-muted-foreground text-[11px] leading-tight font-medium">
          {id ? publicationLabel(id, platform) : back ? "Нет более раннего" : "Нет более нового"}
        </span>
      </span>
    </>
  );
  if (!href) {
    return (
      <span className={cn("border-input text-muted-foreground flex h-auto items-center gap-2 rounded-md border px-3 py-2", !back && "flex-row-reverse")}>
        {body}
      </span>
    );
  }
  return (
    <Button
      variant="outline"
      className={cn("h-auto gap-2 px-3 py-2", !back && "flex-row-reverse")}
      render={<Link href={href} rel={back ? "prev" : "next"} prefetch={false} />}
    >
      {body}
    </Button>
  );
}

export function PublicationDetail({history,historyLimit=100,analysis=null,sampledIds=null,totalPoints}:{history:DetailHistory;historyLimit?:number;analysis?:Promise<AnalysisLoad>|null;sampledIds?:string[]|null;totalPoints?:number}) {
  const p=history.publication, telegram=p.platform === "telegram";
  const archiveUrl=deletedPublicationArchiveUrl(p.platform,p.deletedAt,p.displayExternalId ?? p.externalId,p.accountUsername,history.accountArchiveUrl);
  const url=archiveUrl ?? p.publicUrl;
  const archiveLabel=archiveUrl ? (telegram ? "TGStat" : "MAXSTAT") : null;
  const label=`${publicationLabel(p.displayExternalId ?? p.externalId,p.platform)}${archiveLabel ? ` в ${archiveLabel}` : ""}`;
  const maxstatDate=archiveLabel === "MAXSTAT" ? legacyDate(p.publishedAt).slice(0,10) : null;
  return <>
    <span data-active-platform={p.platform} hidden />
    <header className="mb-7 flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0">
        <h1 className="font-heading text-3xl leading-tight font-bold tracking-tight text-balance">
          {history.accountId
            ? <Link className="text-chart-2 hover:underline" href={accountHref(history.accountId)} prefetch={false}>{history.accountDisplayName || p.accountName || p.accountUsername}</Link>
            : p.accountName}
          <span className="text-muted-foreground">{" / "}</span>
          {url?.startsWith("https://")
            ? <a className="text-chart-2 inline-flex items-center gap-1 hover:underline" href={url} target="_blank" rel="noopener noreferrer">{label}<ExternalLink className="size-4 shrink-0" aria-hidden="true" /></a>
            : label}
        </h1>
        <p data-testid="publication-meta" data-platform={p.platform} className="text-muted-foreground mt-2 flex flex-wrap items-center gap-x-2 gap-y-2">
          <PlatformChip platform={p.platform} className="shrink-0 rounded-lg border border-current/30 px-2.5 py-1 text-xs tracking-wide" />
          <span data-testid="publication-meta-copy">Опубликовано: <b className="text-foreground font-semibold">{legacyDate(p.publishedAt,true)}</b> · история {p.historyCompleteness === "complete" ? "полная" : "неполная"} · тип: {postTypeLabel(p.publicationType)}</span>
          {p.deletedAt ? <StatusPill tone="red">удалена из {PLATFORM_LONG_LABELS[p.platform]}</StatusPill> : null}
          {p.repost ? <StatusPill tone="neutral">репост</StatusPill> : null}
          {p.ambiguousAlbumReactions ? <span className="text-warning font-medium">реакции элементов альбома различаются</span> : null}
          {p.joint ? <StatusPill tone="blue">+{p.additionalAuthorCount} авт.</StatusPill> : null}
        </p>
        {maxstatDate ? <p className="text-muted-foreground mt-2 text-sm">В MAXSTAT выберите в фильтрах дату <b className="text-foreground font-semibold">{maxstatDate}</b>: сервис не сохраняет выбранный день в ссылке.</p> : null}
      </div>
      <nav className="flex shrink-0 gap-2" aria-label="Навигация по публикациям">
        <Neighbour direction="prev" platform={p.platform} id={history.previousDisplayId} href={history.previousPublicationId ? publicationHref(history.previousPublicationId) : undefined} />
        <Neighbour direction="next" platform={p.platform} id={history.nextDisplayId} href={history.nextPublicationId ? publicationHref(history.nextPublicationId) : undefined} />
      </nav>
    </header>

    {/* Заголовок и кнопки «назад/вперёд» остаются на месте, а данные прошлого
        поста прячутся сразу: иначе на экране несколько секунд висели чужие
        графики и числа, неотличимые от новых. */}
    <NavigationBoundary fallback={<PublicationSkeleton />}>
    {p.deletedAt && history.archivedText ? (
      <Card className="mb-4">
        <CardHeader>
          <CardTitle as="h2" className="font-heading text-lg">Сохранённый текст публикации</CardTitle>
          <p className="text-muted-foreground mt-2 text-sm">Последняя копия, полученная до удаления из {PLATFORM_LONG_LABELS[p.platform]}.</p>
        </CardHeader>
        <CardContent>
          <div data-testid="archived-publication-text" className="text-pretty whitespace-pre-wrap">{history.archivedText}</div>
        </CardContent>
      </Card>
    ) : null}

    <PublicationMeasurements key={p.publicationId} publicationId={p.publicationId} rows={history.items} sampledIds={sampledIds} totalPoints={totalPoints ?? history.items.length} collectorCoverage={history.collectorCoverage} platform={p.platform} publishedAt={p.publishedAt} historyLimit={historyLimit} analysis={analysis}
      fullHistoryHref={historyLimit < FULL_PUBLICATION_HISTORY_LIMIT ? queryHref(publicationHref(p.publicationId),{history_limit:FULL_PUBLICATION_HISTORY_LIMIT}) : undefined} />
    </NavigationBoundary>
  </>;
}
