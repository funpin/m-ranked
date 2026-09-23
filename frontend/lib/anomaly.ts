import { duration } from "./format";
import type { AnomalySignal, HistorySnapshot, PublicationAnomalyAnalysis } from "./types";

/** Результат загрузки анализа. Сбой — не отсутствие признаков: карточка
 *  честно скажет, что результата нет. */
export type AnalysisLoad = { value: PublicationAnomalyAnalysis | null; failed: boolean };

/** Символы признаков — те же, что пишет анализ; легенда нужна и тогда, когда
 *  признаков на посте нет, поэтому список полный и живёт здесь. */
export const SIGNAL_LEGEND = [
  { pattern: 1, symbol: "⟋", title: "линейная подача" },
  { pattern: 2, symbol: "⚡", title: "поздний скачок" },
  { pattern: 4, symbol: "⋯", title: "прирост за пробел в замерах" },
  { pattern: 5, symbol: "≈", title: "реакции догоняют просмотры" },
  { pattern: 6, symbol: "⇅", title: "реакции раньше просмотров" },
  { pattern: 7, symbol: "≫", title: "реакций больше просмотров" },
  { pattern: 8, symbol: "⫴", title: "синхронный подъём постов аккаунта" },
  { pattern: 9, symbol: "▭", title: "рывок, обрывающийся в плато" },
  { pattern: 10, symbol: "◇", title: "ERV вне нормы" },
] as const;

export const METRIC_NAMES = { views: "просмотры", reactions: "реакции", comments: "комментарии", shares: "репосты" } as const;
export const FAMILY_NAMES = {
  velocity: "скорость", shape: "форма", cross_metric: "согласие метрик", synchrony: "синхронность",
} as const;

export type Tone = "neutral" | "amber" | "red";

/** Одна строка свёрнутой карточки. «Нет признаков» и «ещё не проанализирован»
 *  спокойные: предупреждающий цвет там читался бы как обвинение. */
export function summaryLine(analysis: PublicationAnomalyAnalysis) {
  const count = analysis.signals.length;
  const calm = analysis.level === null || analysis.level === 0;
  const tone: Tone = calm ? "neutral" : analysis.level === 3 ? "red" : "amber";
  return {
    symbol: analysis.levelSymbol,
    label: analysis.levelLabel,
    count: calm ? null : signalCount(count),
    analyzedAt: analysis.analyzedAt,
    calm,
    tone,
  };
}

export function signalCount(count: number) {
  const tail = count % 100;
  const word = tail >= 11 && tail <= 14 ? "признаков"
    : count % 10 === 1 ? "признак" : count % 10 >= 2 && count % 10 <= 4 ? "признака" : "признаков";
  return `${count} ${word}`;
}

export function scaleText(seconds: number) {
  return seconds >= 3600 ? `${Math.round(seconds / 3600)} ч` : `${Math.round(seconds / 60)} мин`;
}

/** Интервал признака в возрасте поста: так его читают на графиках и в формуле. */
export function intervalText(signal: AnomalySignal, publishedAt: string) {
  const start = (Date.parse(signal.startAt) - Date.parse(publishedAt)) / 1000;
  const end = (Date.parse(signal.endAt) - Date.parse(publishedAt)) / 1000;
  return `${duration(Math.max(0, start))} — ${duration(Math.max(0, end))} после публикации`;
}

/** Сохранённая точка, ближайшая к моменту. */
export function nearestSnapshot(rows: readonly HistorySnapshot[], instant: string) {
  const target = Date.parse(instant);
  let best: HistorySnapshot | undefined;
  for (const row of rows) {
    if (!best || Math.abs(Date.parse(row.observedAt) - target) < Math.abs(Date.parse(best.observedAt) - target)) best = row;
  }
  return best;
}

/** Точки на границах интервалов признаков — на графике они рисуются ромбами. */
export function boundarySnapshotIds(analysis: PublicationAnomalyAnalysis | null, rows: readonly HistorySnapshot[]) {
  const ids = new Set<string>();
  for (const signal of analysis?.signals ?? []) {
    for (const edge of [signal.startAt, signal.endAt]) {
      const row = nearestSnapshot(rows, edge);
      if (row) ids.add(row.snapshotId);
    }
  }
  return ids;
}

export type SignalMarker = { id: string; pattern: number; symbol: string; title: string; from: number; to: number };

export function signalMarkers(analysis: PublicationAnomalyAnalysis | null): SignalMarker[] {
  return (analysis?.signals ?? []).map((signal, index) => ({
    id: markerId(signal, index), pattern: signal.pattern, symbol: signal.symbol, title: signal.title,
    from: Date.parse(signal.startAt), to: Date.parse(signal.endAt),
  }));
}

export function markerId(signal: AnomalySignal, index: number) {
  return `signal-${signal.pattern}-${signal.metric}-${index}`;
}

export type MiniChart =
  | { type: "lines"; series: { key: string; label: string; dashed?: boolean; axis?: "left" | "right" }[];
      band?: { low: string; high: string }; points: Record<string, number | null>[] }
  | { type: "bars"; bars: { label: string; value: number; highlight: boolean }[]; percent: boolean };

function value(row: HistorySnapshot, metric: AnomalySignal["metric"]) {
  return row[metric].value;
}

function numberAt(render: AnomalySignal["render"], key: string) {
  const item = (render as Record<string, unknown>)[key];
  return typeof item === "number" ? item : null;
}

/** Данные мини-графика по типу признака: какая картинка объясняет его лучше.
 *  Прямая аппроксимации поверх точек (1), кривая против полосы модели (2, 4),
 *  совмещённые реакции и просмотры (5, 6, 7), обрыв в плато (9), столбцы для
 *  синхронности (8) и шкала ERV «пост против медианы» (10). */
export function miniChart(signal: AnomalySignal, rows: readonly HistorySnapshot[], publishedAt: string): MiniChart {
  const render = signal.render;
  if (render.kind === "erv") {
    return { type: "bars", percent: true, bars: [
      { label: "этот пост", value: numberAt(render, "erv") ?? 0, highlight: true },
      { label: "медиана нормы", value: numberAt(render, "median") ?? 0, highlight: false },
    ] };
  }
  if (render.kind === "synchrony") {
    return { type: "bars", percent: false, bars: [
      { label: "подросли вместе", value: numberAt(render, "posts") ?? 0, highlight: true },
      { label: "не подросли", value: numberAt(render, "quiet") ?? 0, highlight: false },
    ] };
  }
  const published = Date.parse(publishedAt);
  const start = published + render.startAge * 1000;
  const end = published + render.endAge * 1000;
  // Поля по краям — половина интервала, но не меньше двух часов: видно, что
  // было до признака и что стало после.
  const pad = Math.max((end - start) / 2, 2 * 3600_000);
  const window = rows.filter((row) => {
    const at = Date.parse(row.observedAt);
    return at >= start - pad && at <= end + pad;
  });
  const hours = (at: number) => (at - published) / 3600_000;
  if (render.kind === "lead" || render.kind === "exceed" || render.kind === "ratio") {
    return { type: "lines", series: [
      { key: "reactions", label: "реакции", axis: "left" }, { key: "views", label: "просмотры", axis: "right" },
    ], points: window.map((row) => ({ t: Date.parse(row.observedAt), reactions: value(row, "reactions"), views: value(row, "views") })) };
  }
  const metric = signal.metric;
  const base = nearestSnapshot(rows, new Date(start).toISOString());
  const startValue = base ? value(base, metric) ?? 0 : 0;
  if (render.kind === "linear") {
    const slope = numberAt(render, "slope") ?? 0;
    const intercept = numberAt(render, "intercept") ?? startValue;
    return { type: "lines", series: [
      { key: "actual", label: METRIC_NAMES[metric] }, { key: "fit", label: "прямая аппроксимации", dashed: true },
    ], points: window.map((row) => {
      const at = Date.parse(row.observedAt);
      const inside = at >= start && at <= end;
      return { t: at, actual: value(row, metric), fit: inside ? intercept + slope * (at - start) / 3600_000 : null };
    }) };
  }
  if (render.kind === "expected" || render.kind === "gap") {
    const decay = (render as Record<string, unknown>).decay;
    const expectedTotal = numberAt(render, "expected") ?? 0;
    const model = (at: number) => {
      if (at < start) return null;
      if (Array.isArray(decay) && decay.length === 3) {
        const [a, b, c] = decay as number[];
        const from = hours(start) + c!, to = hours(Math.min(at, end)) + c!;
        const increment = Math.abs(b! - 1) < 1e-9 ? a! * (Math.log(to) - Math.log(from))
          : a! / (1 - b!) * (to ** (1 - b!) - from ** (1 - b!));
        return startValue + increment;
      }
      return startValue + expectedTotal * Math.min(1, (at - start) / Math.max(1, end - start));
    };
    return { type: "lines", series: [
      { key: "actual", label: METRIC_NAMES[metric] }, { key: "expected", label: "ожидание по модели", dashed: true },
    ], band: { low: "low", high: "high" }, points: window.map((row) => {
      const at = Date.parse(row.observedAt);
      const expected = model(at);
      // Полоса — вдвое меньше и вдвое больше ожидаемого прироста: органика
      // укладывается в неё с запасом, признак выходит далеко за край.
      return { t: at, actual: value(row, metric), expected,
        low: expected === null ? null : startValue + (expected - startValue) / 2,
        high: expected === null ? null : startValue + (expected - startValue) * 2 };
    }) };
  }
  return { type: "lines", series: [{ key: "actual", label: METRIC_NAMES[metric] }],
    points: window.map((row) => ({ t: Date.parse(row.observedAt), actual: value(row, metric) })) };
}
