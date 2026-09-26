"use client";
import dynamic from "next/dynamic";
import { use } from "react";
import { ChevronRight, CircleHelp, LocateFixed } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { StatusPill } from "@/components/ui";
import { MethodNote } from "@/components/method-note";
import { NeighborContextTimeline } from "@/components/neighbor-context-timeline";
import { LevelIcon, PatternIcon } from "@/components/anomaly-icons";
import { legacyDate } from "@/lib/format";
import { FAMILY_NAMES, METRIC_NAMES, intervalText, markerId, miniChart, scaleText, summaryLine, type AnalysisLoad } from "@/lib/anomaly";
import type { AnomalySignal, HistorySnapshot, PublicationAnomalyAnalysis } from "@/lib/types";
import type { NeighborContextLoad } from "@/lib/neighbor-context-loader";
import type { ContextWindow } from "@/lib/neighbor-context";
import { cn } from "@/lib/utils";

const MiniChart = dynamic(() => import("./anomaly-mini-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-36 w-full" role="status" aria-label="Загрузка мини-графика" />,
});

function Summary({ analysis, context }: { analysis: PublicationAnomalyAnalysis; context?: NeighborContextLoad | null }) {
  const line = summaryLine(analysis);
  if (context?.assessment.status === "requires_review") return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1" data-testid="contextual-status">
      <LevelIcon level={1} className="text-chart-3 size-4 shrink-0" />
      <StatusPill tone="amber">Требует проверки</StatusPill>
    </span>
  );
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <LevelIcon level={line.level} className={cn("size-4 shrink-0", line.calm ? "text-muted-foreground" : line.tone === "red" ? "text-destructive" : "text-chart-3")} />
      <b className="font-semibold">{line.calm ? line.label.replace(/^./, (letter) => letter.toUpperCase()) : <StatusPill tone={line.tone === "red" ? "red" : "amber"}>{line.label}</StatusPill>}</b>
      {line.count ? <span className="text-muted-foreground">· {line.count}</span> : null}
      {line.analyzedAt ? <span className="text-muted-foreground text-xs">· анализ {legacyDate(line.analyzedAt)}</span> : null}
    </span>
  );
}

function growthPercent(logGrowth: number): number { return Math.max(0, Math.expm1(logGrowth) * 100); }

function ContextRow({ window }: { window: ContextWindow }) {
  const near = window.events.filter((event) => event.observedFeedDistance <= 4);
  const target = window.target ? growthPercent(window.target.logGrowth) : null;
  const peers = window.medianPeerLogGrowth !== null ? growthPercent(window.medianPeerLogGrowth) : null;
  const shared = window.context === "neighbor_and_shared" || window.context === "shared_channel";
  return <div className="border-border bg-muted/20 rounded-lg border px-3 py-2.5" data-testid="neighbor-context-window">
    <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      <span className="font-medium tabular-nums">{new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" }).format(new Date(window.startAt))}</span>
      {near.map((event) => <span key={event.publicationId} className="border-amber-400/30 bg-amber-400/10 text-foreground rounded border px-1.5 py-0.5 font-medium">↗ №{event.displayId}</span>)}
      <span className={cn("ml-auto rounded-full px-2 py-0.5 tabular-nums", shared ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" : "bg-muted text-muted-foreground")}>{window.positivePeerCount}/{window.peers.length} ↗</span>
      <Tooltip><TooltipTrigger render={<button type="button" className="text-muted-foreground hover:text-foreground focus-visible:ring-ring rounded-full focus-visible:ring-2" aria-label="Подробности окна роста" />}><CircleHelp className="size-3.5" /></TooltipTrigger><TooltipContent className="max-w-sm flex-col items-start whitespace-normal leading-relaxed">
        <span>До 24 реальных замеров на линию. Время роста между ними неизвестно.</span>
        <span>Совпадение по времени не доказывает причину.</span>
      </TooltipContent></Tooltip>
    </div>
    {target === null || peers === null ? <div className="text-muted-foreground text-xs">Недостаточно замеров</div> : <>
      <div className="mb-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
        <span className="text-muted-foreground">▧ Окно сигнала</span>
        {near.length ? <span className="text-amber-400">● Новые посты</span> : null}
        <span className="text-blue-500">● Этот +{target.toFixed(1)}%</span>
        <span className="text-emerald-500">● Соседние +{peers.toFixed(1)}% <span className="text-muted-foreground">медиана</span></span>
      </div>
      <NeighborContextTimeline window={window} />
    </>}
  </div>;
}

function ContextEvidence({ context }: { context: NeighborContextLoad }) {
  const { assessment, windows } = context;
  return <div className="border-border bg-card rounded-lg border p-3" data-testid="neighbor-context-method">
    <div className="mb-2 flex items-center gap-2">
      <p className="font-semibold">Поздний рост</p>
      <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium tabular-nums", assessment.status === "insufficient_data" ? "bg-muted text-muted-foreground" : "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300")}>{assessment.status === "insufficient_data" ? "Контекст не подтверждён" : `${assessment.contextualized}/${assessment.totalLateSpikes} вместе с каналом`}</span>
      <Tooltip><TooltipTrigger render={<button type="button" className="text-muted-foreground hover:text-foreground focus-visible:ring-ring ml-auto rounded-full focus-visible:ring-2" aria-label="Как читать сравнение позднего роста" />}><CircleHelp className="size-4" /></TooltipTrigger><TooltipContent className="max-w-sm flex-col items-start whitespace-normal leading-relaxed">
        <span>Сверху — новые посты, снизу — старые. Ось времени общая.</span>
        <span>Совместный рост снижает уверенность в сильном сигнале. Причина неизвестна.</span>
      </TooltipContent></Tooltip>
    </div>
    <div className="grid gap-2">{[...windows].sort((a, b) => Date.parse(a.startAt) - Date.parse(b.startAt)).map((window) => <ContextRow key={`${window.startAt}-${window.endAt}`} window={window} />)}</div>
  </div>;
}

function Signal({ signal, index, rows, publishedAt, onShow }: {
  signal: AnomalySignal; index: number; rows: readonly HistorySnapshot[]; publishedAt: string; onShow?: (id: string) => void;
}) {
  const title = signal.title;
  return (
    <li className="border-border grid gap-2 rounded-lg border p-3" data-testid="anomaly-signal" data-pattern={signal.pattern}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 font-semibold"><PatternIcon pattern={signal.pattern} className="text-chart-3 size-4 shrink-0" />{signal.title}</span>
        <span className="text-muted-foreground text-xs">{METRIC_NAMES[signal.metric]} · {FAMILY_NAMES[signal.family]} · сила {signal.strength.toFixed(2)}</span>
      </div>
      <code className="bg-muted/60 block rounded-md px-2 py-1.5 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">{signal.formula}</code>
      <p className="text-muted-foreground text-xs">{intervalText(signal, publishedAt)} · масштаб {scaleText(signal.scaleSeconds)}
        {signal.normConfidence !== null && signal.normConfidence < 0.5 ? " · норма молодая, признак не сильнее слабого сигнала" : ""}</p>
      <MiniChart chart={miniChart(signal, rows, publishedAt)} label={title} />
      {signal.alternatives.length ? (
        <p className="text-sm">Возможные объяснения: {signal.alternatives.map((item) => item.text).join("; ")}.</p>
      ) : null}
      {onShow ? (
        <button type="button" onClick={() => onShow(markerId(signal, index))}
          className="text-foreground hover:bg-accent focus-visible:ring-ring/50 inline-flex w-fit items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium focus-visible:ring-[3px] focus-visible:outline-none">
          <LocateFixed className="size-3.5" aria-hidden="true" />Показать на графике
        </button>
      ) : null}
    </li>
  );
}

/** Short public explanation; technical versions remain in the method record. */
function AnalysisNote({ analysis }: { analysis: PublicationAnomalyAnalysis }) {
  return (
    <span className="grid gap-1.5">
      {analysis.quality ? <span className="block" data-testid="anomaly-quality">Данные: {analysis.quality.summary}.</span> : null}
      <span>Уровень зависит от силы и числа независимых признаков.</span>
      <span>Аномалия не доказывает накрутку.</span>
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
  return (
    <TooltipProvider><section className="bg-muted/40 border-border mb-4 rounded-xl border text-sm" aria-labelledby="anomaly-title" data-testid="anomaly-card">
      <Collapsible>
        {/* Кнопка внутри заголовка, а не наоборот: так раскрывающийся блок
            читается скринридером как заголовок раздела с состоянием. */}
        <div className="flex items-center gap-1 pr-3">
          <h2 id="anomaly-title" className="m-0 min-w-0 flex-1">
            <CollapsibleTrigger data-testid="anomaly-toggle" className="group focus-visible:ring-ring/50 flex w-full items-center gap-2 rounded-xl px-4 py-3 text-left focus-visible:ring-[3px] focus-visible:outline-none">
              <ChevronRight className="size-4 shrink-0 transition-transform group-data-[panel-open]:rotate-90" aria-hidden="true" />
              <span className="font-heading shrink-0 font-semibold">Анализ динамики</span>
              <Summary analysis={analysis} context={neighborContext} />
            </CollapsibleTrigger>
          </h2>
          {/* Качество данных, легенда и методика — справка, а не вывод: под
              значком, как у остальных карточек, чтобы не теснить признаки. */}
          <span data-testid="anomaly-note"><MethodNote title="Анализ динамики"><AnalysisNote analysis={analysis} /></MethodNote></span>
        </div>
        <CollapsibleContent className="grid gap-3 px-4 pb-4">
          {neighborContext ? <ContextEvidence context={neighborContext} /> : neighborContextFailed
            ? <p className="text-muted-foreground text-xs">Контекстный расчёт временно недоступен; исходный анализ показан без изменений.</p> : null}
          {analysis.signals.length ? (
            <Collapsible className="border-border rounded-lg border">
              <CollapsibleTrigger className="group focus-visible:ring-ring flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs font-medium focus-visible:ring-2 focus-visible:outline-none">
                <ChevronRight className="size-3.5 transition-transform group-data-[panel-open]:rotate-90" aria-hidden="true" />
                Исходные сигналы <span className="bg-muted rounded-full px-1.5 py-0.5 tabular-nums">{analysis.signals.length}</span>
              </CollapsibleTrigger>
              <CollapsibleContent className="px-2 pb-2"><ol className="grid gap-2" aria-label="Признаки">
                {analysis.signals.map((signal, index) => (
                  <Signal key={markerId(signal, index)} signal={signal} index={index} rows={rows} publishedAt={publishedAt} onShow={onShow} />
                ))}
              </ol></CollapsibleContent>
            </Collapsible>
          ) : (
            <p className="text-muted-foreground">{analysis.status === "pending" ? "Пост ещё не проанализирован: анализ идёт по расписанию после первых замеров." : "Признаков аномальной динамики не найдено."}</p>
          )}
        </CollapsibleContent>
      </Collapsible>
    </section></TooltipProvider>
  );
}
