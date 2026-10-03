"use client";

import { ExternalLink } from "lucide-react";
import { useState } from "react";
import Link from "@/components/native-link";
import { RowLink } from "@/components/row-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { typeName } from "@/lib/compare-dashboard";
import { publicationHref } from "@/lib/entity-routes";
import { FINDINGS_SORT_OPTIONS, findingBadge, findingsHrefQuery, formatIndex, type ParsedFindingsQuery } from "@/lib/findings";
import { formatMetric, formatPercentage, PLATFORM_LABELS, publicationLabel } from "@/lib/format";
import { queryHref } from "@/lib/params";
import type { Finding, FindingsPage } from "@/lib/types";
import { cn } from "@/lib/utils";

const published = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow", weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
});

/** Сколько строк показать сразу; остальное из уже полученной страницы — по кнопке. */
const INITIAL_ROWS = 20;

export function FindingsResults({ page, query, anomaliesVisible }: {
  page: FindingsPage; query: ParsedFindingsQuery; anomaliesVisible: boolean;
}) {
  const [shown, setShown] = useState(INITIAL_ROWS);
  const hiddenNote = anomaliesVisible && page.hiddenAnomalous > 0
    ? <p data-testid="findings-hidden-note" className="text-muted-foreground text-xs">
        Скрыто постов с выраженной аномалией: {page.hiddenAnomalous}. <Link className="underline underline-offset-4" href="/compare#anomalies" prefetch={false}>Подробнее на сравнении</Link>
      </p>
    : null;

  if (query.group === "institution") {
    if (!page.groups.length) return <><NoFindings query={query} />{hiddenNote}</>;
    return <TooltipProvider><div data-testid="findings-groups" className="space-y-4">
      {page.groups.map((group) => (
        <section key={group.institutionLegacyId ?? group.institutionCanonicalName} className="bg-card min-w-0 rounded-xl border p-4 md:p-5">
          <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-heading font-semibold" title={group.institutionCanonicalName}>{group.institutionShortName || group.institutionCanonicalName}</h2>
            <span className="text-muted-foreground text-sm">выше нормы: {group.findingCount}</span>
          </header>
          <FindingRows rows={group.items} query={query} anomaliesVisible={anomaliesVisible} showInstitution={false} />
          {group.institutionLegacyId !== null ? (
            <Link className="mt-3 inline-block text-sm underline-offset-4 hover:underline" prefetch={false}
              href={queryHref("/statistics", { ...findingsHrefQuery(query), mode: "institution", institution: group.institutionLegacyId, group: undefined })}>
              Все посты вуза →
            </Link>
          ) : null}
        </section>
      ))}
      {hiddenNote}
    </div></TooltipProvider>;
  }

  if (!page.items.length) return <><NoFindings query={query} />{hiddenNote}</>;
  const visible = page.items.slice(0, shown);
  return <TooltipProvider><div className="min-w-0 space-y-3 md:rounded-xl md:border md:bg-card md:p-5">
    <FindingRows rows={visible} query={query} anomaliesVisible={anomaliesVisible} showInstitution={query.mode === "all"} />
    {shown < page.items.length ? <div className="flex justify-center"><Button type="button" variant="outline" onClick={() => setShown(page.items.length)}>Показать ещё</Button></div>
      : page.nextCursor ? <div className="flex justify-center"><Link className={buttonVariants({ variant: "outline" })} prefetch={false}
          href={queryHref("/statistics", { ...findingsHrefQuery(query), cursor: page.nextCursor })}>Следующие 50</Link></div> : null}
    {hiddenNote}
  </div></TooltipProvider>;
}

const SORT_LABELS = Object.fromEntries(FINDINGS_SORT_OPTIONS) as Record<ParsedFindingsQuery["sort"], string>;

function FindingRows({ rows, query, anomaliesVisible, showInstitution }: {
  rows: Finding[]; query: ParsedFindingsQuery; anomaliesVisible: boolean; showInstitution: boolean;
}) {
  return <>
    <div className="hidden overflow-x-auto md:block"><Table data-testid="findings-table" className="tabular">
      <caption className="sr-only">Посты выше нормы своего аккаунта. Сортировка: {SORT_LABELS[query.sort]}</caption>
      <TableHeader><TableRow>
        <TableHead>Пост</TableHead><TableHead>Индекс</TableHead><TableHead>Взаимодействия · 24 ч</TableHead>
        <TableHead>Просмотры · 24 ч</TableHead><TableHead>ERV · 24 ч</TableHead><TableHead className="w-12"><span className="sr-only">Оригинал</span></TableHead>
      </TableRow></TableHeader>
      <TableBody>{rows.map((row) => (
        <RowLink key={row.publicationId} href={publicationHref(row.publicationId)} className="hover:bg-muted/50 focus-within:bg-muted/50 cursor-pointer">
          <TableCell className="min-w-64 whitespace-normal"><Identity row={row} showInstitution={showInstitution} badge={findingBadge(row, anomaliesVisible)} linked /></TableCell>
          <TableCell><IndexValue row={row} /></TableCell>
          <TableCell><Interactions row={row} /></TableCell>
          <TableCell>{formatMetric(row.views)}</TableCell>
          <TableCell>{formatPercentage(row.erv)}</TableCell>
          <TableCell><Original row={row} /></TableCell>
        </RowLink>
      ))}</TableBody>
    </Table></div>
    <div data-testid="findings-cards" className="grid min-w-0 gap-3 md:hidden">{rows.map((row) => (
      <article key={row.publicationId} className="bg-card min-w-0 rounded-xl border p-4">
        <div className="flex items-start justify-between gap-3">
          <Identity row={row} showInstitution={showInstitution} badge={findingBadge(row, anomaliesVisible)} />
          <IndexValue row={row} prominent />
        </div>
        <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
          <Pair label="Взаимодействия" value={formatMetric(row.interactions)} />
          <Pair label="Просмотры" value={formatMetric(row.views)} />
          <Pair label="ERV" value={formatPercentage(row.erv)} />
        </dl>
        <div className="mt-3 flex gap-2">
          <Link className={cn(buttonVariants({ variant: "outline" }), "flex-1")} href={publicationHref(row.publicationId)} prefetch={false}>Открыть карточку</Link>
          <Original row={row} />
        </div>
      </article>
    ))}</div>
  </>;
}

/** В таблице описание поста — настоящая ссылка: её видят клавиатура и
 *  читалка экрана, а нажатие по строке лишь дублирует её. В карточке ссылкой
 *  служит кнопка «Открыть карточку». */
function Identity({ row, showInstitution, badge, linked = false }: {
  row: Finding; showInstitution: boolean; badge: string | null; linked?: boolean;
}) {
  const number = row.externalId ? publicationLabel(row.externalId, row.platform).replace(/^(?:№\s*)+/, "") : null;
  const description = `${PLATFORM_LABELS[row.platform]} · ${typeName(row.publicationType)}${number ? ` · №${number}` : ""}`;
  return <div className="min-w-0">
    <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-sm">
      {showInstitution ? <span className="font-medium" title={row.institutionCanonicalName}>{row.institutionShortName || row.institutionCanonicalName}</span> : null}
      {linked
        ? <Link className="text-muted-foreground hover:text-foreground break-all underline-offset-4 hover:underline" href={publicationHref(row.publicationId)} prefetch={false}>{description}</Link>
        : <span className="text-muted-foreground break-all">{description}</span>}
    </div>
    <div className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-1.5 text-xs">
      {row.publishedAt ? published.format(new Date(row.publishedAt)) : null}
      {badge ? <Badge variant="outline" className="rounded-full font-normal">{badge}</Badge> : null}
    </div>
  </div>;
}

function IndexValue({ row, prominent = false }: { row: Finding; prominent?: boolean }) {
  const strong = (row.interactionIndex ?? 0) >= 2;
  const text = formatIndex(row.interactionIndex);
  const tip = row.interactionIndex === null
    ? "Мало истории для нормы: нужно 10 постов аккаунта с замером на этом возрасте."
    : `Норма аккаунта: ${formatMetric(row.interactionNorm, true)} взаимодействий${row.ageHours !== null ? ` на ${row.ageHours}-м часу` : ""} (${row.normSampleSize} постов). Индекс просмотров: ${formatIndex(row.viewIndex)}.`;
  return <Tooltip><TooltipTrigger render={<button type="button" className={cn("relative z-10 shrink-0 cursor-help tabular-nums font-bold", prominent && "font-heading text-xl", strong && "text-primary")} aria-label={`Индекс ${text}. Подробнее`} />}>{text}</TooltipTrigger>
    <TooltipContent className="max-w-sm whitespace-normal leading-relaxed">{tip}</TooltipContent></Tooltip>;
}

function Interactions({ row }: { row: Finding }) {
  const parts = [
    row.capabilities.reactions ? `реакции ${formatMetric(row.reactions)}` : null,
    row.capabilities.comments ? `комментарии ${formatMetric(row.comments)}` : null,
    row.capabilities.shares ? `репосты ${formatMetric(row.shares)}` : null,
  ].filter(Boolean).join(" · ");
  if (!parts) return <span className="tabular-nums">{formatMetric(row.interactions)}</span>;
  return <Tooltip><TooltipTrigger render={<button type="button" className="relative z-10 cursor-help border-b border-dotted border-current tabular-nums" aria-label={`Взаимодействия ${formatMetric(row.interactions)}: ${parts}`} />}>{formatMetric(row.interactions)}</TooltipTrigger>
    <TooltipContent>{parts}</TooltipContent></Tooltip>;
}

function Original({ row }: { row: Finding }) {
  return row.publicUrl ? <a className="hover:bg-accent focus-visible:ring-ring relative z-10 inline-flex size-9 shrink-0 items-center justify-center rounded-md focus-visible:ring-2" href={row.publicUrl} target="_blank" rel="noopener noreferrer" aria-label="Открыть оригинал"><ExternalLink className="size-4" aria-hidden="true" /></a> : null;
}

function Pair({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-muted-foreground truncate text-[10px] uppercase">{label}</dt><dd className="font-medium tabular-nums">{value}</dd></div>;
}

function NoFindings({ query }: { query: ParsedFindingsQuery }) {
  const wider = query.period !== "30d";
  // В «Моём вузе» порога нет: пусто, только если у вуза нет постов вовсе.
  const institution = query.mode === "institution";
  const title = query.q ? "Ничего не найдено"
    : institution ? "У вуза нет публикаций за период" : "За период нет постов выше нормы";
  const description = institution ? "Попробуйте другую площадку, период или тип публикации."
    : query.platform === "rutube" ? "На RuTube взаимодействий мало, и посты редко выходят за норму."
      : "Норма — типичный пост своего аккаунта на том же возрасте.";
  return <Empty role="status" className="bg-card border py-10">
    <EmptyHeader>
      <EmptyTitle><h2 className="font-heading text-lg font-semibold">{title}</h2></EmptyTitle>
      <EmptyDescription className="text-sm">{description}</EmptyDescription>
    </EmptyHeader>
    {wider ? <EmptyContent><Link className={buttonVariants({ variant: "outline" })} prefetch={false}
      href={queryHref("/statistics", { ...findingsHrefQuery(query), period: "30d" })}>Расширить до 30 дней</Link></EmptyContent> : null}
  </Empty>;
}
