"use client";

import Link from "@/components/native-link";
import { RowLink } from "@/components/row-link";
import { NativeButton } from "@/components/native-field";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { formatMetric, formatPercentage, PLATFORM_LONG_LABELS, publicationLabel } from "@/lib/format";
import { accountHref, publicationHref } from "@/lib/entity-routes";
import { queryHref } from "@/lib/params";
import { statisticsHrefQuery, type ParsedStatisticsQuery } from "@/lib/statistics";
import type { StatisticsEntity, StatisticsPage, StatisticsPublication, StatisticsPublicationSort } from "@/lib/types";
import { ArrowDown, ArrowUp, CircleHelp, ExternalLink } from "lucide-react";
import { useState, type ReactNode } from "react";

const PUBLICATION_LABELS: Record<StatisticsPublicationSort, string> = {
  erv: "ERV",
  views: "Просмотры",
  interactions: "Взаимодействия",
  published_at: "Дата",
};

export function StatisticsResults({ page, query }: { page: StatisticsPage; query: ParsedStatisticsQuery }) {
  const initial = query.platform === "all" ? 10 : 20;
  const [revealed, setRevealed] = useState<Record<string, number>>({});

  if (query.view === "entities") {
    const visible = page.entities.slice(0, revealed.entities ?? 20);
    return (
      <ResultSection title={`Вузы · ${PLATFORM_LONG_LABELS[query.platform]}`}>
        {!page.entities.length
          ? <EmptyState searched={Boolean(query.q)} />
          : <ResultPanel>
              <EntityTable rows={visible} query={query} />
              <EntityCards rows={visible} query={query} />
              <RevealButton shown={visible.length} total={page.entities.length} onClick={() => setRevealed({ entities: 50 })} />
            </ResultPanel>}
      </ResultSection>
    );
  }

  const nonempty = page.sections.filter((section) => section.items.length > 0);
  if (!nonempty.length) return <EmptyState searched={Boolean(query.q)} />;
  return <div className="space-y-8">{page.sections.map((section) => {
    if (!section.items.length) return query.platform === "all"
      ? <section key={section.platform} className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground"><h2 className="font-heading font-semibold text-foreground">{PLATFORM_LONG_LABELS[section.platform]}</h2><p>Нет публикаций за выбранный период.</p></section>
      : null;
    const count = revealed[section.platform] ?? initial;
    const visible = section.items.slice(0, count);
    return <ResultSection key={section.platform} title={PLATFORM_LONG_LABELS[section.platform]}><ResultPanel>
      <PublicationTable rows={visible} query={query} />
      <PublicationCards rows={visible} query={query} />
      <RevealButton shown={visible.length} total={section.items.length} onClick={() => setRevealed((current) => ({ ...current, [section.platform]: 50 }))} />
    </ResultPanel></ResultSection>;
  })}</div>;
}

function ResultSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="space-y-3"><h2 className="font-heading text-xl font-semibold">{title}</h2>{children}</section>;
}

function ResultPanel({ children }: { children: ReactNode }) {
  return <div data-testid="statistics-results-panel" className="space-y-3 md:rounded-xl md:border md:bg-card md:p-5 md:text-card-foreground md:shadow-sm">{children}</div>;
}

function RevealButton({ shown, total, onClick }: { shown: number; total: number; onClick: () => void }) {
  if (shown >= total) return null;
  return <div className="flex justify-center"><NativeButton type="button" variant="outline" onClick={onClick}>Показать ещё <span className="sr-only">до {total} строк</span></NativeButton></div>;
}

function EmptyState({ searched }: { searched: boolean }) {
  return <section className="rounded-xl border bg-card px-5 py-10 text-center" role="status">
    <h2 className="font-heading text-lg font-semibold">{searched ? "Ничего не найдено" : "Нет данных за выбранный период"}</h2>
    <p className="mt-1 text-sm text-muted-foreground">{searched ? "Измените запрос или очистите поиск." : "Попробуйте выбрать более длинный период."}</p>
    {searched ? <Link className="mt-4 inline-flex min-h-9 items-center rounded-md border px-3 text-sm font-medium" href="/statistics">Сбросить поиск и фильтры</Link> : null}
  </section>;
}

function publicationColumns(query: ParsedStatisticsQuery) {
  const numeric: StatisticsPublicationSort[] = ["erv", "views", "interactions"];
  return [query.publicationSort, ...numeric.filter((metric) => metric !== query.publicationSort), "published_at" as const]
    .filter((metric, index, values) => values.indexOf(metric) === index);
}

function PublicationTable({ rows, query }: { rows: StatisticsPublication[]; query: ParsedStatisticsQuery }) {
  const columns = publicationColumns(query);
  return <div className="hidden overflow-x-auto md:block"><Table data-testid="statistics-publications-table" className="tabular">
    <caption className="sr-only">Публикации, отсортированные по показателю {PUBLICATION_LABELS[query.publicationSort]}</caption>
    <TableHeader><TableRow><TableHead className="w-12">#</TableHead><TableHead>Вуз</TableHead>
      {columns.map((metric) => <SortablePublicationHead key={metric} metric={metric} query={query} />)}
      <TableHead className="w-12"><span className="sr-only">Источник</span></TableHead>
    </TableRow></TableHeader>
    <TableBody>{rows.map((row) => <PublicationRow key={row.publicationId} row={row} columns={columns} />)}</TableBody>
  </Table></div>;
}

function SortablePublicationHead({ metric, query }: { metric: StatisticsPublicationSort; query: ParsedStatisticsQuery }) {
  const active = query.publicationSort === metric;
  const direction = active && query.publicationDirection === "desc" ? "asc" : "desc";
  return <TableHead aria-sort={active ? (query.publicationDirection === "asc" ? "ascending" : "descending") : "none"}>
    <Link className="inline-flex items-center gap-1 whitespace-nowrap font-medium" scroll={false} prefetch={false}
      href={queryHref("/statistics", { ...statisticsHrefQuery(query), publication_sort: metric, publication_direction: direction })}>
      {PUBLICATION_LABELS[metric]}
      {active ? query.publicationDirection === "asc" ? <ArrowUp className="size-3.5" aria-hidden="true" /> : <ArrowDown className="size-3.5" aria-hidden="true" /> : null}
      {active ? <span className="sr-only">, {query.publicationDirection === "asc" ? "по возрастанию" : "по убыванию"}</span> : null}
    </Link>
  </TableHead>;
}

function PublicationRow({ row, columns }: { row: StatisticsPublication; columns: StatisticsPublicationSort[] }) {
  const href = publicationHref(row.publicationId);
  return <RowLink href={href} className="cursor-pointer hover:bg-muted/50 focus-within:bg-muted/50">
    <TableCell className="text-muted-foreground">{row.rank}</TableCell>
    <TableCell className="min-w-64 whitespace-normal"><PublicationIdentity row={row} href={href} /></TableCell>
    {columns.map((metric) => <TableCell key={metric} className={metric === "erv" ? "font-semibold" : undefined}>{publicationMetric(row, metric)}</TableCell>)}
    <TableCell>{row.publicUrl ? <a className="relative z-10 inline-flex size-8 items-center justify-center rounded-md hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring" href={row.publicUrl} target="_blank" rel="noopener noreferrer" aria-label={`Открыть оригинал ${PLATFORM_LONG_LABELS[row.platform]}`}><ExternalLink className="size-4" aria-hidden="true" /></a> : null}</TableCell>
  </RowLink>;
}

function PublicationCards({ rows, query }: { rows: StatisticsPublication[]; query: ParsedStatisticsQuery }) {
  return <div className="grid gap-3 md:hidden" data-testid="statistics-publication-cards">{rows.map((row) => {
    const href = publicationHref(row.publicationId);
    return <article key={row.publicationId} className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3"><div className="min-w-0 flex-1"><span className="text-xs font-semibold text-muted-foreground">#{row.rank}</span><PublicationIdentity row={row} href={href} /></div><div className="shrink-0 text-right"><strong className="font-heading text-xl">{publicationMetric(row, query.publicationSort)}</strong><p className="text-[11px] uppercase text-muted-foreground">{PUBLICATION_LABELS[query.publicationSort]}</p></div></div>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-sm"><MetricPair label="ERV" value={formatPercentage(row.erv)} /><MetricPair label="Просмотры" value={formatMetric(row.views)} /><MetricPair label="Взаимодействия" value={formatMetric(row.interactions)} /></dl>
      <div className="mt-4 flex items-center gap-2"><Link className="inline-flex min-h-9 flex-1 items-center justify-center rounded-md border px-3 text-sm font-medium" href={href} prefetch={false}>Открыть карточку</Link>{row.publicUrl ? <a className="inline-flex size-9 items-center justify-center rounded-md border" href={row.publicUrl} target="_blank" rel="noopener noreferrer" aria-label={`Открыть оригинал ${PLATFORM_LONG_LABELS[row.platform]}`}><ExternalLink className="size-4" aria-hidden="true" /></a> : null}</div>
    </article>;
  })}</div>;
}

function PublicationIdentity({ row, href }: { row: StatisticsPublication; href: string }) {
  const number = publicationLabel(row.externalId, row.platform).replace(/^(?:№\s*)+/, "");
  return <div className="min-w-0">
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      <Link className="font-semibold underline-offset-4 hover:underline" href={href} prefetch={false} title={row.institutionCanonicalName}>{row.institutionShortName || row.institutionCanonicalName}</Link>
      <Badge variant="secondary" className="max-w-48 rounded-full font-semibold tabular text-ellipsis" title={`Публикация №${number}`}>№{number}</Badge>
    </div>
    <div className="mt-0.5 text-xs leading-snug text-muted-foreground" title={row.institutionCanonicalName}>{row.institutionCanonicalName}</div>
  </div>;
}

const ENTITY_LABELS = { erv: "ERV", median_interactions: "Медиана", interactions: "Взаимодействия", views: "Просмотры", publications: "Публикации" } as const;

function EntityTable({ rows, query }: { rows: StatisticsEntity[]; query: ParsedStatisticsQuery }) {
  const metrics = [query.entitySort, ...(["erv", "median_interactions", "interactions", "views", "publications"] as const).filter((metric) => metric !== query.entitySort)];
  return <TooltipProvider><div className="hidden overflow-x-auto md:block"><Table data-testid="statistics-entities-table" className="tabular"><caption className="sr-only">Агрегированная статистика вузов</caption><TableHeader><TableRow><TableHead>#</TableHead><TableHead>Вуз</TableHead>{metrics.map((metric) => {
    const active = metric === query.entitySort;
    const direction = active && query.entityDirection === "desc" ? "asc" : "desc";
    return <TableHead key={metric} aria-sort={active ? (query.entityDirection === "asc" ? "ascending" : "descending") : "none"}><span className="inline-flex items-center gap-1"><Link className="inline-flex items-center gap-1 whitespace-nowrap" scroll={false} prefetch={false} href={queryHref("/statistics", { ...statisticsHrefQuery(query), entity_sort: metric, entity_direction: direction })}>{ENTITY_LABELS[metric]}{active ? query.entityDirection === "asc" ? <ArrowUp className="size-3.5" aria-hidden="true" /> : <ArrowDown className="size-3.5" aria-hidden="true" /> : null}</Link>{metric === "erv" ? <EntityErvHelp /> : metric === "median_interactions" ? <EntityMedianHelp /> : null}</span></TableHead>;
  })}</TableRow></TableHeader><TableBody>{rows.map((row) => <EntityRow key={row.institutionId} row={row} metrics={metrics} />)}</TableBody></Table></div></TooltipProvider>;
}

function EntityRow({ row, metrics }: { row: StatisticsEntity; metrics: readonly (keyof typeof ENTITY_LABELS)[] }) {
  const href = accountHref(row.accountId);
  return <RowLink href={href} className="cursor-pointer hover:bg-muted/50"><TableCell className="text-muted-foreground">{row.rank}</TableCell><TableCell className="min-w-64 whitespace-normal"><EntityIdentity row={row} href={href} /></TableCell>{metrics.map((metric) => <TableCell key={metric}>{metric === "erv" ? <EntityErvValue row={row} /> : entityMetric(row, metric)}</TableCell>)}</RowLink>;
}

function EntityCards({ rows, query }: { rows: StatisticsEntity[]; query: ParsedStatisticsQuery }) {
  return <TooltipProvider><div className="grid gap-3 md:hidden" data-testid="statistics-entity-cards">{rows.map((row) => {
    const href = accountHref(row.accountId);
    return <article key={row.institutionId} className="rounded-xl border bg-card p-4"><div className="flex justify-between gap-3"><div className="min-w-0"><span className="text-xs text-muted-foreground">#{row.rank}</span><EntityIdentity row={row} href={href} heading /></div><div className="text-right">{query.entitySort === "erv" ? <EntityErvValue row={row} prominent /> : <strong className="font-heading text-xl">{entityMetric(row, query.entitySort)}</strong>}<p className="text-[11px] uppercase text-muted-foreground">{ENTITY_LABELS[query.entitySort]}</p></div></div><dl className="mt-3 grid grid-cols-3 gap-2"><MetricPair label="ERV" value={<EntityErvValue row={row} />} /><MetricPair label={<span className="inline-flex items-center gap-0.5">Медиана<EntityMedianHelp compact /></span>} value={formatMetric(row.medianInteractions, true)} /><MetricPair label="Публикации" value={formatMetric(row.publicationCount)} /></dl><Link className="mt-4 inline-flex min-h-9 w-full items-center justify-center rounded-md border px-3 text-sm font-medium" href={href} prefetch={false}>Открыть аккаунт</Link></article>;
  })}</div></TooltipProvider>;
}

function EntityIdentity({ row, href, heading = false }: { row: StatisticsEntity; href: string; heading?: boolean }) {
  const shortName = row.shortName || row.canonicalName;
  const fullName = row.shortName && row.shortName.trim() !== row.canonicalName.trim() ? row.canonicalName : null;
  return <div className="min-w-0">
    {heading
      ? <h3 className="truncate font-semibold" title={row.canonicalName}><Link href={href} prefetch={false}>{shortName}</Link></h3>
      : <Link href={href} className="font-semibold underline-offset-4 hover:underline" prefetch={false} title={row.canonicalName}>{shortName}</Link>}
    {fullName ? <div className="mt-0.5 text-xs leading-snug text-muted-foreground" title={fullName}>{fullName}</div> : null}
  </div>;
}

function MetricPair({ label, value }: { label: ReactNode; value: ReactNode }) {
  return <div><dt className="text-[10px] uppercase text-muted-foreground">{label}</dt><dd className="font-medium">{value}</dd></div>;
}

function EntityErvHelp() {
  return <Tooltip><TooltipTrigger render={<button type="button" className="relative z-10 inline-flex size-6 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring" aria-label="Как считается ERV вузов" />}><CircleHelp className="size-3.5" aria-hidden="true" /></TooltipTrigger><TooltipContent className="max-w-sm whitespace-normal leading-relaxed">ERV вуза = сумма взаимодействий ÷ сумма просмотров × 100%. До 20 последних публикаций; без просмотров не учитываются.</TooltipContent></Tooltip>;
}

function EntityMedianHelp({ compact = false }: { compact?: boolean }) {
  return <Tooltip><TooltipTrigger render={<button type="button" className={`relative z-10 inline-flex items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring ${compact ? "size-5" : "size-6"}`} aria-label="Что означает медиана взаимодействий" />}><CircleHelp className="size-3.5" aria-hidden="true" /></TooltipTrigger><TooltipContent className="max-w-sm whitespace-normal leading-relaxed">Медиана: у половины публикаций взаимодействий меньше, у половины — больше. До 20 последних публикаций.</TooltipContent></Tooltip>;
}

function EntityErvValue({ row, prominent = false }: { row: StatisticsEntity; prominent?: boolean }) {
  const value = formatPercentage(row.erv);
  return <Tooltip><TooltipTrigger render={<button type="button" className={`relative z-10 cursor-help border-b border-dotted border-current ${prominent ? "font-heading text-xl font-bold" : "font-medium"}`} aria-label={`ERV ${value}. Подробнее о расчёте`} />}>{value}</TooltipTrigger><TooltipContent className="max-w-sm whitespace-normal leading-relaxed">ERV по сумме взаимодействий и просмотров. Учтено публикаций: {row.ervSampleSize} из {row.publicationCount}.</TooltipContent></Tooltip>;
}

function publicationMetric(row: StatisticsPublication, metric: StatisticsPublicationSort): string {
  if (metric === "erv") return formatPercentage(row.erv);
  if (metric === "published_at") return new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(row.publishedAt));
  return formatMetric(metric === "views" ? row.views : row.interactions);
}

function entityMetric(row: StatisticsEntity, metric: keyof typeof ENTITY_LABELS): string {
  if (metric === "erv") return formatPercentage(row.erv);
  if (metric === "median_interactions") return formatMetric(row.medianInteractions, true);
  return formatMetric(metric === "interactions" ? row.interactions : metric === "views" ? row.views : row.publicationCount);
}
