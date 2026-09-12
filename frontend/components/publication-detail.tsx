import { accountHref, publicationHref } from "@/lib/entity-routes";
import Link from "@/components/native-link";
import { ArrowLeft, ArrowRight, ExternalLink } from "lucide-react";
import { legacyDate, PLATFORM_LONG_LABELS, postTypeLabel, publicationLabel } from "@/lib/format";
import type { DetailHistory } from "@/lib/detail-data";
import { queryHref } from "@/lib/params";
import { FULL_PUBLICATION_HISTORY_LIMIT } from "@/lib/types";
import type { PublicationAnomalyAnalysis } from "@/lib/types";
import { PublicationMeasurements } from "./publication-measurements";
import { AnomalyAnalysis } from "./anomaly-analysis";
import { StatusPill } from "@/components/ui";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

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
        <span className="text-[11px] leading-tight font-medium opacity-75">
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

export function PublicationDetail({history,historyLimit=100,analysis=null,analysisLoadFailed=false}:{history:DetailHistory;historyLimit?:number;analysis?:PublicationAnomalyAnalysis|null;analysisLoadFailed?:boolean}) {
  const p=history.publication, telegram=p.platform === "telegram";
  const url=telegram && p.deletedAt && p.accountUsername ? `https://tgstat.ru/channel/@${p.accountUsername}/${p.displayExternalId ?? p.externalId}` : p.publicUrl;
  const label=`${publicationLabel(p.displayExternalId ?? p.externalId,p.platform)}${telegram && p.deletedAt ? " в TGStat" : ""}`;
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
        <p className="text-muted-foreground mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-2">
          <span>Опубликовано: <b className="text-foreground font-semibold">{legacyDate(p.publishedAt,true)}</b> · история {p.historyCompleteness === "complete" ? "полная" : "неполная"} · тип: {postTypeLabel(p.publicationType)}{telegram ? "" : ` · ${PLATFORM_LONG_LABELS[p.platform]}`}</span>
          {p.deletedAt ? <StatusPill tone="red">удалена из {PLATFORM_LONG_LABELS[p.platform]}</StatusPill> : null}
          {p.repost ? <StatusPill tone="neutral">репост</StatusPill> : null}
          {p.ambiguousAlbumReactions ? <span className="text-chart-3 font-medium">реакции элементов альбома различаются</span> : null}
          {p.joint ? <StatusPill tone="blue">+{p.additionalAuthorCount} авт.</StatusPill> : null}
        </p>
      </div>
      <nav className="flex shrink-0 gap-2" aria-label="Навигация по публикациям">
        <Neighbour direction="prev" platform={p.platform} id={history.previousDisplayId} href={history.previousPublicationId ? publicationHref(history.previousPublicationId) : undefined} />
        <Neighbour direction="next" platform={p.platform} id={history.nextDisplayId} href={history.nextPublicationId ? publicationHref(history.nextPublicationId) : undefined} />
      </nav>
    </header>

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

    <AnomalyAnalysis analysis={analysis} loadFailed={analysisLoadFailed} historyRevision={history.datasetRevision} />
    <PublicationMeasurements key={p.publicationId} rows={history.items} platform={p.platform} historyLimit={historyLimit} analysis={analysis}
      fullHistoryHref={historyLimit < FULL_PUBLICATION_HISTORY_LIMIT ? queryHref(publicationHref(p.publicationId),{history_limit:FULL_PUBLICATION_HISTORY_LIMIT}) : undefined} />
  </>;
}
