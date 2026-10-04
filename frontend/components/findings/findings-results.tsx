"use client";

import { ExternalLink } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import Link from "@/components/native-link";
import { GrowthSparkline } from "@/components/findings/growth-sparkline";
import { ReactionGlyph } from "@/components/reaction-glyph";
import { RowLink } from "@/components/row-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { typeName } from "@/lib/compare-dashboard";
import { publicationHref } from "@/lib/entity-routes";
import {
  FINDINGS_SORT_OPTIONS, findingBadge, findingIndex, findingsHrefQuery, formatIndex, isNewSince, previousVisit,
  recallInstitution, type ParsedFindingsQuery,
} from "@/lib/findings";
import { formatMetric, formatPercentage, PLATFORM_LABELS, publicationLabel } from "@/lib/format";
import { queryHref } from "@/lib/params";
import type { Finding, FindingsPage } from "@/lib/types";
import { cn } from "@/lib/utils";

const published = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow", weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
});

/** Сколько строк показать сразу; остальное из уже полученной страницы — по кнопке. */
const INITIAL_ROWS = 20;

/** Что знает о пользователе только его браузер: прошлый визит и «свой» вуз. */
type Personal = { visit: number | null; mine: number | null };

function storage(name: "localStorage" | "sessionStorage"): Storage | null {
  try { return window[name]; } catch { return null; }
}

/** Читается после монтирования: сервер не знает localStorage, и разметка
 *  до гидратации должна совпасть. */
function usePersonal(): Personal {
  const [personal, setPersonal] = useState<Personal>({ visit: null, mine: null });
  useEffect(() => {
    const local = storage("localStorage");
    // eslint-disable-next-line react-hooks/set-state-in-effect -- однократное чтение браузерного хранилища
    setPersonal({ visit: previousVisit(local, storage("sessionStorage"), Date.now()), mine: recallInstitution(local) });
  }, []);
  return personal;
}

export function FindingsResults({ page, query, anomaliesVisible }: {
  page: FindingsPage; query: ParsedFindingsQuery; anomaliesVisible: boolean;
}) {
  const [shown, setShown] = useState(INITIAL_ROWS);
  const personal = usePersonal();
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
          <FindingRows rows={group.items} query={query} anomaliesVisible={anomaliesVisible} showInstitution={false} personal={personal} />
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
  return <TooltipProvider><div className="min-w-0 space-y-3 lg:rounded-xl lg:border lg:bg-card lg:p-5">
    <FindingRows rows={visible} query={query} anomaliesVisible={anomaliesVisible} showInstitution={query.mode === "all"} personal={personal} />
    {shown < page.items.length ? <div className="flex justify-center"><Button type="button" variant="outline" onClick={() => setShown(page.items.length)}>Показать ещё</Button></div>
      : page.nextCursor ? <div className="flex justify-center"><Link className={buttonVariants({ variant: "outline" })} prefetch={false}
          href={queryHref("/statistics", { ...findingsHrefQuery(query), cursor: page.nextCursor })}>Следующие 50</Link></div> : null}
    {hiddenNote}
  </div></TooltipProvider>;
}

const SORT_LABELS = Object.fromEntries(FINDINGS_SORT_OPTIONS) as Record<ParsedFindingsQuery["sort"], string>;

const INDEX_HEADERS: Partial<Record<ParsedFindingsQuery["sort"], string>> = {
  comment_index: "комментарии", share_index: "репосты",
};

function FindingRows({ rows, query, anomaliesVisible, showInstitution, personal }: {
  rows: Finding[]; query: ParsedFindingsQuery; anomaliesVisible: boolean; showInstitution: boolean; personal: Personal;
}) {
  // «Ваш вуз» отмечается только в общей ленте: в «Моём вузе» свои все строки.
  const mine = (row: Finding) => showInstitution && personal.mine !== null && row.institutionLegacyId === personal.mine;
  const marks = (row: Finding) => ({ fresh: isNewSince(row, personal.visit), mine: mine(row) });
  return <>
    <div className="hidden overflow-x-auto lg:block"><Table data-testid="findings-table" className="tabular">
      <caption className="sr-only">Посты выше нормы своего аккаунта. Сортировка: {SORT_LABELS[query.sort]}</caption>
      <TableHeader><TableRow>
        <TableHead>Пост</TableHead>
        <TableHead>Индекс{INDEX_HEADERS[query.sort] ? <span className="text-muted-foreground font-normal"> · {INDEX_HEADERS[query.sort]}</span> : null}</TableHead>
        <TableHead>Набор</TableHead><TableHead>Взаимодействия · 24 ч</TableHead>
        <TableHead>Просмотры · 24 ч</TableHead><TableHead>ERV · 24 ч</TableHead><TableHead className="w-12"><span className="sr-only">Оригинал</span></TableHead>
      </TableRow></TableHeader>
      <TableBody>{rows.map((row) => (
        <RowLink key={row.publicationId} href={publicationHref(row.publicationId)} data-mine={mine(row) || undefined}
          className={cn("hover:bg-muted/50 focus-within:bg-muted/50 cursor-pointer", mine(row) && "bg-primary/5 shadow-[inset_3px_0_0_var(--primary)]")}>
          <TableCell className="min-w-64 whitespace-normal"><Identity row={row} showInstitution={showInstitution} badge={findingBadge(row, anomaliesVisible)} marks={marks(row)} linked /></TableCell>
          <TableCell><IndexValue row={row} sort={query.sort} /></TableCell>
          <TableCell><GrowthSparkline curve={row.curve} /></TableCell>
          <TableCell><Interactions row={row} /></TableCell>
          <TableCell>{formatMetric(row.views)}</TableCell>
          <TableCell>{formatPercentage(row.erv)}</TableCell>
          <TableCell><Original row={row} /></TableCell>
        </RowLink>
      ))}</TableBody>
    </Table></div>
    <div data-testid="findings-cards" className="grid min-w-0 gap-3 md:grid-cols-2 lg:hidden">{rows.map((row) => (
      <article key={row.publicationId} data-mine={mine(row) || undefined}
        className={cn("bg-card min-w-0 rounded-xl border p-4", mine(row) && "border-primary/60")}>
        <div className="flex items-start justify-between gap-3">
          <Identity row={row} showInstitution={showInstitution} badge={findingBadge(row, anomaliesVisible)} marks={marks(row)} />
          <IndexValue row={row} sort={query.sort} prominent />
        </div>
        <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
          <Pair label="Взаимодействия" value={<Interactions row={row} />} />
          <Pair label="Просмотры" value={formatMetric(row.views)} />
          <Pair label="ERV" value={formatPercentage(row.erv)} />
        </dl>
        <div className="mt-3 flex items-center gap-2">
          <Link className={cn(buttonVariants({ variant: "outline" }), "flex-1")} href={publicationHref(row.publicationId)} prefetch={false}>Открыть карточку</Link>
          <GrowthSparkline curve={row.curve} />
          <Original row={row} />
        </div>
      </article>
    ))}</div>
  </>;
}

/** В таблице описание поста — настоящая ссылка: её видят клавиатура и
 *  читалка экрана, а нажатие по строке лишь дублирует её. В карточке ссылкой
 *  служит кнопка «Открыть карточку». */
function Identity({ row, showInstitution, badge, marks, linked = false }: {
  row: Finding; showInstitution: boolean; badge: string | null; marks: { fresh: boolean; mine: boolean }; linked?: boolean;
}) {
  const number = row.externalId ? publicationLabel(row.externalId, row.platform).replace(/^(?:№\s*)+/, "") : null;
  const kind = `${PLATFORM_LABELS[row.platform]} · ${typeName(row.publicationType)}`;
  // Номер поста MAX — до 18 цифр: не рвём его посреди строки, а обрезаем
  // многоточием на узком экране; целиком он виден в подсказке.
  const description = <>
    <span className="shrink-0">{kind}{number ? " ·" : ""}</span>
    {number ? <span className="min-w-0 truncate" title={`№${number}`}>№{number}</span> : null}
  </>;
  return <div className="min-w-0">
    <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-sm">
      {showInstitution ? <span className="max-w-full truncate font-medium" title={row.institutionCanonicalName}>{row.institutionShortName || row.institutionCanonicalName}</span> : null}
      {marks.mine ? <span className="text-primary text-xs font-medium">ваш вуз</span> : null}
      {linked
        ? <Link className="text-muted-foreground hover:text-foreground flex min-w-0 max-w-full gap-x-1 underline-offset-4 hover:underline" href={publicationHref(row.publicationId)} prefetch={false}>{description}</Link>
        : <span className="text-muted-foreground flex min-w-0 max-w-full gap-x-1">{description}</span>}
    </div>
    <div className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-1.5 text-xs">
      {marks.fresh ? <span className="bg-primary size-1.5 shrink-0 rounded-full" title="Новое с прошлого визита"><span className="sr-only">Новое с прошлого визита.</span></span> : null}
      {row.publishedAt ? published.format(new Date(row.publishedAt)) : null}
      {badge ? <Badge variant="outline" className="rounded-full font-normal">{badge}</Badge> : null}
    </div>
  </div>;
}

function IndexValue({ row, sort, prominent = false }: { row: Finding; sort: ParsedFindingsQuery["sort"]; prominent?: boolean }) {
  const index = findingIndex(row, sort);
  const strong = (index.value ?? 0) >= 2;
  const text = formatIndex(index.value);
  const others = [
    sort === "comment_index" || sort === "share_index" ? `взаимодействия ${formatIndex(row.interactionIndex)}` : null,
    `просмотры ${formatIndex(row.viewIndex)}`,
    row.capabilities.comments && sort !== "comment_index" ? `комментарии ${formatIndex(row.commentIndex)}` : null,
    row.capabilities.shares && sort !== "share_index" ? `репосты ${formatIndex(row.shareIndex)}` : null,
  ].filter(Boolean).join(", ");
  const tip = index.value === null
    ? "Мало истории для нормы: нужно 10 постов аккаунта с замером на этом возрасте."
    : `Норма аккаунта: ${formatMetric(index.norm, true)} ${index.noun}${row.ageHours !== null ? ` на ${row.ageHours}-м часу` : ""}. Другие индексы: ${others}.`;
  return <Tooltip><TooltipTrigger render={<button type="button" className={cn("relative z-10 shrink-0 cursor-help tabular-nums font-bold", prominent && "font-heading text-xl", strong && "text-primary")} aria-label={`Индекс ${text}. Подробнее`} />}>{text}</TooltipTrigger>
    <TooltipContent className="max-w-sm whitespace-normal leading-relaxed">{tip}</TooltipContent></Tooltip>;
}

/** Число взаимодействий и до трёх самых частых реакций (Telegram, MAX). */
function Interactions({ row }: { row: Finding }) {
  const parts = [
    row.capabilities.reactions ? `реакции ${formatMetric(row.reactions)}` : null,
    row.capabilities.comments ? `комментарии ${formatMetric(row.comments)}` : null,
    row.capabilities.shares ? `репосты ${formatMetric(row.shares)}` : null,
  ].filter(Boolean).join(" · ");
  const top = row.topReactions;
  const glyphs = top.length ? <span className="ml-1.5 inline-flex items-center gap-0.5 align-middle text-sm" aria-hidden="true">
    {top.map((entry) => <ReactionGlyph key={entry.reaction} name={entry.reaction} className="size-4" />)}
  </span> : null;
  const topText = top.length ? `Чаще всего: ${top.map((entry) => `${entry.reaction.startsWith("custom:") ? "своя реакция" : entry.reaction} ${formatMetric(entry.count)}`).join(", ")}` : null;
  if (!parts && !topText) return <span className="tabular-nums">{formatMetric(row.interactions)}</span>;
  return <Tooltip><TooltipTrigger render={<button type="button" className="relative z-10 inline-flex cursor-help items-center whitespace-nowrap tabular-nums" aria-label={`Взаимодействия ${formatMetric(row.interactions)}: ${[parts, topText].filter(Boolean).join(". ")}`} />}>
      <span className="border-b border-dotted border-current">{formatMetric(row.interactions)}</span>{glyphs}
    </TooltipTrigger>
    <TooltipContent className="max-w-sm whitespace-normal leading-relaxed">
      {parts ? <p>{parts}</p> : null}
      {top.length ? <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">{top.map((entry) => (
        <span key={entry.reaction} className="inline-flex items-center gap-1 whitespace-nowrap"><ReactionGlyph name={entry.reaction} className="size-4" /> {formatMetric(entry.count)}</span>
      ))}</p> : null}
    </TooltipContent></Tooltip>;
}

function Original({ row }: { row: Finding }) {
  return row.publicUrl ? <a className="hover:bg-accent focus-visible:ring-ring relative z-10 inline-flex size-9 shrink-0 items-center justify-center rounded-md focus-visible:ring-2" href={row.publicUrl} target="_blank" rel="noopener noreferrer" aria-label="Открыть оригинал"><ExternalLink className="size-4" aria-hidden="true" /></a> : null;
}

function Pair({ label, value }: { label: string; value: ReactNode }) {
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
