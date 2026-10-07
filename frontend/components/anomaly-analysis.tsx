"use client";
import dynamic from "next/dynamic";
import { use, useState } from "react";
import { ArrowUpRight, ChevronRight, CircleHelp, LocateFixed, UsersRound } from "lucide-react";
import Link from "@/components/native-link";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { StatusPill } from "@/components/ui";
import { MethodNote } from "@/components/method-note";
import { NeighborContextTimeline } from "@/components/neighbor-context-timeline";
import { LevelIcon, PatternIcon } from "@/components/anomaly-icons";
import { legacyDate } from "@/lib/format";
import { accountHref, publicationHref } from "@/lib/entity-routes";
import { FAMILY_NAMES, METRIC_NAMES, intervalText, markerId, miniChart, referenceExplanation, scaleText, summaryLine, type AnalysisLoad } from "@/lib/anomaly";
import type { AccountAnomalyFinding, AnomalySignal, HistorySnapshot, PublicationAnomalyAnalysis } from "@/lib/types";
import type { NeighborContextLoad } from "@/lib/neighbor-context-loader";
import type { ContextWindow } from "@/lib/neighbor-context";
import { cn } from "@/lib/utils";

const MiniChart = dynamic(() => import("./anomaly-mini-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-36 w-full" role="status" aria-label="Загрузка мини-графика" />,
});

function Summary({ analysis }: { analysis: PublicationAnomalyAnalysis }) {
  const line = summaryLine(analysis);
  const findings = analysis.accountFindings ?? [];
  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid="saved-anomaly-status">
      <LevelIcon level={line.level} className={cn("size-4 shrink-0", line.calm ? "text-muted-foreground" : line.tone === "red" ? "text-destructive" : "text-chart-3")} />
      {line.calm ? <b className="font-semibold">{line.label.replace(/^./, (letter) => letter.toUpperCase())}{findings.length && line.level === 0 ? " у поста" : ""}</b>
        : <><span className="text-muted-foreground text-xs font-normal">Итоговая оценка</span>
          <StatusPill tone={line.tone === "red" ? "red" : "amber"}>{line.label}</StatusPill></>}
      {/* Пост без собственных признаков, но из аккаунтной находки: сама
          закономерность видна только на многих постах, и «нет признаков» без
          неё читалось бы как «всё обычно». */}
      {line.calm && findings.length ? <span className="inline-flex items-center gap-1.5" data-testid="account-finding-summary">
        <UsersRound className="text-chart-3 size-3.5 shrink-0" aria-hidden="true" />
        <StatusPill tone="amber">{findings[0]!.title}{findings.length > 1 ? ` +${findings.length - 1}` : ""}</StatusPill>
      </span> : null}
    </span>
  );
}

const windowDate = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" });
const windowTime = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" });

function SignalHeading({ signal, expanded }: { signal: AnomalySignal; expanded: boolean }) {
  return <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
    <span className="inline-flex items-center gap-1.5 font-semibold"><PatternIcon pattern={signal.pattern} className="text-chart-3 size-4 shrink-0" />{signal.title}</span>
    <span className="text-muted-foreground text-xs tabular-nums">{windowDate.format(new Date(signal.startAt))}</span>
    <span className="text-muted-foreground text-xs">{METRIC_NAMES[signal.metric]}</span>
    <SameEpisode signal={signal} />
    <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="text-muted-foreground ml-auto" />} data-testid="signal-detail-toggle">
      График <ChevronRight data-icon="inline-end" className={cn("transition-transform", expanded && "rotate-90")} aria-hidden="true" />
    </CollapsibleTrigger>
  </div>;
}

/** Другие проверки, увидевшие то же событие: в уровень оно входит один раз. */
function SameEpisode({ signal }: { signal: AnomalySignal }) {
  const titles = Array.isArray(signal.render.sameEpisode)
    ? signal.render.sameEpisode.filter((item): item is string => typeof item === "string") : [];
  if (!titles.length) return null;
  return <Tooltip><TooltipTrigger render={<Badge variant="outline" className="text-muted-foreground font-normal" data-testid="same-episode" />}>
    +{titles.length} {titles.length === 1 ? "проверка" : "проверки"}
  </TooltipTrigger><TooltipContent className="max-w-xs whitespace-normal">
    То же событие нашли: {titles.join("; ")}. В оценку оно входит один раз.
  </TooltipContent></Tooltip>;
}

function ContextRow({ window, signal, index, onShow }: {
  window: ContextWindow; signal: AnomalySignal; index: number; onShow?: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState(window.events[0]?.publicationId);
  const shared = window.context === "neighbor_and_shared" || window.context === "shared_channel";
  const explanation = window.context === "insufficient_data" ? "Недостаточно замеров"
    : shared && window.events.length ? "Новый пост · общий рост"
      : shared ? "Общий рост канала"
        : window.events.length ? "Новый пост · общего роста нет"
          : "Контекст не найден";
  const activeEvent = window.events.find((event) => event.publicationId === selectedEvent) ?? window.events[0];
  return <Collapsible open={expanded} onOpenChange={setExpanded} render={<li className="border-border border-b py-3 last:border-b-0" data-testid="anomaly-signal" data-pattern={signal.pattern} />}>
    <SignalHeading signal={signal} expanded={expanded} />
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 pl-[22px] text-xs" data-testid="neighbor-context-window">
      <span className={cn("font-medium", shared ? "text-emerald-600 dark:text-emerald-300" : "text-muted-foreground")}>{explanation}</span>
      {window.events.length ? <span className="text-amber-600 dark:text-amber-300 tabular-nums">
        №{window.events[0]!.displayId}{window.events.length > 1 ? ` +${window.events.length - 1}` : ""} · позиция +{window.events[0]!.observedFeedDistance}
      </span> : null}
      {window.peers.length ? <span className="text-muted-foreground tabular-nums">Старые выросли: {window.positivePeerCount}/{window.peers.length}</span> : null}
      <Tooltip><TooltipTrigger render={<Button variant="ghost" size="icon-xs" className="text-muted-foreground rounded-full" aria-label="Что означает контекст" />}><CircleHelp className="size-3.5" /></TooltipTrigger><TooltipContent className="max-w-xs whitespace-normal">
        Порядок в ленте и рост старых постов видны по данным. Источник переходов счётчики не раскрывают.
      </TooltipContent></Tooltip>
    </div>
    <CollapsibleContent className="border-border mt-3 border-t pt-3" data-testid="neighbor-event-chart">
      {window.events.length ? <>
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <ToggleGroup aria-label="Новые публикации в окне" variant="outline" spacing={1.5} className="flex-wrap"
            value={activeEvent ? [activeEvent.publicationId] : []}
            onValueChange={(next) => { if (next[0]) setSelectedEvent(next[0]); }}>
            {window.events.map((event) => <ToggleGroupItem key={event.publicationId} value={event.publicationId}
              className="text-muted-foreground tabular-nums data-pressed:border-amber-500/50 data-pressed:bg-amber-500/10 data-pressed:text-amber-600 dark:data-pressed:text-amber-300">
              ↗ №{event.displayId} · {windowTime.format(new Date(event.publishedAt))}
            </ToggleGroupItem>)}
          </ToggleGroup>
          {activeEvent ? <Link href={publicationHref(activeEvent.publicationId)} className="text-muted-foreground ml-auto text-xs underline-offset-2 hover:underline">Открыть пост ↗</Link> : null}
        </div>
        {activeEvent && !window.eventTraces.some((trace) => trace.publicationId === activeEvent.publicationId && trace.points.length)
          ? <p className="text-muted-foreground text-xs">Замеров нового поста нет</p> : null}
        {window.omittedEventCount ? <p className="text-muted-foreground text-xs">Ещё {window.omittedEventCount} постов за пределом графика</p> : null}
      </> : <p className="text-muted-foreground mb-2 text-xs">Нового поста в окне не найдено</p>}
      <NeighborContextTimeline window={window} event={activeEvent} />
      {onShow ? <Button variant="outline" size="sm" className="mt-2" onClick={() => onShow(markerId(signal, index))}>
        <LocateFixed className="size-3.5" aria-hidden="true" />Показать на общем графике
      </Button> : null}
    </CollapsibleContent>
  </Collapsible>;
}

function Signal({ signal, index, rows, publishedAt, onShow }: {
  signal: AnomalySignal; index: number; rows: readonly HistorySnapshot[]; publishedAt: string; onShow?: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const title = signal.title;
  return (
    <Collapsible open={expanded} onOpenChange={setExpanded} render={<li className="border-border border-b py-3 last:border-b-0" data-testid="anomaly-signal" data-pattern={signal.pattern} />}>
      <SignalHeading signal={signal} expanded={expanded} />
      <CollapsibleContent className="border-border mt-3 grid gap-2 border-t pt-3">
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
          <span>{FAMILY_NAMES[signal.family]} · сила {signal.strength.toFixed(2)}</span>
          <span>{intervalText(signal, publishedAt)} · масштаб {scaleText(signal.scaleSeconds)}</span>
          <Tooltip><TooltipTrigger render={<Button variant="ghost" size="icon-xs" className="rounded-full" aria-label="Формула и возможные объяснения" />}><CircleHelp className="size-3.5" /></TooltipTrigger><TooltipContent className="max-w-xs whitespace-normal">
            {signal.formula}. {signal.alternatives.map((item) => item.text).join("; ")}
          </TooltipContent></Tooltip>
        </div>
        {referenceExplanation(signal) ? <p className="text-muted-foreground text-xs" data-testid="reference-explanation">{referenceExplanation(signal)}</p> : null}
        {signal.render.kind === "bounded_burst" ? <p className="text-muted-foreground text-xs" data-testid="bounded-burst-explanation">{signal.formula}</p> : null}
        {signal.render.kind === "regime" || signal.render.kind === "write_off" || signal.render.kind === "cliff"
          ? <p className="text-muted-foreground text-xs" data-testid="signal-formula">{signal.formula}</p> : null}
        {signal.render.measurementMode === "telegram_counter_order_v1" ? <p className="text-muted-foreground text-xs">{signal.formula}</p> : null}
        <MiniChart chart={miniChart(signal, rows, publishedAt)} label={title} />
        {onShow ? <Button variant="outline" size="sm" className="w-fit" onClick={() => onShow(markerId(signal, index))}>
          <LocateFixed className="size-3.5" aria-hidden="true" />Показать на графике
        </Button> : null}
      </CollapsibleContent>
    </Collapsible>
  );
}

/** Short public explanation; technical versions remain in the method record. */
function AnalysisNote({ analysis }: { analysis: PublicationAnomalyAnalysis }) {
  return (
    <span className="grid gap-1.5">
      {analysis.quality ? <span className="block" data-testid="anomaly-quality">Данные: {analysis.quality.summary}.</span> : null}
      <span>Поздний скачок остаётся в истории. Если одновременно выросли соседние старые посты, итоговую оценку можно понизить.</span>
      <span>Переходы между постами не наблюдаются. Сигнал не доказывает накрутку.</span>
      <span className="text-foreground/70">{analysis.methodologyVersion}</span>
    </span>
  );
}

/** Строка карточки, пока ответ анализа ещё в пути. Страница поста его не ждёт:
 *  история и графики приходят первыми, а карточка дорисовывается следом. */
/** Аккаунтные находки, в которые входит пост. Уровень поста они не меняют —
 *  это закономерность аккаунта, и подробности живут на его странице. */
function AccountFindingRefs({ findings }: { findings: readonly AccountAnomalyFinding[] }) {
  return <section className="border-border mt-3 border-t pt-3" aria-labelledby="account-findings-title" data-testid="post-account-findings">
    <h3 id="account-findings-title" className="text-muted-foreground text-xs font-normal">
      Пост входит в аккаунтную находку · {findings.length}
    </h3>
    <ul className="mt-1 grid gap-2">
      {findings.map((finding) => <li key={finding.kind} className="grid gap-1" data-testid="post-account-finding" data-kind={finding.kind}>
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="inline-flex items-center gap-1.5 font-semibold"><UsersRound className="text-chart-3 size-4 shrink-0" aria-hidden="true" />{finding.title}</span>
          {finding.statusLabel ? <span className="text-muted-foreground text-xs">{finding.statusLabel}</span> : null}
          <Link href={`${accountHref(finding.accountId)}#account-findings`} className="text-primary ml-auto inline-flex items-center gap-0.5 text-xs hover:underline">
            Страница аккаунта<ArrowUpRight className="size-3.5" aria-hidden="true" />
          </Link>
        </span>
        {finding.summary ? <p className="text-muted-foreground pl-[22px] text-xs leading-relaxed">{finding.summary}.</p> : null}
      </li>)}
    </ul>
  </section>;
}

export function AnomalyAnalysisSkeleton() {
  return (
    <section className="bg-muted/40 border-border mb-4 rounded-xl border px-4 py-3 text-sm" aria-busy="true" aria-label="Анализ динамики загружается" data-testid="anomaly-card-skeleton">
      <div className="flex items-center gap-2">
        <Skeleton className="size-4 shrink-0" />
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-4 w-48 max-w-[40%]" />
      </div>
    </section>
  );
}

/** Карточка из обещания, которое страница запустила, не дожидаясь его. */
export function DeferredAnomalyAnalysis({ load, ...props }: {
  load: Promise<AnalysisLoad>; rows: readonly HistorySnapshot[]; publishedAt: string; onShow?: (id: string) => void;
}) {
  const { value, failed, neighborContext, neighborContextFailed } = use(load);
  return <AnomalyAnalysis analysis={value} loadFailed={failed} neighborContext={neighborContext} neighborContextFailed={neighborContextFailed} {...props} />;
}

/** Карточка анализа на странице поста — свёрнута по умолчанию: одна строка с
 *  уровнем, числом признаков и временем анализа. Развёрнутая объясняет каждый
 *  признак формулой, мини-графиком и честными альтернативами. */
export function AnomalyAnalysis({ analysis, loadFailed = false, neighborContext, neighborContextFailed = false, rows, publishedAt, onShow }: {
  analysis: PublicationAnomalyAnalysis | null; loadFailed?: boolean; rows: readonly HistorySnapshot[];
  neighborContext?: NeighborContextLoad | null; neighborContextFailed?: boolean;
  publishedAt: string; onShow?: (id: string) => void;
}) {
  if (loadFailed) {
    return (
      <section className="bg-muted/40 border-border mb-4 rounded-xl border px-4 py-3 text-sm" aria-labelledby="anomaly-title">
        <h2 id="anomaly-title" className="font-heading font-semibold">Анализ динамики</h2>
        <p className="text-muted-foreground mt-1">Результат анализа временно недоступен. Это техническая ошибка, а не отсутствие признаков.</p>
      </section>
    );
  }
  if (!analysis) return null;
  const summary = summaryLine(analysis);
  const contextByInterval = new Map<string, ContextWindow>(neighborContext?.windows.map((window): [string, ContextWindow] =>
    [`${window.startAt}|${window.endAt}`, window]) ?? []);
  return (
    <TooltipProvider><section className="bg-muted/40 border-border mb-4 rounded-xl border text-sm" aria-labelledby="anomaly-title" data-testid="anomaly-card">
      <Collapsible>
        {/* Кнопка внутри заголовка, а не наоборот: так раскрывающийся блок
            читается скринридером как заголовок раздела с состоянием. */}
        <div className="flex items-center gap-1 pr-3">
          <h2 id="anomaly-title" className="m-0 min-w-0 flex-1">
            <CollapsibleTrigger data-testid="anomaly-toggle" className="group focus-visible:ring-ring/50 flex w-full items-start gap-2 rounded-xl px-4 py-3 text-left focus-visible:ring-[3px] focus-visible:outline-none">
              <ChevronRight className="size-4 shrink-0 transition-transform group-data-[panel-open]:rotate-90" aria-hidden="true" />
              <span className="grid min-w-0 gap-1">
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                  <span className="font-heading font-semibold">Анализ динамики</span>
                  <Summary analysis={analysis} />
                </span>
                {summary.count || summary.analyzedAt ? <span className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums">
                  {summary.count ? <span>{summary.count}</span> : null}
                  {summary.analyzedAt ? <span>Анализ {legacyDate(summary.analyzedAt)}</span> : null}
                  {analysis.originalLevel !== null && analysis.level !== null && analysis.originalLevel > analysis.level
                    ? <span data-testid="context-cap-status">Сильный признак ослаблен контекстом</span> : null}
                  {analysis.accountFindings?.length && !summary.calm ? <span className="inline-flex items-center gap-1" data-testid="account-finding-status">
                    <UsersRound className="text-chart-3 size-3.5" aria-hidden="true" />аккаунтная находка</span> : null}
                </span> : null}
              </span>
            </CollapsibleTrigger>
          </h2>
          {/* Качество данных, легенда и методика — справка, а не вывод: под
              значком, как у остальных карточек, чтобы не теснить признаки. */}
          <span data-testid="anomaly-note"><MethodNote title="Анализ динамики"><AnalysisNote analysis={analysis} /></MethodNote></span>
        </div>
        <CollapsibleContent className="px-4 pb-4">
          {analysis.originalLevel !== null && analysis.level !== null && analysis.originalLevel > analysis.level
            ? <p className="text-muted-foreground pt-1 text-xs" data-testid="context-cap-explanation">
              Скачок есть; общий рост после новых постов ослабляет вывод. Источник просмотров неизвестен.
            </p> : null}
          {neighborContextFailed ? <p className="text-muted-foreground text-xs">Контекст временно недоступен; исходные сигналы сохранены.</p> : null}
          {analysis.signals.length ? <>
            <p className="text-muted-foreground pt-1 text-xs">Сигналы аномалий · {analysis.signals.length}</p>
            <ol className="mt-1" aria-label="Сигналы аномалий">
              {analysis.signals.map((signal, index) => ({ signal, index }))
                .sort((a, b) => Date.parse(a.signal.startAt) - Date.parse(b.signal.startAt))
                .map(({ signal, index }) => {
                const context = signal.pattern === 2 && signal.metric === "views"
                  ? contextByInterval.get(`${signal.startAt}|${signal.endAt}`) : undefined;
                return context
                  ? <ContextRow key={markerId(signal, index)} window={context} signal={signal} index={index} onShow={onShow} />
                  : <Signal key={markerId(signal, index)} signal={signal} index={index} rows={rows} publishedAt={publishedAt} onShow={onShow} />;
              })}
            </ol>
          </> : (
            <p className="text-muted-foreground">{analysis.status === "pending" ? "Пост ещё не проанализирован: анализ идёт по расписанию после первых замеров." : analysis.quality?.codes.includes("no_precise_metrics") ? "Недостаточно точных данных для проверки. Отсутствие сигнала не подтверждает обычность статистики." : "Признаков аномальной динамики не найдено."}</p>
          )}
          {analysis.accountFindings?.length ? <AccountFindingRefs findings={analysis.accountFindings} /> : null}
        </CollapsibleContent>
      </Collapsible>
    </section></TooltipProvider>
  );
}
