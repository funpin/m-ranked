"use client";

import { useState } from "react";
import Link from "@/components/native-link";
import { PatternIcon } from "@/components/anomaly-icons";
import { LevelIcon } from "@/components/anomaly-level-icon";
import { Identity, MINE_CARD, MINE_ROW, Original, Pair, usePersonal, type Personal } from "@/components/findings/findings-results";
import { RowLink } from "@/components/row-link";
import { StatusPill } from "@/components/ui";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { publicationHref } from "@/lib/entity-routes";
import { ANOMALOUS_SORT_OPTIONS, anomalyGrowthText, findingsHrefQuery, isNewSince, type ParsedFindingsQuery } from "@/lib/findings";
import { formatMetric } from "@/lib/format";
import { queryHref } from "@/lib/params";
import type { AnomalousFindingsPage, AnomalousPost } from "@/lib/types";
import { cn } from "@/lib/utils";

const INITIAL_ROWS = 20;
const SORT_LABELS = Object.fromEntries(ANOMALOUS_SORT_OPTIONS) as Record<string, string>;
const LEVEL_LABELS: Record<number, string> = { 2: "выраженная аномалия", 3: "признаки искусственной активности" };

/** Рейтинг «Аномальные посты»: посты периода с выраженной аномалией, сильнейшие
 *  первыми. Мера — какая доля итогового значения метрики набрана в участке
 *  признака; слово «накрутка» здесь не появляется (ADR-006). */
export function AnomalousResults({ page, query }: { page: AnomalousFindingsPage; query: ParsedFindingsQuery }) {
  const [shown, setShown] = useState(INITIAL_ROWS);
  const personal = usePersonal();
  if (query.group === "institution") {
    if (!page.groups.length) return <NoAnomalies query={query} />;
    return <TooltipProvider><div data-testid="anomalous-groups" className="space-y-4">
      {page.groups.map((group) => (
        <section key={group.institutionLegacyId ?? group.institutionCanonicalName} className="bg-card min-w-0 rounded-xl border p-4 md:p-5">
          <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-heading font-semibold" title={group.institutionCanonicalName}>{group.institutionShortName || group.institutionCanonicalName}</h2>
            <span className="text-muted-foreground text-sm">аномальных постов: {group.findingCount}</span>
          </header>
          <AnomalousRows rows={group.items} query={query} showInstitution={false} personal={personal} />
          {group.institutionLegacyId !== null ? (
            <Link className="mt-3 inline-block text-sm underline-offset-4 hover:underline" prefetch={false}
              href={queryHref("/findings", { ...findingsHrefQuery(query), mode: "institution", institution: group.institutionLegacyId, group: undefined })}>
              Все аномальные посты вуза →
            </Link>
          ) : null}
        </section>
      ))}
    </div></TooltipProvider>;
  }
  if (!page.items.length) return <NoAnomalies query={query} />;
  const visible = page.items.slice(0, shown);
  return <TooltipProvider><div data-testid="anomalous-results" className="min-w-0 space-y-3 lg:rounded-xl lg:border lg:bg-card lg:p-5">
    <AnomalousRows rows={visible} query={query} showInstitution={query.mode === "all"} personal={personal} />
    {shown < page.items.length ? <div className="flex justify-center"><Button type="button" variant="outline" onClick={() => setShown(page.items.length)}>Показать ещё</Button></div>
      : page.nextCursor ? <div className="flex justify-center"><Link className={buttonVariants({ variant: "outline" })} prefetch={false}
          href={queryHref("/findings", { ...findingsHrefQuery(query), cursor: page.nextCursor })}>Следующие 50</Link></div> : null}
  </div></TooltipProvider>;
}

function AnomalousRows({ rows, query, showInstitution, personal }: {
  rows: AnomalousPost[]; query: ParsedFindingsQuery; showInstitution: boolean; personal: Personal;
}) {
  const mine = (row: AnomalousPost) => showInstitution && personal.mine !== null && row.institutionLegacyId === personal.mine;
  const marks = (row: AnomalousPost) => ({ fresh: isNewSince(row, personal.visit), mine: mine(row) });
  return <>
    <div className="hidden overflow-x-auto lg:block"><Table data-testid="anomalous-table" className="tabular">
      <caption className="sr-only">Посты с выраженной аномалией динамики. Сортировка: {SORT_LABELS[query.sort]}</caption>
      <TableHeader><TableRow>
        <TableHead>Пост</TableHead><TableHead>Уровень</TableHead><TableHead>Необычный прирост</TableHead>
        <TableHead>Признаки</TableHead><TableHead>Просмотры</TableHead><TableHead>Реакции</TableHead>
        <TableHead className="w-12"><span className="sr-only">Оригинал</span></TableHead>
      </TableRow></TableHeader>
      <TableBody>{rows.map((row) => (
        <RowLink key={row.publicationId} href={publicationHref(row.publicationId)} data-mine={mine(row) || undefined}
          className={cn("hover:bg-muted/50 focus-within:bg-muted/50 cursor-pointer", mine(row) && MINE_ROW)}>
          <TableCell className="min-w-64 whitespace-normal"><Identity row={row} showInstitution={showInstitution} badge={null} marks={marks(row)} linked /></TableCell>
          <TableCell><Level level={row.anomalyLevel} /></TableCell>
          <TableCell><Growth row={row} /></TableCell>
          <TableCell><Signals row={row} /></TableCell>
          <TableCell>{formatMetric(row.views)}</TableCell>
          <TableCell>{formatMetric(row.reactions)}</TableCell>
          <TableCell><Original row={row} /></TableCell>
        </RowLink>
      ))}</TableBody>
    </Table></div>
    <div data-testid="anomalous-cards" className="grid min-w-0 gap-3 md:grid-cols-2 lg:hidden">{rows.map((row) => (
      <article key={row.publicationId} data-mine={mine(row) || undefined} className={cn("bg-card min-w-0 rounded-xl border p-4", mine(row) && MINE_CARD)}>
        <div className="flex items-start justify-between gap-3">
          <Identity row={row} showInstitution={showInstitution} badge={null} marks={marks(row)} />
          <Growth row={row} prominent />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2"><Level level={row.anomalyLevel} /><Signals row={row} /></div>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <Pair label="Просмотры" value={formatMetric(row.views)} />
          <Pair label="Реакции" value={formatMetric(row.reactions)} />
        </dl>
        <div className="mt-3 flex items-center gap-2">
          <Link className={cn(buttonVariants({ variant: "outline" }), "flex-1")} href={publicationHref(row.publicationId)} prefetch={false}>Открыть разбор</Link>
          <Original row={row} />
        </div>
      </article>
    ))}</div>
  </>;
}

function Level({ level }: { level: number }) {
  return <span className="inline-flex whitespace-nowrap"><StatusPill tone={level === 3 ? "red" : "amber"}>
    <LevelIcon level={level} className="size-3.5" />{LEVEL_LABELS[level] ?? `уровень ${level}`}
  </StatusPill></span>;
}

function Growth({ row, prominent = false }: { row: AnomalousPost; prominent?: boolean }) {
  const text = anomalyGrowthText(row.anomalyGrowth, row.anomalyShare, row.anomalyMetric, (value) => formatMetric(value));
  const tip = text.detail
    ? `${text.detail} пришло в участке признака — ${text.headline} итогового значения на момент анализа.`
    : "Доля ещё не посчитана: пост проанализирован до появления этой меры и получит её при следующем анализе.";
  return <Tooltip><TooltipTrigger render={<button type="button" className={cn("relative z-10 grid shrink-0 cursor-help justify-items-start text-left tabular-nums", prominent && "justify-items-end text-right")} aria-label={`Необычный прирост: ${tip}`} />}>
      <span className={cn("font-bold", prominent && "font-heading text-xl")}>{text.headline}</span>
      {text.detail ? <span className="text-muted-foreground text-xs">{text.detail}</span> : null}
    </TooltipTrigger>
    <TooltipContent className="max-w-sm whitespace-normal leading-relaxed">{tip}</TooltipContent></Tooltip>;
}

function Signals({ row }: { row: AnomalousPost }) {
  if (!row.signals.length) return <span className="text-muted-foreground">—</span>;
  const titles = row.signals.map((signal) => signal.title);
  return <span className="text-muted-foreground inline-flex items-center gap-1" title={titles.join("; ")} aria-label={`Признаки: ${titles.join("; ")}`} role="img">
    {row.signals.slice(0, 4).map((signal, index) => <PatternIcon key={`${signal.pattern}-${index}`} pattern={signal.pattern} className="size-4" />)}
    {row.signals.length > 4 ? <span className="text-xs">+{row.signals.length - 4}</span> : null}
  </span>;
}

function NoAnomalies({ query }: { query: ParsedFindingsQuery }) {
  const wider = query.period !== "30d";
  return <Empty role="status" className="bg-card border py-10">
    <EmptyHeader>
      <EmptyTitle><h2 className="font-heading text-lg font-semibold">{query.q ? "Ничего не найдено" : "За период нет постов с выраженной аномалией"}</h2></EmptyTitle>
      <EmptyDescription className="text-sm">В рейтинг входят посты с уровнем «выраженная аномалия» и выше.</EmptyDescription>
    </EmptyHeader>
    {wider ? <EmptyContent><Link className={buttonVariants({ variant: "outline" })} prefetch={false}
      href={queryHref("/findings", { ...findingsHrefQuery(query), period: "30d" })}>Расширить до 30 дней</Link></EmptyContent> : null}
  </Empty>;
}
