"use client";
import dynamic from "next/dynamic";
import { use } from "react";
import { ChevronRight, LocateFixed } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui";
import { legacyDate } from "@/lib/format";
import { FAMILY_NAMES, METRIC_NAMES, SIGNAL_LEGEND, intervalText, markerId, miniChart, scaleText, summaryLine, type AnalysisLoad } from "@/lib/anomaly";
import type { AnomalySignal, HistorySnapshot, PublicationAnomalyAnalysis } from "@/lib/types";
import { cn } from "@/lib/utils";

const MiniChart = dynamic(() => import("./anomaly-mini-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-36 w-full" role="status" aria-label="Загрузка мини-графика" />,
});

const REVIEW_NAMES = {
  unreviewed: "не проверен", explained: "объяснён", unresolved: "требует проверки",
  data_error: "ошибка данных", dismissed: "отклонён",
} as const;

function Summary({ analysis }: { analysis: PublicationAnomalyAnalysis }) {
  const line = summaryLine(analysis);
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span aria-hidden="true" className={cn("text-base leading-none", line.calm ? "text-muted-foreground" : line.tone === "red" ? "text-destructive" : "text-chart-3")}>{line.symbol}</span>
      <b className="font-semibold">{line.calm ? line.label.replace(/^./, (letter) => letter.toUpperCase()) : <StatusPill tone={line.tone === "red" ? "red" : "amber"}>{line.label}</StatusPill>}</b>
      {line.count ? <span className="text-muted-foreground">· {line.count}</span> : null}
      {line.analyzedAt ? <span className="text-muted-foreground text-xs">· анализ {legacyDate(line.analyzedAt)}</span> : null}
    </span>
  );
}

function Signal({ signal, index, rows, publishedAt, onShow }: {
  signal: AnomalySignal; index: number; rows: readonly HistorySnapshot[]; publishedAt: string; onShow?: (id: string) => void;
}) {
  const title = `${signal.symbol} ${signal.title}`;
  return (
    <li className="border-border grid gap-2 rounded-lg border p-3" data-testid="anomaly-signal" data-pattern={signal.pattern}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-semibold"><span aria-hidden="true" className="text-chart-3 mr-1.5">{signal.symbol}</span>{signal.title}</span>
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
  const { value, failed } = use(load);
  return <AnomalyAnalysis analysis={value} loadFailed={failed} {...props} />;
}

/** Карточка анализа на странице поста — свёрнута по умолчанию: одна строка с
 *  уровнем, числом признаков и временем анализа. Развёрнутая объясняет каждый
 *  признак формулой, мини-графиком и честными альтернативами. */
export function AnomalyAnalysis({ analysis, loadFailed = false, rows, publishedAt, onShow }: {
  analysis: PublicationAnomalyAnalysis | null; loadFailed?: boolean; rows: readonly HistorySnapshot[];
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
    <section className="bg-muted/40 border-border mb-4 rounded-xl border text-sm" aria-labelledby="anomaly-title" data-testid="anomaly-card">
      <Collapsible>
        {/* Кнопка внутри заголовка, а не наоборот: так раскрывающийся блок
            читается скринридером как заголовок раздела с состоянием. */}
        <h2 id="anomaly-title" className="m-0">
          <CollapsibleTrigger data-testid="anomaly-toggle" className="group focus-visible:ring-ring/50 flex w-full items-center gap-2 rounded-xl px-4 py-3 text-left focus-visible:ring-[3px] focus-visible:outline-none">
            <ChevronRight className="size-4 shrink-0 transition-transform group-data-[panel-open]:rotate-90" aria-hidden="true" />
            <span className="font-heading shrink-0 font-semibold">Анализ динамики</span>
            <Summary analysis={analysis} />
          </CollapsibleTrigger>
        </h2>
        <CollapsibleContent className="grid gap-3 px-4 pb-4">
          {analysis.signals.length ? (
            <ol className="grid gap-2" aria-label="Признаки">
              {analysis.signals.map((signal, index) => (
                <Signal key={markerId(signal, index)} signal={signal} index={index} rows={rows} publishedAt={publishedAt} onShow={onShow} />
              ))}
            </ol>
          ) : (
            <p className="text-muted-foreground">{analysis.status === "pending" ? "Пост ещё не проанализирован: анализ идёт по расписанию после первых замеров." : "Признаков аномальной динамики не найдено."}</p>
          )}
          {analysis.quality ? <p className="text-muted-foreground" data-testid="anomaly-quality">Качество данных: {analysis.quality.summary}.</p> : null}
          <div aria-label="Символы признаков" className="text-muted-foreground flex flex-wrap gap-x-3 gap-y-1 text-xs">
            {SIGNAL_LEGEND.map((item) => <span key={item.pattern}><span aria-hidden="true" className="text-chart-3 mr-1">{item.symbol}</span>{item.title}</span>)}
          </div>
          <Collapsible>
            <CollapsibleTrigger className="group text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 inline-flex w-fit items-center gap-1 rounded-md text-xs font-medium focus-visible:ring-[3px] focus-visible:outline-none">
              <ChevronRight className="size-3.5 transition-transform group-data-[panel-open]:rotate-90" aria-hidden="true" />Методика
            </CollapsibleTrigger>
            <CollapsibleContent className="text-muted-foreground mt-2 grid gap-1 text-xs">
              <p>Уровень складывается из согласия независимых семейств методов: один сильный признак — выраженная аномалия, сильные признаки двух разных семейств — признаки искусственной активности. Признаки относительно нормы при молодой норме не сильнее слабого сигнала.</p>
              <p>Методика {analysis.methodologyVersion} · норма {analysis.normVersion ?? "ещё не построена"} · ревизия данных {analysis.datasetRevision}
                {analysis.lagSeconds !== null ? ` · отставание анализа ${Math.round(analysis.lagSeconds / 60)} мин` : ""} · статус проверки: {REVIEW_NAMES[analysis.reviewStatus]}</p>
              {Object.keys(analysis.detectorVersions).length ? <p>Детекторы: {Object.entries(analysis.detectorVersions).map(([name, version]) => `${name} ${version}`).join(", ")}.</p> : null}
            </CollapsibleContent>
          </Collapsible>
          <p className="text-muted-foreground text-xs">{analysis.disclaimer}</p>
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
