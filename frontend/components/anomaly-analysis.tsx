"use client";
import dynamic from "next/dynamic";
import { use, useState } from "react";
import { ChevronRight, CircleHelp, LocateFixed } from "lucide-react";
import Link from "@/components/native-link";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { StatusPill } from "@/components/ui";
import { MethodNote } from "@/components/method-note";
import { NeighborContextTimeline } from "@/components/neighbor-context-timeline";
import { LevelIcon, PatternIcon } from "@/components/anomaly-icons";
import { legacyDate } from "@/lib/format";
import { publicationHref } from "@/lib/entity-routes";
import { FAMILY_NAMES, METRIC_NAMES, intervalText, markerId, miniChart, referenceExplanation, scaleText, summaryLine, type AnalysisLoad } from "@/lib/anomaly";
import type { AnomalySignal, HistorySnapshot, PublicationAnomalyAnalysis } from "@/lib/types";
import type { NeighborContextLoad } from "@/lib/neighbor-context-loader";
import type { ContextWindow } from "@/lib/neighbor-context";
import { cn } from "@/lib/utils";

const MiniChart = dynamic(() => import("./anomaly-mini-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-36 w-full" role="status" aria-label="Загрузка мини-графика" />,
});

function Summary({ analysis }: { analysis: PublicationAnomalyAnalysis }) {
  const line = summaryLine(analysis);
  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid="saved-anomaly-status">
      <LevelIcon level={line.level} className={cn("size-4 shrink-0", line.calm ? "text-muted-foreground" : line.tone === "red" ? "text-destructive" : "text-chart-3")} />
      {line.calm ? <b className="font-semibold">{line.label.replace(/^./, (letter) => letter.toUpperCase())}</b>
        : <><span className="text-muted-foreground text-xs font-normal">Итоговая оценка</span>
          <StatusPill tone={line.tone === "red" ? "red" : "amber"}>{line.label}</StatusPill></>}
    </span>
  );
}

const windowDate = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" });
const windowTime = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" });

function SignalHeading({ signal, expanded, onToggle }: {
  signal: AnomalySignal; expanded: boolean; onToggle: () => void;
}) {
  return <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
    <span className="inline-flex items-center gap-1.5 font-semibold"><PatternIcon pattern={signal.pattern} className="text-chart-3 size-4 shrink-0" />{signal.title}</span>
    <span className="text-muted-foreground text-xs tabular-nums">{windowDate.format(new Date(signal.startAt))}</span>
    <span className="text-muted-foreground text-xs">{METRIC_NAMES[signal.metric]}</span>
    <button type="button" aria-expanded={expanded} onClick={onToggle}
      className="text-muted-foreground hover:bg-accent hover:text-foreground ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium focus-visible:ring-2 focus-visible:ring-ring"
      data-testid="signal-detail-toggle">
      График <ChevronRight className={cn("size-3.5 transition-transform", expanded && "rotate-90")} aria-hidden="true" />
    </button>
  </div>;
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
  return <li className="border-border border-b py-3 last:border-b-0" data-testid="anomaly-signal" data-pattern={signal.pattern}>
    <SignalHeading signal={signal} expanded={expanded} onToggle={() => setExpanded(!expanded)} />
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 pl-[22px] text-xs" data-testid="neighbor-context-window">
      <span className={cn("font-medium", shared ? "text-emerald-600 dark:text-emerald-300" : "text-muted-foreground")}>{explanation}</span>
      {window.events.length ? <span className="text-amber-600 dark:text-amber-300 tabular-nums">
        №{window.events[0]!.displayId}{window.events.length > 1 ? ` +${window.events.length - 1}` : ""} · позиция +{window.events[0]!.observedFeedDistance}
      </span> : null}
      {window.peers.length ? <span className="text-muted-foreground tabular-nums">Старые выросли: {window.positivePeerCount}/{window.peers.length}</span> : null}
      <Tooltip><TooltipTrigger render={<button type="button" className="text-muted-foreground hover:text-foreground rounded-full focus-visible:ring-2 focus-visible:ring-ring" aria-label="Что означает контекст" />}><CircleHelp className="size-3.5" /></TooltipTrigger><TooltipContent className="max-w-xs whitespace-normal">
        Порядок в ленте и рост старых постов видны по данным. Источник переходов счётчики не раскрывают.
      </TooltipContent></Tooltip>
    </div>
    {expanded ? <div className="border-border mt-3 border-t pt-3" data-testid="neighbor-event-chart">
      {window.events.length ? <>
        <div className="mb-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="Новые публикации в окне">
          {window.events.map((event) => <button key={event.publicationId} type="button"
            aria-pressed={event.publicationId === activeEvent?.publicationId}
            onClick={() => setSelectedEvent(event.publicationId)}
            className={cn("rounded-md border px-2 py-1 text-xs tabular-nums focus-visible:ring-2 focus-visible:ring-ring",
              event.publicationId === activeEvent?.publicationId ? "border-amber-500/50 bg-amber-500/10 text-amber-600 dark:text-amber-300" : "text-muted-foreground hover:bg-accent")}>
            ↗ №{event.displayId} · {windowTime.format(new Date(event.publishedAt))}
          </button>)}
          {activeEvent ? <Link href={publicationHref(activeEvent.publicationId)} className="text-muted-foreground ml-auto text-xs underline-offset-2 hover:underline">Открыть пост ↗</Link> : null}
        </div>
        {activeEvent && !window.eventTraces.some((trace) => trace.publicationId === activeEvent.publicationId && trace.points.length)
          ? <p className="text-muted-foreground text-xs">Замеров нового поста нет</p> : null}
        {window.omittedEventCount ? <p className="text-muted-foreground text-xs">Ещё {window.omittedEventCount} постов за пределом графика</p> : null}
      </> : <p className="text-muted-foreground mb-2 text-xs">Нового поста в окне не найдено</p>}
      <NeighborContextTimeline window={window} event={activeEvent} />
      {onShow ? <button type="button" onClick={() => onShow(markerId(signal, index))}
        className="text-foreground hover:bg-accent focus-visible:ring-ring/50 mt-2 inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium focus-visible:ring-[3px] focus-visible:outline-none">
        <LocateFixed className="size-3.5" aria-hidden="true" />Показать на общем графике
      </button> : null}
    </div> : null}
  </li>;
}

function Signal({ signal, index, rows, publishedAt, onShow }: {
  signal: AnomalySignal; index: number; rows: readonly HistorySnapshot[]; publishedAt: string; onShow?: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const title = signal.title;
  return (
    <li className="border-border border-b py-3 last:border-b-0" data-testid="anomaly-signal" data-pattern={signal.pattern}>
      <SignalHeading signal={signal} expanded={expanded} onToggle={() => setExpanded(!expanded)} />
      {expanded ? <div className="border-border mt-3 grid gap-2 border-t pt-3">
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
          <span>{FAMILY_NAMES[signal.family]} · сила {signal.strength.toFixed(2)}</span>
          <span>{intervalText(signal, publishedAt)} · масштаб {scaleText(signal.scaleSeconds)}</span>
          <Tooltip><TooltipTrigger render={<button type="button" className="rounded-full focus-visible:ring-2 focus-visible:ring-ring" aria-label="Формула и возможные объяснения" />}><CircleHelp className="size-3.5" /></TooltipTrigger><TooltipContent className="max-w-xs whitespace-normal">
            {signal.formula}. {signal.alternatives.map((item) => item.text).join("; ")}
          </TooltipContent></Tooltip>
        </div>
        {referenceExplanation(signal) ? <p className="text-muted-foreground text-xs" data-testid="reference-explanation">{referenceExplanation(signal)}</p> : null}
        <MiniChart chart={miniChart(signal, rows, publishedAt)} label={title} />
        {onShow ? <button type="button" onClick={() => onShow(markerId(signal, index))}
          className="text-foreground hover:bg-accent focus-visible:ring-ring/50 inline-flex w-fit items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium focus-visible:ring-[3px] focus-visible:outline-none">
          <LocateFixed className="size-3.5" aria-hidden="true" />Показать на графике
        </button> : null}
      </div> : null}
    </li>
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
        </CollapsibleContent>
      </Collapsible>
    </section></TooltipProvider>
  );
}
